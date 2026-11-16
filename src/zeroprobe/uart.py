from __future__ import annotations

import os
import re
import select
import termios
import time
from dataclasses import dataclass
from typing import Callable, Optional, Protocol


STANDARD_BAUDS = (1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400)


@dataclass(frozen=True)
class UartCapture:
    device: str
    baud: int
    duration_ms: int
    data: bytes
    framing_errors: int = 0
    breaks: int = 0
    truncated: bool = False
    transmitted: bytes = b""


class ParmrkDecoder:
    """Decode POSIX PARMRK sequences while retaining split markers."""

    def __init__(self) -> None:
        self.pending = b""
        self.framing_errors = 0
        self.breaks = 0

    def feed(self, chunk: bytes, final: bool = False) -> bytes:
        source = self.pending + chunk
        self.pending = b""
        output = bytearray()
        index = 0
        while index < len(source):
            if source[index] != 0xFF:
                output.append(source[index])
                index += 1
                continue
            remaining = len(source) - index
            if remaining < 2 or (remaining < 3 and source[index + 1] == 0x00):
                if final:
                    output.extend(source[index:])
                else:
                    self.pending = source[index:]
                break
            marker = source[index + 1]
            if marker == 0xFF:
                output.append(0xFF)
                index += 2
                continue
            if marker == 0x00:
                value = source[index + 2]
                if value == 0x00:
                    self.breaks += 1
                else:
                    self.framing_errors += 1
                    output.append(value)
                index += 3
                continue
            output.append(0xFF)
            index += 1
        return bytes(output)


class UartReader(Protocol):
    def read(self, size: int, timeout: float) -> bytes: ...
    def close(self) -> None: ...


class PosixUartReader:
    """Receive-only POSIX UART configured for 8N1 with PARMRK errors."""

    def __init__(self, device: str, baud: int):
        speed_name = f"B{baud}"
        if baud not in STANDARD_BAUDS or not hasattr(termios, speed_name):
            raise ValueError(f"unsupported UART baud {baud}")
        self.fd = os.open(device, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        self.original = termios.tcgetattr(self.fd)
        attributes = termios.tcgetattr(self.fd)
        attributes[0] &= ~(
            termios.IGNBRK
            | termios.BRKINT
            | termios.IGNPAR
            | termios.ISTRIP
            | termios.INLCR
            | termios.IGNCR
            | termios.ICRNL
            | termios.IXON
        )
        attributes[0] |= termios.INPCK | termios.PARMRK
        attributes[1] = 0
        attributes[2] &= ~(termios.PARENB | termios.CSTOPB | termios.CSIZE)
        if hasattr(termios, "CRTSCTS"):
            attributes[2] &= ~termios.CRTSCTS
        attributes[2] |= termios.CS8 | termios.CREAD | termios.CLOCAL
        attributes[3] = 0
        attributes[4] = getattr(termios, speed_name)
        attributes[5] = getattr(termios, speed_name)
        attributes[6][termios.VMIN] = 0
        attributes[6][termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSANOW, attributes)
        termios.tcflush(self.fd, termios.TCIFLUSH)
        self.closed = False

    def read(self, size: int, timeout: float) -> bytes:
        ready, _, _ = select.select([self.fd], [], [], max(0.0, timeout))
        return os.read(self.fd, size) if ready else b""

    def close(self) -> None:
        if self.closed:
            return
        try:
            termios.tcsetattr(self.fd, termios.TCSANOW, self.original)
        finally:
            os.close(self.fd)
            self.closed = True


class ScriptedUartReader:
    """Deterministic receive-only reader used by unit tests."""

    def __init__(self, chunks: list[bytes]):
        self.chunks = list(chunks)
        self.opened_read_only = True
        self.closed = False

    @property
    def exhausted(self) -> bool:
        return not self.chunks

    def read(self, size: int, timeout: float) -> bytes:
        del size, timeout
        return self.chunks.pop(0) if self.chunks else b""

    def close(self) -> None:
        self.closed = True


class UartPort(UartReader, Protocol):
    def write(self, data: bytes) -> int: ...


class PosixUartPort(PosixUartReader):
    """Explicitly armed read/write UART for GPIO14 TX and GPIO15 RX."""

    def __init__(self, device: str, baud: int):
        speed_name = f"B{baud}"
        if baud not in STANDARD_BAUDS or not hasattr(termios, speed_name):
            raise ValueError(f"unsupported UART baud {baud}")
        self.fd = os.open(device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        self.original = termios.tcgetattr(self.fd)
        attributes = termios.tcgetattr(self.fd)
        attributes[0] &= ~(
            termios.IGNBRK | termios.BRKINT | termios.IGNPAR | termios.ISTRIP
            | termios.INLCR | termios.IGNCR | termios.ICRNL | termios.IXON
        )
        attributes[0] |= termios.INPCK | termios.PARMRK
        attributes[1] = 0
        attributes[2] &= ~(termios.PARENB | termios.CSTOPB | termios.CSIZE)
        if hasattr(termios, "CRTSCTS"):
            attributes[2] &= ~termios.CRTSCTS
        attributes[2] |= termios.CS8 | termios.CREAD | termios.CLOCAL
        attributes[3] = 0
        attributes[4] = getattr(termios, speed_name)
        attributes[5] = getattr(termios, speed_name)
        attributes[6][termios.VMIN] = 0
        attributes[6][termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSANOW, attributes)
        termios.tcflush(self.fd, termios.TCIOFLUSH)
        self.closed = False

    def write(self, data: bytes) -> int:
        total = 0
        while total < len(data):
            _, ready, _ = select.select([], [self.fd], [], 1.0)
            if not ready:
                raise TimeoutError("UART transmit timed out")
            total += os.write(self.fd, data[total:])
        termios.tcdrain(self.fd)
        return total


class ScriptedUartPort(ScriptedUartReader):
    def __init__(self, chunks: list[bytes]):
        super().__init__(chunks)
        self.opened_read_only = False
        self.opened_read_write = True
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.writes.append(bytes(data))
        return len(data)


class UartMonitor:
    def __init__(self, reader_factory: Callable[[str, int], UartReader] = PosixUartReader):
        self.reader_factory = reader_factory

    def capture(
        self,
        device: str,
        baud: int,
        duration_ms: int = 2000,
        max_bytes: int = 65536,
    ) -> UartCapture:
        if duration_ms <= 0 or max_bytes <= 0:
            raise ValueError("duration and max_bytes must be positive")
        reader = self.reader_factory(device, baud)
        decoder = ParmrkDecoder()
        output = bytearray()
        deadline = time.monotonic() + duration_ms / 1000.0
        truncated = False
        try:
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                chunk = reader.read(min(4096, max_bytes - len(output)), min(0.05, remaining))
                if chunk:
                    output.extend(decoder.feed(chunk))
                    if len(output) >= max_bytes:
                        truncated = True
                        break
                elif getattr(reader, "exhausted", False):
                    break
            output.extend(decoder.feed(b"", final=True))
        finally:
            reader.close()
        return UartCapture(
            device=device,
            baud=baud,
            duration_ms=duration_ms,
            data=bytes(output[:max_bytes]),
            framing_errors=decoder.framing_errors,
            breaks=decoder.breaks,
            truncated=truncated,
        )


class SimulatedUartMonitor:
    def capture(
        self,
        device: str,
        baud: int,
        duration_ms: int = 2000,
        max_bytes: int = 65536,
    ) -> UartCapture:
        data = b"ZeroProbe UART RX ready\r\nlogin: "[:max_bytes]
        return UartCapture(device, baud, duration_ms, data, truncated=len(data) >= max_bytes)


class UartTerminal:
    MAX_TX_BYTES = 4096

    def __init__(self, port_factory: Callable[[str, int], UartPort] = PosixUartPort):
        self.port_factory = port_factory

    def capture(
        self, device: str, baud: int, duration_ms: int = 2000, max_bytes: int = 65536
    ) -> UartCapture:
        return UartMonitor().capture(device, baud, duration_ms, max_bytes)

    def exchange(
        self,
        device: str,
        baud: int,
        transmit: bytes,
        duration_ms: int = 2000,
        max_bytes: int = 65536,
    ) -> UartCapture:
        if not transmit:
            raise ValueError("transmit payload must not be empty")
        if len(transmit) > self.MAX_TX_BYTES:
            raise ValueError(f"transmit payload exceeds {self.MAX_TX_BYTES} bytes")
        if duration_ms <= 0 or max_bytes <= 0:
            raise ValueError("duration and max_bytes must be positive")
        port = self.port_factory(device, baud)
        decoder = ParmrkDecoder()
        output = bytearray()
        truncated = False
        try:
            written = port.write(transmit)
            if written != len(transmit):
                raise IOError(f"short UART write: {written}/{len(transmit)}")
            deadline = time.monotonic() + duration_ms / 1000.0
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                chunk = port.read(min(4096, max_bytes - len(output)), min(0.05, remaining))
                if chunk:
                    output.extend(decoder.feed(chunk))
                    if len(output) >= max_bytes:
                        truncated = True
                        break
                elif getattr(port, "exhausted", False):
                    break
            output.extend(decoder.feed(b"", final=True))
        finally:
            port.close()
        return UartCapture(
            device=device,
            baud=baud,
            duration_ms=duration_ms,
            data=bytes(output[:max_bytes]),
            framing_errors=decoder.framing_errors,
            breaks=decoder.breaks,
            truncated=truncated,
            transmitted=bytes(transmit),
        )


class SimulatedUartTerminal:
    def capture(
        self, device: str, baud: int, duration_ms: int = 2000, max_bytes: int = 65536
    ) -> UartCapture:
        return SimulatedUartMonitor().capture(device, baud, duration_ms, max_bytes)

    def exchange(
        self,
        device: str,
        baud: int,
        transmit: bytes,
        duration_ms: int = 2000,
        max_bytes: int = 65536,
    ) -> UartCapture:
        if not transmit:
            raise ValueError("transmit payload must not be empty")
        if len(transmit) > UartTerminal.MAX_TX_BYTES:
            raise ValueError(f"transmit payload exceeds {UartTerminal.MAX_TX_BYTES} bytes")
        response = b"SIM RX: OK\r\n"[:max_bytes]
        return UartCapture(
            device, baud, duration_ms, response,
            truncated=len(response) >= max_bytes, transmitted=bytes(transmit),
        )


def parse_hex_bytes(value: str) -> bytes:
    compact = re.sub(r"[\s:_-]", "", value)
    if len(compact) % 2:
        raise ValueError("hex payload must contain an even number of digits")
    try:
        return bytes.fromhex(compact)
    except ValueError as error:
        raise ValueError("hex payload contains a non-hex digit") from error


def format_uart_capture(capture: UartCapture) -> str:
    hex_text = " ".join(f"{value:02x}" for value in capture.data)
    ascii_text = "".join(chr(value) if value in (9, 10, 13) or 32 <= value < 127 else "." for value in capture.data)
    return (
        f"device={capture.device} baud={capture.baud} bytes={len(capture.data)} "
        f"framing_errors={capture.framing_errors} breaks={capture.breaks} "
        f"truncated={str(capture.truncated).lower()} tx_bytes={len(capture.transmitted)}\n"
        f"tx_hex: {' '.join(f'{value:02x}' for value in capture.transmitted)}\n"
        f"hex: {hex_text}\n"
        f"ascii:\n{ascii_text}\n"
    )
