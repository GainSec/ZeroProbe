import unittest

from zeroprobe.backends import (
    GpiomonBackend,
    SimulatedBackend,
    build_gpioget_command,
    build_gpiomon_command,
    parse_gpiomon_line,
)


class BackendTests(unittest.TestCase):
    def test_simulated_capture_is_deterministic_and_complete(self):
        capture = SimulatedBackend().capture((22, 23), duration_ms=4, sample_period_us=1000)
        self.assertEqual((22, 23), capture.gpios)
        self.assertEqual(5, len(capture.samples))
        self.assertEqual(0, capture.samples[0].timestamp_ns)
        self.assertTrue(all(set(sample.values) == {22, 23} for sample in capture.samples))
        self.assertNotEqual(capture.samples[0].values, capture.samples[-1].values)

    def test_gpiomon_v1_command_is_read_only_edge_capture(self):
        command = build_gpiomon_command("1.6.3", "/dev/gpiochip0", (22, 23), 20)
        self.assertEqual(
            ["gpiomon", "--line-buffered", "--num-events", "20", "--format", "%o %e %s.%n", "/dev/gpiochip0", "22", "23"],
            command,
        )

    def test_gpiomon_v2_command_uses_chip_selector(self):
        command = build_gpiomon_command("2.1", "/dev/gpiochip0", (22,), 5)
        self.assertEqual(
            ["stdbuf", "-oL", "gpiomon", "--edges", "both", "--num-events", "5", "--format", "%o %E %S", "--chip", "/dev/gpiochip0", "22"],
            command,
        )

    def test_version_banner_with_v_prefix_selects_v2(self):
        command = build_gpiomon_command("gpiomon (libgpiod) v2.1.3", "/dev/gpiochip0", (22,), 5)
        self.assertIn("--edges", command)
        self.assertIn("--chip", command)

    def test_gpiomon_event_parser_accepts_rising_and_falling(self):
        self.assertEqual((22, 1, 123456789), parse_gpiomon_line("22 rising 0.123456789"))
        self.assertEqual((23, 0, 2_000_000_001), parse_gpiomon_line("23 falling 2.000000001"))

    def test_gpiomon_event_parser_accepts_v1_numeric_edges(self):
        self.assertEqual((22, 1, 123456789), parse_gpiomon_line("22 1 0.123456789"))
        self.assertEqual((23, 0, 2_000_000_001), parse_gpiomon_line("23 0 2.000000001"))
        self.assertEqual((23, 0, 2_000_000_001), parse_gpiomon_line("23 2 2.000000001"))

    def test_gpioget_commands_cover_both_libgpiod_generations(self):
        self.assertEqual(
            ["gpioget", "/dev/gpiochip0", "22", "23"],
            build_gpioget_command("1.6.3", "/dev/gpiochip0", (22, 23)),
        )
        self.assertEqual(
            ["gpioget", "--numeric", "--chip", "/dev/gpiochip0", "22", "23"],
            build_gpioget_command("2.1", "/dev/gpiochip0", (22, 23)),
        )

    def test_hardware_backend_preserves_all_channel_levels_on_edges(self):
        commands = []

        def read_levels(command):
            commands.append(command)
            return "0 1\n"

        def monitor(command, duration_seconds):
            commands.append(command)
            self.assertEqual(0.010, duration_seconds)
            return "22 rising 10.000000000\n23 falling 10.000000500\n"

        backend = GpiomonBackend(
            version="2.1",
            chip="/dev/gpiochip0",
            level_runner=read_levels,
            monitor_runner=monitor,
        )
        capture = backend.capture((22, 23), duration_ms=10, max_events=8)
        self.assertEqual({22: 0, 23: 1}, capture.samples[0].values)
        self.assertEqual({22: 1, 23: 1}, capture.samples[1].values)
        self.assertEqual({22: 1, 23: 0}, capture.samples[2].values)
        self.assertEqual(1, capture.samples[1].timestamp_ns)
        self.assertEqual(500, capture.samples[2].timestamp_ns)
        self.assertIn("--edges", commands[1])

    def test_hardware_backend_rejects_invalid_level_output(self):
        backend = GpiomonBackend(
            version="1.6.3",
            level_runner=lambda command: "0\n",
            monitor_runner=lambda command, duration: "",
        )
        with self.assertRaisesRegex(RuntimeError, "gpioget returned"):
            backend.capture((22, 23), duration_ms=10)


if __name__ == "__main__":
    unittest.main()
