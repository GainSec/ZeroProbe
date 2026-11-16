import unittest

from zeroprobe.backends import GpiomonBackend, SimulatedBackend
from zeroprobe.runtime import BackendUnavailable, select_backend


class RuntimeTests(unittest.TestCase):
    def test_auto_selects_gpio_when_tools_exist(self):
        backend = select_backend(
            "auto",
            which=lambda name: f"/usr/bin/{name}",
            version_runner=lambda command: "gpiomon (libgpiod) v2.1.3",
        )
        self.assertIsInstance(backend, GpiomonBackend)
        self.assertEqual("gpiomon (libgpiod) v2.1.3", backend.version)

    def test_auto_falls_back_to_simulator_off_device(self):
        backend = select_backend("auto", which=lambda name: None)
        self.assertIsInstance(backend, SimulatedBackend)

    def test_explicit_gpio_fails_closed_when_tool_is_missing(self):
        with self.assertRaisesRegex(BackendUnavailable, "gpiomon"):
            select_backend("gpio", which=lambda name: None)


if __name__ == "__main__":
    unittest.main()
