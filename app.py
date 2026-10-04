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

# Claude 深色风格：暖灰底色、米白文字、陶土橙强调色。线路颜色（蓝/橙/绿/紫）有教学含义，只调柔和。
BG = (0.149, 0.149, 0.141, 1)       # #262624
CARD = (0.188, 0.188, 0.180, 1)     # #30302E
CARD2 = (0.122, 0.118, 0.114, 1)    # #1F1E1D
WHITE = (0.980, 0.976, 0.961, 1)    # #FAF9F5
MUTED = (0.718, 0.710, 0.663, 1)    # #B7B5A9
DIM = (0.478, 0.467, 0.435, 1)
ACCENT = (0.851, 0.467, 0.341, 1)   # #D97757 陶土橙
ACCENT_DARK = (0.40, 0.22, 0.16, 1)
PRIMARY = (0.72, 0.38, 0.27, 1)     # 主按钮：陶土橙，压暗一点让米白字更清楚
CYAN = (0.45, 0.73, 0.88, 1)
GREEN = (0.50, 0.80, 0.56, 1)
ORANGE = ACCENT
PURPLE = (0.70, 0.60, 0.90, 1)
RED = (0.90, 0.42, 0.40, 1)
YELLOW = (0.93, 0.78, 0.45, 1)
INK = (0.12, 0.11, 0.10, 1)

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

# MCU 内部细节（「细化 MCU」打开时，在对应大步骤之前逐格播放）。
# 每格：(代码标签, 标题, 白话说明, 术语括注, 位级视图模式, 阶段, 动画 (t0, t1, 秒) 或 None)
# 时钟、分频值是举例：假设外设时钟 48 MHz，不对应某块具体芯片。
MICRO = {
    1: [('01a', '上电：配时钟、波特率、GPIO',
         '上电后 board_init() 只做一次准备：选时钟源，给两个 UART 算波特率分频值，把 DIR_GPIO 设成输出。接着 gpio_write_dir(0)，默认处在接收。之后 CPU 进入 while(1)，再也不回来。',
         '分频：波特率 = 外设时钟 ÷ 16 ÷ 分频值。除不尽会有一点误差，收发两边误差一般要小于 2%。',
         'boot', '', None)],
    2: [('02a', '起始位：空闲线上的下降沿',
         'RX 脚空闲时一直是高电平。接收器用比波特率快 16 倍的时钟盯着它：一看到下降沿就开始数拍，数到第 8 拍（半个位）再看一次，仍是低电平才认定是起始位，不是毛刺。这期间 CPU 只在 while 里空转。',
         '16 倍过采样：每个位分 16 拍，在正中间那一拍取值，离两边的跳变最远，最不容易采错。',
         'rx', 'start', (0, 1.5, 2.2)),
        ('02b', '逐位采样：低位先到',
         '之后每过 16 拍（正好 1 个位），在位的正中间采一次。先到的是最低位 b0。每采一位，移位寄存器整体右移一格，新位放进最左边；8 位采完，b0 正好落到最右边。',
         'FF 在线上只有起始位是低电平。没有起始位，FF 和空闲线就分不清。',
         'rx', 'data', (1.5, 9.5, 4.5)),
        ('02c', '停止位检查，字节进 RX FIFO',
         '第 10 个位必须是高电平（停止位）。是 1：整个字节搬进 RX FIFO，RX_EMPTY 从 1 变 0。是 0：说明波特率不对或线上有干扰，硬件置帧错误标志 FE。本固件不看 FE，坏字节留给后面的 CRC 把关。',
         '02a～02c 全是 UART 硬件自己完成的，没有一行代码参与。',
         'rx', 'stop', (9.5, 11.6, 1.8)),
        ('02d', 'CPU 发现有数据，读出来',
         'CPU 每转一圈都读一次状态寄存器。RX_EMPTY 一变 0，if 不成立、不再 continue，往下执行 UART_READ：经总线读 UART 的数据寄存器，FIFO 自动出队一格，值放进变量 b（在 CPU 寄存器里）。',
         '轮询和中断：本固件一直问「到了吗」，叫轮询。中断写法是硬件收到字节就打断 CPU 去执行中断函数，CPU 平时可以做别的事。',
         'read', '', (0, 1, 1.8)),
        ('02e', '包头比对：一个小状态机',
         'n < 4 时，b 必须等于包头 FF FF FD 00 的第 n 个字节，才执行 buf[n++] = b。对不上就重新同步：b 是 FF 时 n 回到 1（它可能是新包头的开头）；n 已是 2 时保持 2，应对 FF FF FF FD 00。',
         '状态机：n 既是计数，也记着「包头已经对上了几个」。',
         'hdr', '', (0, 4, 2.4))],
    3: [('03a', '用长度字段算出整包大小',
         'n 到 7 时，buf[5] 是长度的低字节，buf[6] 是高字节（低位在前，叫小端）。need = 7 + (buf[5] | buf[6] << 8)：7 是包头 4 + ID 1 + 长度 2，长度字段只数它后面的字节。',
         '<< 8 是左移 8 位，等于乘 256，把高字节放回高位。',
         'len', 'calc', None),
        ('03b', '范围检查：不让数组越界',
         'need 小于 10 不可能是合法包（指令 1 + CRC 2，加上前 7 个字节）；大于 PKT_MAX = 64 会写到 g_buf 外面。两种都 return 0，丢掉这包，main() 重新等。',
         '缓冲区溢出：往数组外写会改坏别的变量，是单片机程序最常见的隐患之一。',
         'len', 'range', None),
        ('03c', 'n 追上 need：跳出循环',
         'while (n < need) 每收一个字节判断一次。n 追上 need，条件不成立，return n。注意 MCU 这里不算 CRC，只是原样转发；CRC 由电机检查。',
         '同一个循环收两种长度的包：need 先按 7 设，收到长度后再改成真实值。',
         'len', 'done', None)],
    4: [('04a', '先清掉电机侧的旧字节',
         '发送之前，先把 UART1 RX FIFO 里残留的字节读出来丢掉，例如上一次超时之后才迟到的回包。不清的话，等会儿收回包时会先读到这些旧字节，包头对不上。',
         '(void) 表示故意不用返回值。',
         'drain', '', (0, 1, 1.6)),
        ('04b', 'GPIO：写一位寄存器，引脚变 3.3V',
         'gpio_write_dir(1) 在硬件上就是 CPU 往 GPIO 输出数据寄存器的某一位写 1。这一位直接控制引脚的推挽驱动：上管导通、下管关断，引脚被拉到 3.3V。只要几个时钟周期。',
         '推挽输出：上下两个开关管一次只开一个，输出高、低都能提供电流。',
         'gpio', '', (0, 1, 1.6))],
    5: [('05a', '先看 TX FIFO 满没满',
         'UART_IS_TX_FULL 读的是状态寄存器里的一位。现在 FIFO 是空的，条件不成立，while 立刻结束。如果包比 FIFO 长，CPU 会在这里等硬件发走一个字节、腾出一格。',
         'while (…) {} 空循环：什么也不做，只是反复判断条件。',
         'tx', 'full', None),
        ('05b', 'CPU 写数据寄存器，字节进 TX FIFO',
         'UART_WRITE 把字节写进 UART1 的数据寄存器，硬件马上把它放到 TX FIFO 队尾。CPU 写一个字节只要几个时钟周期，所以一转眼整包都进了 FIFO，远远快过线上发送。',
         '数据寄存器：CPU 和 UART 之间的「投递口」，写它就是入队，读它就是出队。',
         'tx', 'write', (0, 1, 1.6)),
        ('05c', '硬件取字节，加上起始位和停止位',
         '发送移位寄存器一空，硬件自动从 FIFO 队头取一个字节，在前面加起始位 0、后面加停止位 1，凑成 10 位。此时 CPU 已经在写后面的字节了，这一步不需要任何代码。',
         '8N1：8 个数据位、无校验位、1 个停止位。',
         'tx', 'load', (0, 1, 1.4)),
        ('05d', '波特率发生器：一拍移出一位',
         '波特率发生器每 17.4µs（57600 bps）打一拍，移位寄存器右移一格，最右边那一位出现在 ACT_TX 脚上：先起始位，再 b0…b7，最后停止位。10 拍发完一个字节，再取下一个。',
         '最后两个字节的完整波形和 DIR 切换时机，见第 06 步的波形页。',
         'tx', 'shift', (1, 11.4, 4.5))],
    10: [('10a', '带超时的等待',
          '收回包用的还是 read_packet()，只是多了超时：每转一圈先算 millis() - t0，超过 20ms 就 return 0，放弃这包。现在约 0.5ms 后第一个字节到达，RX_EMPTY 变 0，后面的收字节过程和第 02 步完全一样。',
          'millis()：上电后经过的毫秒数，由一个定时器在后台计数。',
          'timeout', '', (0, 1, 1.8))],
    11: [('11a', '回传前同样先看 TX FIFO',
          'pc_write() 和 motor_send() 的写法一样：先查 UART0 的 TX_FULL，再 UART_WRITE。UART0 跑 115200 bps，比电机侧快一倍，一个字节约 87µs 就发完。',
          '这里不用切 DIR：电脑侧 TX、RX 是两根独立的线（全双工）。',
          'tx', 'full', None)],
}
MICRO_COUNT = {step: len(items) for step, items in MICRO.items()}
MICRO_CODE = {'01a': ('main', 'main() → board_init()'),
              '04a': ('motor_send', 'main() → motor_send() 开头'),
              '10a': ('read_packet', 'main() → read_packet(MOTOR_UART, g_rx, 20ms)'),
              '11a': ('pc_write', 'main() → pc_write(g_rx, n)')}
MICRO_CPU = {'01a': 'board_init()', '02a': '空等 RX', '02b': '空等 RX', '02c': '空等 RX',
             '02d': 'UART_READ', '02e': '比对包头', '03a': '算 need', '03b': '检查 need',
             '03c': 'return n', '04a': '清空 RX FIFO', '04b': 'gpio_write_dir(1)',
             '05a': '查 TX_FULL', '05b': 'UART_WRITE', '05c': '继续写 FIFO', '05d': '继续写 FIFO',
             '10a': '等回包（带超时）', '11a': '查 TX_FULL'}

# 新手版讲解：同一个比喻贯穿全程。MCU = 一间收发室：办事员（CPU）、两个收发窗口（UART）、
# 排队传送带（FIFO）、笔记本（SRAM）。电机那根 DATA 线 = 对讲机：按住说话键（DIR=1）才能说，松开（DIR=0）才能听。
# 每格：(白话说明, 一个新词)。开关切到「专业」时用 STEPS / MICRO 里的原文。
EASY = {
    1: ('【比方】电脑要给电机寄一封信，信的内容是一串数字。\n【实际】电脑把指令排成一串字节（底部 TX 那一排格子），准备发出。MCU 的办事员（CPU）这时什么也不干，就守在窗口前等信。',
        '【新词】字节：8 个 0/1 组成的一个数，写成两位 HEX，比如 FF = 255。'),
    2: ('【比方】信一个字一个字地递进收发室：窗口先收下，放上传送带排队，办事员再一个个取下来抄进笔记本。\n【实际】每个字节经 USB 进到 MCU 的电脑侧窗口（UART0），排队后被 CPU 读走，存进内存里的 g_buf。',
        '【新词】UART：芯片里专门负责收发串口数据的「窗口」，一个字节一个字节地收发。'),
    3: ('【比方】信封上写着「共几页」。办事员数到这么多页，才知道信收全了。\n【实际】包的第 6、7 个字节写着后面还有多少字节。MCU 据此算出整包长度，收够了才往下走。',
        '【新词】包：一次完整的指令，开头是固定的暗号 FF FF FD 00，结尾是校验码。'),
    4: ('【比方】电机那根线像对讲机，同一时间只能一边说话。MCU 要说话，先按住说话键。\n【实际】MCU 把 DIR 这根线设成高电平：发送通道打开，接收通道关上。',
        '【新词】DIR：方向控制线。1 = 我说你听，0 = 你说我听。'),
    5: ('【比方】办事员把整封信一下子放上发送传送带，窗口再一个字一个字地念出去。\n【实际】CPU 很快就把整包写进 UART1 的发送队列；硬件每次取一个字节，拆成 0/1 一位一位送到线上。',
        '【新词】FIFO：排队用的传送带，先放上去的先出去。'),
    6: ('【比方】信刚放上传送带，不等于已经念完了。要等最后一个字真正念出口，才能松开说话键。\n【实际】队列空了（FIFO_EMPTY）时，最后一个字节其实还在往外发。固件要等「真正发完」（TX_COMPLETE）。',
        '【新词】停止位：每个字节最后的那一位，表示「这个字说完了」。'),
    7: ('【比方】话说完了，松开对讲机按键，改成听对方说。\n【实际】MCU 把 DIR 设回低电平：发送通道断开，不再占着线；接收通道打开，电机的回话能进来。',
        '【新词】高阻：输出端相当于拔掉了插头，既不发 1 也不发 0，不干扰别人。'),
    8: ('【比方】电机收到信，先核对收件人和校验码，没问题才照着做。\n【实际】电机检查 ID 和 CRC，然后执行：Ping 报到、Write 改设置、Read 读数值。MCU 在一旁等回信，最多等 20ms。',
        '【新词】CRC：按整封信算出来的校验码，传错一位就对不上。'),
    9: ('【比方】对方等你松开按键后，稍等一下再开口，免得两人同时说话。\n【实际】电机约等 0.5ms，再把回信（状态包）发到同一根线上，经接收通道进入 MCU。',
        '【新词】状态包：电机的回信，格式和指令包一样，多一个「有没有出错」的字节。'),
    10: ('【比方】回信也一个字一个字地进收发室，这次走的是电机侧窗口，抄进另一本笔记本。\n【实际】和第 02 步一样的过程，只是换成 UART1，存进 g_rx。用的还是同一个函数。',
         '【新词】函数参数：同一套动作换个对象再做一遍，比如换一个窗口、换一本笔记本。'),
    11: ('【比方】办事员把回信原封不动地转交给电脑，一个字都不改。\n【实际】CPU 把 g_rx 里的字节逐个写进电脑侧窗口（UART0），经 USB 回到电脑。',
         '【新词】转发：MCU 只负责传话，不自己看懂信的内容。'),
    12: ('【比方】电脑拆开回信，检查暗号、页数和校验码都对，再看电机说了什么。\n【实际】Instruction=55 表示这是回信，Error=00 表示没出错。MCU 已经回到第 01 步，等下一封信。',
         '【新词】Error 字节：电机告诉你「刚才那条指令执行得怎么样」，00 就是一切正常。'),
    '01a': ('【比方】收发室开门前，先把钟调好、规定好每个窗口说话的语速。\n【实际】上电后只做一次：设置时钟，给两个 UART 定好速度（波特率），把 DIR 线设成输出，默认先「听」。',
            '【新词】波特率：每秒发多少位。双方必须一样快，就像两个人约好语速。'),
    '02a': ('【比方】平时线上一直是「嗯——」的长音（高电平），突然变低就是对方说「喂」：要开始了。\n【实际】接收器看到电平从高变低，等半个位的时间再看一次，确认真的是低，才开始收这个字节。',
            '【新词】起始位：每个字节前面那一个 0，作用就是喊一声「要开始了」。'),
    '02b': ('【比方】对方按节拍一个字一个字地念，你在每一拍的正中间听一次，记下 0 还是 1。\n【实际】每隔 1 位的时间采样一次，一共 8 次。先到的是最低位，按顺序拼成一个完整的字节。',
            '【新词】移位寄存器：一排 8 个格子，每来一位就整体挪一格，8 位到齐就是一个字节。'),
    '02c': ('【比方】对方说完一个字，要说「完毕」（停止位 = 1）。听到「完毕」，这个字才算数。\n【实际】最后一位是 1，字节就被放上接收传送带（FIFO），同时一盏「有信了」的灯亮起（RX_EMPTY 变 0）。',
            '【新词】标志位：硬件用来报告状态的小灯，0/1 两种，CPU 随时可以看。'),
    '02d': ('【比方】办事员一直在看「有信了」那盏灯。灯一亮，就去窗口把信取走。\n【实际】CPU 在循环里一遍遍检查 RX_EMPTY。一看到 0，就执行 UART_READ，从窗口取出这个字节放进变量 b。',
            '【新词】轮询：不停地去看「到了没」。另一种做法叫中断，像装个门铃，信到了才叫你。'),
    '02e': ('【比方】每封信开头都有固定的暗号：FF FF FD 00。对上暗号才开始记，对不上就当噪音丢掉。\n【实际】前 4 个字节要和暗号逐个比对，n 记录已经对上了几个；对上就存进笔记本，n 加 1。',
            '【新词】包头：包开头的固定字节，用来在一串数据里找到「一封信从哪里开始」。'),
    '03a': ('【比方】信封上写着「后面还有 3 页」。加上信封本身的 7 页，一共 10 页。\n【实际】第 6、7 个字节是长度（低位在前），整包字节数 need = 7 + 长度。',
            '【新词】低位在前（小端）：两个字节拼一个数时，先到的是小的那一半。'),
    '03b': ('【比方】如果信封上写「后面有 1000 页」，笔记本根本写不下，这封信肯定有问题，直接扔掉。\n【实际】need 太小（小于 10）或太大（超过 64）都不可能是正常的包，直接放弃，重新等。',
            '【新词】数组越界：往笔记本的最后一页之后接着写，会把别的内容写坏。'),
    '03c': ('【比方】页数数够了，信就收全了，可以去办下一件事。\n【实际】已收字节数 n 等于 need，循环结束。MCU 不检查校验码，只负责转交；检查是电机的事。',
            '【新词】循环：一段代码反复执行，直到条件不再满足为止。'),
    '04a': ('【比方】开口说话之前，先把信箱里上次没处理的旧信清掉，免得和新回信搞混。\n【实际】把电机侧接收队列里残留的字节读出来扔掉。正常情况下队列本来就是空的。',
            '【新词】残留数据：上一次没来得及处理、留在队列里的旧字节。'),
    '04b': ('【比方】墙上有一排开关，每个开关接一根线。办事员把 DIR 那个开关拨到「开」，线上就有了 3.3V。\n【实际】CPU 往 GPIO 寄存器的某一位写 1，芯片里的开关管导通，引脚电压变成 3.3V。',
            '【新词】寄存器：芯片里的一排「开关」或「指示灯」，写它就控制硬件，读它就知道硬件状态。'),
    '05a': ('【比方】往传送带上放东西之前，先看一眼满没满。\n【实际】CPU 查看 TX_FULL 这盏灯。现在队列是空的，不用等，马上可以放。',
            '【新词】TX_FULL：发送队列已满的指示灯，亮着就得等一会儿。'),
    '05b': ('【比方】办事员把信放进投递口，信就自动排到传送带末尾。\n【实际】CPU 把字节写进 UART1 的数据寄存器，硬件马上把它放到发送队列的末尾。CPU 很快，一转眼整包就都放进去了。',
            '【新词】数据寄存器：CPU 和 UART 之间的投递口，写进去就是排队，读出来就是取走。'),
    '05c': ('【比方】窗口取下一个字，前面加一声「喂」（起始位 0），后面加一声「完毕」（停止位 1）。\n【实际】硬件从队头取出一个字节，前后各加一位，凑成 10 位准备发送。这一步不需要代码。',
            '【新词】8N1：8 个数据位、没有校验位、1 个停止位，是最常见的串口格式。'),
    '05d': ('【比方】像节拍器，每响一下就念出一位：先「喂」，再 8 个 0/1，最后「完毕」。\n【实际】每 17.4µs 送出一位，10 位约 174µs 发完一个字节，再取下一个。',
            '【新词】波特率发生器：给 UART 打节拍的计时器，决定每一位持续多久。'),
    '10a': ('【比方】打电话等对方回话，最多等 20 秒，超时就挂断，不能一直傻等。\n【实际】CPU 每转一圈都看一下过了多久，超过 20ms 就放弃。这次电机约 0.5ms 就回话了，没有超时。',
            '【新词】超时：给等待设一个上限，防止对方不回话时程序永远卡住。'),
    '11a': ('【比方】把回信交给电脑之前，同样先看一眼发送传送带满没满。\n【实际】和第 05 步一样：先查 TX_FULL，再写数据寄存器。电脑侧是两根独立的线，不用切换方向。',
            '【新词】全双工：收和发各用一根线，可以同时进行。电机那边只有一根线，叫半双工。'),
}

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
        for m in re.finditer(r'\[(\d\d)([a-z]?)\]', line):
            before, after = line[:m.start()], line[m.end():]
            if before.endswith('~') or after.startswith('~'):
                continue  # “[04]~[07]” 是范围说明，不当作高亮点
            block = [no]
            for nxt in range(no + 1, min(no + 6, len(lines) + 1)):
                block.append(nxt)
                text = lines[nxt - 1].rstrip()
                if text.endswith(';') or text.endswith('}') or text.endswith('{'):
                    break
            # [02] → 键 2（大步骤）；[02a] → 键 '02a'（MCU 内部细节）
            key = m.group(1) + m.group(2) if m.group(2) else int(m.group(1))
            tags.setdefault(key, []).append(block)
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
        self.bits_anim = None
        self.detail = True      # 细化 MCU：大步骤前先播放 MICRO 里的细节格
        self.beginner = True    # 讲解：新手版（EASY）或专业版（STEPS/MICRO 原文）
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

    def button(self, label, x, y, w, command, color=(0.284,0.275,0.256,1), size=16, h=36, parent=None):
        button = DirectButton(parent=parent or self.pixel2d, text=label, text_font=self.font,
                              text_scale=size, text_fg=WHITE, text_pos=(w/2, -h/2-size*.36),
                              frameSize=(0, w, -h, 0), frameColor=color,
                              pos=(x, 0, -y), relief=1, borderWidth=(0, 0), command=command)
        self.widgets.append(button)
        return button

    def entry(self, value, x, y, w, size=15):
        entry = DirectEntry(parent=self.pixel2d, initialText=value, text_font=self.font,
                            text_fg=WHITE, scale=size, width=w/size, numLines=1,
                            pos=(x, 0, -y), frameColor=(0.134,0.130,0.121,1),
                            cursorKeys=True, focus=0)
        self.widgets.append(entry)
        return entry

    def menu(self, values, x, y, w, callback, size=13):
        menu = DirectOptionMenu(parent=self.pixel2d, items=values, text_font=self.font,
                                text_scale=size, text_fg=WHITE, text_pos=(9, -21),
                                frameSize=(0, w, -30, 0), frameColor=(0.260,0.253,0.235,1),
                                pos=(x, 0, -y), item_text_font=self.font,
                                item_text_scale=size, item_text_fg=WHITE,
                                item_frameColor=(0.260,0.253,0.235,1),
                                item_text_pos=(10, -21), item_frameSize=(0, w, -30, 0),
                                item_relief=1, item_borderWidth=(0, 0),
                                popupMarker_scale=9, popupMarker_pos=(w-10, 0, -15),
                                popupMenu_frameColor=(0.260,0.253,0.235,1),
                                highlightColor=(0.297,0.289,0.269,1), command=callback)
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
        ambient.setColor((.80,.77,.72,1))
        self.render.setLight(self.render.attachNewNode(ambient))
        light = DirectionalLight('sun')
        light.setColor((.62,.58,.52,1))
        sun = self.render.attachNewNode(light)
        sun.setHpr(-20, -60, 0)
        self.render.setLight(sun)
        box(self.render, 'table', (0, .3, -.35), (21, 9.6, .25), (0.174,0.169,0.157,1))
        grid = LineSegs()
        grid.setColor(0.225,0.218,0.203,1)
        for gx in range(-10, 11):
            grid.moveTo(gx, -4.4, -.21); grid.drawTo(gx, 5, -.21)
        for gy in range(-4, 6):
            grid.moveTo(-10.4, gy, -.21); grid.drawTo(10.4, gy, -.21)
        self.render.attachNewNode(grid.create()).setLightOff()
        for key, bx, name, sub, color in [
                ('pc', -8.7, '电脑', 'PC', (0.306,0.297,0.276,1)),
                ('mcu', -4.5, 'MCU', 'UART0 · UART1 · DIR_GPIO', (.10,.40,.31,1)),
                ('ls', -.6, '电平转换', '默认旁路', (.42,.30,.15,1)),
                ('buf', 3.4, '三态缓冲器', '三态缓冲器', (0.296,0.288,0.268,1)),
                ('motor', 8.1, '执行器', '电机', (0.372,0.361,0.335,1))]:
            box(self.render, key, (bx, 0, .40), (2.3, 3.0, .6), color)
            self.world_text(name, (bx, 1.55, 1.55), .46)
            self.world_text(sub, (bx, 1.55, 1.10), .30, MUTED)
            if key in ('mcu', 'ls', 'buf'):
                box(self.render, 'chip', (bx, .1, .78), (1.1, 1.0, .16), (0.149,0.144,0.134,1))
        box(self.render, 'screen', (-8.7, .9, 1.35), (1.9, .16, 1.3), (0.243,0.235,0.219,1))
        box(self.render, 'display', (-8.7, .8, 1.40), (1.62, .04, 1.0), (.10,.48,.58,1))
        self.gate_tx = box(self.render, 'gate-tx', (3.4, -1.1, .80), (.9, .38, .14), (0.978,0.950,0.883,1))
        self.gate_rx = box(self.render, 'gate-rx', (3.4, 0, .80), (.9, .38, .14), (0.978,0.950,0.883,1))
        self.gate_tx.setLightOff(); self.gate_rx.setLightOff()
        # 电机：表盘 + 舵盘 + 目标虚影
        mx, my, mz = 8.1, -.2, .72
        dial = LineSegs()
        dial.setThickness(2)
        dial.setColor(0.574,0.558,0.519,1)
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
        box(self.horn, 'axis', (0, 0, .10), (.30, .30, .16), (0.801,0.778,0.723,1))
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
                                   frameColor=(0.302,0.293,0.273,1), thumb_frameSize=(-7,7,-11,11),
                                   thumb_frameColor=ORANGE, command=self.target_change)
        self.auto_btn = self.button('自动走完整流程', cx, y+98, cw, self.start_sequence, PRIMARY, size=15, h=34)
        half = (cw - 8) / 2
        self.speed_btns = [self.button('慢速·逐步讲解', cx, y+138, half, lambda: self.set_speed(1), size=12, h=26),
                           self.button('快速', cx+half+8, y+138, half, lambda: self.set_speed(3), size=12, h=26)]
        self.text('点一项 = 只发这一包', cx, y+186, 12, MUTED)
        self.flow_rows = {}
        for i, (kind, title, why) in enumerate(FLOW):
            fy = y + 194 + i * 54
            btn = DirectButton(parent=self.pixel2d, frameSize=(0, cw, -50, 0), frameColor=(0.225,0.218,0.203,1),
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
        lines2d(self.dial_root, [ring], (0.466,0.453,0.421,1), 2)
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
        poly2d(self.dial_needle, [(-6, -6), (6, -6), (6, 6), (-6, 6)], (0.801,0.778,0.723,1))
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
        tw = 128
        for i, (key, label) in enumerate([('mcu', 'MCU 内部'), ('buf', '三态缓冲器'), ('wave', '波形'),
                                          ('bits', '位级细节')]):
            self.lens_tabs[key] = self.button(label, x + 14 + i*(tw+6), y + 8, tw,
                                              lambda k=key: self.set_lens(k), size=12, h=26)
        self.detail_btn = self.button('', x + w - 14 - 160, y + 8, 160, self.toggle_detail, size=12, h=26)
        self.paint_detail()

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
        for i, (label, cmd, col) in enumerate([('载入此包', self.load_packet, (0.345,0.335,0.312,1)),
                                               ('下一步', self.next_step, PRIMARY),
                                               ('自动播放', self.toggle_play, (.15,.33,.25,1)),
                                               ('重新播放', self.replay, (0.284,0.275,0.256,1)),
                                               ('恢复初始', self.reset, (0.284,0.275,0.256,1))]):
            btn = self.button(label, x+14+i*(bw+6), y+58, bw, cmd, col, size=13, h=30)
            if label == '自动播放': self.play_btn = btn
        self.easy_btn = self.button('', x+w-14-150, y+6, 150, self.toggle_beginner, size=12, h=24)
        self.paint_beginner()
        self.step_title = self.text('', x+14, y+122, 17, ACCENT)
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
                f['frameColor'] = (0.234,0.227,0.212,1); t.setTextColor(*done_color)

    # ------------------------------------------------------------------ 放大镜
    def set_lens(self, tab):
        self.lens_tab = tab
        for key, btn in self.lens_tabs.items():
            btn['frameColor'] = ACCENT_DARK if key == tab else (0.234,0.227,0.212,1)
        self.lens_tok.show() if tab == 'mcu' else self.lens_tok.hide()
        self.draw_lens()

    def draw_lens(self):
        self.lens_root.removeNode()
        self.lens_root = self.pixel2d.attachNewNode('lens')
        x0, y0, w, h = LENS
        self.lens_root.setPos(x0, 0, -y0)
        self.lens_cursor.hide()
        {'mcu': self.draw_mcu, 'buf': self.draw_chip, 'wave': self.draw_wave,
         'bits': self.draw_bits}[self.lens_tab](self.lens_root)
        self.gate_tx.setColorScale(*(ORANGE if self.dir_level else (0.305,0.297,0.276,1)))
        self.gate_rx.setColorScale(*(GREEN if not self.dir_level else (0.305,0.297,0.276,1)))
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

    def cells2d(self, root, x, y, values, pitch, w, h, color, active=None, size=10, empty=(0.182,0.177,0.164,1)):
        for i, v in enumerate(values):
            cx = x + i * pitch
            if v is None:
                rect2d(root, cx, y, cx + w, y + h, empty)
                continue
            on = (i == active)
            rect2d(root, cx, y, cx + w, y + h, color if on else (0.298,0.290,0.269,1))
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
        rect2d(root, x0, y - 11, x0 + 72, y + 11, color if val is not None else (0.172,0.167,0.155,1))
        self.text('移位寄存器' if val is None else f'{val:02X}', x0 + 36, y + 4.5, 10 if val is None else 13,
                  DIM if val is None else INK, align=TextNode.ACenter, parent=root)

    def pin(self, root, x, y, label, color, left=True):
        rect2d(root, x - 7, y - 6, x + 7, y + 6, (0.863,0.838,0.780,1))
        if left:
            self.text(label, x - 10, y + 4, 10, color, align=TextNode.ARight, parent=root)
        else:
            self.text(label, x + 10, y + 4, 10, color, parent=root)

    def draw_mcu(self, root):
        m, f = self.mcu, self.fw
        rect2d(root, 34, 42, 722, 398, (0.185,0.179,0.167,1))
        lines2d(root, [[(34,42),(722,42),(722,398),(34,398),(34,42)]], (.22,.45,.36,1), 2)
        self.text('MCU 芯片内部', 716, 56, 11, (.45,.75,.62,1), align=TextNode.ARight, parent=root)
        # UART0：电脑侧
        rect2d(root, 48, 60, 446, 168, (0.238,0.231,0.215,1))
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
        rect2d(root, 48, 184, 722, 272, (0.213,0.207,0.192,1))
        self.text('SRAM（内存）', 56, 200, 12, (0.782,0.759,0.706,1), parent=root)
        self.text('g_buf[]', 56, 222, 13, ORANGE, parent=root)
        self.text('g_rx[]', 56, 258, 13, GREEN, parent=root)
        for rx, vals, active, col in ((False, f['buf'], f['i'], ORANGE), (True, f['rx'], f['rx_i'], GREEN)):
            for k in range(16):
                cx, cy = self.sram_cell(k, rx)
                v = vals[k] if k < len(vals) else None
                on = v is not None and k == active
                rect2d(root, cx - 16, cy - 11, cx + 16, cy + 11,
                       col if on else (0.288,0.279,0.260,1) if v is not None else (0.182,0.177,0.165,1))
                if v is not None:
                    self.text(f'{v:02X}', cx, cy + 4.5, 12, INK if on else WHITE, align=TextNode.ACenter, parent=root)
        self.text('CPU 经 APB 总线读写 UART 寄存器、读写 SRAM', 716, 200, 10, DIM, align=TextNode.ARight, parent=root)
        # UART1 发送状态 + GPIO
        e, ef = f['txempty'], f['txemptyf']
        rect2d(root, 48, 280, 304, 380, (0.202,0.196,0.182,1))
        self.text('UART1 发送状态（教学信号）', 56, 298, 12, MUTED, parent=root)
        rect2d(root, 56, 308, 70, 322, YELLOW if e else (0.292,0.284,0.264,1))
        self.text(f'FIFO_EMPTY = {e}  队列空', 78, 320, 12, YELLOW if e else MUTED, parent=root)
        rect2d(root, 56, 332, 70, 346, GREEN if ef else (0.292,0.284,0.264,1))
        self.text(f'TX_COMPLETE = {ef}  真正发完', 78, 344, 12, GREEN if ef else MUTED, parent=root)
        self.text('GPIO DIR_GPIO（DIR）', 56, 370, 12, PURPLE, parent=root)
        rect2d(root, 170, 357, 230, 377, PURPLE if self.dir_level else (0.230,0.223,0.208,1))
        self.text(str(self.dir_level), 200, 373, 14, INK if self.dir_level else MUTED, align=TextNode.ACenter, parent=root)
        lines2d(root, [[(230, 367), (304, 367), (304, 388), (722, 388)]], PURPLE if self.dir_level else (0.435,0.422,0.393,1), 2)
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
        rect2d(root, -125, 156, -88, 268, (0.165,0.161,0.149,1))
        rect2d(root, -125, 156 if hi else 265, -88, 268, YELLOW if hi else GREEN)
        self.text('3.3V', -80, 166, 13, MUTED, parent=root)
        self.text('0V', -80, 268, 13, MUTED, parent=root)
        points = [(-172,307),(-135,307),(-135,282),(-30,282)] if hi else [(-172,282),(-135,282),(-135,307),(-30,307)]
        lines2d(root,[points],YELLOW if hi else GREEN,5)
        self.text('上升沿：拉高' if hi else '低电平：接收', -172, 337, 14, YELLOW if hi else GREEN, parent=root)
        self.text('电压示意，非实物测量', -172, 362, 10, MUTED, parent=root)
        self.text(f'DIR = {self.dir_level}', 324, 34, 22, PURPLE if hi else (0.568,0.551,0.512,1),
                  align=TextNode.ARight, parent=root)
        cx0, cx1, cy0, cy1 = 92, 250, 50, 232
        poly2d(root, [(cx0,cy0),(cx1,cy0),(cx1,cy1),(cx0,cy1)], (0.251,0.243,0.226,1))
        lines2d(root, [[(cx0,cy0),(cx1,cy0),(cx1,cy1),(cx0,cy1),(cx0,cy0)]], (0.418,0.406,0.378,1), 2)
        ty, ry, dy = 80, 188, 134
        self.text('MCU TX', 8, ty+5, 13, ORANGE, parent=root)
        self.text('DIR', 8, dy+5, 13, PURPLE, parent=root)
        self.text('MCU RX', 8, ry+5, 13, GREEN, parent=root)
        dir_col = PURPLE if hi else (0.435,0.422,0.393,1)
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
        digital(224, tDir, 1, PURPLE if not bad else (0.435,0.422,0.393,1), 2)
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

    # ------------------------------------------------------------------ 位级细节（MCU 内部）
    # 时间单位 = 位。每个视图只画一个字节，self.bits['t'] 由 bits_anim 推进。
    BIT_X0, BIT_W = 110, 52
    CPU_MHZ, LOOP_CYCLES = 48, 10   # 举例：48 MHz，空循环每圈约 10 个时钟

    def bx(self, t):
        return self.BIT_X0 + self.BIT_W * t

    @staticmethod
    def along(points, r):
        segs = list(zip(points, points[1:]))
        lengths = [math.dist(a, b) for a, b in segs]
        d = (sum(lengths) or 1) * max(0, min(1, r))
        for (a, b), length in zip(segs, lengths):
            if d <= length and length > 0:
                k = d / length
                return a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k
            d -= length
        return points[-1]

    def token(self, root, x, y, label, color, w=30):
        rect2d(root, x - w/2, y - 11, x + w/2, y + 11, color)
        self.text(label, x, y + 4.5, 12, INK, align=TextNode.ACenter, parent=root)

    def flag(self, root, x, y, name, val, col, note=''):
        on = bool(val)
        rect2d(root, x, y - 11, x + 14, y + 3, col if on else (0.292,0.284,0.264,1))
        self.text(f'{name} = {val}' + (f'  {note}' if note else ''), x + 22, y + 1, 12,
                  col if on else MUTED, parent=root)

    def block(self, root, x0, y0, x1, y1, title, col, sub=''):
        rect2d(root, x0, y0, x1, y1, (0.219,0.212,0.197,1))
        lines2d(root, [[(x0,y0),(x1,y0),(x1,y1),(x0,y1),(x0,y0)]], col, 1)
        self.text(title, (x0 + x1) / 2, y0 + 16, 11, col, align=TextNode.ACenter, parent=root)
        if sub:
            self.text(sub, (x0 + x1) / 2, y1 - 8, 10, MUTED, align=TextNode.ACenter, parent=root)

    def code_box(self, root, rows, y0=272, title='CPU 同一时刻在执行'):
        rect2d(root, 18, y0, 737, 390, (.20,.16,.09,1))
        if title:
            self.text(title, 28, y0 + 18, 12, YELLOW, parent=root)
        for i, (code, note, on) in enumerate(rows):
            yy = y0 + (42 if title else 22) + i * 21
            self.text(code, 28, yy, 12, WHITE if on else MUTED, parent=root)
            if note:
                self.text(note, 430, yy, 12, YELLOW if on else DIM, parent=root)

    def spins(self, us):
        return int(us * self.CPU_MHZ / self.LOOP_CYCLES)

    def draw_bits(self, root):
        b = self.bits
        rect2d(root, 8, 40, 747, 396, (0.172,0.167,0.155,1))
        {'boot': self.bits_boot, 'rx': self.bits_rx, 'read': self.bits_read, 'hdr': self.bits_hdr,
         'len': self.bits_len, 'drain': self.bits_drain, 'gpio': self.bits_gpio, 'tx': self.bits_tx,
         'timeout': self.bits_timeout}.get(b['mode'], self.bits_idle)(root, b)

    def bits_idle(self, root, b):
        state = '开' if self.detail else '关'
        self.text(f'位级细节（细化 MCU：{state}）', 28, 80, 16, CYAN, parent=root)
        for i, line in enumerate(['打开右上角「细化 MCU」后，按「下一步」时，MCU 相关的步骤',
                                  '会先拆成几格，在这里一位一位地展示芯片内部：',
                                  '起始位检测、16 倍过采样、移位寄存器、FIFO、状态寄存器、',
                                  'CPU 轮询循环、包头状态机、长度检查、GPIO 推挽输出、超时计时。']):
            self.text(line, 28, 120 + i * 24, 13, WHITE, parent=root)

    def bits_boot(self, root, b):
        self.text('上电初始化：board_init()（时钟数值为举例）', 18, 62, 13, CYAN, parent=root)
        self.block(root, 18, 84, 138, 140, '时钟源', YELLOW, '晶振 / 内部 RC')
        self.block(root, 168, 84, 288, 140, '倍频 / 分频', YELLOW, 'PLL')
        self.block(root, 318, 84, 438, 140, '外设时钟', YELLOW, '48 MHz')
        lines2d(root, [[(138,112),(168,112)], [(288,112),(318,112)], [(438,112),(470,112)],
                       [(470,82),(470,348)]], YELLOW, 2)
        rows = [('UART0 · 电脑侧', CYAN, '48 000 000 ÷ 16 ÷ 115200 ≈ 26.04 → 分频取 26',
                 '实际 115385 bps，误差 +0.16%'),
                ('UART1 · 电机侧', ORANGE, '48 000 000 ÷ 16 ÷ 57600 ≈ 52.08 → 分频取 52',
                 '实际 57692 bps，误差 +0.16%'),
                ('GPIO DIR_GPIO', PURPLE, '方向设为输出（推挽）', '随后 gpio_write_dir(0)：先接收'),
                ('定时器', GREEN, '每 1ms 中断一次，给 millis() 加 1', '第 09/10 步的 20ms 超时靠它')]
        for i, (name, col, l1, l2) in enumerate(rows):
            y = 92 + i * 66
            lines2d(root, [[(470, y + 20), (490, y + 20)]], YELLOW, 2)
            rect2d(root, 490, y, 737, y + 54, (0.219,0.212,0.197,1))
            self.text(name, 498, y + 17, 12, col, parent=root)
            self.text(l1, 498, y + 33, 10, WHITE, parent=root)
            self.text(l2, 498, y + 48, 10, MUTED, parent=root)
        notes = ['UART 的「波特率」不是凭空来的：外设时钟先除以 16（过采样），',
                 '再除以分频值。除不尽时取整数，就会有一点误差。',
                 '收发两边的误差加起来一般要小于 2%，否则',
                 '到第 10 个位时采样点会滑出位的中间，读错。',
                 '这些设置只在上电做一次；之后 CPU 进入 while(1)。']
        for i, n in enumerate(notes):
            self.text(n, 18, 178 + i * 22, 12, WHITE if i < 4 else GREEN, parent=root)

    def bits_rx(self, root, b):
        byte, t = b['byte'], b['t']
        us = 1e6 / b['baud']
        X = self.bx
        self.text(f'{b["uart"]} 接收器 · {b["baud"]} bps · 1 位 = {us:.2f}µs · 16 倍过采样',
                  18, 60, 13, CYAN, parent=root)
        levels = [1] + uart_bits(byte) + [1]
        names = ['空闲', '起'] + [f'b{k}' for k in range(8)] + ['停', '空闲']
        hi, lo = 84, 108
        self.text(f'{b["pin"]} 脚', 18, 100, 12, CYAN, parent=root)

        def trace(t_end, col, thick):
            pts = []
            for k, v in enumerate(levels):
                if k >= t_end:
                    break
                yv = hi if v else lo
                pts += [(X(k), yv), (X(min(k + 1, t_end)), yv)]
            if len(pts) > 1:
                lines2d(root, [pts], col, thick)
        trace(12, (0.354,0.344,0.320,1), 1)
        trace(t, CYAN, 3)
        cur = int(t)
        for k, name in enumerate(names):
            self.text(name, X(k + .5), 126, 10, YELLOW if k == cur else MUTED,
                      align=TextNode.ACenter, parent=root)
        self.text('采样时钟', 18, 141, 11, MUTED, parent=root)
        done_ticks, todo_ticks = [], []
        for k in range(12):
            for j in range(16):
                x = X(k + j / 16)
                seg = [(x, 134), (x, 142 if j == 8 else 138)]
                (done_ticks if k + j / 16 <= t else todo_ticks).append(seg)
        if todo_ticks: lines2d(root, todo_ticks, (0.302,0.293,0.273,1), 1)
        if done_ticks: lines2d(root, done_ticks, (0.574,0.558,0.519,1), 1)
        samples = [(1.5, levels[1], '确认')] + [(2.5 + k, levels[2 + k], str(levels[2 + k])) for k in range(8)] \
                  + [(10.5, levels[10], '停=1')]
        for s, v, lab in samples:
            if s <= t:
                y = hi if v else lo
                rect2d(root, X(s) - 4, y - 4, X(s) + 4, y + 4, YELLOW)
                self.text(lab, X(s), 76, 10, YELLOW, align=TextNode.ACenter, parent=root)
        if 1 <= t < 1.5:
            self.text('下降沿', X(1) + 6, 78, 10, ORANGE, parent=root)
        lines2d(root, [[(X(t), 66), (X(t), 146)]], YELLOW, 2)
        # 接收移位寄存器：右移，新位从左边进
        self.text('接收移位寄存器（每采一位右移一格，新位从左边进）', 18, 166, 12, WHITE, parent=root)
        m = sum(1 for k in range(8) if 2.5 + k <= t)
        data = uart_bits(byte)[1:9]
        for j in range(8):
            x0 = self.BIT_X0 + j * 44
            v = data[m - 1 - j] if j < m else None
            new = j == 0 and m and b['phase'] == 'data' and t - (2.5 + m - 1) < .6
            rect2d(root, x0, 176, x0 + 40, 204, YELLOW if new else (0.298,0.290,0.269,1) if v is not None else (0.194,0.189,0.175,1))
            if v is not None:
                self.text(str(v), x0 + 20, 196, 15, INK if new else WHITE, align=TextNode.ACenter, parent=root)
            self.text(f'bit{7 - j}', x0 + 20, 218, 9, DIM, align=TextNode.ACenter, parent=root)
        if m == 8:
            self.text(f'= 0x{byte:02X}', self.BIT_X0 + 8 * 44 + 10, 196, 16, YELLOW, parent=root)
        # RX FIFO 与状态标志
        pushed = t >= 10.6
        self.text('RX FIFO', 560, 166, 12, GREEN, parent=root)
        for k in range(5):
            x0 = 560 + k * 35
            on = pushed and k == 0
            rect2d(root, x0, 176, x0 + 32, 204, GREEN if on else (0.194,0.189,0.175,1))
            if on:
                self.text(f'{byte:02X}', x0 + 16, 195, 12, INK, align=TextNode.ACenter, parent=root)
        self.flag(root, 560, 240, 'RX_EMPTY', 0 if pushed else 1, YELLOW, '有字节了' if pushed else '队列空')
        self.flag(root, 560, 262, 'FE', 0, RED, '帧错误：无')
        start_ok = t >= 1.5
        self.text('起始位：' + ('半位处仍为低 → 确认，开始数位' if start_ok else '等待下降沿……'),
                  18, 244, 12, GREEN if start_ok else MUTED, parent=root)
        spin = self.spins(t * us)
        self.code_box(root, [
            ('while (n < need) {', '', False),
            ('    if (UART_GET_RX_EMPTY(uart))', '← 读状态寄存器的 RX_EMPTY 位', True),
            ('        continue;', f'← 还没字节，再转一圈（已转约 {spin} 圈）' if not pushed
             else '← 下一圈就会读到 0，往下走（见下一格）', True),
            ('    uint8_t b = UART_READ(uart);', '这一步还没执行', False)])

    def bits_read(self, root, b):
        r = b['t']
        self.text(f'{b["uart"]}：CPU 经总线读走一个字节', 18, 60, 13, CYAN, parent=root)
        self.block(root, 18, 80, 158, 140, 'RX FIFO', GREEN, '队头')
        self.block(root, 188, 80, 298, 140, '数据寄存器 DR', GREEN, '读它 = 出队')
        self.block(root, 328, 80, 428, 140, 'APB 总线', MUTED)
        self.block(root, 458, 80, 578, 140, 'CPU 寄存器', YELLOW, '变量 b')
        self.block(root, 608, 80, 737, 140, f'SRAM {b["buf"]}[]', PURPLE, '下一格才存')
        lines2d(root, [[(158,110),(188,110)], [(298,110),(328,110)], [(428,110),(458,110)]], DIM, 2)
        path = [(88, 110), (243, 110), (378, 110), (518, 110)]
        x, y = self.along(path, r)
        if r < 1:
            self.token(root, x, y, f'{b["byte"]:02X}', GREEN)
        else:
            self.text(f'b = 0x{b["byte"]:02X}', 518, 116, 15, YELLOW, align=TextNode.ACenter, parent=root)
        empty = 1 if r >= .3 else 0
        self.text('UART 状态寄存器（教学简化：各家芯片的位名和位置不同）', 18, 168, 12, WHITE, parent=root)
        for i, (name, v) in enumerate([('TX_COMPLETE', 1), ('FIFO_EMPTY', 1), ('TX_FULL', 0),
                                        ('FE', 0), ('RX_EMPTY', empty)]):
            x0 = 18 + i * 144
            on = name == 'RX_EMPTY'
            rect2d(root, x0, 178, x0 + 138, 222, (.20,.16,.09,1) if on else (0.219,0.212,0.197,1))
            self.text(name, x0 + 69, 196, 11, YELLOW if on else MUTED, align=TextNode.ACenter, parent=root)
            self.text(str(v), x0 + 69, 216, 15, YELLOW if on else WHITE, align=TextNode.ACenter, parent=root)
        self.text('RX_EMPTY 由硬件自动维护：FIFO 进字节变 0，读空了变回 1。CPU 只读不写。', 18, 248, 11, MUTED, parent=root)
        self.code_box(root, [
            ('    if (UART_GET_RX_EMPTY(uart))', '← 读到 0：条件不成立', r < .3),
            ('        continue;', '← 跳过，不执行', False),
            ('    uint8_t b = (uint8_t)UART_READ(uart);', f'← 读 DR，b = 0x{b["byte"]:02X}' if r >= .75 else '← 读 DR……', r >= .3)])

    def bits_hdr(self, root, b):
        raw = self.packet_bytes
        t = b['t']
        n = min(4, math.ceil(t))
        k = n - 1
        self.text('read_packet() 的包头状态机：n 既是计数，也是「对上了几个」', 18, 60, 13, CYAN, parent=root)
        self.text('HDR[n]', 18, 98, 12, MUTED, parent=root)
        self.text('收到的 b', 18, 140, 12, MUTED, parent=root)
        for i in range(4):
            x0 = 110 + i * 70
            rect2d(root, x0, 78, x0 + 60, 106, (0.298,0.290,0.269,1))
            self.text(f'{(0xFF, 0xFF, 0xFD, 0x00)[i]:02X}', x0 + 30, 98, 14, WHITE, align=TextNode.ACenter, parent=root)
            got = i < t
            rect2d(root, x0, 120, x0 + 60, 148, ORANGE if got and i == k else (0.298,0.290,0.269,1) if got else (0.194,0.189,0.175,1))
            if got:
                self.text(f'{raw[i]:02X}', x0 + 30, 140, 14, INK if i == k else WHITE, align=TextNode.ACenter, parent=root)
        xn = 110 + min(n, 3) * 70 + 30
        poly2d(root, [(xn - 7, 168), (xn + 7, 168), (xn, 156)], YELLOW)
        self.text(f'n = {n}', xn, 184, 12, YELLOW, align=TextNode.ACenter, parent=root)
        if k >= 0:
            i = k
            self.text(f'b = {raw[i]:02X} 等于 HDR[{i}] = {(0xFF, 0xFF, 0xFD, 0x00)[i]:02X} → buf[{i}] = b，n 变成 {i + 1}',
                      400, 98, 12, GREEN, parent=root)
        self.text('规则', 400, 124, 12, WHITE, parent=root)
        for j, line in enumerate(['对上：buf[n++] = b，n 加 1',
                                  '对不上，b 是 FF：n = (n == 2) ? 2 : 1',
                                  '对不上，b 不是 FF：n = 0，从头再找']):
            self.text(line, 400, 146 + j * 20, 11, MUTED, parent=root)
        # 重新同步的例子（静态）
        self.text('例：线上多了噪声字节和一个 FF，看 n 怎么走', 18, 232, 12, WHITE, parent=root)
        seq = [0x12, 0xFF, 0xFF, 0xFF, 0xFD, 0x00, 0x01]
        ns = [0, 1, 2, 2, 3, 4, 5]
        for i, (v, nv) in enumerate(zip(seq, ns)):
            x0 = 18 + i * 64
            bad = i in (0, 3)
            rect2d(root, x0, 242, x0 + 56, 266, (.30,.12,.14,1) if bad else (0.298,0.290,0.269,1))
            self.text(f'{v:02X}', x0 + 28, 260, 13, WHITE, align=TextNode.ACenter, parent=root)
            self.text(f'n={nv}', x0 + 28, 284, 11, RED if bad else MUTED, align=TextNode.ACenter, parent=root)
        self.text('12：对不上且不是 FF → n=0', 470, 254, 11, MUTED, parent=root)
        self.text('第 3 个 FF：n 已是 2 → 留在 2', 470, 274, 11, MUTED, parent=root)
        self.text('这样多出来的 FF 不会让真正的包头错过。', 18, 312, 12, GREEN, parent=root)
        self.text('n ≥ 4 以后不再比对，字节直接存：ID、长度、指令、参数、CRC。', 18, 336, 12, WHITE, parent=root)
        self.text('注意：这里只认包头，不算 CRC；MCU 原样转发，CRC 由电机检查。', 18, 360, 12, YELLOW, parent=root)

    def bits_len(self, root, b):
        raw = self.packet_bytes
        L, Hb = raw[5], raw[6]
        length = L | (Hb << 8)
        need = 7 + length
        stage = ['calc', 'range', 'done'].index(b['phase'])
        self.text('长度字段决定整包有多少字节', 18, 60, 13, CYAN, parent=root)
        for i in range(min(len(raw), 16)):
            x0 = 18 + i * 45
            on = i in (5, 6)
            got = stage == 2 or i < 7
            rect2d(root, x0, 74, x0 + 40, 100, ORANGE if on else (0.298,0.290,0.269,1) if got else (0.194,0.189,0.175,1))
            if got:
                self.text(f'{raw[i]:02X}', x0 + 20, 93, 13, INK if on else WHITE, align=TextNode.ACenter, parent=root)
            self.text(f'[{i}]', x0 + 20, 114, 9, ORANGE if on else DIM, align=TextNode.ACenter, parent=root)
        self.text('包头 4 + ID 1 + 长度 2 = 7', 18 + 3.5 * 45 - 40, 132, 10, MUTED, align=TextNode.ACenter, parent=root)
        lines2d(root, [[(18, 120), (18 + 7 * 45 - 5, 120)]], MUTED, 1)
        self.text(f'长度 = buf[5] | (buf[6] << 8) = 0x{L:02X} | (0x{Hb:02X} << 8) = {length}', 18, 160, 14, WHITE, parent=root)
        self.text(f'need = 7 + {length} = {need}', 18, 184, 14, YELLOW, parent=root)
        self.text('低位在前（小端）：先到的 buf[5] 是低 8 位。', 400, 184, 11, MUTED, parent=root)
        if stage >= 1:
            x = lambda v: 60 + v * 8.4
            y = 236
            lines2d(root, [[(x(0), y), (x(80), y)]], DIM, 2)
            rect2d(root, x(10), y - 7, x(64), y + 7, (.10,.30,.20,1))
            for v in (0, 10, 64, 80):
                self.text(str(v), x(v), y + 24, 10, MUTED, align=TextNode.ACenter, parent=root)
            poly2d(root, [(x(need) - 7, y - 18), (x(need) + 7, y - 18), (x(need), y - 6)], YELLOW)
            self.text(f'need = {need}', x(need), y - 22, 11, YELLOW, align=TextNode.ACenter, parent=root)
            self.text('合法区间 10～64（PKT_MAX）', x(37), y + 4, 10, GREEN, align=TextNode.ACenter, parent=root)
            ok = 10 <= need <= 64
            self.text(('在区间内 → 继续收' if ok else '越界 → return 0'), 18, 290, 13, GREEN if ok else RED, parent=root)
        if stage == 2:
            self.text(f'n = {need}，need = {need}：while (n < need) 不成立 → return {need}', 300, 290, 13, YELLOW, parent=root)
        self.code_box(root, [
            ('need = 7u + (buf[5] | (buf[6] << 8));', f'← n == 7 时只算一次，= {need}', stage == 0),
            ('if (need < 10u || need > PKT_MAX) return 0;', '← 防止写出数组', stage == 1),
            ('return n;', '← 整包收齐', stage == 2)], y0=304, title='')

    def bits_drain(self, root, b):
        r = b['t']
        stale = [0xFD, 0x00]
        left = [v for i, v in enumerate(stale) if r < (.35, .7)[i]]
        self.text('UART1 RX FIFO：发送前先读空', 18, 60, 13, ORANGE, parent=root)
        self.block(root, 18, 80, 258, 140, 'RX FIFO（举例的残留字节）', GREEN)
        for k in range(4):
            x0 = 30 + k * 54
            v = left[k] if k < len(left) else None
            rect2d(root, x0, 104, x0 + 46, 128, GREEN if v is not None else (0.194,0.189,0.175,1))
            if v is not None:
                self.text(f'{v:02X}', x0 + 23, 121, 12, INK, align=TextNode.ACenter, parent=root)
        self.block(root, 330, 80, 450, 140, 'CPU', YELLOW, '读出不保存')
        self.block(root, 540, 80, 680, 140, '丢弃', RED, '(void)')
        lines2d(root, [[(258, 110), (330, 110)], [(450, 110), (540, 110)]], DIM, 2)
        for i, v in enumerate(stale):
            t0 = (.05, .4)[i]
            rr = (r - t0) / .3
            if 0 <= rr < 1:
                x, y = self.along([(57 + 0 * 54, 116), (390, 110), (610, 110)], rr)
                self.token(root, x, y, f'{v:02X}', RED)
        empty = 1 if not left else 0
        self.flag(root, 18, 176, 'RX_EMPTY', empty, YELLOW, '读空了，循环结束' if empty else '还有字节，再读一个')
        for i, line in enumerate(['残留字节从哪来：上一次回包超时之后才到，或者上电时线上的干扰。',
                                  '正常情况下 FIFO 本来就是空的，这个循环一次都不执行。',
                                  '不清掉的话，等会儿收回包时会先读到它们，包头对不上。']):
            self.text(line, 18, 210 + i * 20, 12, WHITE if i < 2 else MUTED, parent=root)
        self.code_box(root, [
            ('while (!UART_GET_RX_EMPTY(MOTOR_UART))', '← 还有字节吗？', True),
            ('    (void)UART_READ(MOTOR_UART);', '← 读出来，不保存', bool(left) or r < .75),
            ('gpio_write_dir(1);', '下一格', False)])

    def bits_gpio(self, root, b):
        r = b['t']
        set_ = r >= .45
        on = r >= .65
        self.text('gpio_write_dir(1)：从一条写寄存器指令到引脚电压', 18, 60, 13, PURPLE, parent=root)
        self.block(root, 18, 80, 118, 140, 'CPU', YELLOW, '写 1')
        self.block(root, 148, 80, 238, 140, '总线', MUTED)
        lines2d(root, [[(118, 110), (148, 110)], [(238, 110), (268, 110)]], DIM, 2)
        self.text('GPIO 输出数据寄存器', 268, 84, 11, PURPLE, parent=root)
        for k in range(8):
            x0 = 268 + k * 26
            bit = 7 - k
            dir_bit = bit == 3
            v = (1 if set_ else 0) if dir_bit else 0
            rect2d(root, x0, 94, x0 + 23, 120, (PURPLE if v else (0.277,0.269,0.250,1)) if dir_bit else (0.213,0.207,0.192,1))
            self.text(str(v), x0 + 11.5, 113, 12, INK if v else (WHITE if dir_bit else DIM), align=TextNode.ACenter, parent=root)
            self.text(str(bit), x0 + 11.5, 134, 9, PURPLE if dir_bit else DIM, align=TextNode.ACenter, parent=root)
        self.text('第 3 位 = DIR（举例），其他位不动', 268, 152, 10, MUTED, parent=root)
        if r < .45:
            x, y = self.along([(68, 110), (193, 110), (268 + 4 * 26 + 11, 107)], r / .45)
            self.token(root, x, y, '1', PURPLE, w=22)
        # 推挽驱动
        cx = 600
        lines2d(root, [[(372, 107), (cx - 60, 107), (cx - 60, 230), (cx - 30, 230)]], PURPLE if set_ else DIM, 2)
        self.text('3.3V', cx, 74, 12, YELLOW, align=TextNode.ACenter, parent=root)
        lines2d(root, [[(cx - 20, 80), (cx + 20, 80)], [(cx, 80), (cx, 150)]], YELLOW, 2)
        up_col, dn_col = (YELLOW if on else DIM), (DIM if on else GREEN)
        rect2d(root, cx - 26, 150, cx + 26, 186, (.30,.24,.08,1) if on else (0.213,0.207,0.192,1))
        self.text('上管 ' + ('导通' if on else '关断'), cx, 173, 11, up_col, align=TextNode.ACenter, parent=root)
        lines2d(root, [[(cx, 186), (cx, 274)]], YELLOW if on else DIM, 2)
        rect2d(root, cx - 26, 274, cx + 26, 310, (.08,.24,.16,1) if not on else (0.213,0.207,0.192,1))
        self.text('下管 ' + ('关断' if on else '导通'), cx, 297, 11, dn_col, align=TextNode.ACenter, parent=root)
        lines2d(root, [[(cx, 310), (cx, 340)], [(cx - 20, 340), (cx + 20, 340)]], GREEN, 2)
        self.text('GND', cx, 358, 12, GREEN, align=TextNode.ACenter, parent=root)
        lines2d(root, [[(cx, 230), (720, 230)]], YELLOW if on else (0.435,0.422,0.393,1), 3)
        rect2d(root, 714, 222, 730, 238, (0.863,0.838,0.780,1))
        self.text('DIR_GPIO', 722, 214, 11, PURPLE, align=TextNode.ACenter, parent=root)
        self.text(('约 3.3V' if on else '约 0V'), 722, 260, 13, YELLOW if on else GREEN, align=TextNode.ACenter, parent=root)
        self.text('→ 缓冲器 1 脚、7 脚', 737, 280, 10, MUTED, align=TextNode.ARight, parent=root)
        for i, line in enumerate(['推挽输出：上下两个开关管一次只开一个。',
                                  '位 = 1：上管通，引脚接到 3.3V；',
                                  '位 = 0：下管通，引脚接到 GND。',
                                  '方向寄存器早在 board_init() 里',
                                  '设成了「输出」，这里只改输出值。',
                                  '整个过程只要几个时钟周期（≈ 0.1µs）。']):
            self.text(line, 18, 190 + i * 22, 12, WHITE if i < 3 else MUTED, parent=root)

    def bits_tx(self, root, b):
        phase, t, byte = b['phase'], b['t'], b['byte']
        us = 1e6 / b['baud']
        X = self.bx
        stage = ['full', 'write', 'load', 'shift'].index(phase)
        self.text(f'{b["uart"]} 发送器 · {b["baud"]} bps · 1 位 = {us:.1f}µs', 18, 60, 13, ORANGE, parent=root)
        self.block(root, 18, 76, 98, 136, 'CPU', YELLOW)
        self.block(root, 112, 76, 196, 136, '数据寄存器', ORANGE, '写它 = 入队')
        # FIFO：队头在右
        queue = []
        if stage == 1 and t >= 1:
            queue = [byte]
        elif stage == 2:
            queue = list(b['queue']) if t < .5 else list(b['queue'][1:])
        elif stage == 3:
            queue = list(b['queue'][1:])
        self.text('TX FIFO（队头在右）', 210, 84, 10, ORANGE, parent=root)
        for k in range(7):
            x0 = 210 + (6 - k) * 30
            v = queue[k] if k < len(queue) else None
            rect2d(root, x0, 94, x0 + 27, 122, ORANGE if v is not None else (0.194,0.189,0.175,1))
            if v is not None:
                self.text(f'{v:02X}', x0 + 13.5, 113, 11, INK, align=TextNode.ACenter, parent=root)
        if len(queue) > 7:
            self.text(f'…还有 {len(queue) - 7} 个', 210, 136, 9, MUTED, parent=root)
        # 发送移位寄存器：[停][b7..b0][起]，起始位在最右，先出去
        frame = [1] + [(byte >> k) & 1 for k in range(7, -1, -1)] + [0]
        names = ['停'] + [f'b{k}' for k in range(7, -1, -1)] + ['起']
        sent = max(0, min(10, int(t - 1))) if stage == 3 else 0
        loaded = stage == 3 or (stage == 2 and t >= .6)
        self.text('发送移位寄存器（右移，最右一位上线）', 430, 84, 10, ORANGE, parent=root)
        for j in range(10):
            x0 = 430 + j * 28
            src = j - sent
            v = frame[src] if loaded and 0 <= src < 10 else None
            out = src == 9 and stage == 3
            rect2d(root, x0, 94, x0 + 25, 122, YELLOW if out else (0.298,0.290,0.269,1) if v is not None else (0.194,0.189,0.175,1))
            if v is not None:
                self.text(str(v), x0 + 12.5, 114, 13, INK if out else WHITE, align=TextNode.ACenter, parent=root)
                self.text(names[src], x0 + 12.5, 137, 10, YELLOW if names[src] in ('起', '停') else DIM,
                          align=TextNode.ACenter, parent=root)
        self.pin(root, 722, 108, '', ORANGE, left=False)
        self.text(b['pin'], 722, 150, 10, ORANGE, align=TextNode.ACenter, parent=root)
        lines2d(root, [[(98, 106), (112, 106)], [(196, 106), (210, 106)], [(420, 106), (430, 106)], [(710, 106), (715, 106)]], DIM, 2)
        if stage == 1 and t < 1:
            x, y = self.along([(58, 106), (154, 106), (210 + 6 * 30 + 13.5, 108)], t)
            self.token(root, x, y, f'{byte:02X}', ORANGE)
        if stage == 2 and t < .6:
            x, y = self.along([(210 + 6 * 30 + 13.5, 108), (430 + 4.5 * 28, 108)], t / .6)
            self.token(root, x, y, f'{byte:02X}', ORANGE)
        # 引脚波形（只在移出阶段）
        hi, lo = 168, 190
        self.text(f'{b["pin"]} 波形', 18, 184, 11, ORANGE, parent=root)
        wire = [1] + [0] + [(byte >> k) & 1 for k in range(8)] + [1, 1]
        tt = t if stage == 3 else 1
        if stage < 3:
            lines2d(root, [[(X(0), hi), (X(12), hi)]], (.35,.30,.22,1), 2)
            self.text('空闲：一直是高电平', X(6), hi - 6, 10, MUTED, align=TextNode.ACenter, parent=root)
        pts = []
        for k, v in enumerate(wire):
            if k >= tt:
                break
            yv = hi if v else lo
            pts += [(X(k), yv), (X(min(k + 1, tt)), yv)]
        if len(pts) > 1:
            lines2d(root, [pts], ORANGE, 3)
        if stage == 3:
            lines2d(root, [[(X(k), 160), (X(k), 198)] for k in range(1, 12) if k <= t], (.45,.40,.25,1), 1)
            lines2d(root, [[(X(t), 156), (X(t), 202)]], YELLOW, 2)
            wn = ['空闲', '起'] + [f'b{k}' for k in range(8)] + ['停', '空闲']
            for k, n in enumerate(wn):
                if k < t:
                    self.text(n, X(k + .5), 212, 9, MUTED, align=TextNode.ACenter, parent=root)
        tx_full = 0
        fifo_empty = 0 if queue else 1
        busy = loaded and not (stage == 3 and t >= 11)
        tx_done = 0 if (busy or queue) else 1
        if stage == 0:
            fifo_empty, tx_done = 1, 1
        self.flag(root, 18, 240, 'TX_FULL', tx_full, RED, '不满，可以写' if stage == 0 else '')
        self.flag(root, 210, 240, 'FIFO_EMPTY', fifo_empty, YELLOW)
        self.flag(root, 400, 240, 'TX_COMPLETE', tx_done, GREEN)
        div = round(self.CPU_MHZ * 1e6 / 16 / b['baud'])
        self.text(f'波特率发生器：48 MHz ÷ 16 ÷ {div} → 每 {us:.1f}µs 一拍（举例时钟）', 18, 262, 11, MUTED, parent=root)
        if stage == 0:
            rows = [('while (UART_IS_TX_FULL(uart)) {}', '← 读到 0：不满，马上往下', True),
                    ('UART_WRITE(uart, p[i]);', '下一格', False)]
        elif stage == 1:
            rows = [('while (UART_IS_TX_FULL(uart)) {}', '', False),
                    ('UART_WRITE(uart, p[i]);', f'← 0x{byte:02X} 写进数据寄存器 → FIFO 队尾', True)]
        elif stage == 2:
            rows = [('for (i = 1; i < len; i++) UART_WRITE(...)', '← CPU 早已把后面的字节写完', True),
                    ('（硬件）FIFO 队头 → 移位寄存器，加起始位和停止位', '没有代码参与', True)]
        else:
            spin = self.spins(max(0, t - 1) * us)
            rows = [('（硬件）每拍右移一位：起 b0 b1 … b7 停', f'已发 {sent} / 10 位', True),
                    ('while (!uart_tx_complete(MOTOR_UART)) {}' if b['uart'] == 'UART1' else 'for (…) 下一个字节',
                     f'CPU 在这里空转（约 {spin} 圈）' if b['uart'] == 'UART1' else '', b['uart'] == 'UART1')]
        self.code_box(root, rows, y0=284)

    def bits_timeout(self, root, b):
        r = b['t']
        elapsed = .5 * r
        self.text('read_packet(MOTOR_UART, g_rx, 20)：带超时地等第一个字节', 18, 60, 13, GREEN, parent=root)
        x = lambda ms: 60 + ms * 32
        y = 110
        rect2d(root, x(0), y - 10, x(20), y + 10, (0.194,0.189,0.175,1))
        rect2d(root, x(0), y - 10, x(max(.08, elapsed)), y + 10, GREEN)
        lines2d(root, [[(x(20), y - 18), (x(20), y + 18)]], RED, 2)
        for v in (0, 5, 10, 15, 20):
            self.text(f'{v}ms', x(v), y + 34, 10, RED if v == 20 else MUTED, align=TextNode.ACenter, parent=root)
        self.text('超时线', x(20), y - 22, 11, RED, align=TextNode.ACenter, parent=root)
        self.text(f'实际经过 {elapsed:.2f} ms', 60, 170, 14, GREEN, parent=root)
        self.text('millis() 每 1ms 才加 1，所以此刻 millis() - t0 读出来还是 0。', 60, 194, 12, MUTED, parent=root)
        arrived = r >= 1
        self.flag(root, 60, 228, 'RX_EMPTY', 0 if arrived else 1, YELLOW,
                  '电机回包的第一个字节到了' if arrived else '回包还没到')
        self.text('电机约 0.5ms 后开始回话（回复延时）。远小于 20ms，所以不会超时。', 60, 256, 12, WHITE, parent=root)
        self.code_box(root, [
            ('if (timeout_ms && (millis() - t0) > timeout_ms)', '← 0 > 20 ? 否，不返回', True),
            ('    return 0;', '电机不回话时才会走到这里', False),
            ('if (UART_GET_RX_EMPTY(uart)) continue;', '← 收到了，往下读' if arrived else f'← 空转（约 {self.spins(elapsed * 1000)} 圈）', True)],
            y0=272)

    def flash_lens(self):
        self.lens_frame['frameColor'] = (0.274,0.266,0.248,1)
        self.timers.append((time.monotonic() + .9, lambda: self.lens_frame.__setitem__('frameColor', CARD)))

    # ------------------------------------------------------------------ 代码与变量
    def show_code(self, step, intro=False, note='', tag=None):
        title, _, _, func, where = STEPS[step]
        if tag:
            func, where = MICRO_CODE.get(tag, (func, where))
            where = f'[{tag}] {where}'
        self.code_where.setText(where + ('' if not note else '   ' + note))
        start, end = self.fw_functions.get(func, (1, len(self.fw_lines)))
        blocks = list(self.fw_tags.get(tag or step, []))
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
                                (0.582,0.565,0.525,1) if is_comment else (0.870,0.845,0.786,1)))
            num.setTextColor(*(YELLOW if on else DIM))
        self.hl_lines = sorted(hl)

    def reset_fw(self):
        self.fw = {'buf': [], 'rx': [], 'n': 0, 'need': 7, 'i': None, 'b': None,
                   'txempty': 1, 'txemptyf': 1, 'wait': None, 'rx_n': 0, 'rx_need': 7,
                   'rx_i': None, 'tx_active': None, 'rx_active': None, 'pc_rx': []}
        self.mcu = {'txq': [], 'shift1': None}
        self.cpu_note = '等待'
        self.micro_queue, self.micro_done = [], set()
        self.bits = {'mode': 'idle', 'phase': '', 't': 0}
        self.bits_anim = None

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
            btn['frameColor'] = ACCENT_DARK if (speed == 1) == (i == 0) else (0.234,0.227,0.212,1)

    def refresh_flow(self):
        for kind, (btn, t1, t2, mark) in self.flow_rows.items():
            state, note = self.flow_state[kind]
            current = self.kind == kind and not self.finished
            btn['frameColor'] = ((.22,.20,.10,1) if current else (.08,.20,.15,1) if state == 'ok'
                                 else (.25,.10,.12,1) if state == 'fail' else (0.225,0.218,0.203,1))
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
        self.bits_anim = None

    def settle(self):
        """跳到下一步前，把上一步还在飞的字节和延时事件立刻做完。"""
        for _ in range(200):
            if not self.flights and not self.timers and not self.wave_anim and not self.bits_anim:
                break
            if self.bits_anim:
                self.bits['t'] = self.bits_anim[3]
                self.bits_anim = None
                if self.lens_tab == 'bits': self.draw_lens()
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
        self.started = time.monotonic()
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

    def record(self, step, title=None, body=None, term=None, micro=None):
        self.last_record = (step, title, body, term, micro)
        t, b, tm, *_ = STEPS[step]
        if micro:
            b, tm = body, term
        title, body, term = title or t, body if body is not None else b, term if term is not None else tm
        easy = EASY.get(micro[0] if micro else step)
        if self.beginner and easy and body.startswith(b):
            body = easy[0] + body[len(b):]
            if term == tm:
                term = easy[1]
        event = {'step': step, 'elapsed_s': round(time.monotonic() - self.started, 3),
                 'title': title, 'detail': body, 'firmware_lines': self.hl_lines}
        label = f'{step:02d}/12'
        if micro:
            event['micro'] = micro[0]
            label += f' · 细节 {micro[1]}/{MICRO_COUNT[step]}'
        self.events.append(event)
        self.set_step_text(f'{label}  {title}', body, term)

    def run_micro(self, step, item):
        """播放一格 MCU 内部细节：位级视图 + 对应代码行，不推进大步骤。"""
        tag, title, body, term, mode, phase, anim = item
        raw, f = self.packet_bytes, self.fw
        b = {'mode': mode, 'phase': phase, 't': anim[1] if anim else 0, 'uart': 'UART0', 'baud': 115200,
             'pin': 'HOST_RX', 'byte': raw[0], 'buf': 'g_buf', 'queue': []}
        if step == 5:
            b.update(uart='UART1', baud=57600, pin='ACT_TX', queue=list(raw))
        elif step == 10:
            b.update(uart='UART1', baud=57600, pin='ACT_RX', byte=self.response[0], buf='g_rx')
        elif step == 11:
            b.update(pin='HOST_TX', byte=self.response[0])
        if anim:
            b['t'] = anim[0]
            self.bits_anim = (time.monotonic(), anim[2] / self.speed, anim[0], anim[1], None)
        self.bits = b
        self.cpu_note = MICRO_CPU.get(tag, self.cpu_note)
        if tag == '02d':
            f['buf'], f['n'], f['b'], f['tx_active'] = [None] * len(raw), 0, raw[0], 0
        elif tag == '02e':
            f['buf'][0], f['n'], f['i'] = raw[0], 1, 0
        elif tag == '05b':
            f['b'], f['i'] = raw[0], 0
        self.set_lens('bits')
        self.show_code(step, tag=tag)
        k = [it[0] for it in MICRO[step]].index(tag) + 1
        self.record(step, title, body, term, micro=(tag, k))
        self.refresh_vars()

    def paint_beginner(self):
        self.easy_btn['text'] = '讲解：新手' if self.beginner else '讲解：专业'
        self.easy_btn['frameColor'] = (.14,.33,.30,1) if self.beginner else (0.234,0.227,0.212,1)

    def toggle_beginner(self):
        self.beginner = not self.beginner
        self.paint_beginner()
        if self.events and getattr(self, 'last_record', None):   # 当前这一格立刻换成另一种讲法
            self.events.pop()
            self.record(*self.last_record)

    def paint_detail(self):
        self.detail_btn['text'] = '细化 MCU：开' if self.detail else '细化 MCU：关'
        self.detail_btn['frameColor'] = (0.288,0.279,0.260,1) if self.detail else (0.234,0.227,0.212,1)

    def toggle_detail(self):
        self.detail = not self.detail
        if not self.detail:
            self.micro_queue = []
        self.paint_detail()
        if self.lens_tab == 'bits':
            self.draw_lens()

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
        upcoming = self.step_index + 2
        if self.detail and not self.micro_queue and upcoming in MICRO and upcoming not in self.micro_done:
            self.micro_done.add(upcoming)
            self.micro_queue = list(MICRO[upcoming])
        if self.micro_queue:
            self.run_micro(upcoming, self.micro_queue.pop(0))
            return
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
            first = 1 if 2 in self.micro_done else 0   # 第 1 个字节已在细节格里逐位看过
            if first:
                f['buf'][0], f['n'] = raw[0], 1

            def in_sram(i):
                f['buf'][i] = raw[i]; f['n'] = i + 1; f['b'] = raw[i]; f['i'] = i
                if f['n'] == 7: f['need'] = 7 + int.from_bytes(raw[5:7], 'little')
                self.refresh_vars()

            def at_mcu(i):
                f['tx_active'] = i
                self.fly([labels[i]], self.path_pc_in(i), CYAN, travel=1.1, space='2d',
                         on_arrive=lambda _, i=i: in_sram(i))
            self.fly(labels[first:], 'usb', CYAN, gap=.32, travel=1.0, on_arrive=lambda i: at_mcu(i + first))
            self.record(2, body=STEPS[2][1] + ('\n第 1 个字节已在细节里逐位看过，这里把其余字节走完；每个都重复 02a～02e。' if first else ''))
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
        if self.bits_anim:
            start, dur, t0, t1, done = self.bits_anim
            r = min(1, (now - start) / dur) if dur > 0 else 1
            t = t0 + (t1 - t0) * r
            if r >= 1 or abs(t - self.bits['t']) >= 1 / 16:   # 一个采样拍重画一次
                self.bits['t'] = t
                if self.lens_tab == 'bits': self.draw_lens()
            if r >= 1:
                self.bits_anim = None
                if done: done()
        busy = False
        for fl in list(self.flights):
            if fl.update(now):
                fl.destroy(); self.flights.remove(fl)
            else:
                busy = True
        busy = busy or bool(self.timers) or bool(self.wave_anim) or bool(self.bits_anim)
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
    if app.bits_anim:
        start, dur, *rest = app.bits_anim
        app.bits_anim = (now - dur * fraction, dur, *rest)
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
    app.detail = False   # 先按原来的 12 步自检；细化 MCU 的逐格自检在最后
    app.paint_detail()

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

    # 细化 MCU：逐格走完一包 Ping，每个细节格截一张图
    app.reset()
    app.detail = True
    app.paint_detail()
    app.set_preset('ping'); app.load_packet()
    tags = []
    for _ in range(80):
        app.next_step()
        last = app.events[-1] if app.events else {}
        if 'micro' in last and last['micro'] not in tags:
            freeze(app, .7)
            tags.append(last['micro'])
            render(app); shot(f'micro-{last["micro"]}.png')
        if app.finished: break
    app.settle()
    expected = [item[0] for step in sorted(MICRO) for item in MICRO[step]]
    assert tags == expected, tags
    for tag in expected:
        assert app.fw_tags.get(tag), f'firmware has no [{tag}] tag'
    assert app.fw['pc_rx'] == list(app.response) and app.fw['buf'] == list(app.packet_bytes)
    assert sum(1 for e in app.events if 'micro' not in e) == 12
    data = json.loads(app.export().read_text(encoding='utf-8'))
    assert [e['micro'] for e in data['steps'] if 'micro' in e] == expected
    assert all(e['detail'].startswith('【比方】') for e in data['steps']), '新手版讲解没有生效'

    # 新手版讲解要放得下：正文最多 5 行，新词最多 2 行
    w = STEP[2] - 28
    for key, (body, term) in EASY.items():
        assert len(app.wrap(body, app.step_text, w, 14).split('\n')) <= 5, f'EASY[{key!r}] 正文太长'
        assert len(app.wrap(term, app.term_text, w, 13).split('\n')) <= 2, f'EASY[{key!r}] 新词太长'
    assert set(EASY) == set(STEPS) | set(expected)
    app.toggle_beginner()
    assert not app.events[-1]['detail'].startswith('【比方】')
    app.toggle_beginner()
    assert app.events[-1]['detail'].startswith('【比方】')
    print('GUI scenarios passed: 12 steps, MCU internals, waveform, FIFO_EMPTY fault, 90° flow, 6 faults, voltage review, invalid HEX, export, '
          f'{len(expected)} MCU detail steps.')
    app.destroy()


if __name__ == '__main__':
    main()
