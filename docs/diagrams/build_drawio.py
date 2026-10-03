#!/usr/bin/env python3
"""Generate the draw.io diagrams (Japanese + English) for Serial Actuator Lab.

Usage:  python docs/diagrams/build_drawio.py
Output: docs/diagrams/serial-actuator-lab.ja.drawio
        docs/diagrams/serial-actuator-lab.en.drawio

Every label is written once as L(ja, en); packet bytes are computed with
protocol.py so the examples can never drift from the code.
"""
import sys
import zlib
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from protocol import hexline, packet, read, status, write  # noqa: E402

LANG = 'en'
FONT_BUMP = 1   # every explicit font size is raised by this many points


def L(ja, en):
    return ja if LANG == 'ja' else en


# ------------------------------------------------------------------ palette
FILL = dict(
    pc='fillColor=#dae8fc;strokeColor=#6c8ebf', mcu='fillColor=#d5e8d4;strokeColor=#82b366',
    ls='fillColor=#ffe6cc;strokeColor=#d79b00', buf='fillColor=#e1d5e7;strokeColor=#9673a6',
    act='fillColor=#f5f5f5;strokeColor=#666666', red='fillColor=#f8cecc;strokeColor=#b85450',
    yel='fillColor=#fff2cc;strokeColor=#d6b656', white='fillColor=#ffffff;strokeColor=#666666',
    cyan='fillColor=#d4f1f9;strokeColor=#1a9bb5', grey='fillColor=#eeeeee;strokeColor=#999999',
    hdr='fillColor=#1f3a5f;strokeColor=#1f3a5f;fontColor=#ffffff;fontStyle=1',
    blue='fillColor=#cfe2f3;strokeColor=#3d85c6',
)
C = dict(tx='#E67E00', rx='#2E9E5B', dir='#7E57C2', data='#0097B8', usb='#1E88E5',
         gnd='#666666', pwr='#D32F2F', v33='#3D85C6', dark='#333333', bad='#C62828')


class Page:
    def __init__(self, name, w=1654, h=1169):
        self.name, self.w, self.h = name, w, h
        self.cells, self.n, self.origin = [], 1, {}
        self.pid = 'p%d' % (zlib.crc32(name.encode('utf-8')) % 10**6)

    def _id(self):
        self.n += 1
        return '%s-%d' % (self.pid, self.n)

    def box(self, x, y, w, h, text='', style='white', size=12, id=None, parent=None,
            align='center', valign='middle', extra='', shape='rounded=1;arcSize=8;'):
        cid = id or self._id()
        base = FILL.get(style, style)
        st = ('%shtml=1;whiteSpace=wrap;%s;fontSize=%s;align=%s;verticalAlign=%s;%s'
              % (shape, base, size + FONT_BUMP, align, valign, extra))
        ox, oy = self.origin.get(parent, (0, 0))
        self.origin[cid] = (x, y)
        self.cells.append(
            '<mxCell id="%s" value="%s" style="%s" vertex="1" parent="%s">'
            '<mxGeometry x="%s" y="%s" width="%s" height="%s" as="geometry"/></mxCell>'
            % (cid, escape(text, quote=True), st, parent or '1', x - ox, y - oy, w, h))
        return cid

    def group(self, x, y, w, h, title, style='pc', size=14, parent=None):
        return self.box(x, y, w, h, '<b>%s</b>' % title, style, size, parent=parent,
                        valign='top', extra='container=1;collapsible=0;dashed=0;strokeWidth=2;')

    def text(self, x, y, w, h, text, size=12, bold=False, color='#333333', align='left',
             valign='middle', extra='', parent=None):
        t = ('<b>%s</b>' % text) if bold else text
        return self.box(x, y, w, h, t, 'strokeColor=none;fillColor=none;fontColor=%s' % color, size,
                        parent=parent, align=align, valign=valign, extra=extra, shape='text;')

    def pt(self, x, y):
        return self.box(x, y, 2, 2, '', 'fillColor=none;strokeColor=none', shape='ellipse;')

    def edge(self, src, tgt, label='', color=None, width=2, points=None, dashed=False,
             both=False, arrow=True, style='', label_bg=True, size=11):
        color = color or C['dark']
        st = ('edgeStyle=%s;html=1;rounded=0;strokeColor=%s;strokeWidth=%s;fontSize=%s;fontColor=#333333;%s%s%s%s%s'
              % ('none' if points is None else 'orthogonalEdgeStyle', color, width, size,
                 'endArrow=block;endFill=1;' if arrow else 'endArrow=none;',
                 'startArrow=block;startFill=1;' if both else '',
                 'dashed=1;' if dashed else '', 'labelBackgroundColor=#ffffff;' if label_bg else '', style))
        pts = ''
        if points:
            pts = '<Array as="points">%s</Array>' % ''.join('<mxPoint x="%s" y="%s"/>' % p for p in points)
        cid = self._id()
        self.cells.append(
            '<mxCell id="%s" value="%s" style="%s" edge="1" parent="1" source="%s" target="%s">'
            '<mxGeometry relative="1" as="geometry">%s</mxGeometry></mxCell>'
            % (cid, escape(label, quote=True), st, src, tgt, pts))
        return cid

    def line(self, x1, y1, x2, y2, label='', color=None, width=2, points=None, dashed=False,
             both=False, arrow=True, size=11, label_bg=True):
        """Free-floating edge between two coordinates."""
        color = color or C['dark']
        st = ('edgeStyle=none;html=1;rounded=0;strokeColor=%s;strokeWidth=%s;fontSize=%s;fontColor=#333333;%s%s%s%s'
              % (color, width, size, 'endArrow=block;endFill=1;' if arrow else 'endArrow=none;',
                 'startArrow=block;startFill=1;' if both else '', 'dashed=1;' if dashed else '',
                 'labelBackgroundColor=#ffffff;' if label_bg else ''))
        pts = ''
        if points:
            pts = '<Array as="points">%s</Array>' % ''.join('<mxPoint x="%s" y="%s"/>' % p for p in points)
        cid = self._id()
        self.cells.append(
            '<mxCell id="%s" value="%s" style="%s" edge="1" parent="1"><mxGeometry relative="1" as="geometry">'
            '<mxPoint x="%s" y="%s" as="sourcePoint"/><mxPoint x="%s" y="%s" as="targetPoint"/>%s</mxGeometry></mxCell>'
            % (cid, escape(label, quote=True), st, x1, y1, x2, y2, pts))
        return cid

    def title(self, ja_en, sub=None):
        self.text(30, 14, self.w - 60, 36, ja_en, 24, True, '#1f3a5f')
        if sub:
            self.text(30, 50, self.w - 60, 26, sub, 13, False, '#666666')

    def table(self, x, y, colw, rowh, rows, header=True, size=11, styles=None, align=None):
        """Grid of cells; rows is a list of lists of strings. rowh may be a list."""
        cy = y
        for r, row in enumerate(rows):
            h = rowh[r] if isinstance(rowh, list) else rowh
            cx = x
            for c, val in enumerate(row):
                st = 'hdr' if (header and r == 0) else (styles[r][c] if styles and styles[r][c] else 'white')
                al = (align[c] if align else 'left') if not (header and r == 0) else 'center'
                self.box(cx, cy, colw[c], h, val, st, size, align=al, shape='rounded=0;spacingLeft=4;spacingRight=4;')
                cx += colw[c]
            cy += h
        return cy

    def xml(self):
        return ('<diagram name="%s" id="%s"><mxGraphModel dx="1422" dy="800" grid="1" gridSize="10" guides="1" '
                'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="%d" pageHeight="%d" '
                'math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/>%s</root></mxGraphModel></diagram>'
                % (escape(self.name, quote=True), self.pid, self.w, self.h, ''.join(self.cells)))


# ======================================================================
# 1. Hardware wiring
# ======================================================================
def page_hardware():
    p = Page(L('1. ハードウェア構成と信号線', '1. Hardware wiring & signals'), 1560, 900)
    p.title(L('1. ハードウェア構成：PC → MCU → レベルシフタ → トライステートバッファ → アクチュエータ',
              '1. Hardware: PC → MCU → level shifter → tri-state buffer → actuator'),
            L('hardware.html の配線図に対応。信号名は汎用の教育用名称で、特定ボードのピンではありません。',
              'Matches hardware.html. Signal names are generic teaching names, not pins of a specific board.'))
    # power sources
    v33 = p.box(500, 90, 330, 56, L('<b>基板上 3.3V ロジック電源</b><br>MCU の I/O 電源域と同じ（モータ電源ではない）',
                                    '<b>On-board 3.3V logic supply</b><br>Same domain as MCU I/O (not the motor supply)'),
                'fillColor=#cfe2f3;strokeColor=#3d85c6', 11)
    v5 = p.box(1210, 90, 220, 56, L('<b>外部安定化 5V</b><br>容量は実機の仕様で選定', '<b>External regulated 5V</b><br>Size per the real actuator spec'),
               FILL['red'], 11)
    # containers
    pc = p.group(30, 190, 170, 300, 'PC')
    mcu = p.group(300, 190, 250, 300, 'MCU')
    ls = p.group(640, 190, 180, 300, 'Level shifter')
    buf = p.group(910, 190, 240, 300, L('トライステートバッファ', 'Tri-state buffer'), 'buf')
    act = p.group(1260, 190, 170, 300, L('アクチュエータ', 'Actuator'), 'act')
    p.cells[-5] = p.cells[-5].replace('fillColor=#dae8fc', 'fillColor=#eaf1fb')
    host = p.box(45, 235, 140, 70, L('ホストプログラム<br><span style="font-size:10px">HEX パケット入力<br>Status 表示</span>',
                                     'Host program<br><span style="font-size:10px">HEX packet in<br>Status out</span>'), 'pc', 11, parent=pc)
    p.box(45, 330, 140, 60, L('電気的には USB の<br>GND を共有', 'Shares USB GND'), 'grey', 10, parent=pc)
    uart0 = p.box(315, 235, 220, 50, L('UART0 ↔ USB-シリアルブリッジ<br><span style="font-size:10px">HOST_RX / HOST_TX（VCOM）</span>',
                                     'UART0 ↔ USB-serial bridge<br><span style="font-size:10px">HOST_RX / HOST_TX (VCOM)</span>'), 'mcu', 11, parent=mcu)
    utx = p.box(315, 300, 220, 40, 'UART1 TX · ACT_TX', 'mcu', 11, parent=mcu)
    urx = p.box(315, 355, 220, 40, 'UART1 RX · ACT_RX', 'mcu', 11, parent=mcu)
    udir = p.box(315, 410, 220, 40, 'GPIO DIR · DIR_GPIO', 'mcu', 11, parent=mcu)
    p.box(315, 457, 220, 24, 'firmware/main.c', 'white', 10, parent=mcu)
    ltx = p.box(660, 300, 140, 40, L('TX 出力方向 →', 'TX output →'), 'ls', 11, parent=ls)
    lrx = p.box(660, 355, 140, 40, L('← RX 入力方向', '← RX input'), 'ls', 11, parent=ls)
    ldr = p.box(660, 410, 140, 40, L('DIR 出力方向 →', 'DIR output →'), 'ls', 11, parent=ls)
    p.box(660, 235, 140, 50, L('既定ではバイパス<br>型番は未定', 'Bypassed by default<br>part TBD'), 'grey', 10, parent=ls)
    btx = p.box(930, 300, 200, 40, L('送信バッファ 5脚 A2 → 3脚 Y2', 'TX buffer  pin5 A2 → pin3 Y2'), 'buf', 10, parent=buf)
    brx = p.box(930, 355, 200, 40, L('受信バッファ 2脚 A1 → 6脚 Y1', 'RX buffer  pin2 A1 → pin6 Y1'), 'buf', 10, parent=buf)
    boe = p.box(930, 410, 200, 40, L('1脚 /OE1(Low有効) + 7脚 OE2(High有効)', 'pin1 /OE1 (active low) + pin7 OE2 (active high)'), 'buf', 10, parent=buf)
    p.box(930, 235, 200, 50, L('8脚 VCC=3.3V　4脚 GND<br>0.1µF デカップリング', 'pin8 VCC=3.3V  pin4 GND<br>0.1µF decoupling'), 'grey', 10, parent=buf)
    adata = p.box(1275, 305, 140, 36, '3  DATA', 'white', 11, parent=act)
    avdd = p.box(1275, 375, 140, 36, '2  VDD (5V)', 'red', 11, parent=act)
    agnd = p.box(1275, 435, 140, 36, '1  GND', 'grey', 11, parent=act)
    # signal edges
    p.edge(host, uart0, 'USB', C['usb'], 4, both=True, style='exitX=1;exitY=0.5;entryX=0;entryY=0.5;')
    p.edge(utx, ltx, 'TX', C['tx'], 3)
    p.edge(ltx, btx, '', C['tx'], 3)
    p.edge(lrx, urx, 'RX', C['rx'], 3)
    p.edge(brx, lrx, '', C['rx'], 3)
    p.edge(udir, ldr, 'DIR', C['dir'], 3)
    p.edge(ldr, boe, '', C['dir'], 3)
    p.edge(btx, adata, '', C['data'], 3, points=[(1190, 320), (1190, 323)], style='exitX=1;exitY=0.5;entryX=0;entryY=0.5;')
    p.edge(adata, brx, '', C['data'], 3, points=[(1190, 323), (1190, 375)], style='exitX=0;exitY=0.5;entryX=1;entryY=0.5;')
    p.text(1160, 255, 100, 30, L('DATA（単線）', 'DATA (single wire)'), 11, True, C['data'], 'center')
    # power
    p.edge(v33, ls, '3.3V', C['v33'], 2, dashed=True, points=[(730, 168)], style='exitX=0.5;exitY=1;entryX=0.5;entryY=0;')
    p.edge(v33, buf, '3.3V', C['v33'], 2, dashed=True, points=[(1030, 118), (1030, 168)], style='exitX=1;exitY=0.5;entryX=0.5;entryY=0;')
    p.edge(v33, mcu, '3.3V', C['v33'], 2, dashed=True, points=[(425, 118), (425, 168)], style='exitX=0;exitY=0.5;entryX=0.5;entryY=0;')
    p.edge(v5, avdd, '5V', C['pwr'], 4, points=[(1470, 118), (1470, 393)], style='exitX=1;exitY=0.5;entryX=1;entryY=0.5;')
    # GND bus
    gy = 540
    ids = []
    for cx in (115, 425, 730, 1030, 1345):
        top = p.pt(cx - 1, 490)
        bot = p.pt(cx - 1, gy)
        p.edge(top, bot, '', C['gnd'], 3, arrow=False)
        ids.append(bot)
    for a, b in zip(ids, ids[1:]):
        p.edge(a, b, '', C['gnd'], 3, arrow=False)
    p.text(480, 548, 600, 24, L('GND：PC・開発ボード・変換器・バッファ・モータ・電源をすべて共通接地',
                                'GND: PC, board, shifter, buffer, actuator and supply all share one ground'), 12, True, C['gnd'], 'center')
    # legend
    p.box(30, 620, 700, 230, '', 'fillColor=#ffffff;strokeColor=#bbbbbb', shape='rounded=1;arcSize=3;')
    p.text(45, 626, 300, 24, L('凡例', 'Legend'), 13, True)
    for i, (lab, col, w) in enumerate([
            (L('USB（双方向）', 'USB (bidirectional)'), C['usb'], 4), (L('TX: MCU → モータ', 'TX: MCU → actuator'), C['tx'], 3),
            (L('RX: モータ → MCU', 'RX: actuator → MCU'), C['rx'], 3), (L('DIR: 方向制御', 'DIR: direction control'), C['dir'], 3),
            (L('DATA: 半二重の単線', 'DATA: half-duplex single wire'), C['data'], 3), (L('3.3V ロジック電源', '3.3V logic supply'), C['v33'], 2),
            (L('5V モータ電源', '5V actuator supply'), C['pwr'], 4), ('GND', C['gnd'], 3)]):
        yy = 665 + (i % 4) * 42
        xx = 50 + (i // 4) * 340
        p.line(xx, yy, xx + 60, yy, '', col, w, arrow=False)
        p.text(xx + 70, yy - 12, 250, 24, lab, 12)
    # notes
    p.box(760, 620, 770, 230, L(
        '<b>教育用の前提（検証済み回路図ではありません）</b><br><br>'
        '• MCU の I/O とバッファは 3.3V、レベルシフタは既定でバイパス、アクチュエータは外部 5V。<br>'
        '• DIR は約 10kΩ でプルダウンし、既定で「受信」。DATA / RX を上拉する場合も 3.3V へ。<br>'
        '• 5V 電源を MCU の 3.3V I/O に接続してはいけません。<br>'
        '• 5V バッファの入力 High 閾値 0.7×VCC = 3.5V は 3.3V 応答を超えるため、3.3V バッファを既定としています。<br>'
        '• 実機の電圧・ピン・電源容量は選定部品の仕様で必ず確認してください。',
        '<b>Teaching assumptions (not a verified schematic)</b><br><br>'
        '• MCU I/O and buffer at 3.3V, level shifter bypassed by default, actuator on external 5V.<br>'
        '• DIR has a ~10kΩ pull-down, so the default state is "receive". Any pull-up on DATA / RX goes to 3.3V.<br>'
        '• Never connect the 5V supply to MCU 3.3V I/O.<br>'
        '• A 5V buffer needs VIH = 0.7×VCC = 3.5V, above a 3.3V reply, so the model defaults to a 3.3V buffer.<br>'
        '• Check voltages, pins and supply capacity against the datasheets of the parts you choose.'),
        'yel', 11, align='left', valign='top', extra='spacingLeft=10;spacingTop=6;spacingRight=10;')
    return p


# ======================================================================
# 2. Software architecture
# ======================================================================
def page_software():
    p = Page(L('2. ソフトウェア構成', '2. Software architecture'), 1654, 1169)
    p.title(L('2. ソフトウェア構成：ファイル・クラス・依存関係', '2. Software architecture: files, classes and dependencies'),
            L('PC 上のシミュレータ（app.py + protocol.py）と、実機に移植するための参考ファームウェア（firmware/）に分かれます。',
              'A PC-side simulator (app.py + protocol.py) and reference firmware (firmware/) meant to be ported to real hardware.'))
    # app.py
    app = p.group(30, 100, 780, 780, 'app.py  (1762 lines · Panda3D GUI)', 'pc', 15)
    demo = p.group(50, 140, 740, 560, L('class Demo(ShowBase)  ― アプリ本体', 'class Demo(ShowBase)  — the application'), 'blue', 13, parent=app)
    # inside Demo – sub-modules
    sm = [
        (65, 180, 340, 120, L('<b>3D シーン</b>  build_scene()<br>PC / MCU / レベルシフタ / バッファ / アクチュエータの箱、<br>配線（USB/TX/RX/DIR/DATA/GND/電源）、<br>モータのダイヤルと舵盤、world_text()',
                              '<b>3D scene</b>  build_scene()<br>Boxes for PC / MCU / shifter / buffer / actuator,<br>wires (USB/TX/RX/DIR/DATA/GND/power),<br>motor dial and horn, world_text()')),
        (425, 180, 350, 120, L('<b>2D UI</b>  build_ui() / resize_ui()<br>パネル：LEFT / VIEW / LENS / CODE / STEP / STRIP<br>部品：DirectButton / DirectEntry / DirectSlider /<br>DirectOptionMenu、byte_cells()',
                              '<b>2D UI</b>  build_ui() / resize_ui()<br>Panels: LEFT / VIEW / LENS / CODE / STEP / STRIP<br>Widgets: DirectButton / DirectEntry / DirectSlider /<br>DirectOptionMenu, byte_cells()')),
        (65, 315, 340, 120, L('<b>12 ステップ状態機械</b><br>load_packet() → next_step() ×12 → settle()<br>record() / stop() / packet_result()<br>STEPS 辞書（タイトル・解説・用語・コード位置）',
                              '<b>12-step state machine</b><br>load_packet() → next_step() ×12 → settle()<br>record() / stop() / packet_result()<br>STEPS dict (title, text, term, code anchor)')),
        (425, 315, 350, 120, L('<b>アニメーション</b><br>Flight（バイトトークンの飛行）、later() タイマ、<br>wave_anim（波形カーソル）、tick() フレームループ、<br>速度 1× / 3×',
                              '<b>Animation</b><br>Flight (byte tokens in flight), later() timers,<br>wave_anim (waveform cursor), tick() frame loop,<br>speed 1× / 3×')),
        (65, 450, 340, 120, L('<b>レンズ（拡大図）</b>  set_lens() / draw_lens()<br>draw_mcu(): FIFO・シフトレジスタ・SRAM<br>draw_chip(): バッファの 2 つのゲート<br>draw_wave(): TX / DIR / FIFO_EMPTY / TX_COMPLETE',
                              '<b>Lens (zoom view)</b>  set_lens() / draw_lens()<br>draw_mcu(): FIFO, shift register, SRAM<br>draw_chip(): the two buffer gates<br>draw_wave(): TX / DIR / FIFO_EMPTY / TX_COMPLETE')),
        (425, 450, 350, 120, L('<b>コードビュー</b>  load_firmware() / show_code()<br>main.c を読み込み、[NN] タグでステップと同期ハイライト<br>reset_fw() / refresh_vars() で変数表示',
                              '<b>Code view</b>  load_firmware() / show_code()<br>Reads main.c, syncs highlight to steps via [NN] tags<br>reset_fw() / refresh_vars() show variables')),
        (65, 585, 340, 100, L('<b>角度制御フロー</b><br>FLOW / AUTO_FLOW、start_sequence()、<br>seq_next()（pos を最大 8 回ポーリング）',
                              '<b>Angle-control flow</b><br>FLOW / AUTO_FLOW, start_sequence(),<br>seq_next() (polls pos up to 8 times)')),
        (425, 585, 350, 100, L('<b>故障注入・出力</b><br>FAULTS ×8 + 電気プロファイル ×2、set_fault()<br>export() → output/trace-*.json',
                              '<b>Fault injection & export</b><br>FAULTS ×8 + 2 electrical profiles, set_fault()<br>export() → output/trace-*.json')),
    ]
    for x, y, w, h, t in sm:
        p.box(x, y, w, h, t, 'white', 10, align='left', valign='top', parent=demo, extra='spacingLeft=6;spacingTop=4;')
    flight = p.box(50, 715, 360, 70, L('<b>class Flight</b><br>パスに沿って複数バイトを順に飛ばす。<br>on_depart / on_arrive / cut（途中で消える）',
                                       '<b>class Flight</b><br>Moves byte tokens along a path in order.<br>on_depart / on_arrive / cut (vanish midway)'),
                   'yel', 10, align='left', valign='top', parent=app, extra='spacingLeft=6;spacingTop=4;')
    helpers = p.box(430, 715, 360, 70, L('<b>モジュール関数</b><br>box / poly2d / rect2d / lines2d（描画）、uart_bits()、<br>load_firmware()、render / freeze / run_packet / main()',
                                         '<b>Module functions</b><br>box / poly2d / rect2d / lines2d (drawing), uart_bits(),<br>load_firmware(), render / freeze / run_packet / main()'),
                    'yel', 10, align='left', valign='top', parent=app, extra='spacingLeft=6;spacingTop=4;')
    p.box(50, 800, 740, 66, L('<b>定数</b>  W,H=1600×1000 ／ MAX_BYTES=16（表示用 FIFO 深さ）／ MOTOR_DEMO_SPEED=260 ticks/s（アニメ用）／<br>FAULTS・STEPS・LENS_FOR_STEP・FLOW・AUTO_FLOW ／ 色: BG / CARD / ORANGE / GREEN / PURPLE …',
                              '<b>Constants</b>  W,H=1600×1000 / MAX_BYTES=16 (display FIFO depth) / MOTOR_DEMO_SPEED=260 ticks/s (animation) /<br>FAULTS, STEPS, LENS_FOR_STEP, FLOW, AUTO_FLOW / colours: BG / CARD / ORANGE / GREEN / PURPLE …'),
          'grey', 10, align='left', valign='top', parent=app, extra='spacingLeft=6;spacingTop=4;')
    # protocol.py
    prot = p.group(950, 100, 670, 520, 'protocol.py  (168 lines · ' + L('シリアル I/O なし', 'no serial I/O') + ')', 'ls', 15)
    p.box(970, 140, 310, 230, L(
        '<b>フレーミング関数</b><br><br>'
        'HEADER = FF FF FD 00<br>'
        'crc16(data) — 多項式 0x8005、初期値 0<br>'
        'stuff() / unstuff() — バイトスタッフィング<br>'
        'packet(id, inst, params) — フレーム生成<br>'
        'parse(raw) → Packet — 検証＋分解<br>'
        'from_hex() / hexline() — HEX 変換<br>'
        'write() / read() / read_position() / status()',
        '<b>Framing functions</b><br><br>'
        'HEADER = FF FF FD 00<br>'
        'crc16(data) — poly 0x8005, init 0<br>'
        'stuff() / unstuff() — byte stuffing<br>'
        'packet(id, inst, params) — build a frame<br>'
        'parse(raw) → Packet — validate + decode<br>'
        'from_hex() / hexline() — HEX conversion<br>'
        'write() / read() / read_position() / status()'),
        'white', 10, align='left', valign='top', parent=prot, extra='spacingLeft=8;spacingTop=6;')
    p.box(1295, 140, 310, 230, L(
        '<b>class Motor</b>（教育用レジスタのサブセット）<br><br>'
        '属性: device_id=1, torque, position, goal,<br>'
        'return_level=2, operating_mode=3, firmware_version=1,<br>'
        'speed=700 ticks/s（app が 260 に上書き）<br><br>'
        'moving — torque ∧ |goal−pos|&gt;1<br>'
        'update(dt) — 目標へ速度制限付きで移動<br>'
        'reply(Packet) → (応答 or None, 説明文)',
        '<b>class Motor</b> (teaching register subset)<br><br>'
        'attrs: device_id=1, torque, position, goal,<br>'
        'return_level=2, operating_mode=3, firmware_version=1,<br>'
        'speed=700 ticks/s (app overrides to 260)<br><br>'
        'moving — torque ∧ |goal−pos|&gt;1<br>'
        'update(dt) — move toward goal, rate limited<br>'
        'reply(Packet) → (response or None, note)'),
        'white', 10, align='left', valign='top', parent=prot, extra='spacingLeft=8;spacingTop=6;')
    p.box(970, 385, 635, 70, L(
        '<b>@dataclass Packet</b>(device_id, instruction, params)　　'
        '<b>電気モデルではありません</b>：Motor はレジスタ挙動のみを模擬します。',
        '<b>@dataclass Packet</b>(device_id, instruction, params)　　'
        '<b>Not an electrical model</b>: Motor only simulates register behaviour.'),
        'yel', 10, align='left', valign='top', parent=prot, extra='spacingLeft=8;spacingTop=6;')
    p.box(970, 470, 635, 130, L(
        '<b>本物の通信路は存在しない</b><br>'
        'app.py は serial / socket を一切開きません。Demo.next_step() が Motor.reply() を直接呼び、<br>'
        'MCU・バッファ・USB はアニメーションと状態変数としてだけ表現されます。',
        '<b>There is no real link</b><br>'
        'app.py never opens a serial port or socket. Demo.next_step() calls Motor.reply() directly;<br>'
        'the MCU, buffer and USB exist only as animation and state variables.'),
        'white', 10, align='left', valign='top', parent=prot, extra='spacingLeft=8;spacingTop=6;')
    # firmware
    fw = p.group(950, 650, 670, 230, 'firmware/  ' + L('（参考実装・ビルド不可）', '(reference, not buildable)'), 'mcu', 15)
    p.box(970, 690, 310, 175, L(
        '<b>board.h</b>  — プラットフォーム適応インターフェース<br><br>'
        'PC_UART / MOTOR_UART、board_init()、millis()<br>'
        'UART_GET_RX_EMPTY / UART_READ<br>'
        'UART_IS_TX_FULL / UART_WRITE<br>'
        'uart_tx_complete() — FIFO ＋ シフトレジスタ ＋ 停止ビット<br>'
        'gpio_write_dir(level)<br>'
        'PKT_MAX=64 / WAIT_FOREVER=0 / REPLY_TIMEOUT_MS=20',
        '<b>board.h</b> — platform adaptation interface<br><br>'
        'PC_UART / MOTOR_UART, board_init(), millis()<br>'
        'UART_GET_RX_EMPTY / UART_READ<br>'
        'UART_IS_TX_FULL / UART_WRITE<br>'
        'uart_tx_complete() — FIFO + shift reg + stop bit<br>'
        'gpio_write_dir(level)<br>'
        'PKT_MAX=64 / WAIT_FOREVER=0 / REPLY_TIMEOUT_MS=20'),
        'white', 10, align='left', valign='top', parent=fw, extra='spacingLeft=8;spacingTop=6;')
    p.box(1295, 690, 310, 175, L(
        '<b>main.c</b>  — ブリッジ本体<br><br>'
        'read_packet(uart, buf, timeout)<br>'
        'motor_send(p, len)<br>'
        'pc_write(p, len)<br>'
        'main() — 受信 → 送信 → 応答待ち → 転送<br><br>'
        '[01]〜[12] タグ = GUI のステップ番号',
        '<b>main.c</b> — the bridge itself<br><br>'
        'read_packet(uart, buf, timeout)<br>'
        'motor_send(p, len)<br>'
        'pc_write(p, len)<br>'
        'main() — receive → send → wait → forward<br><br>'
        '[01]–[12] tags = GUI step numbers'),
        'white', 10, align='left', valign='top', parent=fw, extra='spacingLeft=8;spacingTop=6;')
    # other files
    p.group(30, 910, 780, 200, L('その他のファイル', 'Other files'), 'grey', 14)
    p.box(50, 945, 240, 150, L('<b>test_protocol.py</b><br>unittest ×8<br>Ping ベクタ FF FF FD 00 01 03 00 01 19 4E、<br>スタッフィング、CRC/Length 拒否、<br>トルクと移動、ID 不一致、返信ポリシー',
                               '<b>test_protocol.py</b><br>unittest ×8<br>Ping vector FF FF FD 00 01 03 00 01 19 4E,<br>stuffing, CRC/Length rejection,<br>torque gating, ID mismatch, reply policy'),
          'white', 10, align='left', valign='top', extra='spacingLeft=6;spacingTop=4;')
    p.box(300, 945, 240, 150, L('<b>hardware.html</b><br>静的ドキュメント：配線 SVG、<br>OE の真理値表、DIR タイミング、<br>ソフト/ハードの分担、電圧閾値',
                                '<b>hardware.html</b><br>Static document: wiring SVG,<br>OE truth table, DIR timing,<br>software/hardware split, voltage threshold'),
          'white', 10, align='left', valign='top', extra='spacingLeft=6;spacingTop=4;')
    p.box(550, 945, 240, 150, L('<b>start.cmd / requirements.txt / README.md</b><br>Windows 起動スクリプト（.venv を探す）<br>panda3d==1.10.16<br>環境変数 SERVO_LAB_FONT = 日本語/中国語フォント<br>output/ = スクリーンショット・trace JSON',
                                '<b>start.cmd / requirements.txt / README.md</b><br>Windows launcher (finds .venv)<br>panda3d==1.10.16<br>env SERVO_LAB_FONT = CJK font file<br>output/ = screenshots and trace JSON'),
          'white', 10, align='left', valign='top', extra='spacingLeft=6;spacingTop=4;')
    # external
    pd = p.box(950, 920, 320, 70, L('<b>外部依存: Panda3D 1.10.16</b><br>ShowBase / DirectGui / OffscreenBuffer / LineSegs',
                                    '<b>External: Panda3D 1.10.16</b><br>ShowBase / DirectGui / offscreen buffer / LineSegs'),
               'cyan', 11, align='left', valign='top', extra='spacingLeft=8;spacingTop=6;')
    font = p.box(1290, 920, 330, 70, L('<b>CJK フォント</b>（Windows: msyh.ttc ほか、<br>または SERVO_LAB_FONT）— 無いと起動時に RuntimeError',
                                       '<b>CJK font</b> (Windows msyh.ttc etc.,<br>or SERVO_LAB_FONT) — RuntimeError at startup if none'),
                 'cyan', 11, align='left', valign='top', extra='spacingLeft=8;spacingTop=6;')
    # relations between the big containers (all straight / single-bend, labels kept short)
    p.edge(app, prot, 'import', C['dark'], 2, style='exitX=1;exitY=0.1923;entryX=0;entryY=0.2885;')
    p.edge(app, fw, L('main.c を<br>読むだけ', 'reads main.c<br>(never runs it)'), C['dark'], 2, dashed=True, style='exitX=1;exitY=0.859;entryX=0;entryY=0.5217;')
    p.edge(pd, app, L('継承 / 使用', 'extends / uses'), C['dark'], 2, dashed=True, points=[(880, 955), (880, 850)], style='exitX=0;exitY=0.5;entryX=1;entryY=0.9615;')
    return p


# ======================================================================
# 3. Packet format
# ======================================================================
def cells(p, x, y, items, cw=62, ch=44, size=12):
    """items: list of (text, style, width_in_cells)"""
    out = []
    for t, st, n in items:
        out.append(p.box(x, y, cw * n, ch, t, st, size, shape='rounded=0;', extra='fontStyle=1;'))
        x += cw * n
    return out


def page_packet():
    p = Page(L('3. パケット形式', '3. Packet format'), 1654, 1260)
    p.title(L('3. 通信パケット：構造・バイトスタッフィング・CRC・検証順序',
              '3. Packet format: layout, byte stuffing, CRC and validation order'),
            L('protocol.py の packet() / parse() に対応。数値例は protocol.py から自動計算。',
              'Mirrors packet() / parse() in protocol.py. Numeric examples are computed from protocol.py.'))
    x0 = 90
    p.text(30, 100, 300, 24, L('命令パケット (Instruction Packet)', 'Instruction Packet'), 14, True, C['tx'])
    cells(p, x0, 150, [('FF', 'ls', 1), ('FF', 'ls', 1), ('FD', 'ls', 1), ('00', 'ls', 1), ('ID', 'pc', 1),
                       ('LEN_L', 'cyan', 1), ('LEN_H', 'cyan', 1), ('INST', 'red', 1),
                       ('Parameters …', 'yel', 3), ('CRC_L', 'buf', 1), ('CRC_H', 'buf', 1)], 90)
    marks = [(0, 4, L('Header（固定）', 'Header (fixed)'), 'byte 0–3'), (4, 1, L('デバイス ID', 'Device ID'), 'byte 4'),
             (5, 2, L('Length（リトルエンディアン）', 'Length (little endian)'), 'byte 5–6'), (7, 1, L('命令', 'Instr.'), 'byte 7'),
             (8, 3, L('パラメータ（スタッフィング済み）', 'Parameters (byte-stuffed)'), 'byte 8 …'), (11, 2, L('CRC-16（LE）', 'CRC-16 (LE)'), 'last 2')]
    for s, n, lab, by in marks:
        p.text(x0 + s * 90, 194, n * 90, 38, '<b>%s</b><br><span style="font-size:10px;color:#888">%s</span>' % (lab, by), 11, False, '#333', 'center')
    # Length bracket
    p.line(x0 + 7 * 90, 118, x0 + 13 * 90, 118, '', C['dir'], 2, arrow=True, both=True, label_bg=False)
    p.line(x0 + 7 * 90, 118, x0 + 7 * 90, 148, '', C['dir'], 1, arrow=False, dashed=True, label_bg=False)
    p.line(x0 + 13 * 90, 118, x0 + 13 * 90, 148, '', C['dir'], 1, arrow=False, dashed=True, label_bg=False)
    p.text(x0 + 7 * 90, 96, 6 * 90, 22, L('Length = 命令＋パラメータ（スタッフィング後）＋ CRC 2 バイト', 'Length = instruction + parameters (after stuffing) + 2 CRC bytes'),
           11, True, C['dir'], 'center')
    p.line(x0, 250, x0 + 7 * 90 - 4, 250, '', '#888', 1, arrow=True, both=True, label_bg=False)
    p.line(x0 + 7 * 90 + 4, 250, x0 + 13 * 90, 250, '', C['dir'], 1, arrow=True, both=True, label_bg=False)
    p.text(x0, 252, 7 * 90, 20, L('先頭 7 バイト', 'first 7 bytes'), 10, False, '#888', 'center')
    p.text(x0 + 7 * 90, 252, 6 * 90, 20, L('Length の指す範囲', 'range counted by Length'), 10, False, C['dir'], 'center')
    p.text(x0, 276, 1200, 22, L('総バイト数 ＝ 7 ＋ Length ／ 最小 10 バイト ／ ID は単播 0〜252（ブロードキャスト不可）／ firmware の PKT_MAX = 64',
                                'Total bytes = 7 + Length / minimum 10 bytes / unicast ID 0–252 only (no broadcast) / firmware PKT_MAX = 64'), 12, False, '#444')
    # Status packet
    p.text(30, 320, 400, 24, L('状態パケット (Status Packet)', 'Status Packet'), 14, True, C['rx'])
    cells(p, x0, 360, [('FF', 'ls', 1), ('FF', 'ls', 1), ('FD', 'ls', 1), ('00', 'ls', 1), ('ID', 'pc', 1),
                       ('LEN_L', 'cyan', 1), ('LEN_H', 'cyan', 1), ('55', 'red', 1), ('ERR', 'yel', 1),
                       ('Parameters …', 'yel', 2), ('CRC_L', 'buf', 1), ('CRC_H', 'buf', 1)], 90)
    p.text(x0 + 7 * 90, 406, 90, 22, L('Status = 0x55', 'Status = 0x55'), 10, True, C['bad'], 'center')
    p.text(x0 + 8 * 90, 406, 90, 22, L('Error バイト', 'Error byte'), 10, True, '#8a6d00', 'center')
    p.text(x0, 432, 1200, 22, L('命令パケットと同じ枠組み ＋ Error 1 バイト（パラメータの先頭）。', 'Same framing as an instruction packet, plus 1 Error byte at the start of the parameters.'), 12, False, '#444')
    # instructions table
    p.text(30, 480, 300, 22, L('命令（本シミュレータが対応するもの）', 'Instructions supported by this simulator'), 14, True)
    p.table(30, 510, [80, 150, 420, 330], 34, [
        ['INST', L('名前', 'Name'), L('パラメータ', 'Parameters'), L('応答', 'Response')],
        ['01', 'Ping', L('なし（付けると Error 5）', 'none (any params → Error 5)'), L('モデル番号 2B ＝1、ファームウェア版 1B ＝1', 'model number 2B =1, firmware version 1B =1')],
        ['02', 'Read', L('addr(2B LE) ＋ length(2B LE)', 'addr (2B LE) + length (2B LE)'), L('Error ＋ レジスタ値', 'Error + register value')],
        ['03', 'Write', L('addr(2B LE) ＋ データ(1〜4B LE)', 'addr (2B LE) + data (1–4B LE)'), L('Error のみ（成功＝受理、到達ではない）', 'Error only (success = accepted, not arrived)')],
        ['55', 'Status', L('Error(1B) ＋ 応答データ', 'Error (1B) + response data'), L('モータ → PC 方向のみ', 'actuator → PC direction only')],
        ['other', L('その他', 'Others'), '—', L('Error 2（本模擬は未実装）', 'Error 2 (not implemented)')],
    ], header=True, size=11)
    p.text(1040, 480, 300, 22, 'Error', 14, True)
    p.table(1040, 510, [60, 520], 34, [
        ['Err', L('意味（Motor.reply で使用）', 'Meaning (used by Motor.reply)')],
        ['00', L('正常に受理', 'Accepted')], ['02', L('未実装の命令', 'Instruction not implemented')],
        ['04', L('値の範囲外（Torque>1 / Return Level>2 / Mode≠3）', 'Data out of range (Torque>1 / Return Level>2 / Mode≠3)')],
        ['05', L('パラメータ/データ長が不正', 'Wrong parameter / data length')],
        ['06', L('目標位置が 0〜4095 の範囲外', 'Goal position outside 0–4095')],
        ['07', L('未実装レジスタ / トルク ON 中のモード変更', 'Unimplemented register / mode change while torque on')],
    ], header=True, size=11)
    # examples
    p.text(30, 770, 400, 22, L('実例（protocol.py で生成）', 'Examples (generated by protocol.py)'), 14, True)
    ex = [
        (L('Ping（ID=1）', 'Ping (ID=1)'), packet(1, 1)),
        (L('Ping の Status 応答', 'Status reply to Ping'), status(1, 0, (1).to_bytes(2, 'little') + bytes([1]))),
        (L('Read 11 番（モード）', 'Read addr 11 (mode)'), read(11, 1)),
        (L('Write 64 番 ＝ 1（トルク ON）', 'Write addr 64 = 1 (torque on)'), write(64, b'\x01')),
        (L('Write 116 番 ＝ 1024（90°）', 'Write addr 116 = 1024 (90°)'), write(116, (1024).to_bytes(4, 'little'))),
        (L('Read 132 番（現在位置 4B）', 'Read addr 132 (present pos, 4B)'), read(132, 4)),
    ]
    rows = [[L('内容', 'Case'), 'HEX', L('バイト数', 'Bytes')]]
    for lab, raw in ex:
        rows.append([lab, hexline(raw), str(len(raw))])
    p.table(30, 800, [310, 560, 90], 32, rows, header=True, size=11, align=['left', 'left', 'center'])
    # stuffing + crc
    p.box(1040, 770, 570, 130, L(
        '<b>バイトスタッフィング</b><br>ボディ中に FF FF FD が現れたら直後に FD を 1 つ挿入し、<br>ヘッダと誤認されないようにする（受信側は FF FF FD FD → FF FF FD に戻す）。<br>'
        '例: params FF FF FD → ボディ FF FF FD <b>FD</b>、Length が 1 増える。',
        '<b>Byte stuffing</b><br>If FF FF FD appears in the body, insert one extra FD after it<br>so it cannot be mistaken for a header (receiver turns FF FF FD FD back into FF FF FD).<br>'
        'Example: params FF FF FD → body FF FF FD <b>FD</b>, Length grows by 1.'),
        'yel', 11, align='left', valign='top', extra='spacingLeft=8;spacingTop=6;')
    p.box(1040, 915, 570, 110, L(
        '<b>CRC-16</b>　多項式 0x8005、初期値 0、MSB ファースト（非反転）。<br>ヘッダ〜パラメータの全バイトに対して計算し、<b>下位バイト先</b>で末尾 2 バイトに付ける。<br>'
        '例: Ping → CRC = 19 4E',
        '<b>CRC-16</b>  polynomial 0x8005, init 0, MSB-first (non-reflected).<br>Computed over header … parameters; appended <b>low byte first</b>.<br>'
        'Example: Ping → CRC = 19 4E'),
        'cyan', 11, align='left', valign='top', extra='spacingLeft=8;spacingTop=6;')
    # validation flow
    p.text(30, 1060, 900, 22, L('parse() の検証順序（失敗すると ValueError → GUI は「入力未送信」）', 'Validation order in parse() (any failure → ValueError → GUI shows "input not sent")'), 13, True)
    chk = [L('① 長さ≥10 かつ<br>ヘッダ FF FF FD 00', '① len ≥ 10 and<br>header FF FF FD 00'), L('② ID ≤ 252', '② ID ≤ 252'),
           L('③ Length + 7<br>＝ 実バイト数', '③ Length + 7<br>= actual bytes'), L('④ CRC 一致', '④ CRC matches'),
           L('⑤ スタッフィング<br>が正しい', '⑤ stuffing is<br>well-formed'), L('→ Packet(id,<br>inst, params)', '→ Packet(id,<br>inst, params)')]
    ids = []
    for i, t in enumerate(chk):
        ids.append(p.box(30 + i * 180, 1100, 150, 56, t, 'mcu' if i < 5 else 'blue', 11))
    for a, b in zip(ids, ids[1:]):
        p.edge(a, b, '', C['dark'], 2)
    p.text(30, 1170, 1200, 22, L('load_packet() はさらに「命令が 01/02/03 のみ」「全長 ≤ 16 バイト（表示用 FIFO 深さ）」を要求します。',
                                 'load_packet() additionally requires "instruction is 01/02/03" and "total length ≤ 16 bytes (display FIFO depth)".'), 11, False, '#555')
    return p


# ======================================================================
# 4. Register map & Motor model
# ======================================================================
def page_registers():
    p = Page(L('4. レジスタとモータモデル', '4. Registers & motor model'), 1654, 940)
    p.title(L('4. 教育用モータ：レジスタ表・返信ポリシー・動作モデル', '4. Teaching motor: register map, reply policy and motion model'),
            L('protocol.py の Motor クラス。すべて本シミュレーション内の定義であり、実機の仕様ではありません。',
              'The Motor class in protocol.py. All of this is defined by the simulation, not a real device spec.'))
    p.text(30, 90, 400, 22, L('レジスタ表', 'Register map'), 14, True)
    p.table(30, 120, [70, 190, 60, 70, 190, 380, 160], 44, [
        [L('アドレス', 'Addr'), L('名前', 'Name'), L('長さ', 'Size'), L('属性', 'Access'), L('値', 'Values'), L('挙動', 'Behaviour'), L('初期値', 'Initial')],
        ['11', 'Operating Mode', '1', 'R/W', L('3 = 位置制御のみ', '3 = position control only'), L('トルク ON 中の変更は Error 7、3 以外は Error 4', 'Change while torque ON → Error 7; value ≠ 3 → Error 4'), '3'],
        ['64', 'Torque Enable', '1', 'R/W', '0 / 1', L('1 のときだけ位置が目標へ動く。2 以上は Error 4', 'Position only moves when 1; ≥2 → Error 4'), '0 (OFF)'],
        ['68', 'Status Return Level', '1', 'R/W', '0 / 1 / 2', L('どの命令に応答するか（下表）。3 以上は Error 4', 'Which instructions get a reply (table below); ≥3 → Error 4'), '2'],
        ['116', 'Goal Position', '4', 'R/W', '0 – 4095', L('4096 以上は Error 6。トルク OFF なら値だけ保存して動かない', '≥ 4096 → Error 6. With torque OFF it is stored but nothing moves'), '2048 (180°)'],
        ['122', 'Moving', '1', 'R', '0 / 1', L('torque ∧ |goal − position| > 1（Read のみ対応）', 'torque ∧ |goal − position| > 1 (readable only)'), '0'],
        ['132', 'Present Position', '4', 'R', 'ticks', L('現在位置。ID=1 の Read(132,4) で取得', 'Current position, read with Read(132,4)'), '2048 (180°)'],
    ], size=11, styles=None, align=['center', 'left', 'center', 'center', 'left', 'left', 'center'])
    p.text(30, 450, 500, 22, L('返信ポリシー（Status Return Level）', 'Reply policy (Status Return Level)'), 14, True)
    ok, no = 'mcu', 'red'
    p.table(30, 480, [160, 130, 130, 130], 40, [
        ['Level', 'Ping', 'Read', 'Write'],
        ['0', '✔', '✘', '✘'], ['1', '✔', '✔', '✘'], ['2 (' + L('既定', 'default') + ')', '✔', '✔', '✔'],
    ], size=12, styles=[[None] * 4, ['white', ok, no, no], ['white', ok, ok, no], ['white', ok, ok, ok]], align=['center'] * 4)
    p.text(30, 650, 550, 70, L('Write の返信有無は「書き込み前の」Level で決まる（Level を 2→1 に書き換えた Write 自体は返信される）。'
                               'エラー応答も同じポリシーに従う（Ping の長さエラーは常に返信）。',
                               'Whether a Write replies depends on the Level <b>before</b> the write (a Write that changes 2→1 is still answered). '
                               'Error replies follow the same policy (Ping length error is always answered).'), 11, False, '#444', valign='top')
    # conversion + motion
    p.box(600, 450, 480, 130, L(
        '<b>角度 ↔ ticks</b><br>ticks = 角度 × 4096 ÷ 360（GUI は round() ％ 4096）<br>角度 = ticks × 360 ÷ 4096<br>'
        '例: 90° = 1024、180° = 2048、359° = 4085<br>Goal は 4 バイト・リトルエンディアン（90° → 00 04 00 00）',
        '<b>Angle ↔ ticks</b><br>ticks = angle × 4096 ÷ 360 (GUI: round() mod 4096)<br>angle = ticks × 360 ÷ 4096<br>'
        'e.g. 90° = 1024, 180° = 2048, 359° = 4085<br>Goal is 4 bytes, little endian (90° → 00 04 00 00)'),
        'cyan', 11, align='left', valign='top', extra='spacingLeft=8;spacingTop=6;')
    p.box(1110, 450, 510, 130, L(
        '<b>動作モデル  Motor.update(dt)</b><br>torque = 1 のとき<br>position += clamp(goal − position, ±speed × dt)<br>'
        'speed = 700 ticks/s（Demo は 260 ticks/s に変更：アニメを遅くするため）<br>torque = 0 のときは位置は動かない',
        '<b>Motion model  Motor.update(dt)</b><br>when torque = 1<br>position += clamp(goal − position, ±speed × dt)<br>'
        'speed = 700 ticks/s (Demo sets 260 ticks/s to slow the animation)<br>when torque = 0 the position never moves'),
        'yel', 11, align='left', valign='top', extra='spacingLeft=8;spacingTop=6;')
    p.box(600, 600, 1020, 110, L(
        '<b>注意：Write 成功 ≠ 到達</b>　Status の Error=0 は「命令を受理した」だけです。'
        '到達の確認は Read(132) の現在位置と目標の差（|Δ| ≤ 2 ticks）で行います。<br>'
        'GUI では位置更新が tick() で毎フレーム進むため、Write 直後に Read すると途中の値が返ります。',
        '<b>Note: Write success ≠ arrival</b>  Error = 0 only means the instruction was accepted. '
        'Arrival is checked by reading Present Position (132) and comparing with the goal (|Δ| ≤ 2 ticks).<br>'
        'In the GUI the position advances every frame in tick(), so a Read right after a Write returns a mid-move value.'),
        'red', 11, align='left', valign='top', extra='spacingLeft=8;spacingTop=6;')
    # Ping details
    p.box(30, 740, 1590, 150, L(
        '<b>Ping の応答内容</b>　params = 02 バイトのモデル番号（LE、値 1）＋ 1 バイトのファームウェア版（値 1）。いずれも<b>模擬値</b>で、実機の検出結果ではありません。Ping は Return Level に関わらず常に応答します。<br><br>'
        '<b>Read で対応する (アドレス, 長さ)</b>　(64,1) (68,1) (132,4) (116,4) (11,1) (122,1)　— それ以外は Error 7。<br>'
        '<b>ID 照合</b>　request.device_id ≠ 1 のときはパケット全体を無視（応答なし）。GUI の「ID 不一致」故障は ID を 2 に書き換えてこれを再現します。',
        '<b>Ping reply</b>  params = 2-byte model number (LE, value 1) + 1-byte firmware version (value 1). Both are <b>simulated values</b>, not detected from a real device. Ping always replies regardless of Return Level.<br><br>'
        '<b>(address, length) pairs supported by Read</b>  (64,1) (68,1) (132,4) (116,4) (11,1) (122,1) — anything else → Error 7.<br>'
        '<b>ID matching</b>  if request.device_id ≠ 1 the whole packet is ignored (no reply). The GUI fault "ID mismatch" rewrites the ID to 2 to reproduce this.'),
        'white', 11, align='left', valign='top', extra='spacingLeft=10;spacingTop=8;')
    return p


# ======================================================================
# 5. Motor.reply flow
# ======================================================================
def page_reply():
    p = Page(L('5. Motor.reply の処理フロー', '5. Motor.reply decision flow'), 1900, 1260)
    p.title(L('5. 模擬モータの応答ロジック Motor.reply(request)', '5. Simulated motor logic: Motor.reply(request)'),
            L('戻り値は (応答 or None, 説明文)。None ＝ 何も送らない（MCU 側は 20 ms でタイムアウト）。',
              'Returns (response or None, note). None means nothing is sent (the MCU times out after 20 ms).'))
    DEC = 'rhombus;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;'
    yes, no_ = L('はい', 'Yes'), L('いいえ', 'No')

    def dec(cx, cy, w, h, t):
        return p.box(cx - w / 2, cy - h / 2, w, h, t, DEC, 10, shape='')

    def proc(cx, cy, w, h, t, st='white'):
        return p.box(cx - w / 2, cy - h / 2, w, h, t, st, 10)
    start = proc(950, 105, 220, 36, 'reply(request)', 'blue')
    d_id = dec(950, 195, 340, 90, L('request.device_id ＝ 自分の ID (1)?', 'request.device_id == my ID (1)?'))
    ign = proc(1400, 195, 300, 56, L('None「ID 不一致：無視」<br>（応答なし → タイムアウト）', 'None  "ID mismatch: ignored"<br>(no reply → timeout)'), 'red')
    d_ins = dec(950, 320, 300, 90, 'request.instruction')
    p.edge(start, d_id)
    p.edge(d_id, ign, no_, C['bad'])
    p.edge(d_id, d_ins, yes)
    X = {'ping': 190, 'read': 800, 'write': 1400, 'other': 1770}
    heads = {}
    for k, lab in [('ping', '== 1  Ping'), ('read', '== 2  Read'), ('write', '== 3  Write'), ('other', L('その他', 'other'))]:
        heads[k] = proc(X[k], 430, 200, 36, lab, 'cyan')
        p.edge(d_ins, heads[k], '', C['dark'], points=[(950, 385), (X[k], 385)], style='exitX=0.5;exitY=1;entryX=0.5;entryY=0;')
    # ---- Ping
    a = dec(190, 540, 260, 90, L('params が空?', 'params empty?'))
    b = proc(100, 660, 170, 60, L('status(err=5)<br>Ping 長さエラー', 'status(err=5)<br>Ping length error'), 'red')
    c = proc(290, 660, 180, 70, L('status(params =<br>モデル 1 ＋ 版 1)', 'status(params =<br>model 1 + fw 1)'), 'mcu')
    p.edge(heads['ping'], a)
    p.edge(a, b, no_, C['bad'], points=[(100, 540)], style='exitX=0;exitY=0.5;entryX=0.5;entryY=0;')
    p.edge(a, c, yes, C['dark'], points=[(290, 540)], style='exitX=1;exitY=0.5;entryX=0.5;entryY=0;')
    p.box(70, 760, 300, 70, L('Ping は Return Level に関係なく<br>必ず応答する', 'Ping is always answered<br>regardless of Return Level'), 'grey', 10)
    # ---- Read (centre 640)
    r = X['read']
    r1 = dec(r, 540, 260, 90, 'len(params) == 4 ?')
    r2 = proc(r - 290, 540, 150, 50, 'status(err=5)', 'red')
    r3 = proc(r, 665, 270, 74, L('(addr, len) を表で検索<br>(64,1) (68,1) (132,4)<br>(116,4) (11,1) (122,1)', 'look up (addr, len) in<br>(64,1) (68,1) (132,4)<br>(116,4) (11,1) (122,1)'), 'white')
    r4 = dec(r, 790, 240, 80, L('見つかった?', 'found?'))
    r5 = proc(r - 290, 790, 150, 50, 'status(err=7)', 'red')
    r6 = proc(r, 905, 220, 44, L('status(params = 値)', 'status(params = value)'), 'mcu')
    r7 = dec(r, 1010, 260, 90, L('return_level ≥ 1 ?', 'return_level ≥ 1 ?'))
    r8 = proc(r - 150, 1130, 170, 44, L('None（応答なし）', 'None (silent)'), 'red')
    r9 = proc(r + 130, 1130, 170, 44, L('応答を返す', 'return the reply'), 'mcu')
    p.edge(heads['read'], r1)
    p.edge(r1, r2, no_, C['bad'])
    p.edge(r1, r3, yes)
    p.edge(r3, r4)
    p.edge(r4, r5, no_, C['bad'])
    p.edge(r4, r6, yes)
    p.edge(r6, r7)
    p.edge(r2, r7, '', C['dark'], points=[(r - 410, 540), (r - 410, 1010)], style='exitX=0;exitY=0.5;entryX=0;entryY=0.5;')
    p.edge(r5, r7, '', C['dark'], points=[(r - 410, 790)], style='exitX=0;exitY=0.5;entryX=0;entryY=0.5;', arrow=False)
    p.edge(r7, r8, no_, C['bad'], points=[(r - 150, 1010)], style='exitX=0;exitY=0.5;entryX=0.5;entryY=0;')
    p.edge(r7, r9, yes, C['dark'], points=[(r + 130, 1010)], style='exitX=1;exitY=0.5;entryX=0.5;entryY=0;')
    # ---- Write (centre 1250)
    w = X['write']
    w1 = dec(w, 540, 280, 90, 'len(params) < 3 ?')
    w2 = dec(w, 665, 280, 90, L('addr ∈ {11, 64, 68, 116} ?', 'addr ∈ {11, 64, 68, 116} ?'))
    w3 = dec(w, 790, 280, 100, L('len(data) ＝ 期待長?<br>(64,68,11→1B / 116→4B)', 'len(data) == expected?<br>(64,68,11→1B / 116→4B)'))
    w1e = proc(w - 330, 540, 170, 56, L('err=5<br>長さエラー', 'err=5<br>length error'), 'red')
    w2e = proc(w - 330, 665, 170, 56, L('err=7<br>未実装レジスタ', 'err=7<br>unimplemented reg.'), 'red')
    w3e = proc(w - 330, 790, 170, 56, L('err=5<br>データ長エラー', 'err=5<br>data length error'), 'red')
    w4 = proc(w, 960, 400, 190, L(
        '<b>アドレス別の検証と反映</b><br>'
        '<b>64</b>: value&gt;1 → err4 ／ 他は torque=bool(value)<br>'
        '<b>68</b>: value&gt;2 → err4 ／ 他は return_level=value<br>'
        '<b>11</b>: torque ON → err7 ／ value≠3 → err4 ／ 他は mode=3<br>'
        '<b>116</b>: value&gt;4095 → err6 ／ 他は goal=value<br>'
        '　（torque OFF なら「動かない」と注記）<br>'
        '<i>エラー時はレジスタを一切変更しない</i>',
        '<b>Per-address validation and effect</b><br>'
        '<b>64</b>: value&gt;1 → err4 / else torque=bool(value)<br>'
        '<b>68</b>: value&gt;2 → err4 / else return_level=value<br>'
        '<b>11</b>: torque ON → err7 / value≠3 → err4 / else mode=3<br>'
        '<b>116</b>: value&gt;4095 → err6 / else goal=value<br>'
        '  (note "will not move" if torque OFF)<br>'
        '<i>On any error no register is modified</i>'), 'yel')
    w5 = dec(w, 1150, 340, 90, L('書き込み前の return_level ＝ 2 ?', 'return_level before the write == 2 ?'))
    w6 = proc(w - 330, 1190, 190, 44, L('None（応答なし）', 'None (silent)'), 'red')
    w7 = proc(w + 330, 1190, 220, 44, L('status(err) を返す', 'return status(err)'), 'mcu')
    p.edge(heads['write'], w1)
    p.edge(w1, w1e, yes, C['bad'])
    p.edge(w1, w2, no_)
    p.edge(w2, w2e, no_, C['bad'])
    p.edge(w2, w3, yes)
    p.edge(w3, w3e, no_, C['bad'])
    p.edge(w3, w4, yes)
    p.edge(w4, w5)
    # error boxes merge into the reply-policy decision
    p.edge(w1e, w5, '', C['dark'], points=[(w - 450, 540), (w - 450, 1100), (w, 1100)], style='exitX=0;exitY=0.5;entryX=0.5;entryY=0;', arrow=False)
    p.edge(w2e, w5, '', C['dark'], points=[(w - 450, 665), (w - 450, 1100), (w, 1100)], style='exitX=0;exitY=0.5;entryX=0.5;entryY=0;', arrow=False)
    p.edge(w3e, w5, '', C['dark'], points=[(w - 450, 790), (w - 450, 1100), (w, 1100)], style='exitX=0;exitY=0.5;entryX=0.5;entryY=0;', arrow=False)
    p.edge(w5, w6, no_, C['bad'], points=[(w - 330, 1150)], style='exitX=0;exitY=0.5;entryX=0.5;entryY=0;')
    p.edge(w5, w7, yes, C['dark'], points=[(w + 330, 1150)], style='exitX=1;exitY=0.5;entryX=0.5;entryY=0;')
    p.text(w - 160, 1200, 320, 24, L('（エラー応答も同じ返信ポリシーに従う）', '(error replies obey the same policy)'), 10, False, '#666', 'center')
    # ---- Other
    o = X['other']
    o1 = proc(o, 540, 210, 74, L('status(err=2)<br>「未実装の命令」', 'status(err=2)<br>"instruction not implemented"'), 'red')
    p.edge(heads['other'], o1)
    p.box(o - 120, 650, 240, 170, L(
        '<b>load_packet() が先に弾く</b><br>GUI は 01/02/03 以外を<br>モータへ渡す前に拒否する。<br>この枝はユニットテスト／<br>直接呼び出しでのみ到達。',
        '<b>Filtered earlier</b><br>load_packet() rejects anything<br>except 01/02/03 before it<br>reaches the motor; this branch<br>only runs from tests / direct calls.'),
        'grey', 10, align='left', valign='top', extra='spacingLeft=8;spacingTop=6;')
    return p


# ======================================================================
# 6. Sequence – 12 steps
# ======================================================================
def page_sequence():
    p = Page(L('6. 12ステップ通信シーケンス', '6. 12-step communication sequence'), 1760, 1330)
    p.title(L('6. 12 ステップの通信シーケンス（1 パケット往復）', '6. The 12-step sequence for one packet round-trip'),
            L('GUI の「次へ」ボタン 1 回 ＝ 1 ステップ。各行の番号は firmware/main.c の [NN] コメントタグと一致します。',
              'One click of "Next" = one step. Each number matches the [NN] comment tags in firmware/main.c.'))
    lanes = [
        ('PC', 'pc', 230), (L('UART0<br>+ USB ブリッジ', 'UART0<br>+ USB bridge'), 'mcu', 510),
        ('MCU CPU<br>main.c', 'mcu', 790), (L('UART1 / DIR<br>GPIO', 'UART1 / DIR<br>GPIO'), 'mcu', 1070),
        (L('三態バッファ', 'Tri-state<br>buffer'), 'buf', 1350), (L('アクチュエータ', 'Actuator'), 'act', 1630)]
    top, bottom = 100, 1300
    X = {}
    for i, (lab, st, x) in enumerate(lanes):
        p.box(x - 85, top, 170, 56, '<b>%s</b>' % lab, st, 12)
        p.line(x, top + 56, x, bottom, '', '#999999', 1, arrow=False, dashed=True, label_bg=False)
        X[i] = x
    steps = [
        (1, L('PC がパケットを組み立てる。<br>MCU は read_packet(PC_UART) で空待ち', 'PC builds the packet.<br>MCU idles in read_packet(PC_UART)'), 'note', 0, 2),
        (2, L('HEX バイトを 1 つずつ送信（USB → HOST_RX）→ RX FIFO → UART_READ → g_buf[n]', 'bytes sent one by one (USB → HOST_RX) → RX FIFO → UART_READ → g_buf[n]'), 'arrow', 0, 1, C['usb']),
        (3, L('n が 7 に達したら need = 7 + Length を算出。n == need で 1 パケット完成', 'at n = 7 compute need = 7 + Length; packet complete when n == need'), 'note', 1, 2),
        (4, L('gpio_write_dir(1)：DIR = 1 → 送信ゲート開・受信ゲート閉', 'gpio_write_dir(1): DIR = 1 → TX gate open, RX gate closed'), 'arrow', 2, 4, C['dir']),
        (5, L('UART_WRITE → TX FIFO → シフトレジスタ → ACT_TX → バッファ → DATA（1 ビットずつ）', 'UART_WRITE → TX FIFO → shift register → ACT_TX → buffer → DATA (bit by bit)'), 'arrow', 3, 5, C['tx']),
        (6, L('while (!uart_tx_complete) ― 最後の停止ビットが出るまで待つ（FIFO 空では不可）', 'while (!uart_tx_complete) — wait for the last stop bit (FIFO empty is NOT enough)'), 'note', 2, 4),
        (7, L('gpio_write_dir(0)：DIR = 0 → 送信出力ハイインピーダンス・受信ゲート開', 'gpio_write_dir(0): DIR = 0 → TX output Hi-Z, RX gate open'), 'arrow', 2, 4, C['dir']),
        (8, L('モータが ID / CRC を検査して実行。MCU は read_packet(MOTOR_UART, 20 ms) で待つ', 'Actuator checks ID / CRC and executes; MCU waits in read_packet(MOTOR_UART, 20 ms)'), 'note', 2, 5),
        (9, L('約 0.5 ms（Return Delay）後、Status パケットを DATA へ送出 → 受信ゲートを通過', 'after ~0.5 ms (Return Delay) the Status packet goes onto DATA → through the RX gate'), 'arrow', 5, 4, C['rx']),
        (10, L('ACT_RX → UART1 シフトレジスタ → RX FIFO → UART_READ → g_rx（同じ read_packet）', 'ACT_RX → UART1 shift reg → RX FIFO → UART_READ → g_rx (same read_packet)'), 'arrow', 4, 2, C['rx']),
        (11, L('pc_write(g_rx, n)：1 バイトも変えずに UART0 → USB で PC へ転送', 'pc_write(g_rx, n): forwarded unchanged via UART0 → USB to the PC'), 'arrow', 2, 0, C['usb']),
        (12, L('PC がヘッダ / Length / CRC を検査。Instruction = 55、Error = 00。MCU はステップ 1 に戻る', 'PC checks header / Length / CRC; Instruction = 55, Error = 00. MCU is back at step 1'), 'note', 0, 2),
    ]
    y, rowh = 190, 92
    for st in steps:
        n, txt, kind, a, b = st[:5]
        ycen = y + 46
        p.box(20, ycen - 16, 44, 32, '%02d' % n, 'fillColor=#1f3a5f;strokeColor=#1f3a5f;fontColor=#ffffff;fontStyle=1', 12)
        if kind == 'arrow':
            col = st[5]
            xa, xb = X[a], X[b]
            p.line(xa, ycen + 12, xb, ycen + 12, '', col, 4)
            lo, hi = sorted([xa, xb])
            p.text(lo + 8, ycen - 32, hi - lo - 16, 40, txt, 11, False, '#222222', 'center', valign='bottom')
        else:
            lo, hi = sorted([X[a], X[b]])
            p.box(lo - 100, ycen - 30, hi - lo + 200, 60, txt, 'yel', 11, extra='arcSize=15;')
        y += rowh
    return p


# ======================================================================
# 7. Firmware flowchart
# ======================================================================
def page_firmware():
    p = Page(L('7. ファームウェア フローチャート', '7. Firmware flowcharts'), 1700, 1260)
    p.title(L('7. firmware/main.c ：main() / read_packet() / motor_send() / pc_write()', '7. firmware/main.c: main() / read_packet() / motor_send() / pc_write()'),
            L('[NN] はコード内コメントのステップタグ。左：メインループ ／ 中：受信 ／ 右：送信と転送。丸の「A」は while (n &lt; need) の先頭へ戻ることを表す。',
              '[NN] are the step tags in the code comments. Left: main loop / middle: receive / right: send and forward. A circled "A" jumps back to the top of while (n &lt; need).'))
    DEC = 'rhombus;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;'
    yes, no_ = L('はい', 'Yes'), L('いいえ', 'No')

    def dec(cx, cy, w, h, t):
        return p.box(cx - w / 2, cy - h / 2, w, h, t, DEC, 10, shape='')

    def proc(x, y, w, h, t, st='white'):
        return p.box(x, y, w, h, t, st, 10)

    def conn(cx, cy):
        return p.box(cx - 15, cy - 15, 30, 30, 'A', 'fillColor=#ffffff;strokeColor=#666666;fontStyle=1', 11, shape='ellipse;')
    # ---- main
    p.group(30, 90, 440, 1130, 'main()', 'blue')
    m0 = proc(90, 130, 320, 40, 'board_init();  gpio_write_dir(0);', 'white')
    m1 = proc(90, 205, 320, 56, '[01][12]  len = read_packet(PC_UART, g_buf, WAIT_FOREVER)', 'mcu')
    m2 = dec(250, 335, 220, 76, 'len == 0 ?')
    m3 = proc(90, 420, 320, 56, L('motor_send(g_buf, len)<br>[04]〜[07]', 'motor_send(g_buf, len)<br>[04]–[07]'), 'ls')
    m4 = proc(90, 520, 320, 60, '[08]  n = read_packet(MOTOR_UART, g_rx, REPLY_TIMEOUT_MS)', 'mcu')
    m5 = dec(250, 655, 220, 76, 'n != 0 ?')
    m6 = proc(90, 745, 320, 56, L('[11]  pc_write(g_rx, n)<br>応答をそのまま PC へ', '[11]  pc_write(g_rx, n)<br>return the reply unchanged'), 'cyan')
    m7 = proc(90, 850, 320, 60, L('タイムアウト時は何も返さず沈黙<br>（再送しない）', 'On timeout stay silent<br>(no retry, nothing sent)'), 'red')
    m8 = proc(90, 960, 320, 50, L('while (1) の先頭へ戻る', 'back to the top of while (1)'), 'grey')
    p.edge(m0, m1)
    p.edge(m1, m2)
    p.edge(m2, m3, no_)
    p.edge(m2, m1, yes, C['gnd'], points=[(440, 335), (440, 233)], style='exitX=1;exitY=0.5;entryX=1;entryY=0.5;')
    p.edge(m3, m4)
    p.edge(m4, m5)
    p.edge(m5, m6, yes)
    p.edge(m5, m7, no_, C['bad'], points=[(60, 655), (60, 880)], style='exitX=0;exitY=0.5;entryX=0;entryY=0.5;')
    p.edge(m6, m8, '', C['dark'], points=[(440, 773), (440, 985)], style='exitX=1;exitY=0.5;entryX=1;entryY=0.5;')
    p.edge(m7, m8)
    p.edge(m8, m1, '', C['gnd'], dashed=True, points=[(45, 985), (45, 233)], style='exitX=0;exitY=0.5;entryX=0;entryY=0.5;')
    # ---- read_packet
    p.group(510, 90, 640, 1130, 'read_packet(uart, buf, timeout_ms)', 'mcu')
    cx = 800
    r0 = proc(620, 130, 360, 56, L('n = 0, need = 7, t0 = millis()<br>HDR = FF FF FD 00', 'n = 0, need = 7, t0 = millis()<br>HDR = FF FF FD 00'), 'white')
    r1 = dec(cx, 255, 290, 76, 'n &lt; need ?')
    r1e = proc(1010, 227, 125, 50, L('n ≥ need<br>[03] return n', 'n ≥ need<br>[03] return n'), 'mcu')
    r2 = dec(cx, 375, 290, 90, L('[09] timeout あり ∧<br>経過 &gt; timeout_ms ?', '[09] timeout set ∧<br>elapsed &gt; timeout_ms ?'))
    r2e = proc(535, 355, 100, 40, 'return 0', 'red')
    r3 = dec(cx, 495, 290, 80, L('[01] RX FIFO が空?', '[01] RX FIFO empty?'))
    c3 = conn(590, 495)
    r4 = proc(620, 575, 360, 44, '[02][10] b = UART_READ(uart)', 'white')
    r5 = dec(cx, 685, 290, 84, 'n &lt; 4 ∧ b ≠ HDR[n] ?')
    r5y = proc(530, 770, 250, 80, L('ヘッダ再同期<br>n = (b==FF) ? ((n==2)?2:1) : 0<br>buf[0] = FF; continue', 'resync on header<br>n = (b==FF) ? ((n==2)?2:1) : 0<br>buf[0] = FF; continue'), 'yel')
    c5 = conn(655, 885)
    r6 = proc(880, 770, 230, 44, '[02][10] buf[n++] = b', 'white')
    r7 = dec(995, 890, 230, 84, 'n == 7 ?')
    c7 = conn(815, 890)
    r8 = proc(870, 970, 250, 60, '[03]  need = 7 + (buf[5] | buf[6] &lt;&lt; 8)', 'cyan')
    r9 = dec(995, 1100, 280, 88, 'need &lt; 10 ∨ need &gt; PKT_MAX ?')
    c9 = conn(785, 1100)
    r9y = proc(930, 1175, 130, 36, 'return 0', 'red')
    p.edge(r0, r1)
    p.edge(r1, r1e, no_, C['rx'], 2, style='exitX=1;exitY=0.5;entryX=0;entryY=0.5;')
    p.edge(r1, r2, yes)
    p.edge(r2, r2e, yes, C['bad'])
    p.edge(r2, r3, no_)
    p.edge(r3, c3, yes, C['gnd'])
    p.edge(r3, r4, no_)
    p.edge(r4, r5)
    p.edge(r5, r5y, yes, C['dark'], points=[(655, 685)], style='exitX=0;exitY=0.5;entryX=0.5;entryY=0;')
    p.edge(r5y, c5, '', C['gnd'], style='exitX=0.5;exitY=1;entryX=0.5;entryY=0;')
    p.edge(r5, r6, no_, C['dark'], points=[(995, 685)], style='exitX=1;exitY=0.5;entryX=0.5;entryY=0;')
    p.edge(r6, r7)
    p.edge(r7, c7, no_, C['gnd'])
    p.edge(r7, r8, yes)
    p.edge(r8, r9)
    p.edge(r9, c9, no_, C['gnd'])
    p.edge(r9, r9y, yes, C['bad'])
    p.text(520, 1180, 360, 30, L('Ⓐ ＝ while (n &lt; need) の先頭へ戻る', 'Ⓐ = back to the top of while (n &lt; need)'), 10, False, '#555')
    # ---- motor_send
    p.group(1190, 90, 480, 700, 'motor_send(p, len)', 'ls')
    s0 = proc(1225, 130, 410, 60, L('MOTOR_UART の受信 FIFO を空にする<br>（エコーや古いデータを捨てる）', 'Drain the MOTOR_UART RX FIFO<br>(discard echo / stale data)'), 'white')
    s1 = proc(1225, 220, 410, 44, L('[04]  gpio_write_dir(1)　送信ゲート開 / 受信ゲート閉', '[04]  gpio_write_dir(1)   TX gate open / RX gate closed'), 'buf')
    s2 = proc(1225, 295, 410, 60, 'for i in 0..len-1:  while (UART_IS_TX_FULL) {}<br>[05]  UART_WRITE(MOTOR_UART, p[i])', 'ls')
    s3 = proc(1225, 385, 410, 70, L('[06]  while (!uart_tx_complete(MOTOR_UART)) {}<br>FIFO ＋ シフトレジスタ ＋ 停止ビットがすべて空', '[06]  while (!uart_tx_complete(MOTOR_UART)) {}<br>FIFO + shift register + stop bit all done'), 'red')
    s4 = proc(1225, 485, 410, 44, L('[07]  gpio_write_dir(0)　送信 Hi-Z / 受信ゲート開', '[07]  gpio_write_dir(0)   TX Hi-Z / RX gate open'), 'buf')
    p.edge(s0, s1)
    p.edge(s1, s2)
    p.edge(s2, s3)
    p.edge(s3, s4)
    p.box(1225, 560, 410, 210, L(
        '<b>なぜ「FIFO 空」では駄目か</b><br>FIFO が空になった時点で、最後のバイトはまだシフトレジスタで送出中。'
        'そこで DIR を下げると送信ゲートが閉じて最後のバイトが切れ、CRC が壊れてモータはパケットを破棄します。'
        '（故障実験「FIFO_EMPTY だけ待って DIR を切替」で再現）<br><br>'
        '<b>board.h の約束</b>：uart_tx_complete() は最終停止ビットがピンを離れて初めて真。',
        '<b>Why "FIFO empty" is not enough</b><br>When the FIFO empties the last byte is still being shifted out. '
        'Dropping DIR then closes the TX gate mid-byte, corrupting the CRC, and the actuator drops the packet '
        '(reproduced by the fault "Only wait for FIFO_EMPTY").<br><br>'
        '<b>board.h contract</b>: uart_tx_complete() is true only after the final stop bit has left the pin.'),
        'yel', 10, align='left', valign='top', extra='spacingLeft=8;spacingTop=6;')
    # ---- pc_write
    p.group(1190, 830, 480, 390, 'pc_write(p, len)', 'pc')
    w1 = proc(1225, 880, 410, 60, 'for i in 0..len-1:<br>while (UART_IS_TX_FULL(PC_UART)) {}', 'white')
    w2 = proc(1225, 975, 410, 60, L('[11]  UART_WRITE(PC_UART, p[i])<br>受信したバイトをそのまま転送', '[11]  UART_WRITE(PC_UART, p[i])<br>forward each received byte as is'), 'cyan')
    p.edge(w1, w2)
    p.box(1225, 1070, 410, 110, L('診断情報や追加バイトを混ぜない。<br>PC は元の Status をそのまま検査する。<br>board.h: PKT_MAX=64 / REPLY_TIMEOUT_MS=20 / WAIT_FOREVER=0',
                                  'No diagnostics or extra bytes are mixed in.<br>The PC verifies the original Status unchanged.<br>board.h: PKT_MAX=64 / REPLY_TIMEOUT_MS=20 / WAIT_FOREVER=0'), 'grey', 10)
    return p


# ======================================================================
# 8. DIR tri-state truth table & timing
# ======================================================================
def page_dir():
    p = Page(L('8. DIR 制御とタイミング', '8. DIR control & timing'), 1654, 1120)
    p.title(L('8. DIR 1 本で 2 つのゲートを切り替える：真理値表とタイミング', '8. One DIR line drives both gates: truth table and timing'),
            L('hardware.html の「一つの GPIO が二つのバッファを制御」と 12 ステップの [04]〜[07] に対応。',
              'Corresponds to "one GPIO controls two buffers" in hardware.html and steps [04]–[07].'))
    p.table(30, 100, [100, 330, 360, 560], 46, [
        ['DIR', L('1脚 /OE1（Low 有効）', 'pin 1 /OE1 (active low)'), L('7脚 OE2（High 有効）', 'pin 7 OE2 (active high)'), L('結果', 'Result')],
        ['1 / High', L('High → 受信ゲート<b>閉</b>', 'High → RX gate <b>closed</b>'), L('High → 送信ゲート<b>開</b>', 'High → TX gate <b>open</b>'), L('MCU TX → DATA → モータ（命令パケット送出）', 'MCU TX → DATA → actuator (sending the instruction)')],
        ['0 / Low', L('Low → 受信ゲート<b>開</b>', 'Low → RX gate <b>open</b>'), L('Low → 送信ゲート閉（ハイインピーダンス）', 'Low → TX gate closed (Hi-Z)'), L('モータ DATA → MCU RX（Status 受信）', 'actuator DATA → MCU RX (receiving the Status)')],
    ], size=11, styles=[[None] * 4, ['white', 'red', 'mcu', 'ls'], ['white', 'mcu', 'red', 'cyan']], align=['center', 'left', 'left', 'left'])
    p.text(30, 250, 1590, 44, L('ハイインピーダンス ＝ 出力が「プラグを抜いた」状態で、1 も 0 も出さず DATA 線を占有しない。チップは Ping も CRC も知らず、いつ送り終わったかも分からない。DIR を切り替えるのは MCU ファームウェアの責任。',
                                'Hi-Z = the output is "unplugged": it drives neither 1 nor 0 and leaves DATA free. The chip knows nothing about Ping, CRC or when a frame ends. Switching DIR is the MCU firmware\'s job.'),
           11, False, '#444', valign='top')
    x0, x1 = 170, 1580
    rows = {'dir': 380, 'tx': 450, 'fe': 520, 'tc': 590, 'rx': 660}
    lab = lambda y, t: p.text(30, y - 12, 130, 24, t, 12, True)
    wf = lambda xa, ya, xb, yb, col, wd=3: p.line(xa, ya, xb, yb, '', col, wd, arrow=False, label_bg=False)
    p.text(30, 305, 900, 24, L('正しいタイミング（firmware の通り：uart_tx_complete を待つ）', 'Correct timing (as in firmware: wait for uart_tx_complete)'), 13, True, '#1f7a3d')
    for k, t in [('dir', 'DIR'), ('tx', L('DATA (TX側)', 'DATA (TX)')), ('fe', 'FIFO_EMPTY'), ('tc', 'TX_COMPLETE'), ('rx', L('DATA (応答)', 'DATA (reply)'))]:
        lab(rows[k], t)
    xa, xd, xr0, xr1 = 340, 840, 1060, 1540
    xf = xd - 150
    y = rows['dir']
    wf(x0, y + 14, xa, y + 14, C['dir']); wf(xa, y + 14, xa, y - 14, C['dir']); wf(xa, y - 14, xd, y - 14, C['dir'])
    wf(xd, y - 14, xd, y + 14, C['dir']); wf(xd, y + 14, x1, y + 14, C['dir'])
    p.text(xa + 20, y - 40, 400, 22, L('1：送信中（命令パケット）', '1: sending (instruction packet)'), 10, False, C['dir'])
    p.text(xd + 20, y + 16, 400, 22, L('0：Hi-Z・待機／受信', '0: Hi-Z, waiting / receiving'), 10, False, C['dir'])
    p.box(xa + 20, rows['tx'] - 18, xd - xa - 60, 36, L('Instruction Packet（全バイト）', 'Instruction Packet (all bytes)'), 'ls', 11)
    p.box(xd - 40, rows['tx'] - 18, 40, 36, L('停止', 'stop'), 'red', 9)
    y = rows['fe']
    wf(x0, y + 14, xf, y + 14, '#555'); wf(xf, y + 14, xf, y - 14, '#555'); wf(xf, y - 14, x1, y - 14, '#555')
    p.text(xf - 520, y - 12, 510, 24, L('最後のバイトがシフトレジスタへ移った時点で 1 に', 'goes 1 when the last byte moves into the shift register'), 10, False, '#555', 'right')
    y = rows['tc']
    wf(x0, y + 14, xd - 40, y + 14, '#555'); wf(xd - 40, y + 14, xd - 40, y - 14, '#555'); wf(xd - 40, y - 14, x1, y - 14, '#555')
    p.text(xd + 20, y + 16, 560, 22, L('最後の停止ビットが出終わって 1 に ← ここで DIR を下げる', 'goes 1 once the last stop bit is out ← drop DIR here'), 10, True, '#1f7a3d')
    p.box(xr0, rows['rx'] - 18, xr1 - xr0, 36, 'Status Packet', 'mcu', 11)
    p.line(xd, 350, xd, 625, '', '#1f7a3d', 1, arrow=False, dashed=True, label_bg=False)
    p.line(xd, 705, xr0, 705, '', '#333', 1, both=True, label_bg=False)
    p.text(xd, 708, xr0 - xd, 22, L('約 500 µs（Return Delay、模擬値）', '~500 µs (Return Delay, simulated)'), 10, False, '#333', 'center')
    # wrong timing
    p.text(30, 760, 900, 24, L('誤ったタイミング（FIFO_EMPTY だけで DIR を下げる）', 'Wrong timing (dropping DIR as soon as FIFO_EMPTY)'), 13, True, C['bad'])
    r2 = {'dir': 830, 'tx': 900, 'rx': 970}
    lab(r2['dir'], 'DIR'); lab(r2['tx'], L('DATA (TX側)', 'DATA (TX)')); lab(r2['rx'], L('モータ応答', 'Actuator reply'))
    y = r2['dir']
    wf(x0, y + 14, xa, y + 14, C['dir']); wf(xa, y + 14, xa, y - 14, C['dir']); wf(xa, y - 14, xf, y - 14, C['dir'])
    wf(xf, y - 14, xf, y + 14, C['bad']); wf(xf, y + 14, x1, y + 14, C['dir'])
    p.box(xa + 20, r2['tx'] - 18, xf - xa - 20, 36, 'Instruction Packet', 'ls', 11)
    p.box(xf, r2['tx'] - 18, 150, 36, L('最後のバイトが切れる ✂', 'last byte cut off ✂'), 'red', 10, extra='dashed=1;')
    p.text(xf + 20, y + 16, 950, 40, L('送信ゲートが早く閉じ最後のバイトが欠ける → CRC 不一致 → モータはパケット全体を破棄し応答しない → MCU は 20 ms でタイムアウト',
                                       'The TX gate closes early so the last byte is lost → CRC mismatch → the actuator discards the whole packet and stays silent → the MCU times out after 20 ms'),
           10, True, C['bad'], valign='top')
    p.box(xr0, r2['rx'] - 18, xr1 - xr0, 36, L('（応答なし）', '(no reply)'), 'red', 11, extra='dashed=1;')
    p.box(30, 1020, 1590, 80, L(
        '<b>もう一つの失敗：DIR を 0 に戻さない</b>　送信ゲートが DATA を占有し続け、受信ゲートも閉じたまま。モータは応答を送るが MCU に届かず、20 ms でタイムアウト。<br>'
        '<b>実機での確認</b>　オシロスコープの 2 チャンネルを DATA と DIR_GPIO に当て、DIR の立ち下がりが最後の停止ビットより後ろにあるか確認する。GUI の波形は教育用の模式図で、実測ではありません。',
        '<b>Another failure: DIR never returns to 0</b>  The TX gate keeps occupying DATA and the RX gate stays closed. The actuator replies but the MCU never hears it → 20 ms timeout.<br>'
        '<b>Verify on hardware</b>  Probe DATA and DIR_GPIO with an oscilloscope and check that the DIR falling edge lands after the last stop bit. The GUI waveform is a teaching sketch, not a measurement.'),
        'yel', 11, align='left', valign='top', extra='spacingLeft=10;spacingTop=8;')
    return p


# ======================================================================
# 9. Angle control flow
# ======================================================================
def page_flow():
    p = Page(L('9. 角度制御フロー', '9. Angle-control flow'), 1700, 1180)
    p.title(L('9. 目標角度まで回す：自動フロー（Ping → モード確認 → トルク ON → 目標書込 → 位置ポーリング）',
              '9. Turning to a target angle: the automatic flow (Ping → mode → torque on → write goal → poll position)'),
            L('GUI 左パネルの FLOW / AUTO_FLOW。各ボタンは 1 パケットだけ送る。自動フローは ①〜⑤ を順に実行。',
              'FLOW / AUTO_FLOW in the left panel. Each button sends a single packet; the automatic flow runs ①–⑤.'))
    DEC = 'rhombus;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;'
    goal = (1024).to_bytes(4, 'little')
    steps = [
        ('①  Ping', packet(1, 1), L('ID 1 は在席か？', 'Is ID 1 there?')),
        (L('②  Read 11 番：動作モード', '②  Read addr 11: operating mode'), read(11, 1), L('3（位置制御）でないと角度指令が効かない', 'must equal 3 (position control) for angle commands')),
        (L('③  Write 64 番 = 1：トルク ON', '③  Write addr 64 = 1: torque ON'), write(64, b'\x01'), L('トルクが OFF だと目標を書いても回らない', 'with torque OFF, writing a goal does not move it')),
        (L('④  Write 116 番：目標位置（例 90° = 1024）', '④  Write addr 116: goal (e.g. 90° = 1024)'), write(116, goal), L('Write 成功は「受理」だけ。ここから回り始める', 'success only means "accepted"; the motor starts moving')),
        (L('⑤  Read 132 番：現在位置', '⑤  Read addr 132: present position'), read(132, 4), L('目標 ±2 ticks 以内なら到達。未達なら再読込', 'within ±2 ticks of the goal = arrived; otherwise read again')),
    ]
    ids = []
    y = 110
    for t, raw, why in steps:
        ids.append(p.box(60, y, 600, 100, '<b>%s</b><br><span style="font-size:11px;font-family:Courier New">%s</span><br><span style="font-size:11px;color:#555">%s</span>' % (t, hexline(raw), why),
                         'cyan', 11, align='left', extra='spacingLeft=10;'))
        y += 150
    for a, b in zip(ids, ids[1:]):
        p.edge(a, b, L('Error=0 かつ回包 OK', 'reply OK, Error = 0'), C['rx'])
    dpos = p.box(800, 690, 270, 120, L('|現在位置 − 目標| ≤ 2<br>または ポーリング 8 回目?', '|position − goal| ≤ 2<br>or 8 polls done?'), DEC, 10, shape='')
    p.edge(ids[4], dpos, L('Status 受信', 'Status received'), C['dark'], 2, style='exitX=1;exitY=0.5;entryX=0;entryY=0.5;')
    p.edge(dpos, ids[4], L('いいえ：（1.2 s ÷ 速度）後に ⑤ をもう一度', 'No: read ⑤ again after (1.2 s ÷ speed)'), C['tx'], 2, dashed=True,
           points=[(935, 880), (360, 880)], style='exitX=0.5;exitY=1;entryX=0.5;entryY=1;')
    fin = p.box(1130, 725, 250, 50, L('完了（ボタンが「全フロー自動実行」に戻る）', 'Done (button returns to "Run whole flow")'), 'mcu', 10)
    p.edge(dpos, fin, L('はい', 'Yes'), C['rx'])
    p.box(60, 940, 600, 100, L('<b>⑥  Write 64 番 = 0：トルク OFF（任意）</b><br><span style="font-size:11px;font-family:Courier New">%s</span><br><span style="font-size:11px;color:#555">モータを解放し手で回せる。自動フローには含まれず手動ボタンのみ</span>' % hexline(write(64, b'\x00')),
                               '<b>⑥  Write addr 64 = 0: torque OFF (optional)</b><br><span style="font-size:11px;font-family:Courier New">%s</span><br><span style="font-size:11px;color:#555">releases the motor so it can be turned by hand; manual button only, not in the automatic flow</span>' % hexline(write(64, b'\x00'))),
          'grey', 11, align='left', extra='spacingLeft=10;')
    p.box(760, 110, 420, 150, L(
        '<b>中断条件</b>（seq_next）<br>いずれかのステップが ok でなければ自動フローを停止:<br>'
        '・Status が届かない（タイムアウト）<br>・CRC / Length 不一致<br>・Error ≠ 0<br>→「フロー中断」と表示し、以降のパケットは送らない',
        '<b>Abort rule</b> (seq_next)<br>If any step is not ok the automatic flow stops:<br>'
        '• no Status (timeout)<br>• CRC / Length mismatch<br>• Error ≠ 0<br>→ shows "flow interrupted" and sends nothing further'),
          'red', 11, align='left', valign='top', extra='spacingLeft=10;spacingTop=8;')
    p.box(760, 290, 420, 140, L(
        '<b>角度 → ticks</b><br>スライダ 0〜359° ／ 初期 90°<br>ticks = round(角度 × 4096 / 360) mod 4096<br>'
        '4 バイト LE：90° → <span style="font-family:Courier New">00 04 00 00</span><br>モータ初期位置 180°(2048)、表示用速度 260 ticks/s',
        '<b>Angle → ticks</b><br>slider 0–359°, default 90°<br>ticks = round(angle × 4096 / 360) mod 4096<br>'
        '4-byte LE: 90° → <span style="font-family:Courier New">00 04 00 00</span><br>motor starts at 180° (2048), display speed 260 ticks/s'),
          'cyan', 11, align='left', valign='top', extra='spacingLeft=10;spacingTop=8;')
    p.box(760, 460, 420, 120, L(
        '<b>パケット間の待ち</b><br>各パケット（12 ステップ）が終わると、<br>pos 以外は 1.6 s、pos は 1.2 s（÷ 速度）待って次を送る。<br>速度ボタン：低速（1×）/ 高速（3×）。',
        '<b>Pause between packets</b><br>After each packet finishes (12 steps) the flow waits<br>1.6 s (1.2 s for pos) ÷ speed, then sends the next.<br>Speed buttons: Slow (1×) / Fast (3×).'),
          'yel', 11, align='left', valign='top', extra='spacingLeft=10;spacingTop=8;')
    p.box(1230, 110, 430, 300, L(
        '<b>自己検査の期待値（app.py --screenshot）</b><br><br>'
        '・手順 kinds[:5] == [ping, mode, on, goal, pos]<br>・pos は 2 回以上（1 回目＝途中、2 回目＝到達）<br>'
        '・motor.goal == 1024 かつ |位置 − 1024| ≤ 2<br>・AUTO_FLOW の全ステップが ok<br><br>'
        '<b>要点</b><br>Write の成功 ≠ 到達。必ず Read 132 で現在位置を確認する。<br>トルク ON を忘れると、目標は保存されても回らない。',
        '<b>Expected self-check (app.py --screenshot)</b><br><br>'
        '• sequence kinds[:5] == [ping, mode, on, goal, pos]<br>• pos appears ≥ 2 times (1st = midway, 2nd = arrived)<br>'
        '• motor.goal == 1024 and |position − 1024| ≤ 2<br>• every AUTO_FLOW step is ok<br><br>'
        '<b>Take-aways</b><br>Write success ≠ arrival. Always confirm with Read 132.<br>Forget torque ON and the goal is stored but nothing moves.'),
          'white', 11, align='left', valign='top', extra='spacingLeft=10;spacingTop=8;')
    return p


# ======================================================================
# 10. Fault injection
# ======================================================================
def page_faults():
    p = Page(L('10. 故障実験', '10. Fault experiments'), 1654, 930)
    p.title(L('10. 故障実験（FAULTS ×8）と電気プロファイル（×2）', '10. Fault injection (FAULTS ×8) and electrical profiles (×2)'),
            L('左パネルのプルダウンで選択。選択はパケット読み込み時に確定（active_fault）。', 'Chosen in the left-panel drop-downs. The choice is latched when a packet is loaded (active_fault).'))
    rows = [[L('故障（GUI 表示名）', 'Fault (GUI label)'), L('模擬の仕組み', 'How it is simulated'), L('止まる/変わるステップ', 'Step affected'), L('結果', 'Outcome')],
            [L('正常通信', 'Normal'), L('通常動作', 'Nominal'), L('1 → 12 完走', '1 → 12 complete'), L('Status 受信、CRC OK', 'Status received, CRC OK')],
            [L('FIFO_EMPTY だけ待って DIR 切替', 'Only wait for FIFO_EMPTY, then switch DIR'), L('[06] を FIFO_EMPTY 待ちに置換', '[06] replaced by a FIFO_EMPTY wait'),
             L('6：波形の赤線／7：DIR が早く下がる／8：回包なし', '6: red line on waveform / 7: DIR drops early / 8: no reply'), L('最後のバイトが欠損 → CRC 不一致 → モータは破棄 → 20 ms タイムアウト', 'last byte truncated → CRC mismatch → actuator discards → 20 ms timeout')],
            [L('DIR を受信に戻さない', 'DIR not returned to receive'), L('[07] を実行しない（DIR=1 のまま）', '[07] skipped (DIR stays 1)'),
             L('7：行がスキップ／9：回包が門前払い', '7: line skipped / 9: reply blocked at the gate'), L('モータは応答するが MCU に届かない → タイムアウト', 'actuator replies but the MCU never hears it → timeout')],
            [L('モータ未給電', 'Actuator unpowered'), L('外部 5V なし', 'no external 5V'), L('8：回包なし', '8: no reply'), L('MCU は 20 ms 待って return 0、何も PC へ転送しない', 'MCU waits 20 ms, read_packet returns 0, nothing reaches the PC')],
            [L('共地なし', 'No common ground'), L('共通の電圧基準がない（通信失敗として扱う）', 'no shared voltage reference (treated as failure)'), L('8：回包なし', '8: no reply'), L('実機の挙動は不確定、とされる', 'real behaviour is undefined; shown as failure')],
            [L('ID 不一致', 'ID mismatch'), L('load_packet() が ID を 2 に書換', 'load_packet() rewrites the ID to 2'), L('8：モータが無視', '8: actuator ignores it'), L('Motor.reply() が None → 回包なし', 'Motor.reply() returns None → no reply')],
            [L('伝送中の CRC 破損', 'CRC corrupted in transit'), L('線路でバイトが化けた', 'a byte is garbled on the wire'), L('8：回包なし', '8: no reply'), L('CRC 不一致 → 実行も応答もしない', 'CRC mismatch → neither executes nor replies')],
            [L('Write は Status を返さない', 'Write returns no Status'), L('return_level を 1 に強制（policy_override）', 'return_level forced to 1 (policy_override)'), L('8：書込は実行、9 以降なし', '8: write executes, nothing after'), L('「実行済みだが設定により無応答」。次の load_packet() で 2 に戻る', '"executed, no reply by setting"; restored to 2 on the next load_packet()')],
            [L('電気：5V バッファ例（要確認）', 'Electrical: example 5V buffer (to verify)'), L('VIH = 0.7×5V = 3.5V &gt; 3.3V 応答', 'VIH = 0.7×5V = 3.5V &gt; a 3.3V reply'), L('8：リスク警告で停止', '8: stops with a risk warning'), L('「通信が確実かどうか判定不能」。必ず失敗する、という意味ではない', '"cannot judge reliability" — a conservative warning, not a measured failure')]]
    styles = [[None] * 4] + [[None] * 4 for _ in rows[1:]]
    styles[1] = ['mcu'] * 4
    for r in range(2, len(rows)):
        styles[r] = ['white', 'white', 'yel', 'red']
    styles[8] = ['white', 'white', 'yel', 'mcu']
    styles[9] = ['white', 'white', 'yel', 'yel']
    p.table(30, 100, [270, 380, 420, 520], [38] + [58] * (len(rows) - 1), rows, size=10, styles=styles)
    p.box(30, 760, 1590, 140, L(
        '<b>どの故障でも共通</b>　stop() が呼ばれると finished=True、running=False。「タイムアウト：有効な Status を受信できません」を表示し、flow_state を fail にして自動フローを中断します（Write 無応答の場合のみ ok 扱い）。<br>'
        '<b>観察ポイント</b>　実験前に「初期化」ボタンで状態を戻す。故障は次の「パケット読込」まで反映されない。<br>'
        '<b>既知の挙動</b>　「ID 不一致」は Motor.reply() が None を返すため、画面上は「Status Return Level 設定による無応答」と同じ経路（実行済み・ok 扱い）で表示されます。',
        '<b>Common to all faults</b>  stop() sets finished=True, running=False, shows "timeout: no valid Status" and marks the flow step failed, aborting the automatic flow (only the "Write returns no Status" case is marked ok).<br>'
        '<b>Tip</b>  Press Reset before an experiment. A fault only takes effect when the next packet is loaded.<br>'
        '<b>Known behaviour</b>  "ID mismatch" makes Motor.reply() return None, so the screen takes the same path as "no reply due to Status Return Level" (shown as executed / ok).'),
        'yel', 11, align='left', valign='top', extra='spacingLeft=10;spacingTop=8;')
    return p


# ======================================================================
# 11. UI layout
# ======================================================================
def page_ui():
    p = Page(L('11. 画面レイアウト', '11. UI layout'), 1654, 1060)
    p.title(L('11. シミュレータの画面（1600×1000 を 0.55 倍で表示）', '11. Simulator window (1600×1000 shown at 0.55×)'),
            L('app.py の矩形定数 LEFT / VIEW / LENS / CODE / STEP / STRIP と一致。', 'Matches the rectangle constants LEFT / VIEW / LENS / CODE / STEP / STRIP in app.py.'))
    k = 0.55
    ox, oy = 40, 100

    def R(r, t, st, size=11, valign='middle'):
        x, y, w, h = r
        return p.box(ox + x * k, oy + y * k, w * k, h * k, t, st, size, valign=valign, extra='spacingLeft=4;spacingTop=4;')
    p.box(ox, oy, 1600 * k, 1000 * k, '', 'fillColor=#10192a;strokeColor=#10192a', shape='rounded=0;')
    p.text(ox + 10, oy + 8, 400, 30, '<font color="#ffffff"><b>%s</b></font>' % L('Serial Actuator Communication Lab', 'Serial Actuator Communication Lab'), 14)
    p.text(ox + 10, oy + 32, 600, 20, '<font color="#9fb3c8">%s</font>' % L('ハード・MCU 内部・ファームのコードを同期表示', 'Hardware, MCU internals and firmware code stay in sync'), 10)
    p.box(ox + 1270 * k, oy + 22 * k, 310 * k, 44 * k, L('<font color="#4de0a1">シミュレーションモード・実機未接続</font>', '<font color="#4de0a1">Simulation mode · no hardware</font>'), 'fillColor=#1e3d33;strokeColor=#2a6a52', 10)
    R((20, 108, 270, 776), L('<b>01 目標角度へ回す</b><br><br>スライダ（0–359°）<br>[全フロー自動実行]<br>[低速][高速]<br><br>① Ping<br>② Read 11<br>③ Write 64=1<br>④ Write 116<br>⑤ Read 132<br>⑥ Write 64=0<br><br>故障実験メニュー<br>電気プロファイル<br><br>モータ表盘<br>（現在角/目標）',
                             '<b>01 Turn to angle</b><br><br>slider (0–359°)<br>[Run whole flow]<br>[Slow][Fast]<br><br>① Ping<br>② Read 11<br>③ Write 64=1<br>④ Write 116<br>⑤ Read 132<br>⑥ Write 64=0<br><br>Fault menu<br>Electrical profile<br><br>Motor dial<br>(current / goal)'),
      'fillColor=#223247;strokeColor=#3b5473;fontColor=#d9e6f5', 10, 'top')
    R((305, 108, 755, 362), L('<b>02 ハードウェア（3D）</b>　←/→ で回転<br><br>PC — USB — MCU — レベルシフタ — 三態バッファ — アクチュエータ<br>USB青 · TX橙 · RX緑 · DIR紫 · DATA青緑<br>飛ぶ四角 = 転送中のバイト<br><br>下部バッジ: DIR HIGH/LOW とゲートの状態',
                             '<b>02 Hardware (3D)</b>   ←/→ to rotate<br><br>PC — USB — MCU — level shifter — buffer — actuator<br>USB blue · TX orange · RX green · DIR purple · DATA cyan<br>flying squares = bytes in transit<br><br>bottom badge: DIR HIGH/LOW and gate state'),
      'fillColor=#223247;strokeColor=#3b5473;fontColor=#d9e6f5', 10, 'top')
    R((305, 482, 755, 402), L('<b>レンズ（拡大図）</b>  [MCU 内部] [三態バッファ] [波形]<br><br>MCU 内部: UART0/UART1 の移位レジスタ・FIFO(16)・SRAM g_buf/g_rx・DIR<br>三態バッファ: 送信/受信ゲートと /OE1・OE2<br>波形: TX・DIR・FIFO_EMPTY・TX_COMPLETE',
                              '<b>Lens (zoom)</b>  [MCU internals] [Buffer] [Waveform]<br><br>MCU: UART0/UART1 shift registers, FIFO(16), SRAM g_buf/g_rx, DIR<br>Buffer: TX/RX gates, /OE1 and OE2<br>Waveform: TX, DIR, FIFO_EMPTY, TX_COMPLETE'),
      'fillColor=#223247;strokeColor=#3b5473;fontColor=#d9e6f5', 10, 'top')
    R((1075, 108, 505, 460), L('<b>03 ファーム firmware/main.c</b><br>現在位置 main() → read_packet(...)<br><br>[NN] タグの行を黄色くハイライト<br>ステップごとに自動スクロール',
                               '<b>03 Firmware main.c</b><br>where: main() → read_packet(...)<br><br>lines tagged [NN] highlighted yellow<br>auto-scrolls with the step'),
      'fillColor=#223247;strokeColor=#3b5473;fontColor=#d9e6f5', 10, 'top')
    R((1075, 580, 505, 304), L('<b>操作・解説</b><br>HEX 入力（編集可）<br>[パケット読込][次へ][自動再生][再生し直す][初期化]<br><br>ステップ見出し 01/12 …<br>やさしい説明＋用語メモ',
                               '<b>Controls & explanation</b><br>HEX entry (editable)<br>[Load][Next][Auto play][Replay][Reset]<br><br>step heading 01/12 …<br>plain-language text + glossary'),
      'fillColor=#223247;strokeColor=#3b5473;fontColor=#d9e6f5', 10, 'top')
    R((20, 900, 1560, 84), L('<b>バイトストリップ</b>　TX PC → モータ（20 セル）／ RX モータ → PC（20 セル）　　デコード: ID · 命令 · 長さ · CRC OK／Error',
                             '<b>Byte strip</b>   TX PC→actuator (20 cells) / RX actuator→PC (20 cells)   decode: ID · instr · length · CRC OK / Error'),
      'fillColor=#223247;strokeColor=#3b5473;fontColor=#d9e6f5', 10)
    # side table: step → lens
    p.text(1000, 90, 600, 24, L('各ステップで自動的に切り替わるレンズ（LENS_FOR_STEP）', 'Lens tab chosen per step (LENS_FOR_STEP)'), 13, True)
    p.table(1000, 120, [200, 400], 40, [
        [L('レンズ', 'Lens tab'), L('ステップ', 'Steps')],
        [L('MCU 内部', 'MCU internals'), '1, 2, 3, 5, 8, 10, 11, 12'],
        [L('三態バッファ', 'Tri-state buffer'), '4, 7, 9'],
        [L('波形', 'Waveform'), '6'],
    ], size=11, align=['left', 'left'])
    p.text(1000, 300, 600, 24, L('キーボード・特殊動作', 'Keyboard & behaviour'), 13, True)
    p.box(1000, 330, 600, 270, L(
        '• <b>Space</b> ＝ 次へ（next_step）<br>• <b>←/→</b> ＝ 3D 視点の回転 ±8°<br>• <b>Esc</b> ＝ 終了<br>'
        '• ウィンドウサイズ変更に追従（resize_ui）<br>• <b>--screenshot</b> ＝ オフスクリーンで自己検査 ＋ output/*.png を保存<br>'
        '• トレースの書き出し export() → output/trace-YYYYMMDD-HHMMSS.json<br>　　mode = SIMULATION_ONLY、hardware_tested = false<br>'
        '• 入力 HEX は 16 バイトまで（表示用 FIFO 深さ）、命令は 01/02/03 のみ',
        '• <b>Space</b> = next step (next_step)<br>• <b>←/→</b> = rotate the 3D camera ±8°<br>• <b>Esc</b> = quit<br>'
        '• follows window resizes (resize_ui)<br>• <b>--screenshot</b> = headless self-test + saves output/*.png<br>'
        '• trace export() → output/trace-YYYYMMDD-HHMMSS.json<br>   mode = SIMULATION_ONLY, hardware_tested = false<br>'
        '• HEX input limited to 16 bytes (display FIFO depth), instructions 01/02/03 only'),
        'white', 11, align='left', valign='top', extra='spacingLeft=10;spacingTop=8;')
    return p


# ======================================================================
# 12. Runtime state machine
# ======================================================================
def page_runtime():
    p = Page(L('12. 実行時の状態機械とフレームループ', '12. Runtime state machine & frame loop'), 1654, 1120)
    p.title(L('12. 実行時：パケットの状態遷移と tick() フレームループ', '12. Runtime: packet state transitions and the tick() frame loop'),
            L('Demo の finished / running / step_index / seq の関係。', 'How Demo.finished / running / step_index / seq relate.'))
    ST = 'ellipse;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;'
    GR = ST.replace('#dae8fc', '#d5e8d4').replace('#6c8ebf', '#82b366')
    RD = ST.replace('#dae8fc', '#f8cecc').replace('#6c8ebf', '#b85450')
    DEC = 'rhombus;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;'
    idle = p.box(60, 150, 240, 100, L('<b>待機</b><br>finished = True', '<b>Idle</b><br>finished = True'), ST, 11, shape='')
    load = p.box(430, 150, 260, 100, L('<b>読込済み</b><br>step_index = −1<br>finished = False', '<b>Loaded</b><br>step_index = −1<br>finished = False'), ST, 11, shape='')
    step = p.box(820, 150, 280, 100, L('<b>ステップ実行中</b><br>step 1 … 12', '<b>Stepping</b><br>step 1 … 12'), GR, 11, shape='')
    fin = p.box(1230, 150, 240, 100, L('<b>完了</b><br>step 12 の後<br>finished = True', '<b>Finished</b><br>after step 12<br>finished = True'), ST, 11, shape='')
    stop = p.box(820, 340, 280, 100, L('<b>停止（失敗）</b><br>stop(): finished = True<br>flow_state = fail', '<b>Stopped (failure)</b><br>stop(): finished = True<br>flow_state = fail'), RD, 11, shape='')
    p.edge(idle, load, L('load_packet() 成功<br>（HEX / ボタン）', 'load_packet() ok<br>(HEX / button)'), C['dark'], 2)
    p.edge(load, step, L('次へ ／ Space ／<br>自動再生', 'Next / Space /<br>Auto play'), C['dark'], 2)
    p.edge(step, fin, L('step 12 完了', 'step 12 done'), C['rx'], 2)
    p.text(870, 108, 180, 36, L('各ステップ ＝ next_step() 1 回<br>（×12）', 'one next_step() call per step<br>(×12)'), 10, False, '#555', 'center')
    p.edge(step, stop, L('故障 ／ 回包なし ／ 電気リスク', 'fault / no reply / electrical risk'), C['bad'], 2)
    p.edge(fin, idle, L('「リプレイ」/ 新しい load_packet()', 'Replay / a new load_packet()'), C['gnd'], 2, dashed=True, points=[(1350, 100), (180, 100)], style='exitX=0.5;exitY=0;entryX=0.5;entryY=0;')
    p.edge(stop, idle, '', C['gnd'], 2, dashed=True, points=[(180, 390)], style='exitX=0;exitY=0.5;entryX=0.5;entryY=1;')
    p.box(60, 470, 640, 115, L(
        '<b>load_packet() の入力検査</b><br>from_hex() → parse()（CRC / Length / ヘッダ）→ 命令 ∈ {1,2,3} → 長さ ≤ 16<br>'
        'NG なら「入力未送信」と表示して状態は変えない。OK なら飛行中のバイトを破棄、active_fault / active_profile を確定、return_level を調整、FW 変数を初期化し、デコード行を表示。',
        '<b>load_packet() input checks</b><br>from_hex() → parse() (CRC / Length / header) → instruction ∈ {1,2,3} → length ≤ 16<br>'
        'On failure shows "input not sent" and leaves state unchanged. On success discards flights, latches active_fault / active_profile, adjusts return_level, resets FW variables and shows the decode line.'),
          'yel', 10, align='left', valign='top', extra='spacingLeft=8;spacingTop=6;')
    p.box(780, 470, 690, 70, L('<b>settle()</b>：次のステップへ進む前に、飛行中のバイト・タイマ・波形アニメを即座に完了させる（最大 200 回ループ）。',
                               '<b>settle()</b>: before advancing, instantly finishes flights, timers and waveform animation (up to 200 passes).'),
          'cyan', 10, align='left', valign='top', extra='spacingLeft=8;spacingTop=6;')
    p.group(30, 640, 1590, 440, L('tick(task)  ― 毎フレーム実行（taskMgr）', 'tick(task) — runs every frame (taskMgr)'), 'mcu', 14)
    t = []
    labels = [L('dt = min(frame dt, 0.1)', 'dt = min(frame dt, 0.1)'),
              L('active_fault ≠「モータ未給電」なら<br>motor.update(dt)', 'unless active_fault is "unpowered":<br>motor.update(dt)'),
              L('refresh_motor()<br>ダイヤル・3D ホーン・テキスト', 'refresh_motor()<br>dial, 3D horn, text'),
              L('timers：期限の来た<br>later() を実行', 'timers: run due<br>later() callbacks'),
              L('wave_anim<br>波形カーソルを進める', 'wave_anim<br>advance waveform cursor'),
              L('flights<br>Flight.update(now)', 'flights<br>Flight.update(now)')]
    xs = 60
    for lb in labels:
        t.append(p.box(xs, 700, 235, 70, lb, 'white', 11))
        xs += 260
    for a, b in zip(t, t[1:]):
        p.edge(a, b)
    busy = p.box(1330, 820, 270, 70, L('busy ＝ flights ∨ timers ∨ wave_anim', 'busy = flights ∨ timers ∨ wave_anim'), 'yel', 10)
    p.edge(t[-1], busy, '', C['dark'], 2, style='exitX=0.5;exitY=1;entryX=0.5;entryY=0;')
    d1 = p.box(960, 810, 250, 90, L('running ?', 'running ?'), DEC, 10, shape='')
    p.edge(busy, d1, '', C['dark'], 2, style='exitX=0;exitY=0.5;entryX=1;entryY=0.5;')
    a1 = p.box(520, 815, 380, 80, L('busy なら step_done_at = 0。空いて 1.5 s ÷ speed 経過したら<br><b>next_step()</b>', 'if busy: step_done_at = 0. Once idle for 1.5 s ÷ speed:<br><b>next_step()</b>'), 'blue', 10)
    p.edge(d1, a1, L('はい', 'Yes'), C['rx'], 2)
    a2 = p.box(900, 950, 370, 100, L('<b>seq</b> あり ∧ finished ∧ 非 busy ∧ next_at 経過<br>→ seq_next() → flow_click_seq()', '<b>seq</b> set ∧ finished ∧ not busy ∧ next_at passed<br>→ seq_next() → flow_click_seq()'), 'blue', 10)
    p.edge(d1, a2, L('いいえ', 'No'), C['dark'], 2)
    p.box(60, 810, 420, 190, L(
        '<b>速度</b>  set_speed(1|3)<br>すべての遅延・移動時間を speed で割る。<br><br>'
        '<b>自動フロー（seq）</b><br>start_sequence() → ping → mode → on → goal → pos（最大 8 回）<br>'
        'packet_result() が next_at を設定（1.6 s ／ pos は 1.2 s）<br>失敗すると seq = None で停止。',
        '<b>Speed</b>  set_speed(1|3)<br>All delays and travel times are divided by speed.<br><br>'
        '<b>Automatic flow (seq)</b><br>start_sequence() → ping → mode → on → goal → pos (up to 8 times)<br>'
        'packet_result() sets next_at (1.6 s; pos 1.2 s)<br>On failure seq = None and the flow stops.'),
          'yel', 10, align='left', valign='top', extra='spacingLeft=8;spacingTop=6;')
    return p


# ======================================================================
def main():
    global LANG
    builders = [page_hardware, page_software, page_packet, page_registers, page_reply, page_sequence,
                page_firmware, page_dir, page_flow, page_faults, page_ui, page_runtime]
    for lang in ('ja', 'en'):
        LANG = lang
        pages = [b() for b in builders]
        xml = '<mxfile host="app.diagrams.net" agent="build_drawio.py" version="24.0.0">%s</mxfile>' % ''.join(pg.xml() for pg in pages)
        out = HERE / ('serial-actuator-lab.%s.drawio' % lang)
        out.write_text(xml, encoding='utf-8')
        print('wrote', out, len(xml) // 1024, 'KB,', len(pages), 'pages')


if __name__ == '__main__':
    main()
