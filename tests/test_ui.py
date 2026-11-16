import os
import io
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from zeroprobe.backends import SimulatedBackend
from zeroprobe.i2c import I2cScan
from zeroprobe.ui import AppController, FramebufferMirror, Screen, render_frame
from zeroprobe.web import WebSettings


class GuiTests(unittest.TestCase):
    def test_framebuffer_mirror_writes_exact_rgb565_frame(self):
        import pygame

        sink = io.BytesIO()
        mirror = FramebufferMirror(sink)
        frame = pygame.Surface((320, 170))
        frame.fill((255, 0, 0))
        mirror.present(frame)
        data = sink.getvalue()
        self.assertEqual(320 * 170 * 2, len(data))
        self.assertEqual(b"\x00\xf8", data[:2])

    def open_uart(self, app, read_send=False):
        if read_send:
            app.move(1)
        app.activate()
        app.activate()

    def open_i2c(self, app, read_send=False):
        if read_send:
            app.move(1)
        app.activate()
        app.move(1)
        app.activate()

    def test_dashboard_shows_one_mode_card_and_scrolls_between_modes(self):
        app = AppController(SimulatedBackend())
        self.assertEqual(Screen.DASHBOARD, app.screen)
        self.assertEqual("Read Only", app.selected_item.label)
        app.move(1)
        self.assertEqual("Read / Send", app.selected_item.label)

    def test_web_dashboard_setting_selects_interface_and_toggles_enabled(self):
        saved = []
        app = AppController(
            SimulatedBackend(),
            web_settings=WebSettings(False, "lo", 8765),
            web_interfaces=(("lo", "127.0.0.1"), ("wlan0", "192.168.1.42")),
            web_settings_saver=saved.append,
        )
        app.move(2)
        self.assertEqual("Web Dashboard", app.selected_item.label)
        app.activate()
        self.assertEqual(Screen.WEB, app.screen)
        app.move(1)
        self.assertEqual("wlan0", app.web_settings.interface)
        app.activate()
        self.assertTrue(app.web_settings.enabled)
        self.assertEqual(app.web_settings, saved[-1])

    def test_web_settings_write_failure_is_nonfatal(self):
        def fail_save(settings):
            raise OSError("read-only filesystem")

        app = AppController(
            SimulatedBackend(),
            web_settings=WebSettings(False, "lo", 8765),
            web_interfaces=(("lo", "127.0.0.1"), ("wlan0", "192.168.1.42")),
            web_settings_saver=fail_save,
        )
        app.move(2)
        app.activate()

        app.move(1)
        self.assertIn("SETTINGS ERROR", app.status)
        app.activate()
        self.assertIn("SETTINGS ERROR", app.status)

    def test_dashboard_renders_only_the_selected_mode_card(self):
        import zeroprobe.ui as ui

        app = AppController(SimulatedBackend())
        calls = []
        original = ui._text

        def record(surface, pygame, value, xy, size=12, color=(238, 238, 230), bold=False):
            calls.append(value)
            return original(surface, pygame, value, xy, size, color, bold)

        ui._text = record
        try:
            render_frame(app)
        finally:
            ui._text = original

        self.assertIn("Read Only", calls)
        self.assertNotIn("Read / Send", calls)

    def test_dashboard_uses_blue_header_without_safe_or_simulator_ready_labels(self):
        import zeroprobe.ui as ui

        app = AppController(SimulatedBackend())
        calls = []
        original = ui._text

        def record(surface, pygame, value, xy, size=12, color=(238, 238, 230), bold=False):
            calls.append(value)
            return original(surface, pygame, value, xy, size, color, bold)

        ui._text = record
        try:
            frame = render_frame(app)
        finally:
            ui._text = original

        self.assertEqual((20, 92, 170), frame.get_at((0, 0))[:3])
        self.assertNotIn("SAFE", calls)
        self.assertFalse(any("SIMULATOR" in value for value in calls))

    def test_dashboard_card_uses_blue_instead_of_yellow(self):
        app = AppController(SimulatedBackend())
        frame = render_frame(app)
        self.assertEqual((20, 92, 170), frame.get_at((40, 60))[:3])

    def test_read_only_opens_protocol_picker_then_uart_without_tx(self):
        app = AppController(SimulatedBackend())
        app.activate()
        self.assertEqual(Screen.PROTOCOL, app.screen)
        self.assertEqual("UART", app.selected_item.label)
        app.activate()
        self.assertEqual(Screen.UART, app.screen)
        app.append_uart_text("ATI")
        self.assertEqual("", app.uart_tx_text)

    def test_read_send_opens_protocol_picker_then_uart_with_tx(self):
        app = AppController(SimulatedBackend())
        app.move(1)
        app.activate()
        self.assertEqual(Screen.PROTOCOL, app.screen)
        app.activate()
        self.assertEqual(Screen.UART, app.screen)
        app.append_uart_text("ATI")
        self.assertEqual("ATI", app.uart_tx_text)

    def test_switching_to_read_only_clears_stale_uart_payload(self):
        app = AppController(SimulatedBackend())
        self.open_uart(app, read_send=True)
        app.append_uart_text("ATI")
        app.back()
        app.back()
        app.move(-1)
        self.open_uart(app)
        app.activate()
        self.assertEqual("", app.uart_tx_text)
        self.assertIn("RX15", app.status)
        self.assertNotIn("TX14", app.status)

    def test_protocol_picker_scrolls_to_i2c(self):
        app = AppController(SimulatedBackend())
        app.activate()
        app.move(1)
        self.assertEqual("I²C", app.selected_item.label)
        app.activate()
        self.assertEqual(Screen.I2C, app.screen)

    def test_terminal_escape_tap_returns_without_triggering_launcher_hold(self):
        app = AppController(SimulatedBackend())
        self.open_uart(app)
        self.assertFalse(app.press_escape(now=10.0))
        self.assertEqual(Screen.PROTOCOL, app.screen)

    def test_escape_release_allows_a_new_back_press(self):
        app = AppController(SimulatedBackend())
        self.open_i2c(app)
        app.press_escape(now=10.0)
        self.assertEqual(Screen.PROTOCOL, app.screen)
        app.release_escape()
        self.assertFalse(app.press_escape(now=11.0))
        self.assertEqual(Screen.DASHBOARD, app.screen)

    def test_escape_repeat_after_terminal_back_does_not_close_app(self):
        app = AppController(SimulatedBackend())
        self.open_uart(app)

        self.assertFalse(app.press_escape(now=10.0))
        self.assertEqual(Screen.PROTOCOL, app.screen)

        # A physical key repeat can arrive after the press changed screens but
        # before the matching key-up. It must not become another back/quit.
        self.assertFalse(app.press_escape(now=10.1))
        self.assertEqual(Screen.PROTOCOL, app.screen)

        app.release_escape()
        self.assertFalse(app.press_escape(now=14.0))
        self.assertEqual(Screen.DASHBOARD, app.screen)

    def test_uart_terminal_renders_full_screen_exit_instruction(self):
        import zeroprobe.ui as ui

        app = AppController(SimulatedBackend())
        self.open_uart(app)
        calls = []
        original = ui._text

        def record(surface, pygame, value, xy, size=12, color=(238, 238, 230), bold=False):
            calls.append((value, xy, size))
            return original(surface, pygame, value, xy, size, color, bold)

        ui._text = record
        try:
            frame = render_frame(app)
        finally:
            ui._text = original

        self.assertEqual((20, 92, 170), frame.get_at((0, 0))[:3])
        values = [value for value, _, _ in calls]
        self.assertIn("TAP ESC TO BACK", values)

    def test_back_returns_from_protocol_picker_to_selected_mode(self):
        app = AppController(SimulatedBackend())
        app.move(1)
        app.activate()
        app.back()
        self.assertEqual(Screen.DASHBOARD, app.screen)
        self.assertEqual("Read / Send", app.selected_item.label)

    def test_escape_returns_to_dashboard_without_writing_gpio(self):
        app = AppController(SimulatedBackend())
        self.open_uart(app)
        app.back()
        self.assertEqual(Screen.PROTOCOL, app.screen)
        app.back()
        self.assertEqual(Screen.DASHBOARD, app.screen)

    def test_uart_screen_requires_arm_then_captures_decoded_bytes(self):
        app = AppController(SimulatedBackend())
        self.open_uart(app)
        self.assertEqual(Screen.UART, app.screen)
        original_baud = app.uart_baud
        app.move(-1)
        self.assertNotEqual(original_baud, app.uart_baud)
        app.activate()
        self.assertTrue(app.uart_armed)
        self.assertIsNone(app.uart_capture)
        app.activate()
        self.assertIn(b"ZeroProbe", app.uart_capture.data)
        self.assertIn("RX", app.status)

    def test_uart_failure_is_shown_without_crashing_gui(self):
        class FailingUart:
            def capture(self, device, baud, duration_ms=2000, max_bytes=65536):
                raise RuntimeError("serial port busy")

        app = AppController(SimulatedBackend(), uart_monitor=FailingUart())
        self.open_uart(app)
        app.activate()
        app.activate()
        self.assertEqual(Screen.UART, app.screen)
        self.assertIn("ERROR", app.status)
        self.assertIn("busy", app.status)

    def test_uart_screen_can_edit_arm_and_transmit_payload(self):
        from zeroprobe.uart import SimulatedUartTerminal

        app = AppController(SimulatedBackend(), uart_monitor=SimulatedUartTerminal())
        self.open_uart(app, read_send=True)
        app.append_uart_text("ATI")
        self.assertEqual("ATI", app.uart_tx_text)
        app.activate()
        self.assertTrue(app.uart_armed)
        app.activate()
        self.assertEqual(b"ATI\r\n", app.uart_capture.transmitted)
        self.assertIn("TX 5B", app.status)

    def test_uart_tx_editing_is_bounded_and_disabled_while_armed(self):
        app = AppController(SimulatedBackend())
        self.open_uart(app, read_send=True)
        app.append_uart_text("X" * 200)
        self.assertEqual(64, len(app.uart_tx_text))
        app.erase_uart_text()
        self.assertEqual(63, len(app.uart_tx_text))
        app.activate()
        app.append_uart_text("Y")
        self.assertNotIn("Y", app.uart_tx_text)

    def test_uart_screen_uses_legible_sizes_for_critical_text(self):
        import zeroprobe.ui as ui

        app = AppController(SimulatedBackend())
        self.open_uart(app, read_send=True)
        app.append_uart_text("ATI")
        calls = []
        original = ui._text

        def record(surface, pygame, value, xy, size=12, color=(238, 238, 230), bold=False):
            calls.append((value, size))
            return original(surface, pygame, value, xy, size, color, bold)

        ui._text = record
        try:
            render_frame(app)
        finally:
            ui._text = original

        sizes = {value: size for value, size in calls}
        self.assertGreaterEqual(sizes["TX> ATI_"], 17)
        self.assertGreaterEqual(sizes["UART R/S TX-G14 RX-G15 115 8N1 3.3V"], 9)

    def test_uart_result_keeps_both_tx_and_rx_visible(self):
        import zeroprobe.ui as ui

        app = AppController(SimulatedBackend())
        self.open_uart(app, read_send=True)
        app.append_uart_text("ATI")
        app.activate()
        app.activate()
        calls = []
        original = ui._text

        def record(surface, pygame, value, xy, size=12, color=(238, 238, 230), bold=False):
            calls.append(value)
            return original(surface, pygame, value, xy, size, color, bold)

        ui._text = record
        try:
            render_frame(app)
        finally:
            ui._text = original

        self.assertTrue(any(value.startswith("TX> ATI") for value in calls))
        self.assertTrue(any(value.startswith("RX>") for value in calls))

    def test_uart_footer_tracks_selected_baud(self):
        import zeroprobe.ui as ui

        app = AppController(SimulatedBackend())
        self.open_uart(app, read_send=True)
        app.move(-1)
        calls = []
        original = ui._text

        def record(surface, pygame, value, xy, size=12, color=(238, 238, 230), bold=False):
            calls.append(value)
            return original(surface, pygame, value, xy, size, color, bold)

        ui._text = record
        try:
            render_frame(app)
        finally:
            ui._text = original

        self.assertIn("UART R/S TX-G14 RX-G15 57.6 8N1 3.3V", calls)

    def test_cardputer_bare_navigation_keys_work_without_fn(self):
        import pygame
        from zeroprobe.ui import _navigation_delta

        app = AppController(SimulatedBackend())
        self.assertEqual(-1, _navigation_delta(pygame.K_f, app, pygame))
        self.assertEqual(1, _navigation_delta(pygame.K_x, app, pygame))
        self.assertEqual(-1, _navigation_delta(pygame.K_z, app, pygame))
        self.assertEqual(1, _navigation_delta(pygame.K_c, app, pygame))

    def test_cardputer_bare_navigation_keys_do_not_corrupt_uart_payload(self):
        import pygame
        from zeroprobe.ui import _navigation_delta

        app = AppController(SimulatedBackend())
        self.open_uart(app, read_send=True)
        for key in (pygame.K_f, pygame.K_x, pygame.K_z, pygame.K_c):
            self.assertIsNone(_navigation_delta(key, app, pygame))

    def test_i2c_screen_requires_arm_then_scans_external_addresses(self):
        app = AppController(SimulatedBackend())
        self.open_i2c(app)
        self.assertEqual(Screen.I2C, app.screen)
        self.assertIsNone(app.i2c_scan)
        app.activate()
        self.assertTrue(app.i2c_armed)
        app.activate()
        self.assertEqual((0x3C, 0x48), app.i2c_scan.addresses)
        self.assertFalse(app.i2c_armed)
        self.assertIn("2 FOUND", app.status)

    def test_i2c_results_select_address_and_guard_one_byte_read(self):
        app = AppController(SimulatedBackend())
        self.open_i2c(app)
        app.activate()
        app.activate()
        self.assertEqual(0x3C, app.selected_i2c_address)
        app.move(1)
        self.assertEqual(0x48, app.selected_i2c_address)
        app.activate()
        self.assertTrue(app.i2c_read_armed)
        app.activate()
        self.assertEqual(0x48, app.i2c_read.address)
        self.assertEqual(b"\x19", app.i2c_read.data)

    def test_i2c_results_keep_the_selected_fourth_address_visible(self):
        import zeroprobe.ui as ui

        app = AppController(SimulatedBackend())
        self.open_i2c(app)
        app.i2c_scan = I2cScan("/dev/i2c-1", (0x20, 0x21, 0x22, 0x23), ())
        app.i2c_selection = 3
        calls = []
        original = ui._text

        def record(surface, pygame, value, xy, size=12, color=(238, 238, 230), bold=False):
            calls.append(value)
            return original(surface, pygame, value, xy, size, color, bold)

        ui._text = record
        try:
            render_frame(app)
        finally:
            ui._text = original

        self.assertIn("> 0x23  ACK  UNKNOWN", calls)

    def test_i2c_screen_renders_clear_shared_bus_warning(self):
        import zeroprobe.ui as ui

        app = AppController(SimulatedBackend())
        self.open_i2c(app)
        calls = []
        original = ui._text

        def record(surface, pygame, value, xy, size=12, color=(238, 238, 230), bold=False):
            calls.append((value, size))
            return original(surface, pygame, value, xy, size, color, bold)

        ui._text = record
        try:
            render_frame(app)
        finally:
            ui._text = original

        sizes = {value: size for value, size in calls}
        self.assertGreaterEqual(sizes["SHARED BUS — INTERNALS SKIPPED"], 13)
        self.assertGreaterEqual(sizes["I2C RO SDA-G2 SCL-G3 I2C1 3.3V"], 9)

    def test_frame_renders_at_cardputer_resolution(self):
        app = AppController(SimulatedBackend())
        surface = render_frame(app)
        self.assertEqual((320, 170), surface.get_size())
        with tempfile.NamedTemporaryFile(suffix=".png") as output:
            import pygame
            pygame.image.save(surface, output.name)
            self.assertGreater(os.path.getsize(output.name), 1000)

    def test_screenshot_startup_skips_unused_pygame_subsystems(self):
        import pygame
        from unittest.mock import patch
        from zeroprobe.ui import run_gui

        app = AppController(SimulatedBackend())
        with tempfile.TemporaryDirectory() as temporary:
            output = os.path.join(temporary, "frame.png")
            with patch.object(pygame, "init", side_effect=AssertionError("global init is slow")):
                self.assertEqual(0, run_gui(app, screenshot=output))
            self.assertTrue(os.path.isfile(output))


if __name__ == "__main__":
    unittest.main()
