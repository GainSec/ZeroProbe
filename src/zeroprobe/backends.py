from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Callable, Tuple

from .capture import Capture, Sample


class SimulatedBackend:
    name = "simulator"

    def capture(
        self, gpios: Tuple[int, ...], duration_ms: int = 1000, sample_period_us: int = 1000
    ) -> Capture:
        if duration_ms < 0 or sample_period_us <= 0:
            raise ValueError("duration and sample period must be positive")
        end_ns = duration_ms * 1_000_000
        step_ns = sample_period_us * 1000
        samples = []
        timestamp = 0
        while timestamp <= end_ns:
            tick = timestamp // step_ns
            values = {
                gpio: int(((tick + index) // (index + 2)) % 2)
                for index, gpio in enumerate(gpios)
            }
            samples.append(Sample(timestamp, values))
            timestamp += step_ns
        return Capture(tuple(gpios), tuple(samples))


def _major_version(version: str) -> int:
    match = re.search(r"(?:^|\s)v?(\d+)(?:\.\d+)", version)
    return int(match.group(1)) if match else 1


def build_gpiomon_command(
    version: str, chip: str, gpios: Tuple[int, ...], num_events: int
) -> list[str]:
    if not gpios:
        raise ValueError("at least one GPIO is required")
    major = _major_version(version)
    if major >= 2:
        return [
            "stdbuf", "-oL", "gpiomon", "--edges", "both", "--num-events", str(num_events),
            "--format", "%o %E %S", "--chip", chip, *(str(gpio) for gpio in gpios),
        ]
    return [
        "gpiomon", "--line-buffered", "--num-events", str(num_events),
        "--format", "%o %e %s.%n", chip, *(str(gpio) for gpio in gpios),
    ]


def build_gpioget_command(version: str, chip: str, gpios: Tuple[int, ...]) -> list[str]:
    if not gpios:
        raise ValueError("at least one GPIO is required")
    major = _major_version(version)
    if major >= 2:
        return [
            "gpioget", "--numeric", "--chip", chip,
            *(str(gpio) for gpio in gpios),
        ]
    return ["gpioget", chip, *(str(gpio) for gpio in gpios)]


def _run_level_command(command: list[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return result.stdout


def _run_monitor_command(command: list[str], duration_seconds: float) -> str:
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout = ""
    try:
        stdout, stderr = process.communicate(timeout=duration_seconds)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=0.5)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
    if process.returncode not in (0, -15) and not stdout:
        raise RuntimeError(f"gpiomon failed ({process.returncode}): {stderr.strip()}")
    return stdout


def _parse_levels(output: str, gpios: Tuple[int, ...]) -> dict[int, int]:
    normalized = output.replace("=active", "=1").replace("=inactive", "=0")
    values = [int(value) for value in re.findall(r"(?<!\d)([01])(?!\d)", normalized)]
    if len(values) != len(gpios):
        raise RuntimeError(f"gpioget returned {len(values)} values for {len(gpios)} GPIOs")
    return dict(zip(gpios, values))


class GpiomonBackend:
    """Read-only edge capture using libgpiod command-line tools."""

    name = "gpiomon"

    def __init__(
        self,
        version: str,
        chip: str = "/dev/gpiochip0",
        level_runner: Callable[[list[str]], str] = _run_level_command,
        monitor_runner: Callable[[list[str], float], str] = _run_monitor_command,
    ):
        self.version = version
        self.chip = chip
        self.level_runner = level_runner
        self.monitor_runner = monitor_runner

    def capture(
        self,
        gpios: Tuple[int, ...],
        duration_ms: int = 1000,
        sample_period_us: int = 1000,
        max_events: int = 10000,
    ) -> Capture:
        del sample_period_us  # Edge capture is event-driven, not periodically sampled.
        if duration_ms <= 0 or max_events <= 0:
            raise ValueError("duration and max_events must be positive")
        levels = _parse_levels(
            self.level_runner(build_gpioget_command(self.version, self.chip, gpios)), gpios
        )
        output = self.monitor_runner(
            build_gpiomon_command(self.version, self.chip, gpios, max_events),
            duration_ms / 1000.0,
        )
        samples = [Sample(0, dict(levels))]
        first_event_ns = None
        for line in output.splitlines():
            if not line.strip():
                continue
            gpio, value, timestamp_ns = parse_gpiomon_line(line)
            if gpio not in levels:
                raise RuntimeError(f"gpiomon reported unexpected GPIO{gpio}")
            if first_event_ns is None:
                first_event_ns = timestamp_ns
            relative_ns = max(1, timestamp_ns - first_event_ns)
            levels[gpio] = value
            samples.append(Sample(relative_ns, dict(levels)))
        return Capture(tuple(gpios), tuple(samples))


def parse_gpiomon_line(line: str) -> tuple[int, int, int]:
    fields = line.strip().split()
    if len(fields) != 3:
        raise ValueError(f"unexpected gpiomon event: {line!r}")
    gpio = int(fields[0])
    edge = fields[1].lower()
    edge_values = {"rising": 1, "falling": 0, "1": 1, "2": 0, "0": 0}
    if edge not in edge_values:
        raise ValueError(f"unknown edge {edge!r}")
    seconds, _, fraction = fields[2].partition(".")
    timestamp_ns = int(seconds) * 1_000_000_000 + int((fraction + "000000000")[:9])
    return gpio, edge_values[edge], timestamp_ns
