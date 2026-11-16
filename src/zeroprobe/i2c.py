from __future__ import annotations

import errno
import fcntl
import os
from dataclasses import dataclass
from typing import Callable, Protocol


I2C_SLAVE = 0x0703
INTERNAL_I2C_ADDRESSES = frozenset({0x10, 0x32, 0x34, 0x4F, 0x55, 0x68})
NO_DEVICE_ERRORS = frozenset({errno.EIO, errno.ENXIO, getattr(errno, "EREMOTEIO", 121)})


@dataclass(frozen=True)
class I2cScan:
    device: str
    addresses: tuple[int, ...]
    skipped: tuple[int, ...]


@dataclass(frozen=True)
class I2cRead:
    device: str
    address: int
    data: bytes


class I2cBus(Protocol):
    def probe_read(self, address: int) -> bool: ...
    def read(self, address: int, length: int) -> bytes: ...
    def close(self) -> None: ...


class PosixI2cBus:
    """Read-probe Linux i2c-dev without issuing write transactions."""

    def __init__(self, device: str):
        self.fd = os.open(device, os.O_RDWR | os.O_CLOEXEC)
        self.closed = False

    def probe_read(self, address: int) -> bool:
        fcntl.ioctl(self.fd, I2C_SLAVE, address)
        try:
            os.read(self.fd, 1)
        except OSError as error:
            if error.errno in NO_DEVICE_ERRORS:
                return False
            raise
        return True

    def read(self, address: int, length: int) -> bytes:
        fcntl.ioctl(self.fd, I2C_SLAVE, address)
        return os.read(self.fd, length)

    def close(self) -> None:
        if self.closed:
            return
        os.close(self.fd)
        self.closed = True


class ScriptedI2cBus:
    def __init__(self, responding: set[int], reads: dict[int, bytes] | None = None):
        self.responding = set(responding)
        self.reads = dict(reads or {})
        self.probed: list[int] = []
        self.closed = False

    def probe_read(self, address: int) -> bool:
        self.probed.append(address)
        return address in self.responding

    def read(self, address: int, length: int) -> bytes:
        self.probed.append(address)
        if address not in self.responding:
            raise OSError(errno.ENXIO, "no device")
        return self.reads.get(address, b"\x00" * length)[:length]

    def close(self) -> None:
        self.closed = True


class I2cScanner:
    def __init__(self, bus_factory: Callable[[str], I2cBus] = PosixI2cBus):
        self.bus_factory = bus_factory

    def scan(self, device: str, include_internal: bool = False) -> I2cScan:
        skipped = () if include_internal else tuple(sorted(INTERNAL_I2C_ADDRESSES))
        bus = self.bus_factory(device)
        found: list[int] = []
        try:
            for address in range(0x08, 0x78):
                if address in skipped:
                    continue
                if bus.probe_read(address):
                    found.append(address)
        finally:
            bus.close()
        return I2cScan(device, tuple(found), skipped)


class SimulatedI2cScanner:
    def scan(self, device: str, include_internal: bool = False) -> I2cScan:
        skipped = () if include_internal else tuple(sorted(INTERNAL_I2C_ADDRESSES))
        addresses = (0x3C, 0x48)
        if include_internal:
            addresses = (0x10,) + addresses + (0x68,)
        return I2cScan(device, addresses, skipped)


class I2cInspector:
    def __init__(self, bus_factory: Callable[[str], I2cBus] = PosixI2cBus):
        self.bus_factory = bus_factory

    def read(self, device: str, address: int, length: int = 1) -> I2cRead:
        if not 0x08 <= address <= 0x77:
            raise ValueError("I2C address must be a normal 7-bit device address")
        if not 1 <= length <= 32:
            raise ValueError("I2C read length must be between 1 and 32 bytes")
        bus = self.bus_factory(device)
        try:
            data = bus.read(address, length)
        finally:
            bus.close()
        return I2cRead(device, address, data)


class SimulatedI2cInspector:
    VALUES = {0x3C: b"\x00", 0x48: b"\x19"}

    def read(self, device: str, address: int, length: int = 1) -> I2cRead:
        value = self.VALUES.get(address, b"\x00")
        return I2cRead(device, address, (value * length)[:length])


def format_i2c_scan(scan: I2cScan) -> str:
    addresses = " ".join(f"0x{address:02x}" for address in scan.addresses) or "none"
    skipped = " ".join(f"0x{address:02x}" for address in scan.skipped) or "none"
    return (
        f"device={scan.device} found={len(scan.addresses)} "
        f"internal_skipped={len(scan.skipped)}\n"
        f"addresses: {addresses}\n"
        f"skipped: {skipped}\n"
    )
