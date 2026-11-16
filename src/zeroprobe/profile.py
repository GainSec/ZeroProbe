from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple


class UnsafePinUse(ValueError):
    """Raised when a request would seize a board-shared signal."""


@dataclass(frozen=True)
class Pin:
    gpio: int
    aliases: Tuple[str, ...] = ()
    shared_with: Optional[str] = None


@dataclass(frozen=True)
class ResolvedCapture:
    gpios: Tuple[int, ...]
    allow_shared: bool = False


@dataclass(frozen=True)
class CaptureRequest:
    tokens: Tuple[str, ...]
    allow_shared: bool = False

    @classmethod
    def from_csv(cls, value: str, allow_shared: bool = False) -> "CaptureRequest":
        tokens = tuple(token.strip().upper() for token in value.split(",") if token.strip())
        if not tokens:
            raise ValueError("at least one GPIO is required")
        return cls(tokens, allow_shared)

    def resolve(self, profile: "BoardProfile") -> ResolvedCapture:
        gpios = []
        for token in self.tokens:
            normalized = token[4:] if token.startswith("GPIO") else token
            if normalized.isdigit() and int(normalized) in profile.pins:
                gpio = int(normalized)
            else:
                gpio = profile.aliases.get(token)
            if gpio is None:
                raise ValueError(f"GPIO token {token!r} is not exposed on {profile.name}")
            if gpio not in gpios:
                gpios.append(gpio)
        return ResolvedCapture(tuple(gpios), self.allow_shared)


@dataclass(frozen=True)
class BoardProfile:
    name: str
    logic_level: str
    pins: Dict[int, Pin]

    @property
    def aliases(self) -> Dict[str, int]:
        aliases: Dict[str, int] = {}
        for pin in self.pins.values():
            aliases[f"GPIO{pin.gpio}"] = pin.gpio
            aliases[str(pin.gpio)] = pin.gpio
            for alias in pin.aliases:
                aliases[alias.upper()] = pin.gpio
        return aliases

    def validate_capture(self, request: CaptureRequest) -> ResolvedCapture:
        resolved = request.resolve(self)
        if not resolved.allow_shared:
            for gpio in resolved.gpios:
                shared = self.pins[gpio].shared_with
                if shared:
                    raise UnsafePinUse(
                        f"GPIO{gpio} is shared with {shared}; repeat with allow_shared only after isolating the conflict"
                    )
        return resolved


def _pin(gpio: int, *aliases: str, shared_with: Optional[str] = None) -> Pin:
    return Pin(gpio, tuple(aliases), shared_with)


CARDPUTER_ZERO = BoardProfile(
    name="CardputerZero",
    logic_level="3.3V",
    pins={
        2: _pin(2, "I2C_SDA", shared_with="I2C1/keyboard"),
        3: _pin(3, "I2C_SCL", shared_with="I2C1/keyboard"),
        7: _pin(7, "SPI_CS1"),
        9: _pin(9, "SPI_MISO", shared_with="SPI0/display"),
        10: _pin(10, "SPI_MOSI", shared_with="SPI0/display"),
        11: _pin(11, "SPI_CLK", shared_with="SPI0/display"),
        14: _pin(14, "UART_TX", shared_with="Grove/UART"),
        15: _pin(15, "UART_RX", shared_with="Grove/UART"),
        22: _pin(22, "GPIO_FREE"),
        23: _pin(23, "HAT_P1", shared_with="USB4 D-/GPIO mux"),
        26: _pin(26, "HAT_P0", shared_with="USB4 D+/GPIO mux"),
    },
)
