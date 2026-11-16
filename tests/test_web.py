import json
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from zeroprobe.web import WebDashboard, WebSettings, load_web_settings, save_web_settings


class WebTests(unittest.TestCase):
    def test_settings_import_does_not_eagerly_load_http_server(self):
        result = subprocess.run(
            [sys.executable, "-c", "import sys; import zeroprobe.web; print('http.server' in sys.modules)"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual("False", result.stdout.strip())

    def test_settings_are_disabled_by_default_and_round_trip_securely(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            settings = load_web_settings(path)
            self.assertFalse(settings.enabled)
            self.assertEqual("lo", settings.interface)
            self.assertEqual(8765, settings.port)
            save_web_settings(path, WebSettings(True, "wlan0", 9000))
            self.assertEqual(
                WebSettings(True, "wlan0", 9000),
                load_web_settings(path),
            )
            self.assertEqual(0o600, path.stat().st_mode & 0o777)

    def test_dashboard_serves_frames_and_forwards_key_events_without_auth(self):
        events = []
        dashboard = WebDashboard(
            bind="127.0.0.1",
            port=0,
            key_handler=lambda key, pressed, text="": events.append((key, pressed, text)),
            log_reader=lambda: b"PERSISTED LOG\n",
        )
        dashboard.update_frame(b"PNGDATA")
        dashboard.append_log("SIMULATOR · READY")
        dashboard.start()
        try:
            base = f"http://127.0.0.1:{dashboard.port}"
            self.assertEqual(
                b"PNGDATA",
                urlopen(base + "/frame.png", timeout=2).read(),
            )
            page = urlopen(base + "/", timeout=2).read()
            self.assertIn(b"DOWNLOAD SESSION LOG", page)
            self.assertIn(b"ZEROPROBE REMOTE CONSOLE", page)
            self.assertIn(b"DEVICE VIEW", page)
            self.assertIn(b"REMOTE CONTROL", page)
            self.assertIn(b"LOCAL NETWORK / NO AUTH", page)
            self.assertIn(b"TAP TO GO BACK", page)
            self.assertIn(b"aria-label='ZeroProbe device display'", page)
            self.assertIn(b"@media(max-width:760px)", page)
            self.assertEqual(
                b"PERSISTED LOG\n",
                urlopen(base + "/log.txt", timeout=2).read(),
            )
            request = Request(
                base + "/key",
                data=json.dumps({"key": "left", "pressed": True}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            self.assertEqual(204, urlopen(request, timeout=2).status)
            self.assertEqual([("left", True, "")], events)

            cross_origin = Request(
                base + "/key",
                data=json.dumps({"key": "enter", "pressed": True}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Origin": "https://attacker.example",
                },
                method="POST",
            )
            with self.assertRaises(HTTPError) as rejected:
                urlopen(cross_origin, timeout=2)
            self.assertEqual(403, rejected.exception.code)

            simple_cross_origin = Request(
                base + "/key",
                data=b'{"key":"enter","pressed":true}',
                headers={"Content-Type": "text/plain"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as rejected:
                urlopen(simple_cross_origin, timeout=2)
            self.assertEqual(415, rejected.exception.code)
            self.assertEqual([("left", True, "")], events)
        finally:
            dashboard.stop()


if __name__ == "__main__":
    unittest.main()
