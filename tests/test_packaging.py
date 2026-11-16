import tempfile
import re
import unittest
from pathlib import Path

from tools.build_deb import stage_package


class PackagingTests(unittest.TestCase):
    def test_python_and_project_versions_match(self):
        root = Path(__file__).resolve().parents[1]
        project_text = (root / "pyproject.toml").read_text()
        project_version = re.search(r'^version = "([^"]+)"$', project_text, re.MULTILINE).group(1)
        package_text = (root / "src/zeroprobe/__init__.py").read_text()
        package_version = re.search(r'^__version__ = "([^"]+)"$', package_text, re.MULTILINE).group(1)
        self.assertEqual(package_version, project_version)

    def test_stage_contains_launcher_metadata_and_python_application(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory) / "root"
            stage_package(root, stage)
            control = (stage / "DEBIAN/control").read_text()
            self.assertIn("Package: zeroprobe", control)
            self.assertIn("Version: 0.5.6-1", control)
            self.assertIn("UART transmit/receive", control)
            self.assertIn("Architecture: arm64", control)
            self.assertIn("Depends: python3", control)
            desktop = (stage / "usr/share/APPLaunch/applications/zeroprobe.desktop").read_text()
            self.assertIn("Exec=/usr/share/ZeroProbe/bin/zeroprobe", desktop)
            self.assertIn("Terminal=false", desktop)
            wrapper = stage / "usr/share/ZeroProbe/bin/zeroprobe"
            self.assertTrue(wrapper.stat().st_mode & 0o111)
            postinst = stage / "DEBIAN/postinst"
            self.assertTrue(postinst.stat().st_mode & 0o111)
            self.assertIn("python3 -m compileall", postinst.read_text())
            self.assertTrue(
                (stage / "usr/share/ZeroProbe/zeroprobe/assets/gainsec-header.png").is_file()
            )
            self.assertIn("python3 -m zeroprobe gui --backend auto", wrapper.read_text())
            cli = stage / "usr/bin/zeroprobe"
            self.assertTrue(cli.stat().st_mode & 0o111)
            self.assertIn('python3 -m zeroprobe "$@"', cli.read_text())
            self.assertTrue((stage / "usr/share/ZeroProbe/zeroprobe/ui.py").is_file())
            self.assertTrue((stage / "usr/share/ZeroProbe/zeroprobe/uart.py").is_file())
            self.assertTrue(
                (stage / "usr/share/doc/zeroprobe/packaging/debian/assets/zeroprobe.png").is_file()
            )
            self.assertTrue(
                (stage / "usr/share/doc/zeroprobe/screenshots/dashboard.png").is_file()
            )
            self.assertFalse((stage / "etc/sudoers.d").exists())


if __name__ == "__main__":
    unittest.main()
