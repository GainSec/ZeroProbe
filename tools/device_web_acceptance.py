import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

from zeroprobe.web import WebDashboard, WebSettings, list_ipv4_interfaces, load_web_settings, save_web_settings


events = []
dashboard = WebDashboard(
    bind="127.0.0.1",
    port=0,
    key_handler=lambda key, pressed, text="": events.append((key, pressed, text)),
)
dashboard.update_frame(b"PNGDATA")
dashboard.append_log("DEVICE WEB READY")
dashboard.start()
try:
    base = f"http://127.0.0.1:{dashboard.port}"
    page = urlopen(base + "/", timeout=2).read()
    assert b"ZEROPROBE REMOTE CONSOLE" in page
    assert b"DOWNLOAD SESSION LOG" in page
    assert b"TAP TO GO BACK" in page
    assert b"@media(max-width:760px)" in page
    assert urlopen(base + "/frame.png", timeout=2).read() == b"PNGDATA"
    assert urlopen(base + "/log.txt", timeout=2).read() == b"DEVICE WEB READY\n"
    request = Request(
        base + "/key",
        data=b'{"key":"right","pressed":true}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    assert urlopen(request, timeout=2).status == 204
    assert events == [("right", True, "")]
finally:
    dashboard.stop()

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "web.json"
    assert not load_web_settings(path).enabled
    save_web_settings(path, WebSettings(True, "lo", 8765))
    assert load_web_settings(path).enabled

print("DEVICE_WEB_ACCEPTANCE_OK", list_ipv4_interfaces())
