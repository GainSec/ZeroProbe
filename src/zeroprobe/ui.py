from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from io import BytesIO
from pathlib import Path
from queue import Empty, SimpleQueue
from time import monotonic
from typing import BinaryIO, Callable, Optional, Protocol, Tuple

from .capture import Capture
from .i2c import (
    I2cInspector,
    I2cRead,
    I2cScan,
    I2cScanner,
    SimulatedI2cInspector,
    SimulatedI2cScanner,
)
from .session_log import PersistentLog
from .uart import STANDARD_BAUDS, SimulatedUartTerminal, UartCapture, UartTerminal
from .web import WebDashboard, WebSettings


class CaptureBackend(Protocol):
    name: str

    def capture(
        self, gpios: Tuple[int, ...], duration_ms: int = 1000, sample_period_us: int = 1000
    ) -> Capture: ...


class UartBackend(Protocol):
    def capture(
        self, device: str, baud: int, duration_ms: int = 2000, max_bytes: int = 65536
    ) -> UartCapture: ...

    def exchange(
        self,
        device: str,
        baud: int,
        transmit: bytes,
        duration_ms: int = 2000,
        max_bytes: int = 65536,
    ) -> UartCapture: ...


class I2cBackend(Protocol):
    def scan(self, device: str, include_internal: bool = False) -> I2cScan: ...


class I2cInspectBackend(Protocol):
    def read(self, device: str, address: int, length: int = 1) -> I2cRead: ...


class FramebufferMirror:
    """Mirror a 320×170 pygame frame to the CardputerZero RGB565 framebuffer."""

    def __init__(self, sink: BinaryIO, owns_sink: bool = False):
        self.sink = sink
        self.owns_sink = owns_sink

    @classmethod
    def open_device(cls, path: str = "/dev/fb_lcd") -> "FramebufferMirror":
        return cls(open(path, "r+b", buffering=0), owns_sink=True)

    def present(self, frame) -> None:
        import pygame

        if frame.get_size() != (320, 170):
            raise ValueError("framebuffer mirror requires a 320x170 frame")
        rgb565 = pygame.Surface(
            (320, 170), depth=16, masks=(0xF800, 0x07E0, 0x001F, 0)
        )
        rgb565.blit(frame, (0, 0))
        data = bytes(rgb565.get_buffer())
        self.sink.seek(0)
        self.sink.write(data)
        self.sink.flush()

    def close(self) -> None:
        if self.owns_sink:
            self.sink.close()


class Screen(Enum):
    DASHBOARD = "dashboard"
    PROTOCOL = "protocol"
    CAPTURE = "capture"
    PINS = "pins"
    UART = "uart"
    I2C = "i2c"
    BUSES = "buses"
    ABOUT = "about"
    WEB = "web"


@dataclass(frozen=True)
class MenuItem:
    label: str
    subtitle: str
    screen: Screen


class AccessMode(Enum):
    READ_ONLY = "read-only"
    READ_SEND = "read-send"


MODE_MENU = (
    MenuItem("Read Only", "Monitor without transmitting", Screen.PROTOCOL),
    MenuItem("Read / Send", "Monitor and transmit", Screen.PROTOCOL),
    MenuItem("Web Dashboard", "Remote screen and controls", Screen.WEB),
)

PROTOCOL_MENU = (
    MenuItem("UART", "GPIO14 TX · GPIO15 RX", Screen.UART),
    MenuItem("I²C", "GPIO2 SDA · GPIO3 SCL", Screen.I2C),
)


class AppController:
    def __init__(
        self,
        backend: CaptureBackend,
        uart_monitor: Optional[UartBackend] = None,
        i2c_scanner: Optional[I2cBackend] = None,
        i2c_inspector: Optional[I2cInspectBackend] = None,
        web_settings: WebSettings = WebSettings(),
        web_interfaces: Tuple[Tuple[str, str], ...] = (("lo", "127.0.0.1"),),
        web_settings_saver: Optional[Callable[[WebSettings], None]] = None,
    ):
        self.backend = backend
        self.uart_monitor = uart_monitor or (
            SimulatedUartTerminal() if backend.name == "simulator" else UartTerminal()
        )
        self.i2c_scanner = i2c_scanner or (
            SimulatedI2cScanner() if backend.name == "simulator" else I2cScanner()
        )
        self.i2c_inspector = i2c_inspector or (
            SimulatedI2cInspector() if backend.name == "simulator" else I2cInspector()
        )
        self.screen = Screen.DASHBOARD
        self.selection = 0
        self.access_mode = AccessMode.READ_ONLY
        self.capture: Optional[Capture] = None
        self.uart_capture: Optional[UartCapture] = None
        self.uart_baud_index = STANDARD_BAUDS.index(115200)
        self.uart_armed = False
        self.uart_tx_text = ""
        self.i2c_scan: Optional[I2cScan] = None
        self.i2c_armed = False
        self.i2c_selection = 0
        self.i2c_read_armed = False
        self.i2c_read: Optional[I2cRead] = None
        self.escape_hold_started_at: Optional[float] = None
        self.escape_key_down = False
        self.web_interfaces = web_interfaces or (("lo", "127.0.0.1"),)
        self.web_settings_saver = web_settings_saver or (lambda settings: None)
        names = [name for name, _ in self.web_interfaces]
        self.web_interface_index = names.index(web_settings.interface) if web_settings.interface in names else 0
        selected_interface = self.web_interfaces[self.web_interface_index][0]
        self.web_settings = WebSettings(web_settings.enabled, selected_interface, web_settings.port)
        self.status = f"{backend.name.upper()} · READY"

    @property
    def uart_baud(self) -> int:
        return STANDARD_BAUDS[self.uart_baud_index]

    @property
    def selected_item(self) -> MenuItem:
        menu = PROTOCOL_MENU if self.screen is Screen.PROTOCOL else MODE_MENU
        return menu[self.selection]

    @property
    def selected_i2c_address(self) -> Optional[int]:
        if not self.i2c_scan or not self.i2c_scan.addresses:
            return None
        return self.i2c_scan.addresses[self.i2c_selection]

    def _save_web_settings(self) -> bool:
        try:
            self.web_settings_saver(self.web_settings)
        except OSError as error:
            self.status = f"WEB SETTINGS ERROR · {error}"
            return False
        return True

    def move(self, delta: int) -> None:
        if self.screen is Screen.DASHBOARD:
            self.selection = (self.selection + delta) % len(MODE_MENU)
        elif self.screen is Screen.PROTOCOL:
            self.selection = (self.selection + delta) % len(PROTOCOL_MENU)
        elif self.screen is Screen.WEB:
            self.web_interface_index = (self.web_interface_index + delta) % len(self.web_interfaces)
            interface = self.web_interfaces[self.web_interface_index][0]
            self.web_settings = WebSettings(self.web_settings.enabled, interface, self.web_settings.port)
            self._save_web_settings()
        elif self.screen is Screen.I2C and self.i2c_scan and not self.i2c_read_armed:
            count = len(self.i2c_scan.addresses)
            if count:
                self.i2c_selection = (self.i2c_selection + delta) % count
        elif self.screen is Screen.UART and not self.uart_armed:
            self.uart_baud_index = (self.uart_baud_index + delta) % len(STANDARD_BAUDS)
            self.status = f"RX15 · {self.uart_baud} BAUD"

    def append_uart_text(self, value: str) -> None:
        if (
            self.screen is not Screen.UART
            or self.access_mode is AccessMode.READ_ONLY
            or self.uart_armed
        ):
            return
        printable = "".join(character for character in value if character.isprintable())
        self.uart_tx_text = (self.uart_tx_text + printable)[:64]

    def erase_uart_text(self) -> None:
        if self.screen is Screen.UART and not self.uart_armed:
            self.uart_tx_text = self.uart_tx_text[:-1]

    @property
    def in_terminal(self) -> bool:
        return self.screen in (Screen.UART, Screen.I2C)

    def begin_escape_hold(self, now: Optional[float] = None) -> None:
        if self.in_terminal and self.escape_hold_started_at is None:
            self.escape_hold_started_at = monotonic() if now is None else now

    def cancel_escape_hold(self) -> None:
        self.escape_hold_started_at = None

    def press_escape(self, now: Optional[float] = None) -> bool:
        """Handle one physical Escape press; return True to quit the app."""
        if self.escape_key_down:
            return False
        self.escape_key_down = True
        if self.in_terminal:
            self.back()
            return False
        if self.screen is Screen.DASHBOARD:
            return True
        self.back()
        return False

    def release_escape(self) -> None:
        self.escape_key_down = False
        self.cancel_escape_hold()

    def update_escape_hold(self, now: Optional[float] = None) -> bool:
        if not self.in_terminal or self.escape_hold_started_at is None:
            return False
        current = monotonic() if now is None else now
        if current - self.escape_hold_started_at < 3.0:
            return False
        self.back()
        return True

    def activate(self) -> None:
        if self.screen is Screen.DASHBOARD:
            if self.selection == 2:
                self.screen = Screen.WEB
                return
            self.access_mode = (
                AccessMode.READ_ONLY if self.selection == 0 else AccessMode.READ_SEND
            )
            if self.access_mode is AccessMode.READ_ONLY:
                self.uart_tx_text = ""
            self.selection = 0
            self.screen = Screen.PROTOCOL
            return
        if self.screen is Screen.WEB:
            self.web_settings = WebSettings(
                not self.web_settings.enabled,
                self.web_settings.interface,
                self.web_settings.port,
            )
            if self._save_web_settings():
                state = "ON" if self.web_settings.enabled else "OFF"
                self.status = f"WEB {state} · {self.web_settings.interface}"
            return
        if self.screen is Screen.PROTOCOL:
            self.screen = self.selected_item.screen
            return
        if self.screen is Screen.CAPTURE:
            self.status = "CAPTURING GPIO22…"
            try:
                self.capture = self.backend.capture(
                    (22,), duration_ms=1000, sample_period_us=20_000
                )
            except Exception as error:
                self.capture = None
                self.status = f"ERROR · {error}"
                return
            self.status = f"CAPTURED {len(self.capture.samples)} SAMPLES · GPIO22"
            return
        if self.screen is Screen.UART:
            if not self.uart_armed:
                self.uart_armed = True
                action = (
                    "TX14 + RX15"
                    if self.access_mode is AccessMode.READ_SEND and self.uart_tx_text
                    else "RX15"
                )
                self.status = f"ARMED · ENTER START {action}"
                return
            payload = (
                self.uart_tx_text.encode("utf-8") + b"\r\n"
                if self.access_mode is AccessMode.READ_SEND and self.uart_tx_text
                else b""
            )
            self.status = (
                f"ACTIVE TX14/RX15 · {self.uart_baud}"
                if payload else f"LISTENING RX15 · {self.uart_baud}"
            )
            try:
                if payload:
                    self.uart_capture = self.uart_monitor.exchange(
                        "/dev/serial0", self.uart_baud, payload,
                        duration_ms=1500, max_bytes=2048,
                    )
                else:
                    self.uart_capture = self.uart_monitor.capture(
                        "/dev/serial0", self.uart_baud, duration_ms=1500, max_bytes=2048
                    )
            except Exception as error:
                self.uart_capture = None
                self.uart_armed = False
                self.status = f"ERROR · {error}"
                return
            self.uart_armed = False
            tx_count = len(self.uart_capture.transmitted)
            self.status = (
                f"TX {tx_count}B · RX {len(self.uart_capture.data)}B · "
                f"ERR {self.uart_capture.framing_errors}"
            )
            return
        if self.screen is Screen.I2C:
            if self.i2c_scan is not None and self.i2c_scan.addresses:
                address = self.selected_i2c_address
                if address is None:
                    return
                if not self.i2c_read_armed:
                    self.i2c_read_armed = True
                    self.status = f"ARMED READ 0x{address:02X} · ENTER CONFIRM"
                    return
                try:
                    self.i2c_read = self.i2c_inspector.read("/dev/i2c-1", address, 1)
                except Exception as error:
                    self.i2c_read = None
                    self.status = f"ERROR · {error}"
                else:
                    self.status = f"READ 0x{address:02X} · {self.i2c_read.data.hex(' ').upper()}"
                self.i2c_read_armed = False
                return
            if not self.i2c_armed:
                self.i2c_armed = True
                self.status = "ARMED · ENTER SCAN EXTERNAL I²C"
                return
            self.status = "SCANNING EXTERNAL I²C…"
            try:
                self.i2c_scan = self.i2c_scanner.scan("/dev/i2c-1")
            except Exception as error:
                self.i2c_scan = None
                self.i2c_armed = False
                self.status = f"ERROR · {error}"
                return
            self.i2c_armed = False
            self.i2c_selection = 0
            self.i2c_read = None
            self.status = f"{len(self.i2c_scan.addresses)} FOUND · INTERNALS SKIPPED"

    def back(self) -> None:
        if self.screen is Screen.DASHBOARD:
            return
        if self.screen is Screen.PROTOCOL:
            self.screen = Screen.DASHBOARD
            self.selection = 0 if self.access_mode is AccessMode.READ_ONLY else 1
        elif self.screen is Screen.WEB:
            self.screen = Screen.DASHBOARD
            self.selection = 2
        else:
            previous = self.screen
            self.screen = Screen.PROTOCOL
            self.selection = 0 if previous is Screen.UART else 1
        self.uart_armed = False
        self.i2c_armed = False
        self.i2c_read_armed = False
        self.escape_hold_started_at = None
        self.status = f"{self.backend.name.upper()} · READY"


def _font(pygame, size: int, bold: bool = False):
    font = pygame.font.Font(None, size)
    font.set_bold(bold)
    return font


def _text(surface, pygame, value: str, xy, size=12, color=(238, 238, 230), bold=False):
    surface.blit(_font(pygame, size, bold).render(value, True, color), xy)


_HEADER_LOGO = None


def _header(surface, pygame, title: str) -> None:
    global _HEADER_LOGO
    pygame.draw.rect(surface, (20, 92, 170), (0, 0, 320, 28))
    _text(surface, pygame, "ZEROPROBE", (8, 6), 13, (255, 255, 255), True)
    _text(surface, pygame, title.upper(), (105, 7), 11, (255, 220, 60), True)
    if _HEADER_LOGO is None:
        logo_path = Path(__file__).with_name("assets") / "gainsec-header.png"
        _HEADER_LOGO = pygame.image.load(str(logo_path))
    surface.blit(_HEADER_LOGO, (246, 4))


def _footer(surface, pygame, left: str, right: str) -> None:
    pygame.draw.line(surface, (67, 72, 77), (0, 151), (320, 151), 1)
    _text(surface, pygame, left, (7, 155), 9, (160, 166, 170))
    compact = right[-24:]
    width = _font(pygame, 9).size(compact)[0]
    _text(surface, pygame, compact, (313 - width, 155), 9, (160, 166, 170))


def _draw_carousel(surface, pygame, app: AppController, title: str, count: int) -> None:
    _header(surface, pygame, title)
    item = app.selected_item
    rect = pygame.Rect(24, 47, 272, 82)
    pygame.draw.rect(surface, (20, 92, 170), rect, border_radius=7)
    pygame.draw.rect(surface, (92, 237, 224), rect, 2, border_radius=7)
    _text(surface, pygame, "◀", (8, 79), 18, (160, 166, 170), True)
    _text(surface, pygame, "▶", (300, 79), 18, (160, 166, 170), True)
    _text(surface, pygame, item.label, (rect.x + 14, rect.y + 14), 24, (255, 255, 255), True)
    _text(surface, pygame, item.subtitle, (rect.x + 14, rect.y + 48), 12, (190, 220, 245), True)
    _text(surface, pygame, f"{app.selection + 1} / {count}", (266, 35), 10, (160, 166, 170), True)
    _footer(surface, pygame, "◀▶ SELECT · ENTER OPEN", "")


def _draw_dashboard(surface, pygame, app: AppController) -> None:
    _draw_carousel(surface, pygame, app, "SELECT MODE", len(MODE_MENU))


def _draw_protocol(surface, pygame, app: AppController) -> None:
    mode = "READ ONLY" if app.access_mode is AccessMode.READ_ONLY else "READ / SEND"
    _draw_carousel(surface, pygame, app, mode, len(PROTOCOL_MENU))


def _draw_web(surface, pygame, app: AppController) -> None:
    _header(surface, pygame, "WEB DASHBOARD")
    interface, address = app.web_interfaces[app.web_interface_index]
    state = "ENABLED" if app.web_settings.enabled else "DISABLED"
    color = (98, 232, 139) if app.web_settings.enabled else (160, 166, 170)
    _text(surface, pygame, state, (10, 39), 20, color, True)
    _text(surface, pygame, f"INTERFACE  {interface}", (10, 68), 14, (255, 210, 35), True)
    _text(surface, pygame, address, (10, 89), 14, (238, 238, 230), True)
    if app.web_settings.enabled:
        _text(surface, pygame, f"http://{address}:{app.web_settings.port}", (10, 111), 12, (92, 237, 224), True)
    _text(surface, pygame, "SELECT INTERFACE", (10, 132), 11, (255, 100, 92), True)
    _footer(surface, pygame, "◀▶ INTERFACE · ENTER TOGGLE", app.status)


def _draw_capture(surface, pygame, app: AppController) -> None:
    _header(surface, pygame, "LOGIC CAPTURE")
    _text(surface, pygame, "GPIO22", (8, 36), 12, (255, 210, 35), True)
    _text(surface, pygame, "INPUT · 20ms/sample · SIM", (78, 38), 9, (160, 166, 170))
    plot = pygame.Rect(8, 56, 304, 77)
    pygame.draw.rect(surface, (12, 14, 15), plot)
    for x in range(plot.x, plot.right, 38):
        pygame.draw.line(surface, (39, 43, 46), (x, plot.y), (x, plot.bottom))
    for y in (plot.y + 20, plot.y + 56):
        pygame.draw.line(surface, (39, 43, 46), (plot.x, y), (plot.right, y))
    if app.capture and app.capture.samples:
        points = []
        count = max(1, len(app.capture.samples) - 1)
        for index, sample in enumerate(app.capture.samples):
            x = plot.x + round(index * (plot.width - 1) / count)
            y = plot.y + (18 if sample.values[22] else 57)
            if points and points[-1][1] != y:
                points.append((x, points[-1][1]))
            points.append((x, y))
        if len(points) > 1:
            pygame.draw.lines(surface, (79, 220, 127), False, points, 2)
    else:
        _text(surface, pygame, "PRESS ENTER TO CAPTURE", (68, 86), 12, (104, 111, 116), True)
    _footer(surface, pygame, "ENTER CAPTURE · ESC BACK", app.status)


def _compact_baud(baud: int) -> str:
    if baud >= 100_000:
        return str(baud // 1000)
    value = baud / 1000
    return f"{value:g}"


def _terminal_footer(surface, pygame, value: str) -> None:
    pygame.draw.line(surface, (50, 58, 62), (0, 147), (320, 147), 1)
    _text(surface, pygame, value, (7, 153), 9, (205, 210, 212), True)


def _draw_uart(surface, pygame, app: AppController) -> None:
    surface.fill((8, 8, 10))
    _header(surface, pygame, "UART")
    read_send = app.access_mode is AccessMode.READ_SEND
    if app.uart_capture is None:
        if read_send:
            tx = app.uart_tx_text[-28:]
            _text(surface, pygame, f"TX> {tx}_", (7, 40), 17, (98, 232, 139), True)
            _text(surface, pygame, "RX> WAITING", (7, 68), 15, (92, 237, 224), True)
        else:
            _text(surface, pygame, "RX> READY TO LISTEN", (7, 40), 17, (98, 232, 139), True)
        prompt = "ARMED — ENTER START" if app.uart_armed else "ENTER ARM · ◀▶ BAUD"
        _text(surface, pygame, prompt, (7, 103), 12, (255, 210, 35), True)
    else:
        transmitted = app.uart_capture.transmitted.decode("utf-8", "replace").strip()
        if read_send:
            _text(surface, pygame, f"TX> {transmitted[-28:]}", (7, 40), 15, (255, 210, 35), True)
        data = app.uart_capture.data
        decoded = "".join(
            chr(value) if value in (10, 13) or 32 <= value < 127 else "." for value in data
        )
        line = decoded.replace("\r", "").replace("\n", " ")[-30:]
        _text(surface, pygame, f"RX> {line}", (7, 68), 15, (98, 232, 139), True)
        counters = f"{len(data)}B  ERR {app.uart_capture.framing_errors}  BREAK {app.uart_capture.breaks}"
        _text(surface, pygame, counters, (7, 98), 11, (160, 166, 170), True)
    _text(surface, pygame, "TAP ESC TO BACK", (7, 130), 10, (104, 111, 116), True)
    mode = "R/S" if read_send else "RO"
    pins = "TX-G14 RX-G15" if read_send else "RX-G15"
    _terminal_footer(
        surface, pygame,
        f"UART {mode} {pins} {_compact_baud(app.uart_baud)} 8N1 3.3V",
    )


def _draw_i2c(surface, pygame, app: AppController) -> None:
    surface.fill((8, 8, 10))
    _header(surface, pygame, "I2C")
    _text(surface, pygame, "SHARED BUS — INTERNALS SKIPPED", (7, 34), 13, (255, 165, 72), True)
    if app.i2c_scan is None:
        label = "ARMED — ENTER SCAN" if app.i2c_armed else "EXTERNAL ADDRESS SCAN"
        color = (255, 210, 35) if app.i2c_armed else (92, 237, 224)
        _text(surface, pygame, label, (7, 64), 17, color, True)
        if not app.i2c_armed:
            _text(surface, pygame, "ENTER ARM", (7, 91), 12, (160, 166, 170), True)
    else:
        if not app.i2c_scan.addresses:
            _text(surface, pygame, "NONE FOUND", (7, 62), 16, (160, 166, 170), True)
        window_start = max(0, min(app.i2c_selection - 1, len(app.i2c_scan.addresses) - 3))
        visible_addresses = app.i2c_scan.addresses[window_start:window_start + 3]
        for row, address in enumerate(visible_addresses):
            index = window_start + row
            marker = ">" if index == app.i2c_selection else " "
            color = (98, 232, 139) if index == app.i2c_selection else (205, 210, 212)
            _text(surface, pygame, f"{marker} 0x{address:02X}  ACK  UNKNOWN", (7, 57 + row * 21), 14, color, True)
        if app.i2c_read_armed:
            _text(surface, pygame, "ARMED READ — ENTER CONFIRM", (7, 121), 11, (255, 210, 35), True)
        elif app.i2c_read is not None:
            _text(
                surface, pygame,
                f"READ 0x{app.i2c_read.address:02X}> {app.i2c_read.data.hex(' ').upper()}",
                (7, 121), 11, (92, 237, 224), True,
            )
        else:
            _text(surface, pygame, "◀▶ SELECT · ENTER READ", (7, 121), 11, (160, 166, 170), True)
    mode = "R/S" if app.access_mode is AccessMode.READ_SEND else "RO"
    _terminal_footer(surface, pygame, f"I2C {mode} SDA-G2 SCL-G3 I2C1 3.3V")


def _draw_info(surface, pygame, app: AppController) -> None:
    titles = {Screen.PINS: "PIN SAFETY", Screen.BUSES: "BUS TOOLS", Screen.ABOUT: "ABOUT"}
    _header(surface, pygame, titles[app.screen])
    if app.screen is Screen.PINS:
        lines = ("GPIO22     FREE / RECOMMENDED", "GPIO23/26  USB MUX · LOCKED", "GPIO2/3    KEYBOARD I²C · SHARED", "GPIO9/10/11 DISPLAY SPI · SHARED")
    elif app.screen is Screen.BUSES:
        lines = ("UART  SERIAL CONSOLE        NEXT", "I²C   SAFE SCAN             NEXT", "SPI   TRANSACTION / FLASH   NEXT", "SWD   OPENOCD ADAPTER       LATER")
    else:
        lines = ("READ-ONLY BY DEFAULT", "NO 5V INPUT · USE PROTECTION", f"BACKEND: {app.backend.name.upper()}", "V0.1 · CARDPUTERZERO")
    for index, line in enumerate(lines):
        color = (255, 210, 35) if index == 0 else (218, 221, 219)
        _text(surface, pygame, line, (11, 43 + index * 24), 10, color, index == 0)
    _footer(surface, pygame, "ESC BACK", "NO GPIO WRITES")


def render_frame(app: AppController):
    import pygame

    if not pygame.font.get_init():
        pygame.font.init()
    surface = pygame.Surface((320, 170))
    surface.fill((16, 18, 20))
    if app.screen is Screen.DASHBOARD:
        _draw_dashboard(surface, pygame, app)
    elif app.screen is Screen.PROTOCOL:
        _draw_protocol(surface, pygame, app)
    elif app.screen is Screen.WEB:
        _draw_web(surface, pygame, app)
    elif app.screen is Screen.CAPTURE:
        _draw_capture(surface, pygame, app)
    elif app.screen is Screen.UART:
        _draw_uart(surface, pygame, app)
    elif app.screen is Screen.I2C:
        _draw_i2c(surface, pygame, app)
    else:
        _draw_info(surface, pygame, app)
    return surface


def _navigation_delta(key: int, app: AppController, pygame) -> Optional[int]:
    if key in (pygame.K_UP, pygame.K_LEFT):
        return -1
    if key in (pygame.K_DOWN, pygame.K_RIGHT):
        return 1
    # CardputerZero labels F/X/Z/C as Up/Down/Left/Right on the Fn layer.
    # Accept their bare forms on screens without UART payload entry.
    if app.screen is Screen.UART and app.access_mode is AccessMode.READ_SEND:
        return None
    if key in (pygame.K_f, pygame.K_z):
        return -1
    if key in (pygame.K_x, pygame.K_c):
        return 1
    return None


def run_gui(app: AppController, screenshot: Optional[str] = None) -> int:
    import pygame

    pygame.display.init()
    pygame.font.init()
    screen = pygame.display.set_mode((320, 170))
    pygame.display.set_caption("ZeroProbe")
    clock = pygame.time.Clock()
    if screenshot:
        pygame.image.save(render_frame(app), screenshot)
        pygame.quit()
        return 0
    framebuffer = (
        FramebufferMirror.open_device() if Path("/dev/fb_lcd").exists() else None
    )
    local_log = PersistentLog()
    local_log.append(f"START · backend={app.backend.name}")
    web_events = SimpleQueue()
    web_dashboard: Optional[WebDashboard] = None
    web_signature = None
    next_web_frame_at = 0.0
    last_logged_status = None
    last_logged_uart = None
    last_logged_i2c = None

    def append_log(line: str) -> None:
        local_log.append(line)
        if web_dashboard is not None:
            web_dashboard.append_log(line)

    def sync_web_dashboard() -> None:
        nonlocal web_dashboard, web_signature
        settings = app.web_settings
        signature = (settings.enabled, settings.interface, settings.port)
        if signature == web_signature:
            return
        if web_dashboard is not None:
            web_dashboard.stop()
            web_dashboard = None
        web_signature = signature
        if not settings.enabled:
            return
        addresses = dict(app.web_interfaces)
        bind = addresses.get(settings.interface)
        if bind is None:
            app.status = f"WEB ERROR · NO {settings.interface}"
            return
        try:
            web_dashboard = WebDashboard(
                bind=bind,
                port=settings.port,
                key_handler=lambda key, pressed, text="": web_events.put(
                    (key, pressed, text)
                ),
                log_reader=local_log.read,
            )
            web_dashboard.start()
            append_log(f"WEB START · {bind}:{web_dashboard.port}")
            app.status = f"WEB ON · {bind}:{web_dashboard.port}"
        except OSError as error:
            web_dashboard = None
            app.status = f"WEB ERROR · {error}"

    sync_web_dashboard()
    running = True
    while running:
        sync_web_dashboard()
        while True:
            try:
                key, pressed, text = web_events.get_nowait()
            except Empty:
                break
            key_map = {
                "left": pygame.K_LEFT,
                "right": pygame.K_RIGHT,
                "up": pygame.K_UP,
                "down": pygame.K_DOWN,
                "enter": pygame.K_RETURN,
                "escape": pygame.K_ESCAPE,
                "backspace": pygame.K_BACKSPACE,
            }
            if key == "text":
                pygame.event.post(
                    pygame.event.Event(pygame.KEYDOWN, key=0, unicode=text)
                )
            elif key in key_map:
                event_type = pygame.KEYDOWN if pressed else pygame.KEYUP
                pygame.event.post(
                    pygame.event.Event(event_type, key=key_map[key], unicode="")
                )
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q and not app.in_terminal:
                    running = False
                elif event.key == pygame.K_ESCAPE:
                    if app.press_escape():
                        running = False
                elif event.key == pygame.K_BACKSPACE:
                    if app.screen is Screen.UART and app.uart_tx_text and not app.uart_armed:
                        app.erase_uart_text()
                    elif app.in_terminal:
                        pass
                    elif app.screen is Screen.DASHBOARD:
                        running = False
                    else:
                        app.back()
                elif (delta := _navigation_delta(event.key, app, pygame)) is not None:
                    app.move(delta)
                elif event.key == pygame.K_RETURN or (
                    event.key == pygame.K_SPACE and app.screen is not Screen.UART
                ):
                    app.activate()
                elif app.screen is Screen.UART and event.unicode:
                    app.append_uart_text(event.unicode)
            elif event.type == pygame.KEYUP and event.key == pygame.K_ESCAPE:
                app.release_escape()
        app.update_escape_hold()
        frame = render_frame(app)
        if app.status != last_logged_status:
            append_log(f"{app.screen.value.upper()} · {app.status}")
            last_logged_status = app.status
        if app.uart_capture is not None and app.uart_capture is not last_logged_uart:
            append_log(
                f"UART TX={app.uart_capture.transmitted.hex(' ')} RX={app.uart_capture.data.hex(' ')}"
            )
            last_logged_uart = app.uart_capture
        if app.i2c_scan is not None and app.i2c_scan is not last_logged_i2c:
            addresses = " ".join(f"0x{address:02x}" for address in app.i2c_scan.addresses)
            append_log(f"I2C FOUND · {addresses or 'NONE'}")
            last_logged_i2c = app.i2c_scan
        screen.blit(frame, (0, 0))
        if framebuffer is not None:
            framebuffer.present(frame)
        if web_dashboard is not None and monotonic() >= next_web_frame_at:
            encoded = BytesIO()
            pygame.image.save(frame, encoded, "frame.png")
            web_dashboard.update_frame(encoded.getvalue())
            next_web_frame_at = monotonic() + 0.15
        pygame.display.flip()
        clock.tick(30)
    if web_dashboard is not None:
        web_dashboard.stop()
    if framebuffer is not None:
        framebuffer.close()
    local_log.append("STOP")
    pygame.quit()
    return 0
