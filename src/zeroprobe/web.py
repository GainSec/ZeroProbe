from __future__ import annotations

import fcntl
import json
import os
import socket
import struct
import threading
from dataclasses import asdict, dataclass

from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, Tuple

if TYPE_CHECKING:
    from http.server import ThreadingHTTPServer


DEFAULT_SETTINGS_PATH = Path.home() / ".config/zeroprobe/web.json"


@dataclass(frozen=True)
class WebSettings:
    enabled: bool = False
    interface: str = "lo"
    port: int = 8765


def load_web_settings(path: Path = DEFAULT_SETTINGS_PATH) -> WebSettings:
    if not path.exists():
        return WebSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        settings = WebSettings(
            enabled=bool(data.get("enabled", False)),
            interface=str(data.get("interface", "lo")),
            port=int(data.get("port", 8765)),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return WebSettings()
    if not 1 <= settings.port <= 65535:
        return WebSettings()
    return settings


def save_web_settings(path: Path, settings: WebSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(asdict(settings), sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)
    path.chmod(0o600)


def interface_ipv4(name: str) -> Optional[str]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        packed = struct.pack("256s", name[:15].encode("ascii", "ignore"))
        result = fcntl.ioctl(sock.fileno(), 0x8915, packed)
        return socket.inet_ntoa(result[20:24])
    except OSError:
        return None
    finally:
        sock.close()


def list_ipv4_interfaces() -> Tuple[Tuple[str, str], ...]:
    interfaces = []
    for _, name in socket.if_nameindex():
        address = interface_ipv4(name)
        if address:
            interfaces.append((name, address))
    interfaces.sort(key=lambda item: (item[0] != "lo", item[0]))
    return tuple(interfaces)


HTML = b"""<!doctype html>
<html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>ZeroProbe Remote Console</title><style>
:root{--bg:#080b10;--panel:#101722;--panel2:#0c121b;--line:#273347;--ink:#edf5ff;--muted:#8d9bb0;--blue:#1464b7;--cyan:#5ce6dc;--yellow:#ffd54a;--red:#ff6f68;--green:#62e88b;--radius:10px}
*{box-sizing:border-box}html{background:var(--bg)}body{margin:0;min-height:100vh;background:var(--bg);color:var(--ink);font:14px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;-webkit-font-smoothing:antialiased}.shell{width:min(1180px,calc(100% - 32px));margin:0 auto;padding:28px 0 36px}.topbar{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:0 2px 18px;border-bottom:1px solid var(--line)}.brand{display:flex;align-items:center;gap:12px}.mark{width:10px;height:34px;background:var(--blue);box-shadow:0 0 20px rgba(20,100,183,.45)}h1{font-size:17px;line-height:1.1;letter-spacing:.08em;margin:0}.eyebrow{color:var(--muted);font-size:10px;letter-spacing:.18em;margin-top:5px}.network{display:flex;align-items:center;gap:8px;color:var(--yellow);font-size:11px;letter-spacing:.06em}.network:before{content:'';width:7px;height:7px;border-radius:50%;background:var(--yellow)}
.workspace{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:16px;margin-top:16px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden}.panel-head{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:46px;padding:0 14px;border-bottom:1px solid var(--line);background:var(--panel2)}.panel-title{font-size:11px;font-weight:700;letter-spacing:.14em}.transport{display:flex;align-items:center;gap:7px;color:var(--muted);font-size:10px}.transport:before{content:'';width:7px;height:7px;border-radius:50%;background:var(--muted)}.transport.live{color:var(--green)}.transport.live:before{background:var(--green);box-shadow:0 0 10px rgba(98,232,139,.5)}
.device-stage{min-height:430px;display:grid;place-items:center;padding:28px;background:#06090d}.screen-shell{width:min(100%,860px);padding:8px;background:#020304;border:1px solid #344257;border-radius:7px;box-shadow:0 24px 80px rgba(0,0,0,.48)}.screen{display:block;width:100%;height:auto;aspect-ratio:320/170;image-rendering:pixelated;background:#08080a}.caption{display:flex;justify-content:space-between;gap:12px;padding:11px 14px;color:var(--muted);font-size:10px;border-top:1px solid var(--line)}
.control-body{padding:18px}.dpad{display:grid;grid-template-columns:repeat(3,64px);grid-template-rows:repeat(3,58px);gap:7px;justify-content:center;margin:4px auto 18px}.key{border:1px solid #41516a;border-bottom-color:#1d2634;border-radius:7px;background:#172131;color:var(--ink);font:700 18px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;cursor:pointer;touch-action:none;user-select:none;box-shadow:0 3px 0 #080c13;transition:transform 60ms ease,background 60ms ease}.key:hover{background:#1d2b40;border-color:#5a6f91}.key:focus-visible,.download:focus-visible{outline:2px solid var(--cyan);outline-offset:2px}.key:active,.key.pressed{transform:translateY(2px);box-shadow:0 1px 0 #080c13;background:#23405b}.up{grid-column:2;grid-row:1}.left{grid-column:1;grid-row:2}.enter{grid-column:2;grid-row:2;font-size:11px;color:var(--cyan)}.right{grid-column:3;grid-row:2}.down{grid-column:2;grid-row:3}.escape{width:100%;min-height:52px;color:#fff;border-color:#72403f;background:#352021;font-size:13px;letter-spacing:.08em}.escape:hover{background:#462727;border-color:#a55551}.hold{display:block;margin-top:5px;color:#d9a09d;font-size:9px;letter-spacing:.04em}.hints{margin:18px 0 0;padding:14px 0 0;border-top:1px solid var(--line);display:grid;gap:9px}.hint{display:flex;justify-content:space-between;align-items:center;color:var(--muted);font-size:10px}.kbd{color:var(--ink);border:1px solid #3c4960;background:#0a1018;border-radius:4px;padding:2px 6px}.actions{display:grid;gap:9px;margin-top:18px}.download{display:flex;align-items:center;justify-content:center;min-height:44px;border:1px solid #42536d;border-radius:7px;background:#121b29;color:var(--ink);text-decoration:none;font-weight:700;font-size:11px;letter-spacing:.08em}.download:hover{background:#1a273a}.safety{margin-top:14px;padding:11px 12px;border:1px solid #4b3f25;border-radius:7px;background:#1b180f;color:#d8c78f;font-size:10px;line-height:1.55}
@media(max-width:760px){.shell{width:min(100% - 20px,640px);padding:16px 0 24px}.topbar{align-items:flex-start;flex-direction:column}.workspace{grid-template-columns:1fr}.device-stage{min-height:auto;padding:12px}.caption{flex-direction:column;gap:3px}.control-body{padding:16px}.dpad{grid-template-columns:repeat(3,minmax(58px,76px));grid-template-rows:repeat(3,58px)}.network{font-size:9px}}
@media(prefers-reduced-motion:reduce){.key{transition:none}}
</style></head><body><main class=shell>
<header class=topbar><div class=brand><span class=mark></span><div><h1>ZEROPROBE REMOTE CONSOLE</h1><div class=eyebrow>CARDPUTERZERO INTERFACE EXPLORER</div></div></div><div class=network>LOCAL NETWORK / NO AUTH</div></header>
<section class=workspace><article class=panel><div class=panel-head><span class=panel-title>DEVICE VIEW</span><span id=link class=transport>WAITING FOR FRAME</span></div><div class=device-stage><div class=screen-shell><img id=f class=screen src='/frame.png' aria-label='ZeroProbe device display'></div></div><div class=caption><span>Canonical 320 x 170 device framebuffer</span><span>Updates approximately 6 times per second</span></div></article>
<aside class=panel><div class=panel-head><span class=panel-title>REMOTE CONTROL</span><span class=transport>INPUT FORWARDING</span></div><div class=control-body><div class=dpad><button class='key up' data-k=up aria-label=Up>&uarr;</button><button class='key left' data-k=left aria-label=Left>&larr;</button><button class='key enter' data-k=enter>ENTER</button><button class='key right' data-k=right aria-label=Right>&rarr;</button><button class='key down' data-k=down aria-label=Down>&darr;</button></div><button class='key escape' data-k=escape>ESCAPE<span class=hold>TAP TO GO BACK</span></button><div class=hints><div class=hint><span>Navigate</span><span class=kbd>ARROW KEYS</span></div><div class=hint><span>Select / arm</span><span class=kbd>ENTER</span></div><div class=hint><span>Type UART payload</span><span class=kbd>KEYBOARD</span></div></div><div class=actions><a class=download href='/log.txt' download='zeroprobe-log.txt'>DOWNLOAD SESSION LOG</a></div><div class=safety>Remote input uses the device's native controller and safety gates. This page does not bypass UART or I2C arming.</div></div></aside></section></main><script>
const map={ArrowLeft:'left',ArrowRight:'right',ArrowUp:'up',ArrowDown:'down',Enter:'enter',Escape:'escape',Backspace:'backspace'};const held=new Set();async function key(k,p,t=''){try{await fetch('/key',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:k,pressed:p,text:t})})}catch(_){setLink(false)}}function setLink(ok){const n=document.querySelector('#link');n.textContent=ok?'LIVE':'WAITING FOR FRAME';n.classList.toggle('live',ok)}document.addEventListener('keydown',e=>{if(map[e.key]){e.preventDefault();if(!e.repeat)key(map[e.key],true)}else if(e.key.length===1)key('text',true,e.key)});document.addEventListener('keyup',e=>{if(map[e.key]){e.preventDefault();key(map[e.key],false)}});document.querySelectorAll('button[data-k]').forEach(b=>{const down=e=>{e.preventDefault();if(held.has(b.dataset.k))return;held.add(b.dataset.k);b.classList.add('pressed');key(b.dataset.k,true)};const up=e=>{e.preventDefault();if(!held.delete(b.dataset.k))return;b.classList.remove('pressed');key(b.dataset.k,false)};b.onpointerdown=down;b.onpointerup=up;b.onpointercancel=up;b.onpointerleave=e=>{if(e.buttons)up(e)}});window.addEventListener('blur',()=>{document.querySelectorAll('button.pressed').forEach(b=>{held.delete(b.dataset.k);b.classList.remove('pressed');key(b.dataset.k,false)})});const frame=document.querySelector('#f');frame.onload=()=>setLink(true);frame.onerror=()=>setLink(false);setInterval(()=>{frame.src='/frame.png?t='+Date.now()},150);
</script></body></html>"""


class WebDashboard:
    def __init__(
        self,
        bind: str,
        port: int,
        key_handler: Callable[[str, bool, str], None],
        log_reader: Optional[Callable[[], bytes]] = None,
    ):
        self.bind = bind
        self.requested_port = port
        self.key_handler = key_handler
        self.log_reader = log_reader
        self._frame = b""
        self._frame_lock = threading.Lock()
        self._log_lines = []
        self._log_lock = threading.Lock()
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def port(self) -> int:
        return self._server.server_port if self._server else self.requested_port

    def update_frame(self, data: bytes) -> None:
        with self._frame_lock:
            self._frame = bytes(data)

    def append_log(self, line: str) -> None:
        clean = str(line).replace("\r", " ").replace("\n", " ")[:2048]
        with self._log_lock:
            self._log_lines.append(clean)
            del self._log_lines[:-1000]

    def start(self) -> None:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                route = self.path.split("?", 1)[0]
                if route == "/":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(HTML)))
                    self.end_headers()
                    self.wfile.write(HTML)
                    return
                if route == "/frame.png":
                    with dashboard._frame_lock:
                        frame = dashboard._frame
                    if not frame:
                        self.send_error(503, "frame not ready")
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(frame)))
                    self.end_headers()
                    self.wfile.write(frame)
                    return
                if route == "/log.txt":
                    if dashboard.log_reader is not None:
                        log = dashboard.log_reader()
                    else:
                        with dashboard._log_lock:
                            log = (("\n".join(dashboard._log_lines) + "\n") if dashboard._log_lines else "").encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Disposition", "attachment; filename=zeroprobe-log.txt")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(log)))
                    self.end_headers()
                    self.wfile.write(log)
                    return
                self.send_error(404)

            def do_POST(self) -> None:
                if self.path.split("?", 1)[0] != "/key":
                    self.send_error(404)
                    return
                origin = self.headers.get("Origin")
                expected_origin = f"http://{self.headers.get('Host', '')}"
                if origin is not None and origin != expected_origin:
                    self.send_error(403, "cross-origin input rejected")
                    return
                content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type != "application/json":
                    self.send_error(415, "application/json required")
                    return
                try:
                    length = min(int(self.headers.get("Content-Length", "0")), 4096)
                    payload = json.loads(self.rfile.read(length))
                    key = str(payload["key"])
                    pressed = bool(payload["pressed"])
                    text = str(payload.get("text", ""))[:64]
                    if key not in {"left", "right", "up", "down", "enter", "escape", "backspace", "text"}:
                        raise ValueError("invalid key")
                    dashboard.key_handler(key, pressed, text)
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    self.send_error(400, "invalid key event")
                    return
                self.send_response(204)
                self.end_headers()

            def log_message(self, format: str, *args) -> None:
                return

        self._server = ThreadingHTTPServer((self.bind, self.requested_port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._server = None
        self._thread = None
