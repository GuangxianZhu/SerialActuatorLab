"""Binary packet framing. No serial I/O in this educational app."""
from dataclasses import dataclass

HEADER = bytes.fromhex('FF FF FD 00')


def crc16(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x8005) & 0xffff if crc & 0x8000 else (crc << 1) & 0xffff
    return crc


def stuff(data: bytes) -> bytes:
    out = bytearray()
    for byte in data:
        out.append(byte)
        if out[-3:] == b'\xff\xff\xfd':
            out.append(0xfd)
    return bytes(out)


def unstuff(data: bytes) -> bytes:
    return data.replace(b'\xff\xff\xfd\xfd', b'\xff\xff\xfd')


def packet(device_id: int, instruction: int, params: bytes = b'') -> bytes:
    if not 0 <= device_id <= 252:
        raise ValueError('本演示仅支持单播 ID 0～252，不支持广播。')
    body = stuff(bytes([instruction]) + params)
    prefix = HEADER + bytes([device_id]) + (len(body) + 2).to_bytes(2, 'little') + body
    return prefix + crc16(prefix).to_bytes(2, 'little')


@dataclass(frozen=True)
class Packet:
    device_id: int
    instruction: int
    params: bytes


def parse(raw: bytes) -> Packet:
    if len(raw) < 10 or raw[:4] != HEADER:
        raise ValueError('包头必须是 FF FF FD 00；packet 至少 10 字节。')
    if raw[4] > 252:
        raise ValueError('本演示只接受单个电机的 ID 0～252。')
    if int.from_bytes(raw[5:7], 'little') + 7 != len(raw):
        raise ValueError('Length 字段与实际字节数不一致。')
    if crc16(raw[:-2]) != int.from_bytes(raw[-2:], 'little'):
        raise ValueError('CRC 错误：请检查最后两个字节；实际电机的处理依固件而异。')
    body = unstuff(raw[7:-2])
    if stuff(body) != raw[7:-2]:
        raise ValueError('Byte stuffing 格式不正确。')
    return Packet(raw[4], body[0], body[1:])


def from_hex(text: str) -> bytes:
    try:
        return bytes.fromhex(text)
    except ValueError as exc:
        raise ValueError('请输入 HEX 字节，例如 FF FF FD 00；不要输入 0x 或标点。') from exc


def hexline(data: bytes) -> str:
    return data.hex(' ').upper()


def write(address: int, data: bytes, device_id: int = 1) -> bytes:
    return packet(device_id, 3, address.to_bytes(2, 'little') + data)


def read(address: int, length: int, device_id: int = 1) -> bytes:
    return packet(device_id, 2, address.to_bytes(2, 'little') + length.to_bytes(2, 'little'))


def read_position(device_id: int = 1) -> bytes:
    return read(132, 4, device_id)


def status(device_id: int, error: int = 0, params: bytes = b'') -> bytes:
    return packet(device_id, 0x55, bytes([error]) + params)


class Motor:
    """Teaching actuator register subset; not an electrical model."""
    def __init__(self):
        self.device_id = 1
        self.torque = False
        self.position = 2048.0
        self.goal = 2048
        self.return_level = 2
        self.operating_mode = 3
        self.firmware_version = 1  # illustrative, not a detected firmware version
        self.speed = 700.0          # ticks/s；教学演示会调慢，方便看清转动

    @property
    def moving(self):
        return self.torque and abs(self.goal - self.position) > 1

    def update(self, dt):
        if self.torque:
            delta = self.goal - self.position
            self.position += max(-self.speed * dt, min(self.speed * dt, delta))

    def reply(self, request: Packet):
        if request.device_id != self.device_id:
            return None, 'ID 不匹配：电机忽略该包。'
        p = request.params
        if request.instruction == 1:
            if p:
                return status(self.device_id, 5), 'Ping 参数长度错误。'
            data = (1).to_bytes(2, 'little') + bytes([self.firmware_version])
            return status(self.device_id, params=data), 'Ping 回复：演示设备编号 1，固件版本 1（模拟值）。'
        if request.instruction == 2:
            if len(p) != 4:
                return status(self.device_id, 5), 'Read 参数长度错误。'
            address, length = int.from_bytes(p[:2], 'little'), int.from_bytes(p[2:], 'little')
            registers = {(64, 1): bytes([self.torque]), (68, 1): bytes([self.return_level]),
                         (132, 4): int(round(self.position)).to_bytes(4, 'little'),
                         (116, 4): self.goal.to_bytes(4, 'little'), (11, 1): bytes([self.operating_mode]),
                         (122, 1): bytes([self.moving])}
            data = registers.get((address, length))
            response = status(self.device_id, 7) if data is None else status(self.device_id, params=data)
            return (response if self.return_level >= 1 else None), '读取寄存器；角度要由 Present Position(132) 确认。'
        if request.instruction == 3:
            if len(p) < 3:
                return (status(self.device_id, 5) if self.return_level == 2 else None), 'Write 参数长度错误。'
            address, data = int.from_bytes(p[:2], 'little'), p[2:]
            value, error = int.from_bytes(data, 'little'), 0
            old_level = self.return_level
            note = ''
            expected = {64: 1, 68: 1, 116: 4, 11: 1}
            if address not in expected:
                error, note = 7, '本模拟未实现该寄存器，返回 Access Error。'
            elif len(data) != expected[address]:
                error, note = 5, '数据长度错误。'
            elif address == 64:
                if value > 1:
                    error, note = 4, 'Torque Enable 只能为 0 或 1。'
                else:
                    self.torque = bool(value)
                    note = '扭矩已开启。' if value else '扭矩已关闭；电机不会执行新的角度运动。'
            elif address == 68:
                if value > 2:
                    error, note = 4, 'Status Return Level 只能为 0、1、2。'
                else:
                    self.return_level = value
                    note = f'Status Return Level 已设为 {value}；Ping 始终回复。'
            elif address == 11:
                if self.torque:
                    error, note = 7, '修改位置模式前必须关闭扭矩。'
                elif value != 3:
                    error, note = 4, '此教学模拟仅实现位置模式 3。'
                else:
                    self.operating_mode = value
                    note = '已设为位置模式 3。'
            elif address == 116:
                if value > 4095:
                    error, note = 6, '目标超出本模拟单圈位置限制 0～4095。'
                else:
                    self.goal = value
                    note = '目标位置已写入；Write 回复只表示接受指令，不表示已到达。'
                    if not self.torque:
                        note += ' 当前扭矩关闭，因此不会转动。'
            return (status(self.device_id, error) if old_level == 2 else None), note
        return status(self.device_id, 2), '本模拟未实现这条指令。'
