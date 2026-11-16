from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict

from .capture import Capture


_IDS = tuple(chr(code) for code in range(33, 127))


def encode_vcd(capture: Capture, source: str = "zeroprobe") -> str:
    if len(capture.gpios) > len(_IDS):
        raise ValueError("too many channels for the VCD encoder")
    ids = {gpio: _IDS[index] for index, gpio in enumerate(capture.gpios)}
    lines = [
        "$date",
        f"  {datetime.now(timezone.utc).isoformat()}",
        "$end",
        f"$comment ZeroProbe source={source} $end",
        "$version ZeroProbe 0.1 $end",
        "$timescale 1 ns $end",
        "$scope module zeroprobe $end",
    ]
    for gpio in capture.gpios:
        lines.append(f"$var wire 1 {ids[gpio]} GPIO{gpio} $end")
    lines.extend(("$upscope $end", "$enddefinitions $end"))

    previous: Dict[int, int] = {}
    last_timestamp = -1
    for sample in capture.samples:
        if sample.timestamp_ns < last_timestamp:
            raise ValueError("sample timestamps must be monotonic")
        missing = [gpio for gpio in capture.gpios if gpio not in sample.values]
        if missing:
            raise ValueError(f"sample is missing GPIO{missing[0]}")
        changes = []
        for gpio in capture.gpios:
            value = sample.values[gpio]
            if value not in (0, 1):
                raise ValueError(f"GPIO{gpio} has non-digital value {value!r}")
            if previous.get(gpio) != value:
                changes.append(f"{value}{ids[gpio]}")
                previous[gpio] = value
        if changes:
            lines.append(f"#{sample.timestamp_ns}")
            lines.extend(changes)
        last_timestamp = sample.timestamp_ns
    return "\n".join(lines) + "\n"
