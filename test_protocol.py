import unittest
from protocol import Motor, crc16, from_hex, packet, parse, read_position, status, stuff, unstuff, write


class ProtocolTests(unittest.TestCase):
    def test_known_ping_vector(self):
        # Binary packet Ping ID=1 reference vector.
        raw = bytes.fromhex('FF FF FD 00 01 03 00 01 19 4E')
        self.assertEqual(packet(1,1),raw)
        self.assertEqual(parse(raw).instruction,1)

    def test_stuffing_and_length(self):
        params = bytes.fromhex('FF FF FD FD FF FF FD')
        raw = packet(1,3,params)
        self.assertEqual(parse(raw).params,params)
        self.assertEqual(int.from_bytes(raw[5:7],'little'),len(raw)-7)
        self.assertEqual(unstuff(stuff(params)),params)

    def test_reject_corrupt(self):
        raw = bytearray(packet(1,1))
        raw[-1] ^= 1
        with self.assertRaisesRegex(ValueError,'CRC'): parse(bytes(raw))
        with self.assertRaisesRegex(ValueError,'Length'): parse(packet(1,1)+b'\x00')
        with self.assertRaises(ValueError): from_hex('GG')

    def test_ping_model_number(self):
        motor = Motor()
        response,_ = motor.reply(parse(packet(1,1)))
        decoded = parse(response)
        self.assertEqual(decoded.instruction,0x55)
        self.assertEqual(int.from_bytes(decoded.params[1:3],'little'),1)
        self.assertEqual(decoded.params[0],0)

    def test_torque_gates_movement_and_read(self):
        motor = Motor()
        motor.reply(parse(write(116,(1024).to_bytes(4,'little'))))
        motor.update(10)
        self.assertEqual(motor.position,2048)
        motor.reply(parse(write(64,b'\x01')))
        motor.update(10)
        self.assertEqual(motor.position,1024)
        response,_ = motor.reply(parse(read_position()))
        self.assertEqual(int.from_bytes(parse(response).params[1:],'little'),1024)

    def test_id_no_response(self):
        response,_ = Motor().reply(parse(packet(2,1)))
        self.assertIsNone(response)

    def test_write_error_does_not_mutate(self):
        motor = Motor()
        response,_ = motor.reply(parse(write(116,(4096).to_bytes(4,'little'))))
        self.assertEqual(parse(response).params[0],6)
        self.assertEqual(motor.goal,2048)
        response,_ = motor.reply(parse(write(116,b'\x01')))
        self.assertEqual(parse(response).params[0],5)

    def test_reply_policy(self):
        motor = Motor()
        motor.return_level = 1
        response,_ = motor.reply(parse(write(64,b'\x01')))
        self.assertIsNone(response)
        self.assertTrue(motor.torque)
        self.assertIsNotNone(motor.reply(parse(read_position()))[0])
        motor.return_level = 0
        self.assertIsNone(motor.reply(parse(read_position()))[0])
        self.assertIsNotNone(motor.reply(parse(packet(1,1)))[0])

    def test_mode_requires_torque_off(self):
        motor = Motor()
        motor.torque = True
        response,_ = motor.reply(parse(write(11,b'\x03')))
        self.assertEqual(parse(response).params[0],7)


if __name__ == '__main__':
    unittest.main()
