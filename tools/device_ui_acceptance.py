from pathlib import Path

import pygame

from zeroprobe.backends import SimulatedBackend
from zeroprobe.ui import AppController, Screen, render_frame
from zeroprobe.web import WebSettings

out = Path("/tmp/zeroprobe-review")
out.mkdir(exist_ok=True)


def save(name: str, app: AppController) -> None:
    frame = render_frame(app)
    assert frame.get_size() == (320, 170)
    pygame.image.save(frame, out / f"{name}.png")


app = AppController(SimulatedBackend())
assert app.selected_item.label == "Read Only"
save("dashboard-read-only", app)
app.move(1)
assert app.selected_item.label == "Read / Send"
save("dashboard-read-send", app)

app = AppController(SimulatedBackend())
app.activate()
assert app.screen is Screen.PROTOCOL
assert app.selected_item.label == "UART"
save("protocol-read-only-uart", app)
app.move(1)
assert app.selected_item.label == "I²C"
save("protocol-read-only-i2c", app)
app.move(-1)
app.activate()
app.append_uart_text("ATI")
assert app.uart_tx_text == ""
save("uart-read-only", app)

# A tap returns immediately, and a repeat before key-up must not become Back/Quit.
assert not app.press_escape(now=10.0)
assert app.screen is Screen.PROTOCOL
assert not app.press_escape(now=10.1)
assert app.screen is Screen.PROTOCOL
app.release_escape()

app = AppController(SimulatedBackend())
app.move(1)
app.activate()
assert app.screen is Screen.PROTOCOL
save("protocol-read-send-uart", app)
app.move(1)
save("protocol-read-send-i2c", app)
app.move(-1)
app.activate()
app.append_uart_text("ATI")
assert app.uart_tx_text == "ATI"
save("uart-read-send", app)
app.activate()
app.activate()
save("uart-read-send-result", app)

app = AppController(SimulatedBackend())
app.activate()
app.move(1)
app.activate()
save("i2c-read-only", app)
app.activate()
save("i2c-armed", app)
app.activate()
save("i2c-results", app)
app.move(1)
save("i2c-selected-48", app)
app.activate()
save("i2c-read-armed", app)
app.activate()
save("i2c-read-result", app)

app = AppController(SimulatedBackend())
app.move(1)
app.activate()
app.move(1)
app.activate()
save("i2c-read-send", app)

app = AppController(
    SimulatedBackend(),
    web_settings=WebSettings(False, "lo", 8765),
    web_interfaces=(("lo", "127.0.0.1"), ("wlan0", "192.168.1.42")),
)
app.move(2)
app.activate()
save("web-disabled", app)
app.move(1)
app.activate()
save("web-enabled-wlan0", app)

print("DEVICE_UI_ACCEPTANCE_OK", len(list(out.glob("*.png"))))
