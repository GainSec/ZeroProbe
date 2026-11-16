import tempfile
import unittest
from pathlib import Path

from zeroprobe.session_log import PersistentLog


class PersistentLogTests(unittest.TestCase):
    def test_append_creates_private_default_log_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "zeroprobe" / "zeroprobe.log"
            log = PersistentLog(path)
            log.append("DASHBOARD · READY")

            self.assertTrue(path.is_file())
            self.assertEqual(0o700, path.parent.stat().st_mode & 0o777)
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            self.assertIn("DASHBOARD · READY".encode(), log.read())

    def test_append_rotates_bounded_log(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "zeroprobe.log"
            log = PersistentLog(path, max_bytes=80, backups=2)
            for index in range(10):
                log.append(f"EVENT {index} " + "X" * 30)

            self.assertLessEqual(path.stat().st_size, 80)
            self.assertTrue(path.with_suffix(".log.1").is_file())
            self.assertFalse(path.with_suffix(".log.3").exists())

    def test_append_failure_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as directory:
            blocker = Path(directory) / "not-a-directory"
            blocker.write_text("blocked")
            log = PersistentLog(blocker / "zeroprobe.log")

            self.assertFalse(log.append("EVENT"))

    def test_read_failure_returns_empty_log(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "directory-instead-of-log"
            path.mkdir()

            self.assertEqual(b"", PersistentLog(path).read())


if __name__ == "__main__":
    unittest.main()
