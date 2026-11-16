from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Tuple


@dataclass(frozen=True)
class Sample:
    timestamp_ns: int
    values: Mapping[int, int]


@dataclass(frozen=True)
class Capture:
    gpios: Tuple[int, ...]
    samples: Tuple[Sample, ...]
