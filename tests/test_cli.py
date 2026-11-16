import os
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from zeroprobe.cli import main


class CliTests(unittest.TestCase):
    def test_screenshot_command_writes_gui_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            output = os.path.join(directory, "gui.png")
            self.assertEqual(0, main(["gui", "--screenshot", output]))
            self.assertGreater(os.path.getsize(output), 1000)

    def test_simulated_capture_writes_vcd(self):
        with tempfile.TemporaryDirectory() as directory:
            output = os.path.join(directory, "capture.vcd")
            self.assertEqual(
                0,
                main(["capture", "--simulate", "--pins", "22", "--duration-ms", "10", "--output", output]),
            )
            text = __import__("pathlib").Path(output).read_text(encoding="utf-8")
            self.assertIn("GPIO22", text)
            self.assertIn("source=simulator", text)

    def test_simulated_uart_monitor_writes_decoded_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = os.path.join(directory, "uart.txt")
            self.assertEqual(
                0,
                main([
                    "uart", "--simulate", "--baud", "115200",
                    "--duration-ms", "10", "--output", output,
                ]),
            )
            text = __import__("pathlib").Path(output).read_text(encoding="utf-8")
            self.assertIn("ZeroProbe UART RX ready", text)
            self.assertIn("framing_errors=0", text)

    def test_hardware_uart_requires_explicit_grove_acknowledgement(self):
        with self.assertRaisesRegex(ValueError, "allow-grove-uart"):
            main(["uart", "--duration-ms", "10"])

    def test_simulated_uart_can_transmit_text_and_report_response(self):
        with tempfile.TemporaryDirectory() as directory:
            output = os.path.join(directory, "uart-tx.txt")
            self.assertEqual(0, main([
                "uart", "--simulate", "--send-text", "ATI", "--append", "crlf",
                "--duration-ms", "10", "--output", output,
            ]))
            text = __import__("pathlib").Path(output).read_text(encoding="utf-8")
            self.assertIn("tx_bytes=5", text)
            self.assertIn("tx_hex: 41 54 49 0d 0a", text)
            self.assertIn("SIM RX", text)

    def test_hardware_uart_transmit_requires_separate_tx_acknowledgement(self):
        with self.assertRaisesRegex(ValueError, "allow-uart-tx"):
            main([
                "uart", "--allow-grove-uart", "--send-hex", "41",
                "--duration-ms", "10",
            ])

    def test_simulated_i2c_scan_writes_external_addresses(self):
        with tempfile.TemporaryDirectory() as directory:
            output = os.path.join(directory, "i2c.txt")
            self.assertEqual(0, main([
                "i2c", "--simulate", "--output", output,
            ]))
            text = __import__("pathlib").Path(output).read_text(encoding="utf-8")
            self.assertIn("addresses: 0x3c 0x48", text)
            self.assertIn("internal_skipped=6", text)

    def test_hardware_i2c_scan_requires_shared_bus_acknowledgement(self):
        with self.assertRaisesRegex(ValueError, "allow-shared-i2c"):
            main(["i2c"])

    def test_internal_i2c_probe_requires_separate_acknowledgement(self):
        with self.assertRaisesRegex(ValueError, "allow-internal-i2c"):
            main(["i2c", "--allow-shared-i2c", "--include-internal"])


if __name__ == "__main__":
    unittest.main()
