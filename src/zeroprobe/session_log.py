from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


DEFAULT_LOG_PATH = Path.home() / "zeroprobe" / "zeroprobe.log"


class PersistentLog:
    """Small private rotating log for automatic ZeroProbe events."""

    def __init__(
        self,
        path: Path = DEFAULT_LOG_PATH,
        max_bytes: int = 1_048_576,
        backups: int = 3,
    ):
        self.path = Path(path)
        self.max_bytes = max(1, int(max_bytes))
        self.backups = max(0, int(backups))
        self._lock = Lock()

    def append(self, event: str) -> bool:
        clean = str(event).replace("\r", " ").replace("\n", " ")[:4096]
        timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        line = f"{timestamp} {clean}\n".encode("utf-8", "replace")
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                self.path.parent.chmod(0o700)
                current_size = self.path.stat().st_size if self.path.exists() else 0
                if current_size + len(line) > self.max_bytes:
                    self._rotate()
                with self.path.open("ab") as output:
                    output.write(line)
                self.path.chmod(0o600)
            except OSError:
                return False
        return True

    def read(self) -> bytes:
        with self._lock:
            try:
                return self.path.read_bytes()
            except OSError:
                return b""

    def _rotate(self) -> None:
        if self.backups == 0:
            self.path.unlink(missing_ok=True)
            return
        oldest = Path(f"{self.path}.{self.backups}")
        oldest.unlink(missing_ok=True)
        for index in range(self.backups - 1, 0, -1):
            source = Path(f"{self.path}.{index}")
            if source.exists():
                source.replace(Path(f"{self.path}.{index + 1}"))
        if self.path.exists():
            self.path.replace(Path(f"{self.path}.1"))
