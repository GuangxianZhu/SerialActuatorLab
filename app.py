"""执行器通信实验室：硬件（3D + 放大镜）与通用控制器固件同步演示。

不打开任何串口，也不连接实物。固件源码读取自 firmware/main.c，
每一步高亮的代码行由源码里的 [01]~[12] 注释决定，改代码后演示会跟着变。
"""
import argparse
import json
import math
import os
import re
import time
from pathlib import Path

from panda3d.core import (
    AmbientLight, DirectionalLight, Geom, GeomNode, GeomTriangles,
    GeomVertexData, GeomVertexFormat, GeomVertexWriter, LineSegs,
    TextNode, TransparencyAttrib, Vec3, loadPrcFileData, Filename, ClockObject,
)
from direct.showbase.ShowBase import ShowBase
from direct.gui.DirectGui import DirectButton, DirectEntry, DirectFrame, DirectOptionMenu, DirectSlider
from protocol import Motor, from_hex, hexline, packet, parse, read, write

ROOT = Path(__file__).resolve().parent
FIRMWARE = ROOT / 'firmware' / 'main.c'
FONT_CANDIDATES = ['C:/Windows/Fonts/msyh.ttc',
                   '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']

BG = (0.035, 0.055, 0.085, 1)
CARD = (0.065, 0.095, 0.14, 1)
CARD2 = (0.045, 0.07, 0.105, 1)
WHITE = (0.92, 0.96, 1, 1)
MUTED = (0.56, 0.66, 0.78, 1)
DIM = (0.30, 0.37, 0.46, 1)
CYAN = (0.25, 0.84, 0.98, 1)
GREEN = (0.30, 0.92, 0.62, 1)
ORANGE = (1, 0.66, 0.25, 1)
PURPLE = (0.76, 0.60, 1, 1)
RED = (1, 0.38, 0.44, 1)
YELLOW = (1, 0.88, 0.35, 1)
INK = (0.04, 0.06, 0.09, 1)

W, H = 1600, 1000
LEFT = (20, 108, 270, 776)
VIEW = (305, 108, 755, 362)
LENS = (305, 482, 755, 402)
CODE = (1075, 108, 505, 460)
STEP = (1075, 580, 505, 304)
STRIP = (20, 900, 1560, 84)
MAX_BYTES = 16          # 教学显示容量，不是实际设备的 FIFO 规格
MOTOR_DEMO_SPEED = 260  # ticks/s，教学动画刻意放慢，不代表实物转速

FAULTS = ['正常通信', '只等 FIFO_EMPTY 就切 DIR', 'DIR 未切回接收', '电机未供电', '没有共地',
          'ID 不匹配', '传输中 CRC 损坏', 'Write 不返回 Status']

# 每一步：标题、白话说明、术语括注、代码聚焦的函数、调用位置
STEPS = {
    1: ('电脑准备好一整包字节',
        '电脑把要发的指令排成一串字节（指令包）。底部 TX 条里每一格是一个字节。MCU 这时在 read_packet() 里空等。',
        'HEX：两个字符表示一个字节，例如 FF = 255。',
        'main', 'main() → read_packet(PC_UART, …) 等电脑'),
    2: ('字节一个一个进 MCU',
        '字节经 USB → USB 串口桥 → HOST_RX 脚进 UART0。看放大镜：移位寄存器把 8 个位拼成 1 个字节 → 进 RX FIFO 排队 → CPU 用 UART_READ 取出 → 存进 SRAM 的 g_buf[n]。',
        'FIFO：先进先出的小队列。本演示将每个 UART 的队列画成 16 格。',
        'read_packet', 'main() → read_packet(PC_UART, g_buf)'),
    3: ('按长度字段判断收齐没有',
        '收到第 7 个字节后，MCU 读第 6、7 字节（长度，低位在前），算出整包一共 need 个字节。n 追上 need 才算一整包，才往下走。',
        '为什么要等整包：USB 可能分几次送到，一次收到的不一定完整。',
        'read_packet', 'main() → read_packet(PC_UART, g_buf)'),
    4: ('DIR 拉高：发送门开、接收门关',
        'MCU 让 DIR_GPIO 输出 1。这根线同时接芯片 7 脚和 1 脚：7 脚见到高电平，发送门打开；1 脚见到高电平，接收门关上。',
        'OE = Output Enable（输出使能）。名字前带“/”的，低电平才打开。',
        'motor_send', 'main() → motor_send(g_buf, len)'),
    5: ('CPU 写 FIFO，硬件一位一位送出',
        'CPU 很快就把整包写进 UART1 发送 FIFO。硬件再从队头取一个字节放进移位寄存器，从 ACT_TX 一位一位送出去，送完再取下一个。电平转换和 三态缓冲器 只传电压，不认字节。',
        '移位寄存器：把 1 个字节拆成 10 位（起始位 + 8 数据位 + 停止位）逐位输出。',
        'motor_send', 'main() → motor_send(g_buf, len)'),
    6: ('等最后一个停止位真正发完',
        '看放大镜的波形：① FIFO_EMPTY=1 时队列空了，可最后一个字节还在移位寄存器里往外发；② TX_COMPLETE=1 才说明停止位也发完。固件等的是 ②。',
        '实物怎么确认：示波器两个通道夹 DATA 和 DIR_GPIO，看 DIR_GPIO 下降沿是否落在最后一个停止位之后。',
        'motor_send', 'main() → motor_send(g_buf, len)'),
    7: ('DIR 拉低：发送门关、接收门开',
        'MCU 让 DIR_GPIO 输出 0。7 脚变低，发送门断开，输出变成“高阻”，不再占着 DATA 线；1 脚变低，接收门打开，电机的回话可以进来。',
        '高阻：输出像拔掉插头一样断开，既不输出 1，也不输出 0。',
        'motor_send', 'main() → motor_send(g_buf, len)'),
    8: ('电机检查并执行指令',
        '电机先核对 ID 和 CRC（校验码），没问题才执行：Ping 报到、Write 写寄存器、Read 读寄存器。MCU 这时在 read_packet() 里等回包，最多等 20ms。',
        'CRC：按全部字节算出的 2 字节校验码，传错一位就对不上。',
        'main', 'main() → read_packet(MOTOR_UART, g_rx, 20ms)'),
    9: ('电机稍等一下再回话',
        '电机先等约 0.5ms（回复延时），给 MCU 留出切方向的时间，然后把状态包发到同一根 DATA 线上，经接收门进来。',
        'Return Delay Time：电机回话前的等待时间，默认约 500µs。',
        'read_packet', 'main() → read_packet(MOTOR_UART, g_rx)'),
    10: ('回包经 UART1 进 SRAM',
         'ACT_RX → UART1 移位寄存器拼字节 → RX FIFO → CPU 用 UART_READ 取出 → 存进 g_rx。还是同一个 read_packet()，只是这次参数换成 MOTOR_UART 和 g_rx。',
         '同一个函数收两边：参数 uart 和 buf 不同而已。',
         'read_packet', 'main() → read_packet(MOTOR_UART, g_rx)'),
    11: ('MCU 把回包原样还给电脑',
         'CPU 把 g_rx 逐个写进 UART0 发送 FIFO → 移位寄存器 → HOST_TX → USB 串口桥 → USB 回到电脑。MCU 不改任何字节。',
         '原样转发：诊断信息也不能混进回包。',
         'pc_write', 'main() → pc_write(g_rx, n)'),
    12: ('电脑检查回包',
         '电脑核对包头、长度、CRC；Instruction=55 表示这是状态包，Error=00 表示电机没报错。MCU 已经回到第 01 步，等下一包。',
         '状态包 = 指令包的格式 + 1 个 Error 字节。',
         'main', 'main() → read_packet(PC_UART, …) 等下一包'),
}
LENS_FOR_STEP = {1: 'mcu', 2: 'mcu', 3: 'mcu', 4: 'buf', 5: 'mcu', 6: 'wave', 7: 'buf',
                 8: 'mcu', 9: 'buf', 10: 'mcu', 11: 'mcu', 12: 'mcu'}

# 转到目标角度的流程：(kind, 标题, 为什么)
FLOW = [
    ('ping', '① Ping', '问一声：ID 1 在吗？'),
    ('mode', '② 读 11 号：操作模式', '要等于 3（位置模式）才能按角度转'),
    ('on', '③ 写 64 号 = 1：扭矩开', '不开扭矩，写了目标也不会转'),
    ('goal', '④ 写 116 号：目标位置', ''),
    ('pos', '⑤ 读 132 号：当前位置', '读到 ≈ 目标就是转到了；没到就再读'),
    ('off', '⑥ 写 64 号 = 0：扭矩关', '可选：电机松开，可以用手转'),
]
AUTO_FLOW = ['ping', 'mode', 'on', 'goal', 'pos']


def box(parent, name, pos, size, color):
    """Own procedural model; no external models required."""
    data = GeomVertexData(name, GeomVertexFormat.getV3n3c4(), Geom.UHStatic)
    vw, nw, cw = [GeomVertexWriter(data, key) for key in ('vertex', 'normal', 'color')]
    faces = [((0, 0, 1), [(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]),
             ((0, 0, -1), [(-1,1,-1),(1,1,-1),(1,-1,-1),(-1,-1,-1)]),
             ((0,-1,0), [(-1,-1,-1),(1,-1,-1),(1,-1,1),(-1,-1,1)]),
             ((0,1,0), [(1,1,-1),(-1,1,-1),(-1,1,1),(1,1,1)]),
             ((1,0,0), [(1,-1,-1),(1,1,-1),(1,1,1),(1,-1,1)]),
             ((-1,0,0), [(-1,1,-1),(-1,-1,-1),(-1,-1,1),(-1,1,1)])]
    triangles = GeomTriangles(Geom.UHStatic)
    for index, (normal, vertices) in enumerate(faces):
        for v in vertices:
            vw.addData3(*[v[i] * size[i] / 2 for i in range(3)])
            nw.addData3(*normal)
            cw.addData4(*color)
        for a, b, c in [(0,1,2),(0,2,3)]:
            triangles.addVertices(index*4+a, index*4+b, index*4+c)
    geom = Geom(data)
    geom.addPrimitive(triangles)
    node = GeomNode(name)
    node.addGeom(geom)
    np = parent.attachNewNode(node)
    np.setPos(*pos)
    return np


def poly2d(parent, points, color):
    """Filled convex polygon in pixel2d coordinates (x, y-down)."""
    data = GeomVertexData('poly', GeomVertexFormat.getV3c4(), Geom.UHStatic)
    vw, cw = GeomVertexWriter(data, 'vertex'), GeomVertexWriter(data, 'color')
    for x, y in points:
        vw.addData3(x, 0, -y)
        cw.addData4(*color)
    tris = GeomTriangles(Geom.UHStatic)
    for i in range(1, len(points) - 1):
        tris.addVertices(0, i, i + 1)
    geom = Geom(data)
    geom.addPrimitive(tris)
    node = GeomNode('poly')
    node.addGeom(geom)
    np = parent.attachNewNode(node)
    np.setTwoSided(True)
    if len(color) == 4 and color[3] < 1:
        np.setTransparency(TransparencyAttrib.MAlpha)
    return np


def rect2d(parent, x0, y0, x1, y1, color):
    return poly2d(parent, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], color)


def lines2d(parent, segments, color, thickness=2):
    ls = LineSegs()
    ls.setThickness(thickness)
    ls.setColor(*color)
    for pts in segments:
        ls.moveTo(pts[0][0], 0, -pts[0][1])
        for x, y in pts[1:]:
            ls.drawTo(x, 0, -y)
    np = parent.attachNewNode(ls.create())
    if len(color) == 4 and color[3] < 1:
        np.setTransparency(TransparencyAttrib.MAlpha)
    return np


def load_firmware():
    """Parse main.c: lines, function ranges, and [NN] step tags."""
    lines = FIRMWARE.read_text(encoding='utf-8').splitlines()
    functions = {}
    current = None
    for no, line in enumerate(lines, 1):
        m = re.match(r'^(?:static\s+)?[\w\s\*]+?\b(\w+)\s*\(', line)
        if m and not line.rstrip().endswith(';') and not line.startswith(' '):
            current = m.group(1)
            functions[current] = [no, no]
        if current:
            functions[current][1] = no
            if line.startswith('}'):
                current = None
    tags = {}
    for no, line in enumerate(lines, 1):
        for m in re.finditer(r'\[(\d\d)\]', line):
            before, after = line[:m.start()], line[m.end():]
            if before.endswith('~') or after.startswith('~'):
                continue  # “[04]~[07]” 是范围说明，不当作高亮点
            block = [no]
            for nxt in range(no + 1, min(no + 6, len(lines) + 1)):
                block.append(nxt)
                text = lines[nxt - 1].rstrip()
                if text.endswith(';') or text.endswith('}'):
                    break
            tags.setdefault(int(m.group(1)), []).append(block)
    return lines, functions, tags


def uart_bits(byte):
    """一个 UART 字节在线上的 10 位：起始位 0、LSB 在前的 8 个数据位、停止位 1。"""
    return [0] + [(byte >> k) & 1 for k in range(8)] + [1]


class Flight:
    """一串字节沿路径依次飞过；每个字节离开 / 到达时回调。space='3d' 或 '2d'（像素坐标）。"""
    def __init__(self, app, labels, points, color, gap=.17, travel=1.0, space='3d',
                 parent=None, on_depart=None, on_arrive=None, text_color=INK, cut=None):
        self.space = space
        if space == '2d':
            points = [(x, 0, -y) for x, y in points]
        self.points = [Vec3(*p) for p in points]
        self.lengths = [(b - a).length() for a, b in zip(self.points, self.points[1:])]
        self.total = sum(self.lengths) or 1
        self.start = time.monotonic()
        self.gap, self.travel = gap, travel
        self.cut = cut  # 0~1：飞到这里就消失（被截断）
        self.on_depart, self.on_arrive = on_depart, on_arrive
        self.tokens = []
        for label in labels:
            tn = TextNode('byte')
            tn.setFont(app.font)
            tn.setText(label)
            tn.setTextColor(*text_color)
            tn.setAlign(TextNode.ACenter)
            tn.setCardColor(*color)
            tn.setCardAsMargin(.28, .28, .14, .10)
            tn.setCardDecal(True)
            np = (parent or (app.render if space == '3d' else app.pixel2d)).attachNewNode(tn)
            if space == '3d':
                np.setScale(.34)
                np.setBillboardPointEye()
                np.setDepthTest(False)
                np.setDepthWrite(False)
                np.setLightOff()
                np.setBin('fixed', 60)
            else:
                np.setScale(13)
                np.setBin('gui-popup', 60)   # 2D：画在放大镜图形之上
            np.hide()
            self.tokens.append([np, False, False])

    @property
    def end_time(self):
        return self.start + self.gap * max(0, len(self.tokens) - 1) + self.travel

    def position(self, ratio):
        distance = self.total * ratio
        for a, b, length in zip(self.points, self.points[1:], self.lengths):
            if distance <= length and length > 0:
                return a + (b - a) * (distance / length)
            distance -= length
        return self.points[-1]

    def update(self, now):
        for i, token in enumerate(self.tokens):
            np, departed, arrived = token
            t = now - (self.start + i * self.gap)
            if t >= 0 and not departed:
                token[1] = True
                if self.on_depart: self.on_depart(i)
            if t < 0 or arrived:
                np.hide(); continue
            ratio = t / self.travel
            if ratio >= (self.cut or 1):
                token[2] = True
                np.hide()
                if self.on_arrive and not self.cut: self.on_arrive(i)
                continue
            np.show()
            lift = Vec3(0, 0, .30) if self.space == '3d' else Vec3(0, 0, -4)
            np.setPos(self.position(ratio) + lift)
        return all(t[2] for t in self.tokens)

    def finish(self):
        self.update(self.end_time + 1)

    def destroy(self):
        for np, *_ in self.tokens:
            np.removeNode()


class Demo(ShowBase):
    def __init__(self, screenshot=False):
        loadPrcFileData('', f'win-size {W} {H}\nwindow-title Serial Actuator Communication Lab\naudio-library-name null\nsync-video true\nframebuffer-multisample 1\nmultisamples 4\ntextures-power-2 none')
        if screenshot:
            loadPrcFileData('', 'window-type offscreen')
        super().__init__()
        self.disableMouse()
        self.setBackgroundColor(*BG)
        self.font = None
        for path in [os.environ.get('SERVO_LAB_FONT', '')] + FONT_CANDIDATES:
            if path and Path(path).exists():
                self.font = self.loader.loadFont(Filename.fromOsSpecific(path).getFullpath())
                if self.font: break
        if not self.font:
            raise RuntimeError('未找到中文字体：请安装中文字体，或设置环境变量 SERVO_LAB_FONT')
        self.font.setPixelsPerUnit(40)
        self.font.setPageSize(2048, 2048)
        self.fw_lines, self.fw_functions, self.fw_tags = load_firmware()
        self.widgets, self.wires = [], {}
        self.motor = Motor()
        self.motor.speed = MOTOR_DEMO_SPEED
        self.motor_start_angle = 180.0
        self.events = []
        self.step_index = -1
        self.running = False
        self.finished = True
        self.flights, self.timers = [], []
        self.step_done_at = 0
        self.packet_bytes = b''
        self.response = None
        self.request = None
        self.kind = 'ping'
        self.camera_yaw = 0
        self.speed = 1
        self.fault = '正常通信'
        self.profile = '推荐：3.3V 逻辑 / 转换器旁路'
        self.active_fault, self.active_profile = self.fault, self.profile
        self.policy_override = False
        self.dir_level = 0
        self.lens_tab = 'mcu'
        self.wave_anim = None
        self.cpu_note = '等待'
        self.seq = None
        self.flow_state = {k: ('', '') for k, *_ in FLOW}
        self.hl_lines = []
        self.reset_fw()
        self.build_scene()
        self.build_ui()
        self.show_code(1, intro=True)
        self.refresh_vars()
        self.refresh_flow()
        self.refresh_motor()
        self.set_preset('ping')
        self.accept('space', self.space_step)
        self.accept('arrow_left', self.rotate_view, [-8])
        self.accept('arrow_right', self.rotate_view, [8])
        self.accept('escape', self.userExit)
        self.taskMgr.add(self.tick, 'demo-tick')
        self.accept('window-event', self.resize_ui)
        self.resize_ui(self.win)

    # ------------------------------------------------------------------ 基础 UI
    def resize_ui(self, window):
        if hasattr(window, 'getProperties'):
            self.windowEvent(window)
        self.pixel2d.setScale(2 / W, 1, 2 / H)
        if window and window.getXSize() and window.getYSize():
            x, y, w, h = VIEW
            self.camLens.setAspectRatio(w * window.getXSize() / W / (h * window.getYSize() / H))

    def space_step(self):
        if not self.raw_entry.guiItem.getFocus():
            self.next_step()

    def text(self, value, x, y, size=17, color=WHITE, wrap=None, parent=None, align=None):
        node = TextNode('ui-text')
        node.setFont(self.font)
        node.setText(value.replace('↔', '<->'))
        node.setTextColor(*color)
        if align: node.setAlign(align)
        if wrap: node.setWordwrap(wrap / size)
        np = (parent or self.pixel2d).attachNewNode(node)
        np.setPos(x, 0, -y)
        np.setScale(size)
        return node

    def panel(self, x, y, w, h, color=CARD, parent=None):
        frame = DirectFrame(parent=parent or self.pixel2d, frameColor=color,
                            frameSize=(0, w, -h, 0), pos=(x, 0, -y))
        self.widgets.append(frame)
        return frame

    def button(self, label, x, y, w, command, color=(0.13,0.21,0.29,1), size=16, h=36, parent=None):
        button = DirectButton(parent=parent or self.pixel2d, text=label, text_font=self.font,
                              text_scale=size, text_fg=WHITE, text_pos=(w/2, -h/2-size*.36),
                              frameSize=(0, w, -h, 0), frameColor=color,
                              pos=(x, 0, -y), relief=1, borderWidth=(0, 0), command=command)
        self.widgets.append(button)
        return button

    def entry(self, value, x, y, w, size=15):
        entry = DirectEntry(parent=self.pixel2d, initialText=value, text_font=self.font,
                            text_fg=WHITE, scale=size, width=w/size, numLines=1,
                            pos=(x, 0, -y), frameColor=(0.02,0.035,0.06,1),
                            cursorKeys=True, focus=0)
        self.widgets.append(entry)
        return entry

    def menu(self, values, x, y, w, callback, size=13):
        menu = DirectOptionMenu(parent=self.pixel2d, items=values, text_font=self.font,
                                text_scale=size, text_fg=WHITE, text_pos=(9, -21),
                                frameSize=(0, w, -30, 0), frameColor=(0.12,0.18,0.25,1),
                                pos=(x, 0, -y), item_text_font=self.font,
                                item_text_scale=size, item_text_fg=WHITE,
                                item_frameColor=(0.12,0.18,0.25,1),
                                item_text_pos=(10, -21), item_frameSize=(0, w, -30, 0),
                                item_relief=1, item_borderWidth=(0, 0),
                                popupMarker_scale=9, popupMarker_pos=(w-10, 0, -15),
                                popupMenu_frameColor=(0.12,0.18,0.25,1),
                                highlightColor=(0.18,0.30,0.40,1), command=callback)
        self.widgets.append(menu)
        return menu

    def world_text(self, value, pos, scale=.3, color=WHITE, on_top=True):
        tn = TextNode('world-label')
        tn.setFont(self.font)
        tn.setText(value)
        tn.setTextColor(*color)
        tn.setAlign(TextNode.ACenter)
        np = self.render.attachNewNode(tn)
        np.setPos(*pos)
        np.setScale(scale)
        np.setBillboardPointEye()
        np.setLightOff()
        if on_top:
            np.setDepthTest(False); np.setDepthWrite(False); np.setBin('fixed', 40)
        return np

    def wrap(self, text, node, width, size):
        """中英混排折行：英文单词/数字不拆开，中文按字折行。"""
        node.clearWordwrap()
        out = []
        for para in text.split('\n'):
            line = ''
            for tok in re.findall(r'[A-Za-z0-9_.()\[\]+\-/:=%µ<>|&~≈]+|\s|.', para):
                trial = line + tok
                if line and node.calcWidth(trial) * size > width:
                    out.append(line.rstrip())
                    line = tok.lstrip()
                else:
                    line = trial
            out.append(line)
        return '\n'.join(out)

    # ------------------------------------------------------------------ 3D 场景
    def wire(self, name, points, color, thickness=5):
        line = LineSegs(name)
        line.setThickness(thickness)
        line.setColor(*color)
        line.moveTo(*points[0])
        for point in points[1:]:
            line.drawTo(*point)
        np = self.render.attachNewNode(line.create())
        np.setLightOff()
        self.wires[name] = np

    def build_scene(self):
        x, y, w, h = VIEW
        dr = self.camNode.getDisplayRegion(0)
        dr.setDimensions(x / W, (x + w) / W, 1 - (y + h) / H, 1 - y / H)
        self.camLens.setAspectRatio(w / h)
        self.camLens.setFov(63)
        self.camLens.setNearFar(.1, 150)
        self.home_view()
        ambient = AmbientLight('ambient')
        ambient.setColor((.70,.74,.82,1))
        self.render.setLight(self.render.attachNewNode(ambient))
        light = DirectionalLight('sun')
        light.setColor((.55,.6,.7,1))
        sun = self.render.attachNewNode(light)
        sun.setHpr(-20, -60, 0)
        self.render.setLight(sun)
        box(self.render, 'table', (0, .3, -.35), (21, 9.6, .25), (.055,.08,.12,1))
        grid = LineSegs()
        grid.setColor(.09,.14,.20,1)
        for gx in range(-10, 11):
            grid.moveTo(gx, -4.4, -.21); grid.drawTo(gx, 5, -.21)
        for gy in range(-4, 6):
            grid.moveTo(-10.4, gy, -.21); grid.drawTo(10.4, gy, -.21)
        self.render.attachNewNode(grid.create()).setLightOff()
        for key, bx, name, sub, color in [
                ('pc', -8.7, '电脑', 'PC', (.13,.24,.35,1)),
                ('mcu', -4.5, 'MCU', 'UART0 · UART1 · DIR_GPIO', (.10,.40,.31,1)),
                ('ls', -.6, '电平转换', '默认旁路', (.42,.30,.15,1)),
                ('buf', 3.4, '三态缓冲器', '三态缓冲器', (.28,.24,.44,1)),
                ('motor', 8.1, '执行器', '电机', (.24,.30,.37,1))]:
            box(self.render, key, (bx, 0, .40), (2.3, 3.0, .6), color)
            self.world_text(name, (bx, 1.55, 1.55), .46)
            self.world_text(sub, (bx, 1.55, 1.10), .30, MUTED)
            if key in ('mcu', 'ls', 'buf'):
                box(self.render, 'chip', (bx, .1, .78), (1.1, 1.0, .16), (.04,.05,.07,1))
        box(self.render, 'screen', (-8.7, .9, 1.35), (1.9, .16, 1.3), (.11,.16,.21,1))
        box(self.render, 'display', (-8.7, .8, 1.40), (1.62, .04, 1.0), (.10,.48,.58,1))
        self.gate_tx = box(self.render, 'gate-tx', (3.4, -1.1, .80), (.9, .38, .14), (1,1,1,1))
        self.gate_rx = box(self.render, 'gate-rx', (3.4, 0, .80), (.9, .38, .14), (1,1,1,1))
        self.gate_tx.setLightOff(); self.gate_rx.setLightOff()
        # 电机：表盘 + 舵盘 + 目标虚影
        mx, my, mz = 8.1, -.2, .72
        dial = LineSegs()
        dial.setThickness(2)
        dial.setColor(.45,.55,.65,1)
        for k in range(0, 361, 6):
            a = math.radians(k)
            p = (mx + 1.0*math.sin(a), my + 1.0*math.cos(a), mz)
            dial.moveTo(*p) if k == 0 else dial.drawTo(*p)
        for k in range(0, 360, 90):
            a = math.radians(k)
            dial.moveTo(mx + .85*math.sin(a), my + .85*math.cos(a), mz)
            dial.drawTo(mx + 1.0*math.sin(a), my + 1.0*math.cos(a), mz)
        self.render.attachNewNode(dial.create()).setLightOff()
        self.ghost = self.render.attachNewNode('ghost')
        self.ghost.setPos(mx, my, mz + .02)
        g = box(self.ghost, 'ghost-horn', (0, .45, 0), (.26, .9, .05), (1, .66, .25, .45))
        g.setTransparency(TransparencyAttrib.MAlpha); g.setLightOff()
        self.horn = self.render.attachNewNode('motor-horn')
        self.horn.setPos(mx, my, mz + .06)
        box(self.horn, 'horn', (0, .42, 0), (.30, 1.0, .14), (.95,.74,.32,1))
        box(self.horn, 'horn-tail', (0, -.15, 0), (.40, .40, .14), (.95,.74,.32,1))
        box(self.horn, 'axis', (0, 0, .10), (.30, .30, .16), (.70,.75,.80,1))
        self.angle_world = self.world_text('180.0°', (8.1, -1.9, .95), .36, GREEN).node()
        z = .86
        self.paths = {
            'usb': [(-8.7,-.5,z),(-7.55,-.5,z),(-5.65,-.5,z),(-4.5,-.5,z)],
            'tx': [(-4.5,-1.1,z),(-3.35,-1.1,z),(-1.75,-1.1,z),(.55,-1.1,z),(2.25,-1.1,z),(3.4,-1.1,z),(4.55,-.55,z),(5.2,0,z),(6.95,0,z),(8.1,0,z)],
            'data_back': [(8.1,0,z),(6.95,0,z),(5.2,0,z),(3.4,0,z)],
            'rx_back': [(3.4,0,z),(2.25,0,z),(.55,0,z),(-1.75,0,z),(-3.35,0,z),(-4.5,0,z)],
            'dir': [(-4.5,1.1,z),(-3.35,1.1,z),(-1.75,1.1,z),(.55,1.1,z),(2.25,1.1,z),(3.4,1.1,z)],
        }
        self.paths['usb_back'] = list(reversed(self.paths['usb']))
        self.wire('usb', [(-7.55,-.5,z),(-5.65,-.5,z)], CYAN)
        for name, ya, col in [('tx', -1.1, ORANGE), ('rx', 0, GREEN), ('dir', 1.1, PURPLE)]:
            self.wire(name+'1', [(-3.35,ya,z),(-1.75,ya,z)], col)
            self.wire(name+'2', [(.55,ya,z),(2.25,ya,z)], col)
        self.wire('data', [(4.55,-.55,z),(5.2,0,z),(6.95,0,z)], CYAN)
        self.wire('data-rx', [(4.55,0,z),(5.2,0,z)], CYAN)
        self.world_text('USB', (-6.6,-.5,1.25), .30, CYAN)
        self.world_text('TX', (-2.55,-1.1,1.20), .30, ORANGE)
        self.world_text('RX', (-2.55,0,1.20), .30, GREEN)
        self.world_text('DIR', (-2.55,1.1,1.20), .30, PURPLE)
        self.world_text('DATA 单线', (6.05,0,1.25), .30, CYAN)
        self.dir_world = self.world_text('DIR = 0 接收', (3.4, -2.25, .9), .30, PURPLE)
        self.wire('gnd', [(-8.7,-1.5,.15),(-8.7,-2.9,.15),(8.1,-2.9,.15),(8.1,-1.5,.15)], DIM, 3)
        for gx in [-4.5, -.6, 3.4]:
            self.wire('gnd'+str(gx), [(gx,-1.5,.15),(gx,-2.9,.15)], DIM, 3)
        self.world_text('GND 所有设备共地', (-.6,-3.35,.2), .26, MUTED, on_top=False)
        box(self.render, '5V', (8.1, 3.6, .35), (2.4, 1.1, .6), (.42,.16,.19,1))
        self.world_text('外部 5V', (8.1, 3.6, 1.05), .30, RED)
        self.wire('power', [(8.1,3.05,.6),(8.1,1.5,.6)], RED, 4)

    def home_view(self):
        yaw = math.radians(self.camera_yaw)
        dist, height = 13.6, 11.6
        self.camera.setPos(dist*math.sin(yaw), -dist*math.cos(yaw), height)
        self.camera.lookAt(0, 1.7, .1)

    def rotate_view(self, amount):
        self.camera_yaw = max(-24, min(24, self.camera_yaw + amount))
        self.home_view()

    # ------------------------------------------------------------------ 面板
    def build_ui(self):
        self.text('执行器通信实验室', 24, 44, 30)
        self.text('硬件、MCU 内部、固件代码三处同步：每个字节走到哪里，代码就停在哪一行。', 25, 78, 16, MUTED)
        self.panel(1270, 22, 310, 44, (.12,.24,.20,1))
        self.text('模拟模式 · 未连接任何实物', 1286, 50, 16, GREEN)

        # ---- 左栏：转到目标角度的流程
        x, y, w, h = LEFT
        self.panel(x, y, w, h)
        cx, cw = x + 14, w - 28
        self.text('01  让电机转到目标角度', cx, y+30, 18)
        self.target_text = self.text('', cx, y+58, 15, ORANGE)
        self.slider = DirectSlider(parent=self.pixel2d, range=(0, 359), value=90, pageSize=1, scale=1,
                                   pos=(cx+cw/2, 0, -(y+80)), frameSize=(-cw/2+6, cw/2-6, -5, 5),
                                   frameColor=(.15,.23,.31,1), thumb_frameSize=(-7,7,-11,11),
                                   thumb_frameColor=ORANGE, command=self.target_change)
        self.auto_btn = self.button('自动走完整流程', cx, y+98, cw, self.start_sequence, (.14,.36,.26,1), size=15, h=34)
        half = (cw - 8) / 2
        self.speed_btns = [self.button('慢速·逐步讲解', cx, y+138, half, lambda: self.set_speed(1), size=12, h=26),
                           self.button('快速', cx+half+8, y+138, half, lambda: self.set_speed(3), size=12, h=26)]
        self.text('点一项 = 只发这一包', cx, y+186, 12, MUTED)
        self.flow_rows = {}
        for i, (kind, title, why) in enumerate(FLOW):
            fy = y + 194 + i * 54
            btn = DirectButton(parent=self.pixel2d, frameSize=(0, cw, -50, 0), frameColor=(.09,.14,.20,1),
                               pos=(cx, 0, -fy), relief=1, borderWidth=(0, 0),
                               command=self.flow_click, extraArgs=[kind])
            mark = self.text('', cx+cw-8, fy+20, 13, MUTED, align=TextNode.ARight)
            t1 = self.text(title, cx+8, fy+20, 13, WHITE)
            t2 = self.text(why, cx+8, fy+40, 11, MUTED)
            self.flow_rows[kind] = (btn, t1, t2, mark)
        fy = y + 194 + len(FLOW) * 54 + 6
        self.text('故障实验', cx, fy+12, 12, MUTED)
        self.fault_menu = self.menu(FAULTS, cx+60, fy-6, cw-60, self.set_fault, 12)
        self.profile_menu = self.menu(['电气：3.3V 逻辑 / 转换器旁路', '电气：示例 5V 缓冲器（待核对）'],
                                      cx, fy+30, cw, self.set_profile, 12)
        # 电机俯视表盘
        self.dial_y = fy + 72
        self.dial_c = (cx + 74, self.dial_y + 62)
        self.dial_root = self.pixel2d.attachNewNode('dial')
        self.dial_root.setPos(self.dial_c[0], 0, -self.dial_c[1])
        r = 54
        ring = [(r*math.sin(math.radians(k)), -r*math.cos(math.radians(k))) for k in range(0, 361, 5)]
        lines2d(self.dial_root, [ring], (.35,.45,.55,1), 2)
        for k, lab in [(0, '0°'), (90, '90°'), (180, '180°'), (270, '270°')]:
            a = math.radians(k)
            lines2d(self.dial_root, [[((r-7)*math.sin(a), -(r-7)*math.cos(a)), (r*math.sin(a), -r*math.cos(a))]], MUTED, 2)
            self.text(lab, (r+12)*math.sin(a), -(r+12)*math.cos(a) + 4, 10, MUTED,
                      align=TextNode.ACenter, parent=self.dial_root)
        self.dial_arc = self.dial_root.attachNewNode('arc')
        self.dial_goal = self.dial_root.attachNewNode('goal')
        poly2d(self.dial_goal, [(-5, -r-2), (5, -r-2), (0, -r+8)], ORANGE)
        lines2d(self.dial_goal, [[(0, 0), (0, -r+6)]], (1, .66, .25, .55), 2)
        self.dial_needle = self.dial_root.attachNewNode('needle')
        poly2d(self.dial_needle, [(-5, 0), (5, 0), (2, -r+6), (-2, -r+6)], GREEN)
        poly2d(self.dial_needle, [(-6, -6), (6, -6), (6, 6), (-6, 6)], (.70,.75,.80,1))
        self.text('电机俯视', cx+158, self.dial_y+20, 13, WHITE)
        self.motor_text = self.text('', cx+158, self.dial_y+44, 13, GREEN)

        # ---- 3D
        vx, vy, vw, vh = VIEW
        self.text('02  硬件', vx+14, vy+30, 19)
        self.text('USB 蓝 · TX 橙 · RX 绿 · DIR 紫 · DATA 青', vx+14, vy+54, 13, MUTED)
        self.text('飞行的方块 = 正在传的字节', vx+vw-14, vy+30, 13, YELLOW, align=TextNode.ARight)
        self.dir_badge = self.panel(vx+14, vy+vh-34, vw-28, 30, (.10,.23,.19,1))
        self.dir_badge_text = self.text('', vx+24, vy+vh-13, 15, GREEN)

        # ---- 放大镜
        x, y, w, h = LENS
        self.lens_frame = self.panel(x, y, w, h)
        self.lens_root = self.pixel2d.attachNewNode('lens')
        self.lens_tok = self.pixel2d.attachNewNode('lens-tokens')
        self.lens_tok.setPos(x, 0, -y)
        self.lens_cursor = self.pixel2d.attachNewNode('lens-cursor')
        self.lens_tabs = {}
        tw = 150
        for i, (key, label) in enumerate([('mcu', 'MCU 内部'), ('buf', '三态缓冲器'), ('wave', '波形')]):
            self.lens_tabs[key] = self.button(label, x + 14 + i*(tw+6), y + 8, tw,
                                              lambda k=key: self.set_lens(k), size=12, h=26)

        # ---- 代码
        x, y, w, h = CODE
        self.panel(x, y, w, h)
        self.text('03  固件  firmware/main.c', x+14, y+30, 19)
        self.code_where = self.text('', x+14, y+56, 13, CYAN)
        self.code_top = y + 72
        self.code_rows = int((h - 80) / 17)
        self.code_bars, self.code_nodes = [], []
        for r in range(self.code_rows):
            bar = DirectFrame(parent=self.pixel2d, frameColor=(0,0,0,0),
                              frameSize=(0, w-12, -17, 0), pos=(x+6, 0, -(self.code_top + r*17)))
            self.code_bars.append(bar)
            num = self.text('', x+40, self.code_top + r*17 + 13, 12, DIM, align=TextNode.ARight)
            code = self.text('', x+48, self.code_top + r*17 + 13, 12.5, MUTED)
            self.code_nodes.append((num, code))

        # ---- 步骤 + 操作
        x, y, w, h = STEP
        self.panel(x, y, w, h)
        self.text('指令包（HEX，可直接修改）', x+14, y+22, 12, MUTED)
        self.raw_entry = self.entry('', x+15, y+44, w-30, 12)
        bw = (w - 28 - 4*6) / 5
        for i, (label, cmd, col) in enumerate([('载入此包', self.load_packet, (.13,.31,.36,1)),
                                               ('下一步', self.next_step, (.18,.27,.43,1)),
                                               ('自动播放', self.toggle_play, (.15,.33,.25,1)),
                                               ('重新播放', self.replay, (.13,.21,.29,1)),
                                               ('恢复初始', self.reset, (.13,.21,.29,1))]):
            btn = self.button(label, x+14+i*(bw+6), y+58, bw, cmd, col, size=13, h=30)
            if label == '自动播放': self.play_btn = btn
        self.step_title = self.text('', x+14, y+122, 17, CYAN)
        self.step_text = self.text('', x+14, y+150, 14, WHITE)
        self.term_text = self.text('', x+14, y+268, 13, YELLOW)

        # ---- 底部字节条
        x, y, w, h = STRIP
        self.panel(x, y, w, h)
        self.text('TX  电脑 → 电机', x+16, y+30, 14, ORANGE)
        self.text('RX  电机 → 电脑', x+16, y+68, 14, GREEN)
        self.tx_cells = self.byte_cells(x+150, y+10, 20, 36, 28, font=14)
        self.rx_strip = self.byte_cells(x+150, y+48, 20, 36, 28, font=14)
        self.decode_text = self.text('', x+w-16, y+30, 14, MUTED, align=TextNode.ARight)
        self.decode_text2 = self.text('', x+w-16, y+66, 14, MUTED, align=TextNode.ARight)
        self.set_speed(1)
        self.target_change()
        self.set_lens('mcu')

    def byte_cells(self, x, y, count, pitch, height, font=12):
        cells = []
        for i in range(count):
            f = DirectFrame(parent=self.pixel2d, frameColor=CARD2,
                            frameSize=(0, pitch-3, -height, 0), pos=(x + i*pitch, 0, -y))
            t = self.text('', x + i*pitch + (pitch-3)/2, y + height/2 + font*.36, font, DIM, align=TextNode.ACenter)
            cells.append((f, t))
        return cells

    @staticmethod
    def paint_cells(cells, values, active=None, color=ORANGE, done_color=WHITE):
        for i, (f, t) in enumerate(cells):
            v = values[i] if i < len(values) else None
            if v is None:
                f['frameColor'] = CARD2; t.setText(''); continue
            t.setText(f'{v:02X}')
            if i == active:
                f['frameColor'] = color; t.setTextColor(*INK)
            else:
                f['frameColor'] = (.10,.15,.21,1); t.setTextColor(*done_color)

    # ------------------------------------------------------------------ 放大镜
    def set_lens(self, tab):
        self.lens_tab = tab
        for key, btn in self.lens_tabs.items():
            btn['frameColor'] = (.24,.36,.50,1) if key == tab else (.10,.15,.21,1)
        self.lens_tok.show() if tab == 'mcu' else self.lens_tok.hide()
        self.draw_lens()

    def draw_lens(self):
        self.lens_root.removeNode()
        self.lens_root = self.pixel2d.attachNewNode('lens')
        x0, y0, w, h = LENS
        self.lens_root.setPos(x0, 0, -y0)
        self.lens_cursor.hide()
        {'mcu': self.draw_mcu, 'buf': self.draw_chip, 'wave': self.draw_wave}[self.lens_tab](self.lens_root)
        self.gate_tx.setColorScale(*(ORANGE if self.dir_level else (.2,.22,.26,1)))
        self.gate_rx.setColorScale(*(GREEN if not self.dir_level else (.2,.22,.26,1)))
        self.dir_world.node().setText('DIR = 1 发送' if self.dir_level else 'DIR = 0 接收')
        hi = self.dir_level == 1
        self.dir_badge['frameColor'] = (.42,.27,.05,1) if hi else (.07,.24,.18,1)
        self.dir_badge_text.setText('DIR  HIGH = 1  约 3.3V  |  TX 门打开，RX 门关闭' if hi else
                                    'DIR  LOW = 0  约 0V  |  TX 输出高阻，RX 门打开')
        self.dir_badge_text.setTextColor(*(YELLOW if hi else GREEN))
        self.dir_world.node().setText('HIGH 1 · 3.3V' if hi else 'LOW 0 · 0V')
        self.dir_world.node().setTextColor(*(YELLOW if hi else GREEN))
        for key in ('dir1','dir2'):
            self.wires[key].setColor(*(YELLOW if hi else (.27,.39,.35,1)), 1)

    def cells2d(self, root, x, y, values, pitch, w, h, color, active=None, size=10, empty=(.06,.09,.13,1)):
        for i, v in enumerate(values):
            cx = x + i * pitch
            if v is None:
                rect2d(root, cx, y, cx + w, y + h, empty)
                continue
            on = (i == active)
            rect2d(root, cx, y, cx + w, y + h, color if on else (.16,.22,.30,1))
            self.text(f'{v:02X}', cx + w/2, y + h/2 + size*.36, size, INK if on else WHITE,
                      align=TextNode.ACenter, parent=root)

    # MCU 内部的几何（放大镜坐标，y 向下）
    CPU_P = (590, 150)
    BUS_Y = 176

    @staticmethod
    def sram_cell(i, rx=False):
        return 124 + i * 37 + 17, (254 if rx else 218)

    @staticmethod
    def fifo1_slot(k):
        """UART1 发送 FIFO 第 k 格（k=0 是队头，靠右挨着移位寄存器）。"""
        return 326 + (15 - k) * 19 + 8.5, 317

    def path_pc_in(self, i):
        cx, cy = self.sram_cell(i)
        return [(0,103),(92,103),(442,103),(590,103),(590,self.BUS_Y),(cx,self.BUS_Y),(cx,cy)]

    def path_to_fifo(self, i, k):
        cx, cy = self.sram_cell(i)
        sx, sy = self.fifo1_slot(k)
        return [(cx,cy),(cx,self.BUS_Y),(590,self.BUS_Y),self.CPU_P,(590,self.BUS_Y),(590,276),(sx,276),(sx,sy)]

    def path_motor_in(self, i):
        cx, cy = self.sram_cell(i, rx=True)
        return [(755,363),(676,363),(478,363),(478,276),(590,276),self.CPU_P,(590,self.BUS_Y),(cx,self.BUS_Y),(cx,cy)]

    def path_to_pc(self, i):
        cx, cy = self.sram_cell(i, rx=True)
        return [(cx,cy),(cx,self.BUS_Y),(590,self.BUS_Y),self.CPU_P,(442,147),(92,147),(0,147)]

    def lane(self, root, x0, y, values, color, active=None, caption='', caption_x=None):
        self.cells2d(root, x0, y - 11, values, 19, 17, 22, color, active=active, size=11)
        if caption:
            self.text(caption, caption_x or (x0 + 16*19 - 2), y - 15, 10, MUTED, align=TextNode.ARight, parent=root)

    def shift_box(self, root, x0, y, val, color):
        rect2d(root, x0, y - 11, x0 + 72, y + 11, color if val is not None else (.05,.08,.11,1))
        self.text('移位寄存器' if val is None else f'{val:02X}', x0 + 36, y + 4.5, 10 if val is None else 13,
                  DIM if val is None else INK, align=TextNode.ACenter, parent=root)

    def pin(self, root, x, y, label, color, left=True):
        rect2d(root, x - 7, y - 6, x + 7, y + 6, (.78,.80,.84,1))
        if left:
            self.text(label, x - 10, y + 4, 10, color, align=TextNode.ARight, parent=root)
        else:
            self.text(label, x + 10, y + 4, 10, color, parent=root)

    def draw_mcu(self, root):
        m, f = self.mcu, self.fw
        rect2d(root, 34, 42, 722, 398, (.06,.10,.10,1))
        lines2d(root, [[(34,42),(722,42),(722,398),(34,398),(34,42)]], (.22,.45,.36,1), 2)
        self.text('MCU 芯片内部', 716, 56, 11, (.45,.75,.62,1), align=TextNode.ARight, parent=root)
        # UART0：电脑侧
        rect2d(root, 48, 60, 446, 168, (.09,.16,.22,1))
        self.text('UART0 · 电脑侧 · 115200', 56, 80, 13, CYAN, parent=root)
        self.shift_box(root, 56, 103, None, CYAN)
        self.lane(root, 138, 103, [None]*16, CYAN, caption='收 · RX FIFO 16 格')
        self.shift_box(root, 56, 147, None, CYAN)
        self.lane(root, 138, 147, [None]*16, CYAN, caption='发 · TX FIFO 16 格')
        self.pin(root, 34, 103, 'HOST_RX', CYAN)
        self.pin(root, 34, 147, 'HOST_TX', CYAN)
        self.text('电脑', 2, 128, 10, CYAN, parent=root)
        # CPU：正在做什么 + 变量
        rect2d(root, 458, 60, 722, 168, (.20,.16,.09,1))
        self.text('CPU · 通用处理器', 468, 80, 13, YELLOW, parent=root)
        self.text(f'正在执行：{self.cpu_note}', 468, 102, 12, WHITE, parent=root)
        b = '--' if f['b'] is None else f'0x{f["b"]:02X}'
        i = '--' if f['i'] is None else f['i']
        self.text(f'n = {f["n"]}    need = {f["need"]}    b = {b}    i = {i}', 468, 124, 12, WHITE, parent=root)
        self.text(f'g_rx 收到 {f["rx_n"]} / {f["rx_need"]}', 468, 144, 12, WHITE, parent=root)
        if f['wait'] is not None:
            self.text(f'等待 millis() − t0 = {f["wait"]}', 468, 162, 11, YELLOW, parent=root)
        # SRAM
        rect2d(root, 48, 184, 722, 272, (.11,.11,.19,1))
        self.text('SRAM（内存）', 56, 200, 12, (.72,.68,.96,1), parent=root)
        self.text('g_buf[]', 56, 222, 13, ORANGE, parent=root)
        self.text('g_rx[]', 56, 258, 13, GREEN, parent=root)
        for rx, vals, active, col in ((False, f['buf'], f['i'], ORANGE), (True, f['rx'], f['rx_i'], GREEN)):
            for k in range(16):
                cx, cy = self.sram_cell(k, rx)
                v = vals[k] if k < len(vals) else None
                on = v is not None and k == active
                rect2d(root, cx - 16, cy - 11, cx + 16, cy + 11,
                       col if on else (.18,.19,.30,1) if v is not None else (.08,.08,.13,1))
                if v is not None:
                    self.text(f'{v:02X}', cx, cy + 4.5, 12, INK if on else WHITE, align=TextNode.ACenter, parent=root)
        self.text('CPU 经 APB 总线读写 UART 寄存器、读写 SRAM', 716, 200, 10, DIM, align=TextNode.ARight, parent=root)
        # UART1 发送状态 + GPIO
        e, ef = f['txempty'], f['txemptyf']
        rect2d(root, 48, 280, 304, 380, (.10,.10,.16,1))
        self.text('UART1 发送状态（教学信号）', 56, 298, 12, MUTED, parent=root)
        rect2d(root, 56, 308, 70, 322, YELLOW if e else (.2,.2,.24,1))
        self.text(f'FIFO_EMPTY = {e}  队列空', 78, 320, 12, YELLOW if e else MUTED, parent=root)
        rect2d(root, 56, 332, 70, 346, GREEN if ef else (.2,.2,.24,1))
        self.text(f'TX_COMPLETE = {ef}  真正发完', 78, 344, 12, GREEN if ef else MUTED, parent=root)
        self.text('GPIO DIR_GPIO（DIR）', 56, 370, 12, PURPLE, parent=root)
        rect2d(root, 170, 357, 230, 377, PURPLE if self.dir_level else (.14,.12,.22,1))
        self.text(str(self.dir_level), 200, 373, 14, INK if self.dir_level else MUTED, align=TextNode.ACenter, parent=root)
        lines2d(root, [[(230, 367), (304, 367), (304, 388), (722, 388)]], PURPLE if self.dir_level else (.42,.36,.58,1), 2)
        # UART1：电机侧
        rect2d(root, 316, 280, 722, 380, (.17,.12,.08,1))
        self.text('UART1 · 电机侧 · 57600', 324, 298, 13, ORANGE, parent=root)
        q = m['txq']
        slots = [None]*16
        for k, v in enumerate(q[:16]):
            slots[15 - k] = v
        self.lane(root, 326, 317, slots, ORANGE, active=15 if q else None, caption='发 · TX FIFO（队头在右）', caption_x=630)
        self.shift_box(root, 640, 317, m['shift1'], ORANGE)
        self.lane(root, 326, 363, [None]*16, GREEN, caption='收 · RX FIFO', caption_x=630)
        self.shift_box(root, 640, 363, None, GREEN)
        self.pin(root, 722, 317, 'ACT_TX', ORANGE, left=False)
        self.pin(root, 722, 363, 'ACT_RX', GREEN, left=False)
        self.pin(root, 722, 388, 'DIR_GPIO', PURPLE, left=False)

    def draw_chip(self, root):
        hi = self.dir_level == 1
        tx_on, rx_on = hi, not hi
        root = root.attachNewNode('chip')
        root.setPos(200, 0, -30)
        # Large voltage indicator and edge trace, visible without the step log.
        self.text('DIR 引脚电平', -172, 65, 17, WHITE, parent=root)
        self.text('HIGH  1' if hi else 'LOW  0', -172, 105, 27, YELLOW if hi else GREEN, parent=root)
        self.text('约 3.3V' if hi else '约 0V', -172, 136, 20, YELLOW if hi else GREEN, parent=root)
        rect2d(root, -125, 156, -88, 268, (.05,.07,.10,1))
        rect2d(root, -125, 156 if hi else 265, -88, 268, YELLOW if hi else GREEN)
        self.text('3.3V', -80, 166, 13, MUTED, parent=root)
        self.text('0V', -80, 268, 13, MUTED, parent=root)
        points = [(-172,307),(-135,307),(-135,282),(-30,282)] if hi else [(-172,282),(-135,282),(-135,307),(-30,307)]
        lines2d(root,[points],YELLOW if hi else GREEN,5)
        self.text('上升沿：拉高' if hi else '低电平：接收', -172, 337, 14, YELLOW if hi else GREEN, parent=root)
        self.text('电压示意，非实物测量', -172, 362, 10, MUTED, parent=root)
        self.text(f'DIR = {self.dir_level}', 324, 34, 22, PURPLE if hi else (.55,.47,.75,1),
                  align=TextNode.ARight, parent=root)
        cx0, cx1, cy0, cy1 = 92, 250, 50, 232
        poly2d(root, [(cx0,cy0),(cx1,cy0),(cx1,cy1),(cx0,cy1)], (.16,.14,.26,1))
        lines2d(root, [[(cx0,cy0),(cx1,cy0),(cx1,cy1),(cx0,cy1),(cx0,cy0)]], (.40,.34,.60,1), 2)
        ty, ry, dy = 80, 188, 134
        self.text('MCU TX', 8, ty+5, 13, ORANGE, parent=root)
        self.text('DIR', 8, dy+5, 13, PURPLE, parent=root)
        self.text('MCU RX', 8, ry+5, 13, GREEN, parent=root)
        dir_col = PURPLE if hi else (.42,.36,.58,1)
        lines2d(root, [[(62,ty),(140,ty)]], ORANGE, 3)
        lines2d(root, [[(34,dy),(160,dy)], [(160,dy),(160,ty+22)], [(160,dy),(160,ry-22)]], dir_col, 4 if hi else 3)
        tri = [(140,ty-20),(140,ty+20),(182,ty)]
        if tx_on:
            poly2d(root, tri, ORANGE)
            lines2d(root, [[(182,ty),(316,ty)]], ORANGE, 4)
        else:
            lines2d(root, [tri+[tri[0]]], DIM, 2)
            lines2d(root, [[(182,ty),(200,ty)], [(200,ty),(222,ty-14)], [(232,ty),(316,ty)]], DIM, 2)
            self.text('断开·高阻', 196, ty-22, 11, MUTED, parent=root)
        tri = [(182,ry-20),(182,ry+20),(140,ry)]
        if rx_on:
            poly2d(root, tri, GREEN)
            lines2d(root, [[(62,ry),(140,ry)], [(182,ry),(316,ry)]], GREEN, 4)
        else:
            lines2d(root, [tri+[tri[0]]], DIM, 2)
            lines2d(root, [[(62,ry),(110,ry)], [(120,ry-14),(140,ry)], [(182,ry),(316,ry)]], DIM, 2)
            self.text('断开·高阻', 128, ry+38, 11, MUTED, parent=root)
        bubble = [(160+4*math.cos(a/8*math.pi*2), ry-25+4*math.sin(a/8*math.pi*2)) for a in range(9)]
        lines2d(root, [bubble], dir_col, 2)
        lines2d(root, [[(316,ty),(316,ry)]], CYAN, 3)
        self.text('DATA', 322, dy+5, 12, CYAN, parent=root)
        self.text('5 A2', 96, ty-6, 11, MUTED, parent=root)
        self.text('3 Y2', 216, ty+18, 11, MUTED, parent=root)
        self.text('6 Y1', 96, ry-8, 11, MUTED, parent=root)
        self.text('2 A1', 216, ry-8, 11, MUTED, parent=root)
        self.text(f'7 OE2={"高" if hi else "低"}', 168, 114, 11, WHITE if hi else MUTED, parent=root)
        self.text(f'1 /OE1={"高" if hi else "低"}', 168, 164, 11, WHITE if hi else MUTED, parent=root)
        self.text(('发送门：开' if tx_on else '发送门：关（高阻）') + '   ← 7脚 OE2 高电平才开',
                  8, 274, 14, ORANGE if tx_on else MUTED, parent=root)
        self.text(('接收门：开' if rx_on else '接收门：关') + '   ← 1脚 /OE1 低电平才开',
                  8, 302, 14, GREEN if rx_on else MUTED, parent=root)
        self.text('同一根 DIR 接两个脚，所以两扇门永远一开一关。', 8, 334, 12, MUTED, parent=root)

    # 波形：最后两个字节
    WAVE_X0, WAVE_X1, WAVE_BITS = 150, 735, 26

    def wave_x(self, t):
        return self.WAVE_X0 + (self.WAVE_X1 - self.WAVE_X0) * t / self.WAVE_BITS

    def wave_times(self):
        """时间单位 = 位。空闲 1 位，倒数第 2 字节 10 位，最后 1 字节 10 位。"""
        t_empty = 11            # 最后一个字节进移位寄存器：FIFO_EMPTY=1
        t_emptyf = 21           # 最后一个停止位结束：TX_COMPLETE=1
        return t_empty, t_emptyf, t_emptyf + .6

    def draw_wave(self, root):
        raw = self.packet_bytes or packet(1, 1)
        a, b = raw[-2], raw[-1]
        tA, tF, tDir = self.wave_times()
        bad = self.active_fault == '只等 FIFO_EMPTY 就切 DIR'
        X = self.wave_x
        self.text('UART1 TX 最后 2 个字节（1 位 ≈ 17.4µs）', 14, 56, 12, WHITE, parent=root)
        rows = [('ACT_TX TX', 92, ORANGE), ('FIFO_EMPTY', 148, YELLOW), ('TX_COMPLETE', 186, GREEN),
                ('DIR_GPIO DIR', 224, PURPLE), ('错误写法 DIR', 262, RED)]
        for lab, yy, col in rows:
            self.text(lab, 14, yy + 4, 11, col if (lab != '错误写法 DIR' or bad) else (.6,.35,.38,1), parent=root)
        # TX 波形
        bits = [1] + uart_bits(a) + uart_bits(b) + [1] * 5
        hi_y, lo_y = 80, 104
        pts = []
        for k, v in enumerate(bits):
            yv = hi_y if v else lo_y
            pts += [(X(k), yv), (X(k + 1), yv)]
        lines2d(root, [pts], ORANGE, 2)
        for k in range(1, 22):
            lines2d(root, [[(X(k), hi_y - 2), (X(k), lo_y + 2)]], (.25,.3,.38,.6), 1)
        self.text(f'{a:02X}', X(6), 74, 11, ORANGE, align=TextNode.ACenter, parent=root)
        self.text(f'{b:02X}（最后一字节）', X(16), 74, 11, ORANGE, align=TextNode.ACenter, parent=root)
        for k, lab in enumerate(['起'] + [str(v) for v in uart_bits(b)[1:9]] + ['停']):
            self.text(lab, X(11 + k + .5), 120, 9, MUTED, align=TextNode.ACenter, parent=root)
        if bad:
            rect2d(root, X(tA), hi_y - 4, X(tF), lo_y + 4, (1, .3, .35, .22))
            self.text('这一字节被截断', X(16), 136, 11, RED, align=TextNode.ACenter, parent=root)

        def digital(yy, t_change, start, col, thick=2):
            h0, h1 = yy - 10, yy + 8
            y_start = h0 if start else h1
            y_end = h1 if start else h0
            lines2d(root, [[(X(0), y_start), (X(t_change), y_start), (X(t_change), y_end), (X(self.WAVE_BITS), y_end)]], col, thick)
        digital(148, tA, 0, YELLOW)
        digital(186, tF, 0, GREEN)
        digital(224, tDir, 1, PURPLE if not bad else (.42,.36,.58,1), 2)
        digital(262, tA + .3, 1, RED if bad else (.5,.3,.33,1), 2)
        for t, col, mark in ((tA, YELLOW, '①'), (tF, GREEN, '②')):
            for yy in range(66, 276, 8):
                lines2d(root, [[(X(t), yy), (X(t), yy + 4)]], col, 1)
            self.text(mark, X(t), 64, 12, col, align=TextNode.ACenter, parent=root)
        notes = ['① FIFO_EMPTY=1：队列空了，但最后一字节刚进移位寄存器，还在发',
                 '② TX_COMPLETE=1：最后的停止位发完——这时才能把 DIR 拉低',
                 '红线：只等 ① 就切 DIR，最后一字节被砍掉 → 电机 CRC 对不上，不回复']
        for i, n in enumerate(notes):
            self.text(n, 14, 296 + i*19, 11, [YELLOW, GREEN, RED if bad else MUTED][i], parent=root)
        self.text('实物确认：示波器 CH1 夹 DATA，CH2 夹 DIR_GPIO，用 CH2 下降沿触发；', 14, 360, 11, CYAN, parent=root)
        self.text('下降沿必须落在最后一个停止位（高电平）结束之后。', 14, 378, 11, CYAN, parent=root)
        # 光标
        self.lens_cursor.removeNode()
        self.lens_cursor = root.attachNewNode('cursor')
        lines2d(self.lens_cursor, [[(0, 64), (0, 276)]], YELLOW, 2)
        self.cursor_label = self.text('', 4, 284, 10, YELLOW, parent=self.lens_cursor)
        self.lens_cursor.hide()

    def set_wave_cursor(self, t):
        if self.lens_tab != 'wave' or self.lens_cursor.isEmpty():
            return
        self.lens_cursor.show()
        self.lens_cursor.setX(self.wave_x(t))

    def flash_lens(self):
        self.lens_frame['frameColor'] = (.20,.15,.33,1)
        self.timers.append((time.monotonic() + .9, lambda: self.lens_frame.__setitem__('frameColor', CARD)))

    # ------------------------------------------------------------------ 代码与变量
    def show_code(self, step, intro=False, note=''):
        title, _, _, func, where = STEPS[step]
        self.code_where.setText(where + ('' if not note else '   ' + note))
        start, end = self.fw_functions.get(func, (1, len(self.fw_lines)))
        blocks = list(self.fw_tags.get(step, []))
        focus = [b for b in blocks if start <= b[0] <= end] or blocks
        hl = set() if intro else {n for b in blocks for n in b}
        center = focus[0][0] if focus else start
        top = max(1, min(center - self.code_rows // 3, len(self.fw_lines) - self.code_rows + 1))
        for r, (num, code) in enumerate(self.code_nodes):
            no = top + r
            line = self.fw_lines[no - 1] if no <= len(self.fw_lines) else ''
            num.setText(str(no) if no <= len(self.fw_lines) else '')
            code.setText(line.replace('\t', '    '))
            on = no in hl
            is_comment = line.strip().startswith('/*') or line.strip().startswith('//')
            self.code_bars[r]['frameColor'] = (.30,.24,.10,1) if on else (0,0,0,0)
            code.setTextColor(*(YELLOW if on and is_comment else WHITE if on else
                                (.45,.56,.66,1) if is_comment else (.74,.82,.90,1)))
            num.setTextColor(*(YELLOW if on else DIM))
        self.hl_lines = sorted(hl)

    def reset_fw(self):
        self.fw = {'buf': [], 'rx': [], 'n': 0, 'need': 7, 'i': None, 'b': None,
                   'txempty': 1, 'txemptyf': 1, 'wait': None, 'rx_n': 0, 'rx_need': 7,
                   'rx_i': None, 'tx_active': None, 'rx_active': None, 'pc_rx': []}
        self.mcu = {'txq': [], 'shift1': None}
        self.cpu_note = '等待'

    def refresh_vars(self):
        f = self.fw
        self.paint_cells(self.tx_cells, list(self.packet_bytes) if self.packet_bytes else [], f['tx_active'], ORANGE)
        self.paint_cells(self.rx_strip, f['pc_rx'], f['rx_active'], GREEN)
        if self.lens_tab in ('mcu', 'buf'):
            self.draw_lens()

    # ------------------------------------------------------------------ 流程（转到目标角度）
    def goal_ticks(self):
        return round(self.slider['value'] * 4096 / 360) % 4096

    def target_change(self):
        if not hasattr(self, 'flow_rows'):
            return
        deg = round(self.slider['value'])
        self.target_text.setText(f'目标 {deg}° = {self.goal_ticks()} ticks')
        self.flow_rows['goal'][2].setText(f'{deg}° × 4096 ÷ 360 = {self.goal_ticks()}（4 字节，低位在前）')

    def set_speed(self, speed):
        self.speed = speed
        for i, btn in enumerate(self.speed_btns):
            btn['frameColor'] = (.24,.36,.50,1) if (speed == 1) == (i == 0) else (.10,.15,.21,1)

    def refresh_flow(self):
        for kind, (btn, t1, t2, mark) in self.flow_rows.items():
            state, note = self.flow_state[kind]
            current = self.kind == kind and not self.finished
            btn['frameColor'] = ((.22,.20,.10,1) if current else (.08,.20,.15,1) if state == 'ok'
                                 else (.25,.10,.12,1) if state == 'fail' else (.09,.14,.20,1))
            mark.setText({'ok': '√', 'fail': '×', 'run': '…'}.get(state, ''))
            mark.setTextColor(*(GREEN if state == 'ok' else RED if state == 'fail' else YELLOW))
            if note:
                t2.setText(note); t2.setTextColor(*(GREEN if state == 'ok' else RED if state == 'fail' else YELLOW))
            else:
                why = dict((k, w) for k, _, w in FLOW)[kind]
                if kind == 'goal':
                    why = f'{round(self.slider["value"])}° × 4096 ÷ 360 = {self.goal_ticks()}（4 字节，低位在前）'
                t2.setText(why); t2.setTextColor(*MUTED)

    def flow_click(self, kind):
        self.seq = None
        self.auto_btn['text'] = '自动走完整流程'
        self.set_preset(kind)
        if self.load_packet():
            self.running = True
            self.play_btn['text'] = '暂停'

    def start_sequence(self):
        if self.seq:
            self.seq = None
            self.auto_btn['text'] = '自动走完整流程'
            self.running = False
            return
        self.flow_state = {k: ('', '') for k, *_ in FLOW}
        self.seq = {'idx': 0, 'polls': 0, 'next_at': 0}
        self.auto_btn['text'] = '■ 停止流程'
        self.flow_click_seq('ping')

    def flow_click_seq(self, kind):
        self.set_preset(kind)
        if self.load_packet():
            self.running = True
            self.play_btn['text'] = '暂停'

    def seq_next(self):
        """一包结束后决定下一包。返回下一包的 kind；None 表示流程结束。"""
        s = self.seq
        if not s:
            return None
        state, _ = self.flow_state[self.kind]
        if state != 'ok':
            self.seq = None
            self.auto_btn['text'] = '自动走完整流程'
            self.set_step_text('流程中断', f'「{dict((k, t) for k, t, _ in FLOW)[self.kind]}」没有拿到正确回包，后面的步骤不再发。先排除这一步的问题。')
            return None
        if self.kind == 'pos':
            if abs(self.last_position - self.goal_ticks()) <= 2 or s['polls'] >= 8:
                self.seq = None
                self.auto_btn['text'] = '自动走完整流程'
                return None
            s['polls'] += 1
            return 'pos'
        s['idx'] += 1
        if s['idx'] >= len(AUTO_FLOW):
            self.seq = None
            self.auto_btn['text'] = '自动走完整流程'
            return None
        return AUTO_FLOW[s['idx']]

    def packet_result(self, ok, note):
        if self.kind == 'pos' and self.seq:
            note = f'第 {self.seq["polls"] + 1} 次：' + note
        self.flow_state[self.kind] = ('ok' if ok else 'fail', note)
        self.refresh_flow()
        if self.seq:
            self.seq['next_at'] = time.monotonic() + (1.2 if self.kind == 'pos' else 1.6) / self.speed

    # ------------------------------------------------------------------ 控制
    def set_fault(self, value):
        self.fault = value

    def set_profile(self, value):
        self.profile = value

    def set_step_text(self, title, body='', term=''):
        w = STEP[2] - 28
        self.step_title.setText(self.wrap(title, self.step_title, w, 17))
        self.step_text.setText(self.wrap(body, self.step_text, w, 14))
        self.term_text.setText(self.wrap(term, self.term_text, w, 13))

    def set_preset(self, kind):
        presets = {'ping': lambda: packet(1, 1),
                   'mode': lambda: read(11, 1),
                   'on': lambda: write(64, b'\x01'),
                   'off': lambda: write(64, b'\x00'),
                   'pos': lambda: read(132, 4),
                   'goal': lambda: write(116, self.goal_ticks().to_bytes(4, 'little'))}
        self.kind = kind
        self.raw_entry.enterText(hexline(presets[kind]()))
        self.set_step_text('包已生成', '点「载入此包」，再单步或自动播放。')

    def later(self, delay, fn):
        self.timers.append((time.monotonic() + delay / self.speed, fn))

    def fly(self, labels, path, color, gap=.17, travel=1.0, **kw):
        points = self.paths[path] if isinstance(path, str) else path
        kw.setdefault('parent', self.lens_tok if kw.get('space') == '2d' else None)
        fl = Flight(self, labels, points, color, gap=gap / self.speed, travel=travel / self.speed, **kw)
        self.flights.append(fl)
        return fl

    def clear_motion(self):
        for fl in self.flights:
            fl.destroy()
        self.flights = []
        self.timers = []
        self.wave_anim = None

    def settle(self):
        """跳到下一步前，把上一步还在飞的字节和延时事件立刻做完。"""
        for _ in range(200):
            if not self.flights and not self.timers and not self.wave_anim:
                break
            if self.wave_anim:
                *_, done = self.wave_anim
                self.wave_anim = None
                if done: done()
            for fl in list(self.flights):
                fl.finish()
                fl.destroy()
                self.flights.remove(fl)
            for item in sorted(self.timers, key=lambda t: t[0]):
                if item in self.timers:
                    self.timers.remove(item)
                    item[1]()
        self.clear_motion()

    def load_packet(self):
        try:
            raw = from_hex(self.raw_entry.get())
            request = parse(raw)
            if request.instruction not in (1, 2, 3):
                raise ValueError('本演示只支持 Ping(01)、Read(02)、Write(03)。')
            if len(raw) > MAX_BYTES:
                raise ValueError(f'本演示一次最多 {MAX_BYTES} 字节（= 发送 FIFO 深度）。')
        except ValueError as exc:
            self.set_step_text('输入未发送', str(exc))
            return False
        if self.fault == 'ID 不匹配' and request.device_id == self.motor.device_id:
            raw = packet(2, request.instruction, request.params)
            request = parse(raw)
            self.raw_entry.enterText(hexline(raw))
        self.clear_motion()
        self.packet_bytes = raw
        self.request = request
        self.active_fault = self.fault
        self.active_profile = self.profile
        self.response = None
        self.events = []
        self.step_index = -1
        self.running = False
        self.finished = False
        self.step_done_at = 0
        self.play_btn['text'] = '自动播放'
        if self.active_fault == 'Write 不返回 Status':
            self.motor.return_level = 1
            self.policy_override = True
        elif self.policy_override:
            self.motor.return_level = 2
            self.policy_override = False
        self.dir_level = 0
        self.reset_fw()
        length = int.from_bytes(raw[5:7], 'little')
        self.decode_text.setText(f'ID {request.device_id} · 指令 {request.instruction:02X} · 长度 {length} · CRC {hexline(raw[-2:])} OK')
        self.decode_text2.setText('等待回复……')
        self.flow_state[self.kind] = (self.flow_state[self.kind][0], '')
        self.show_code(1, intro=True)
        self.set_lens('mcu')
        self.refresh_vars()
        self.refresh_flow()
        self.set_step_text('已载入', '点「下一步」或「自动播放」。代码面板会停在 MCU 正在执行的那一行。')
        return True

    def replay(self):
        self.load_packet()

    def reset(self):
        self.clear_motion()
        self.seq = None
        self.auto_btn['text'] = '自动走完整流程'
        self.motor = Motor()
        self.motor.speed = MOTOR_DEMO_SPEED
        self.motor_start_angle = 180.0
        self.policy_override = False
        self.packet_bytes = b''
        self.response = None
        self.finished = True
        self.running = False
        self.step_index = -1
        self.events = []
        self.dir_level = 0
        self.reset_fw()
        self.flow_state = {k: ('', '') for k, *_ in FLOW}
        self.fault_menu.set(0)
        self.profile_menu.set(0)
        self.decode_text.setText('')
        self.decode_text2.setText('')
        self.play_btn['text'] = '自动播放'
        self.show_code(1, intro=True)
        self.set_lens('mcu')
        self.refresh_vars()
        self.refresh_motor()
        self.set_preset('ping')
        self.refresh_flow()
        self.set_step_text('已恢复初始状态', '模拟电机：ID 1 · 扭矩关闭 · 180°。')

    def toggle_play(self):
        if self.finished:
            if not self.load_packet(): return
        self.running = not self.running
        self.play_btn['text'] = '暂停' if self.running else '自动播放'
        self.step_done_at = 0

    def record(self, step, title=None, body=None, term=None):
        t, b, tm, *_ = STEPS[step]
        title, body, term = title or t, body if body is not None else b, term if term is not None else tm
        self.events.append({'step': step, 'elapsed_s': round(time.monotonic() - self.started, 3),
                            'title': title, 'detail': body, 'firmware_lines': self.hl_lines})
        self.set_step_text(f'{step:02d}/12  {title}', body, term)

    def stop(self, note, no_response=True):
        self.finished = True
        self.running = False
        self.play_btn['text'] = '自动播放'
        if no_response:
            self.decode_text2.setText('超时：没有收到有效状态包')
        self.term_text.setText(self.wrap(note, self.term_text, STEP[2] - 28, 13))
        self.last_position = getattr(self, 'last_position', 0)
        self.packet_result(False, '没有收到有效回包')

    # ------------------------------------------------------------------ 12 步
    def next_step(self):
        if self.finished:
            if not self.load_packet(): return
        self.settle()
        self.step_index += 1
        step = self.step_index + 1
        f, m = self.fw, self.mcu
        raw = self.packet_bytes
        labels = [f'{b:02X}' for b in raw]
        self.set_lens(LENS_FOR_STEP[step])
        bad_tx = self.active_fault == '只等 FIFO_EMPTY 就切 DIR'
        if step == 1:
            self.started = time.monotonic()
            self.cpu_note = '空等 RX'
            self.show_code(1)
            self.record(1)
        elif step == 2:
            self.show_code(2)
            f['buf'], f['n'], f['need'] = [None] * len(raw), 0, 7
            self.cpu_note = 'UART_READ'

            def in_sram(i):
                f['buf'][i] = raw[i]; f['n'] = i + 1; f['b'] = raw[i]; f['i'] = i
                if f['n'] == 7: f['need'] = 7 + int.from_bytes(raw[5:7], 'little')
                self.refresh_vars()

            def at_mcu(i):
                f['tx_active'] = i
                self.fly([labels[i]], self.path_pc_in(i), CYAN, travel=1.1, space='2d',
                         on_arrive=lambda _, i=i: in_sram(i))
            self.fly(labels, 'usb', CYAN, gap=.32, travel=1.0, on_arrive=at_mcu)
            self.record(2)
        elif step == 3:
            f['i'] = None; f['tx_active'] = None
            self.cpu_note = 'n == need ?'
            self.show_code(3)
            length = int.from_bytes(raw[5:7], 'little')
            self.record(3, body=STEPS[3][1] + f'  本包：长度 = {raw[5]:02X} {raw[6]:02X} → {length}，need = 7 + {length} = {f["need"]}。')
        elif step == 4:
            self.show_code(4)
            self.cpu_note = 'gpio_write_dir(1)'

            def dir_up(i):
                self.dir_level = 1; self.flash_lens(); self.refresh_vars()
            self.fly(['1'], 'dir', PURPLE, travel=.9, on_arrive=dir_up)
            self.record(4)
        elif step == 5:
            self.show_code(5)
            self.cpu_note = 'UART_WRITE'
            f['txempty'], f['txemptyf'] = 0, 0
            m['txq'], m['shift1'] = [], None
            last = len(raw) - 1

            def into_fifo(i):
                m['txq'].append(raw[i]); f['i'] = i; f['b'] = raw[i]
                self.refresh_vars()
                if i == last:
                    self.cpu_note = '写完，往下走'
                    self.later(.2, drain)

            def drain():
                if not m['txq']:
                    return
                byte = m['txq'].pop(0)
                m['shift1'] = byte
                idx = len(raw) - 1 - len(m['txq'])
                f['tx_active'] = idx
                if not m['txq']:
                    f['txempty'] = 1          # 队列空了，最后一字节还在移位寄存器
                    self.refresh_vars()
                    return
                self.refresh_vars()
                self.later(.35, lambda: out_pin(byte))
                self.later(.55, drain)

            def out_pin(byte):
                m['shift1'] = None
                self.refresh_vars()
                self.fly([f'{byte:02X}'], [(676,317),(755,317)], ORANGE, travel=.25, space='2d',
                         on_arrive=lambda _: self.fly([f'{byte:02X}'], 'tx', ORANGE, travel=1.5))

            for i in range(len(raw)):
                self.fly([labels[i]], self.path_to_fifo(i, i), ORANGE,
                         travel=.8, space='2d', on_arrive=lambda _, i=i: into_fifo(i)).start += i * .15 / self.speed
            self.record(5)
        elif step == 6:
            f['i'] = None
            tA, tF, _ = self.wave_times()
            last = raw[-1]
            if bad_tx:
                self.show_code(6, note='（错误写法：只等 FIFO_EMPTY）')
                self.cpu_note = '只看 FIFO_EMPTY'
                self.record(6, '错误写法：只等 FIFO_EMPTY', 'FIFO_EMPTY 已经是 1，while 立刻结束，马上去拉低 DIR。可最后一个字节 ' + f'{last:02X}' + ' 还在移位寄存器里，只发出了起始位。看波形红线。',
                            '正确写法等 TX_COMPLETE，见代码第 06 步。')
                self.wave_anim = (time.monotonic(), .5 / self.speed, tA - 1, tA + .3, None)
            else:
                self.show_code(6)
                self.cpu_note = '等 TX_COMPLETE'

                def done():
                    f['txemptyf'] = 1
                    m['shift1'] = None
                    f['tx_active'] = None
                    self.refresh_vars()
                    self.fly([f'{last:02X}'], 'tx', ORANGE, travel=1.5)
                self.wave_anim = (time.monotonic(), 2.2 / self.speed, tA - .5, tF + .8, done)
                self.record(6)
        elif step == 7:
            if self.active_fault == 'DIR 未切回接收':
                self.show_code(7, note='（故障：这一行没被执行）')
                self.record(7, '故障：DIR 仍然是 1', '这一行被跳过，DIR 还是高电平：发送门一直开着占住 DATA，接收门一直关着，电机回话进不来。')
            else:
                self.show_code(7)
                self.cpu_note = 'gpio_write_dir(0)'

                def dir_down(i):
                    self.dir_level = 0; self.flash_lens(); self.refresh_vars()
                self.fly(['0'], 'dir', PURPLE, travel=.9, on_arrive=dir_down)
                if bad_tx:
                    self.set_lens('wave')
                    f['txemptyf'] = 1; m['shift1'] = None; f['tx_active'] = None
                    self.fly([f'{raw[-1]:02X}'], 'tx', RED, travel=1.5, cut=.45)
                    self.record(7, 'DIR 拉低太早：最后一字节被截断', '发送门关上时，最后一个字节只发了一部分。电机收到的包少了半个字节，CRC 一定对不上。红色字节在缓冲器前消失。')
                else:
                    self.record(7)
        elif step == 8:
            self.show_code(8)
            self.cpu_note = '等电机回包'
            f['wait'] = '0 ms'
            if self.active_profile.startswith('电气：示例'):
                self.record(8, '电平风险：无法判定通信可靠', '假设 5V 缓冲器的高电平门限为 3.5V，而示例执行器回复只有 3.3V：可能无法正确识别。', '这是保守的风险提示，不是模拟测得电路一定失败。')
                self.stop('先核对电平、转换器和示波器波形。'); self.refresh_vars(); return
            dead = {'电机未供电': '电机没有外部 5V 电源，不能回复。',
                    '没有共地': '缺少共同的电压参考，本模拟按通信失败处理；实物行为不确定。',
                    '传输中 CRC 损坏': '线路把字节传错了，CRC 对不上，电机不执行也不回复。',
                    '只等 FIFO_EMPTY 就切 DIR': '最后一字节被截断，CRC 对不上，电机丢掉整包，不执行也不回复。'}
            if self.active_fault in dead:
                self.show_code(9, note='→ 20ms 后超时 return 0')
                f['wait'] = '21 ms > 20 ms 超时'
                self.record(8, '电机没有返回有效包', dead[self.active_fault] + ' MCU 等满 20ms，read_packet() 返回 0，什么也不发给电脑。')
                self.stop(dead[self.active_fault]); self.refresh_vars(); return
            before = self.motor.position
            self.response, note = self.motor.reply(self.request)
            extra = ''
            ins = self.request.instruction
            is_goal = ins == 3 and int.from_bytes(self.request.params[:2], 'little') in (116, 64)
            if is_goal and self.motor.moving and abs(self.motor.goal - before) > 1:
                self.motor_start_angle = before * 360 / 4096
                extra = f'\n电机开始转：{before*360/4096:.0f}° → {self.motor.goal*360/4096:.0f}°（看左下表盘和 3D 舵盘）'
            self.record(8, body=STEPS[8][1] + '\n电机：' + note + extra)
            if self.response is None:
                self.show_code(9, note='→ 超时 return 0')
                f['wait'] = '21 ms > 20 ms 超时'
                self.finished = True; self.running = False; self.play_btn['text'] = '自动播放'
                self.decode_text2.setText('没有回包（Status Return Level 设置所致）')
                self.last_position = self.motor.position
                self.packet_result(True, '已执行，但按设置不回包')
            else:
                f['rx_need'] = len(self.response)
            self.refresh_vars()
            return
        elif step == 9:
            self.show_code(9)
            self.cpu_note = '等电机回包'
            f['wait'] = '0.5 ms'
            rlabels = [f'{b:02X}' for b in self.response]
            if self.active_fault == 'DIR 未切回接收':
                f['wait'] = '21 ms > 20 ms 超时'
                self.show_code(9, note='→ 超时 return 0')
                self.fly(rlabels, 'data_back', RED, gap=.22, travel=1.0)
                self.record(9, '回包被挡在门外', '电机照常回话，但接收门关着、发送门还占着 DATA，回包到了芯片就进不去。')
                self.stop('DIR 时序错误：电机尝试回复，但电脑没有收到有效包。')
                self.refresh_vars(); return
            self.fly(rlabels, 'data_back', GREEN, gap=.22, travel=1.0)
            self.record(9)
        elif step == 10:
            self.show_code(10)
            self.cpu_note = 'UART_READ'
            resp = self.response
            f['rx'], f['rx_n'] = [None] * len(resp), 0

            def in_sram(i):
                f['rx'][i] = resp[i]; f['rx_n'] = i + 1; f['rx_i'] = i; f['b'] = resp[i]
                f['wait'] = f'{0.5 + 0.17*(i+1):.1f} ms'
                self.refresh_vars()

            def at_mcu(i):
                self.fly([f'{resp[i]:02X}'], self.path_motor_in(i), GREEN, travel=1.1, space='2d',
                         on_arrive=lambda _, i=i: in_sram(i))
            self.fly([f'{b:02X}' for b in resp], 'rx_back', GREEN, gap=.3, travel=1.3, on_arrive=at_mcu)
            self.record(10)
        elif step == 11:
            self.show_code(11)
            self.cpu_note = 'UART_WRITE'
            f['wait'] = None
            resp = self.response
            f['pc_rx'] = []

            def to_pc(i):
                self.fly([f'{resp[i]:02X}'], 'usb_back', CYAN, travel=1.0,
                         on_arrive=lambda _, i=i: got(i))

            def got(i):
                f['pc_rx'].append(resp[i]); f['rx_active'] = i; self.refresh_vars()

            for i in range(len(resp)):
                fl = self.fly([f'{resp[i]:02X}'], self.path_to_pc(i), CYAN, travel=1.0, space='2d',
                              on_depart=lambda _, i=i: (f.__setitem__('rx_i', i), self.refresh_vars()),
                              on_arrive=lambda _, i=i: to_pc(i))
                fl.start += i * .3 / self.speed
            self.record(11)
        elif step == 12:
            f['rx_i'] = None; f['rx_active'] = None
            self.cpu_note = '空等 RX'
            self.show_code(12)
            response = parse(self.response)
            error, params = response.params[0], response.params[1:]
            decoded = f'ID {response.device_id} · Status 55 · Error {error:02X} · CRC OK'
            extra, flow_note = '', ''
            self.last_position = self.motor.position
            ins, addr = self.request.instruction, None
            if ins in (2, 3) and len(self.request.params) >= 2:
                addr = int.from_bytes(self.request.params[:2], 'little')
            if error:
                extra = flow_note = f'电机报错 Error {error:02X}'
            elif ins == 1:
                extra = '演示设备 1 / 模拟固件版本 1'
                flow_note = '在线：演示设备 1'
            elif ins == 2 and addr == 11:
                extra = f'操作模式 = {params[0]}' + ('（位置模式，可以按角度转）' if params[0] == 3 else '（不是位置模式：先扭矩关，再写 11 号 = 3）')
                flow_note = f'= {params[0]} 位置模式' if params[0] == 3 else f'= {params[0]}，需改成 3'
            elif ins == 2 and addr == 132 and len(params) == 4:
                value = int.from_bytes(params, 'little')
                self.last_position = value
                near = abs(value - self.goal_ticks()) <= 2
                extra = f'读到 {value} ticks ≈ {value*360/4096:.1f}°' + ('，已到目标' if near else '，还没到，过一会儿再读')
                flow_note = f'{value} ticks = {value*360/4096:.1f}°' + ('，到了' if near else '，还在转')
            elif ins == 3 and addr == 64:
                on = self.request.params[2] == 1
                extra = '扭矩已' + ('开启：电机现在会锁住位置' if on else '关闭：电机松开')
                flow_note = '扭矩已开' if on else '扭矩已关'
            elif ins == 3 and addr == 116:
                extra = 'Write 已接受；电机正在转，用 Read 132 确认是否到位'
                flow_note = '已接受，电机开始转' if self.motor.torque else '已接受，但扭矩关着，不会转'
            elif ins == 3:
                extra = flow_note = 'Write 已接受'
            self.decode_text2.setText(decoded + ('   ' + extra if extra else ''))
            self.record(12, body=STEPS[12][1] + ('\n结果：' + extra if extra else ''))
            self.finished = True
            self.running = False
            self.play_btn['text'] = '自动播放'
            self.packet_result(not error, flow_note)
        self.refresh_vars()
        self.refresh_motor()

    # ------------------------------------------------------------------ 电机与帧更新
    def refresh_motor(self):
        angle = self.motor.position * 360 / 4096
        goal = self.motor.goal * 360 / 4096
        self.horn.setH(-angle)
        self.ghost.setH(-goal)
        moving = self.motor.moving
        self.ghost.show() if moving else self.ghost.hide()
        self.angle_world.setText(f'{angle:.1f}°')
        self.dial_needle.setR(-angle)
        self.dial_goal.setR(-goal)
        self.dial_goal.show() if self.motor.torque or moving else self.dial_goal.hide()
        state = '转动中' if moving else ('锁定' if self.motor.torque else '松开')
        self.motor_text.setText(f'当前 {angle:.1f}°\n目标 {goal:.1f}°\n扭矩 {"开" if self.motor.torque else "关"} · {state}')
        key = (round(self.motor_start_angle, 1), round(angle, 1))
        if getattr(self, '_arc_key', None) != key:
            self._arc_key = key
            self.dial_arc.removeNode()
            self.dial_arc = self.dial_root.attachNewNode('arc')
            a0, a1 = self.motor_start_angle, angle
            if abs(a1 - a0) > .5:
                n = max(2, int(abs(a1 - a0) / 3))
                pts = [(40*math.sin(math.radians(a0 + (a1 - a0)*k/n)), -40*math.cos(math.radians(a0 + (a1 - a0)*k/n)))
                       for k in range(n + 1)]
                lines2d(self.dial_arc, [pts], (.30, .92, .62, .55), 5)
                self.text(f'已转 {abs(a1 - a0):.1f}°', 0, 26, 10, GREEN, align=TextNode.ACenter, parent=self.dial_arc)

    def tick(self, task):
        dt = min(ClockObject.getGlobalClock().getDt(), .1)
        if self.active_fault != '电机未供电':
            self.motor.update(dt)
        self.refresh_motor()
        now = time.monotonic()
        for item in sorted(self.timers, key=lambda t: t[0]):
            if now >= item[0] and item in self.timers:
                self.timers.remove(item); item[1]()
        if self.wave_anim:
            start, dur, t0, t1, done = self.wave_anim
            r = min(1, (now - start) / dur)
            self.set_wave_cursor(t0 + (t1 - t0) * r)
            tA, tF, _ = self.wave_times()
            if self.lens_tab == 'wave' and not self.lens_cursor.isEmpty():
                cur = t0 + (t1 - t0) * r
                self.cursor_label.setText('TX_COMPLETE=1 OK' if cur >= tF else 'FIFO_EMPTY=1，还在发' if cur >= tA else '')
            if r >= 1:
                self.wave_anim = None
                if done: done()
        busy = False
        for fl in list(self.flights):
            if fl.update(now):
                fl.destroy(); self.flights.remove(fl)
            else:
                busy = True
        busy = busy or bool(self.timers) or bool(self.wave_anim)
        if self.running:
            if busy:
                self.step_done_at = 0
            elif not self.step_done_at:
                self.step_done_at = now + 1.5 / self.speed
            elif now >= self.step_done_at:
                self.step_done_at = 0
                self.next_step()
        elif self.seq and self.finished and not busy and now >= self.seq.get('next_at', 0):
            nxt = self.seq_next()
            if nxt:
                self.flow_click_seq(nxt)
        return task.cont

    def export(self):
        folder = ROOT / 'output'
        folder.mkdir(exist_ok=True)
        path = folder / f'trace-{time.strftime("%Y%m%d-%H%M%S")}.json'
        content = {'mode': 'SIMULATION_ONLY', 'hardware_tested': False,
                   'firmware': 'firmware/main.c', 'packet_kind': self.kind,
                   'electrical_profile': self.active_profile, 'fault': self.active_fault,
                   'tx_hex': hexline(self.packet_bytes),
                   'motor_generated_status_hex': hexline(self.response or b''),
                   'pc_received_status_hex': hexline(self.response or b'') if self.finished and self.step_index == 11 else '',
                   'motor': {'id': self.motor.device_id, 'torque': self.motor.torque,
                             'position': self.motor.position, 'goal': self.motor.goal},
                   'steps': self.events}
        path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding='utf-8')
        return path


# ---------------------------------------------------------------------- 自检 / 截图
def render(app, frames=4):
    for _ in range(frames):
        app.taskMgr.step()
        app.graphicsEngine.renderFrame()


def freeze(app, fraction):
    """把当前所有飞行和波形动画定格在某个进度，用于截图。"""
    now = time.monotonic()
    for fl in app.flights:
        fl.start = now - (fl.end_time - fl.start) * fraction
    if app.wave_anim:
        start, dur, *rest = app.wave_anim
        app.wave_anim = (now - dur * fraction, dur, *rest)
    render(app)
    app.running = False


def run_packet(app, kind, steps=12):
    app.set_preset(kind)
    app.load_packet()
    for _ in range(steps):
        app.next_step()
        if app.finished: break
    app.settle()


def main():
    args = argparse.ArgumentParser()
    args.add_argument('--screenshot', action='store_true')
    opts = args.parse_args()
    app = Demo(screenshot=opts.screenshot)
    if not opts.screenshot:
        app.run(); return
    folder = ROOT / 'output'
    folder.mkdir(exist_ok=True)
    shot = lambda name: app.win.saveScreenshot(Filename.fromOsSpecific(str(folder / name)))

    def to_step(kind, n, frac=None):
        app.set_preset(kind); app.load_packet()
        for _ in range(n): app.next_step()
        if frac is not None:
            # 二段飞行（3D → MCU 内部）需要让前一段先到
            for _ in range(3):
                freeze(app, frac)
        render(app)

    to_step('ping', 2, .7); shot('step02-into-mcu.png')
    to_step('ping', 4); app.settle(); render(app); shot('step04-dir-high.png')
    app.set_preset('ping'); app.load_packet()
    for _ in range(5): app.next_step()
    freeze(app, 1.0); render(app)
    for _ in range(6):   # 让 FIFO 排空到一半
        if app.timers:
            item = min(app.timers, key=lambda t: t[0]); app.timers.remove(item); item[1]()
    render(app); shot('step05-fifo.png')
    app.next_step(); freeze(app, .7); shot('step06-wave.png')
    app.next_step(); app.settle(); render(app); shot('step07-dir-low.png')
    to_step('ping', 10, .6); shot('step10-rx.png')
    to_step('ping', 12); app.settle(); render(app); shot('preview.png')
    assert parse(app.response).instruction == 0x55
    assert app.fw['pc_rx'] == list(app.response)
    assert app.fw['buf'] == list(app.packet_bytes)
    for step in range(1, 13):
        assert app.fw_tags.get(step), f'firmware has no [{step:02d}] tag'

    # 错误写法：只等 FIFO_EMPTY
    app.set_fault('只等 FIFO_EMPTY 就切 DIR')
    app.set_preset('ping'); app.load_packet()
    for _ in range(7): app.next_step()
    freeze(app, .4); shot('fault-txempty.png')
    app.next_step()
    assert app.finished and app.response is None
    app.settle()
    app.set_fault('正常通信')

    # 转到 90° 全流程
    app.reset()
    app.start_sequence(); app.settle()
    kinds = []
    while True:
        kind = app.kind
        kinds.append(kind)
        for _ in range(12):
            app.next_step()
            if app.finished: break
        app.settle()
        if kind == 'goal':
            app.motor.update(1.6)     # 写完目标后过一会儿再读：电机转到一半
            app.refresh_motor(); render(app); shot('turn-midway.png')
        nxt = app.seq_next()
        if not nxt: break
        app.set_preset(nxt); app.load_packet()
        if nxt == 'pos' and kinds.count('pos') >= 1:
            app.motor.update(5)
    assert kinds[:5] == ['ping', 'mode', 'on', 'goal', 'pos'], kinds
    assert kinds.count('pos') >= 2, kinds          # 第一次读到一半，第二次到位
    assert app.motor.goal == 1024 and abs(app.last_position - 1024) <= 2
    assert all(app.flow_state[k][0] == 'ok' for k in AUTO_FLOW), app.flow_state
    render(app); shot('turn-done.png')

    for fault in ['DIR 未切回接收', '电机未供电', '没有共地', 'ID 不匹配', '传输中 CRC 损坏']:
        app.set_fault(fault); run_packet(app, 'ping')
        assert app.finished and app.step_index < 11, fault
        if fault == 'DIR 未切回接收':
            assert app.dir_level == 1
    app.set_fault('Write 不返回 Status'); run_packet(app, 'goal')
    assert app.response is None
    app.set_fault('正常通信'); app.set_profile('电气：示例 5V 缓冲器（待核对）')
    run_packet(app, 'ping')
    assert app.step_index == 7 and app.response is None
    app.raw_entry.enterText('FF 00')
    assert not app.load_packet()
    app.reset(); run_packet(app, 'ping')
    data = json.loads(app.export().read_text(encoding='utf-8'))
    assert data['hardware_tested'] is False and len(data['steps']) == 12
    print('GUI scenarios passed: 12 steps, MCU internals, waveform, FIFO_EMPTY fault, 90° flow, 6 faults, voltage review, invalid HEX, export.')
    app.destroy()


if __name__ == '__main__':
    main()
