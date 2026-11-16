from __future__ import annotations

import shutil
import subprocess
from typing import Callable, Optional

from .backends import GpiomonBackend, SimulatedBackend


class BackendUnavailable(RuntimeError):
    pass


def _version_runner(command: list[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return (result.stdout or result.stderr).strip()


def select_backend(
    requested: str,
    *,
    which: Callable[[str], Optional[str]] = shutil.which,
    version_runner: Callable[[list[str]], str] = _version_runner,
):
    requested = requested.lower()
    if requested in {"sim", "simulator"}:
        return SimulatedBackend()
    if requested not in {"auto", "gpio"}:
        raise ValueError(f"unknown backend {requested!r}")
    tools_present = which("gpiomon") is not None and which("gpioget") is not None
    if not tools_present:
        if requested == "auto":
            return SimulatedBackend()
        raise BackendUnavailable("gpiomon and gpioget are required for the GPIO backend")
    version = version_runner(["gpiomon", "--version"])
    return GpiomonBackend(version=version)
