import unittest

from zeroprobe.uart import (
    ParmrkDecoder,
    ScriptedUartReader,
    SimulatedUartMonitor,
    SimulatedUartTerminal,
    ScriptedUartPort,
    UartMonitor,
    UartTerminal,
    parse_hex_bytes,
    format_uart_capture,
)


class UartTests(unittest.TestCase):
    def test_parmrk_decoder_reports_framing_errors_breaks_and_literal_ff(self):
        decoder = ParmrkDecoder()
        self.assertEqual(b"A", decoder.feed(b"A\xff", final=False))
        self.assertEqual(b"\xffB", decoder.feed(b"\xff\xff\x00B", final=False))
        self.assertEqual(b"C", decoder.feed(b"C\xff\x00\x00", final=True))
        self.assertEqual(1, decoder.framing_errors)
        self.assertEqual(1, decoder.breaks)

    def test_uart_monitor_is_receive_only_and_preserves_decoded_bytes(self):
        reader = ScriptedUartReader([b"boot", b"> ", b"ok\n"])
        monitor = UartMonitor(reader_factory=lambda device, baud: reader)
        capture = monitor.capture("/dev/serial0", 115200, duration_ms=10)
        self.assertEqual(b"boot> ok\n", capture.data)
        self.assertEqual(115200, capture.baud)
        self.assertEqual("/dev/serial0", capture.device)
        self.assertTrue(reader.opened_read_only)
        self.assertTrue(reader.closed)

    def test_uart_capture_text_contains_ascii_hex_and_error_counts(self):
        reader = ScriptedUartReader([b"OK\xff\x00X"])
        capture = UartMonitor(reader_factory=lambda device, baud: reader).capture(
            "/dev/serial0", 9600, duration_ms=10
        )
        text = format_uart_capture(capture)
        self.assertIn("baud=9600", text)
        self.assertIn("framing_errors=1", text)
        self.assertIn("4f 4b 58", text)
        self.assertIn("OKX", text)

    def test_simulated_uart_monitor_is_deterministic(self):
        monitor = SimulatedUartMonitor()
        first = monitor.capture("sim://uart", 115200, duration_ms=100)
        second = monitor.capture("sim://uart", 115200, duration_ms=100)
        self.assertEqual(first, second)
        self.assertIn(b"ZeroProbe", first.data)

    def test_uart_terminal_transmits_then_captures_response(self):
        port = ScriptedUartPort([b"PONG\r\n"])
        terminal = UartTerminal(port_factory=lambda device, baud: port)
        capture = terminal.exchange(
            "/dev/serial0", 115200, b"PING\r\n", duration_ms=10
        )
        self.assertEqual([b"PING\r\n"], port.writes)
        self.assertEqual(b"PONG\r\n", capture.data)
        self.assertEqual(b"PING\r\n", capture.transmitted)
        self.assertTrue(port.opened_read_write)
        self.assertTrue(port.closed)

    def test_uart_terminal_rejects_empty_or_oversized_transmit(self):
        terminal = UartTerminal(port_factory=lambda device, baud: ScriptedUartPort([]))
        with self.assertRaisesRegex(ValueError, "transmit payload"):
            terminal.exchange("/dev/serial0", 115200, b"", duration_ms=10)
        with self.assertRaisesRegex(ValueError, "4096"):
            terminal.exchange("/dev/serial0", 115200, b"X" * 4097, duration_ms=10)

    def test_parse_hex_bytes_accepts_separators_and_rejects_invalid_input(self):
        self.assertEqual(b"AT\r\n", parse_hex_bytes("41 54:0d-0a"))
        with self.assertRaisesRegex(ValueError, "even number"):
            parse_hex_bytes("abc")

    def test_simulated_uart_terminal_echoes_transmit_deterministically(self):
        capture = SimulatedUartTerminal().exchange(
            "sim://uart", 9600, b"help\r\n", duration_ms=10
        )
        self.assertEqual(b"help\r\n", capture.transmitted)
        self.assertIn(b"SIM RX", capture.data)
        self.assertIn("tx_bytes=6", format_uart_capture(capture))


if __name__ == "__main__":
    unittest.main()
