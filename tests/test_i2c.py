import unittest

from zeroprobe.i2c import (
    INTERNAL_I2C_ADDRESSES,
    I2cInspector,
    I2cScanner,
    ScriptedI2cBus,
    SimulatedI2cInspector,
    SimulatedI2cScanner,
    format_i2c_scan,
)


class I2cTests(unittest.TestCase):
    def test_scanner_detects_external_addresses_and_skips_internal_devices(self):
        bus = ScriptedI2cBus({0x10, 0x3C, 0x48, 0x68})
        scan = I2cScanner(bus_factory=lambda device: bus).scan("/dev/i2c-1")
        self.assertEqual((0x3C, 0x48), scan.addresses)
        self.assertEqual(tuple(sorted(INTERNAL_I2C_ADDRESSES)), scan.skipped)
        self.assertTrue(bus.closed)
        self.assertNotIn(0x10, bus.probed)
        self.assertNotIn(0x68, bus.probed)

    def test_scanner_can_include_internal_addresses_only_with_explicit_override(self):
        bus = ScriptedI2cBus({0x10, 0x3C})
        scan = I2cScanner(bus_factory=lambda device: bus).scan(
            "/dev/i2c-1", include_internal=True
        )
        self.assertEqual((0x10, 0x3C), scan.addresses)
        self.assertEqual((), scan.skipped)

    def test_simulated_scan_and_report_are_deterministic(self):
        scanner = SimulatedI2cScanner()
        first = scanner.scan("sim://i2c")
        second = scanner.scan("sim://i2c")
        self.assertEqual(first, second)
        report = format_i2c_scan(first)
        self.assertIn("0x3c", report)
        self.assertIn("0x48", report)
        self.assertIn("internal_skipped=6", report)

    def test_selected_address_read_is_bounded_and_closes_bus(self):
        bus = ScriptedI2cBus({0x3C}, reads={0x3C: b"\xa5"})
        result = I2cInspector(bus_factory=lambda device: bus).read(
            "/dev/i2c-1", 0x3C, length=1
        )
        self.assertEqual(0x3C, result.address)
        self.assertEqual(b"\xa5", result.data)
        self.assertTrue(bus.closed)

    def test_simulated_selected_address_read_is_deterministic(self):
        inspector = SimulatedI2cInspector()
        self.assertEqual(b"\x00", inspector.read("sim://i2c", 0x3C).data)
        self.assertEqual(b"\x19", inspector.read("sim://i2c", 0x48).data)


if __name__ == "__main__":
    unittest.main()
