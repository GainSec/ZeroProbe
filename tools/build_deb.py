#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

VERSION = "0.5.6"
PACKAGE = "zeroprobe"


def _write(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def stage_package(root: Path, stage: Path) -> None:
    root = root.resolve()
    stage = stage.resolve()
    if stage == root or root in stage.parents and stage.name in {"src", "tests", "tools"}:
        raise ValueError("refusing unsafe package staging path")
    if stage.exists():
        shutil.rmtree(stage)
    app_root = stage / "usr/share/ZeroProbe"
    package_root = app_root / "zeroprobe"
    package_root.mkdir(parents=True)
    for source in sorted((root / "src/zeroprobe").glob("*.py")):
        shutil.copy2(source, package_root / source.name)
    assets = root / "src/zeroprobe/assets"
    if assets.is_dir():
        shutil.copytree(assets, package_root / "assets")
    wrapper = """#!/bin/sh
set -eu
export PYTHONPATH=/usr/share/ZeroProbe
export PYGAME_HIDE_SUPPORT_PROMPT=1
exec python3 -m zeroprobe gui --backend auto "$@"
"""
    _write(app_root / "bin/zeroprobe", wrapper, 0o755)
    cli_wrapper = """#!/bin/sh
set -eu
export PYTHONPATH=/usr/share/ZeroProbe
export PYGAME_HIDE_SUPPORT_PROMPT=1
exec python3 -m zeroprobe "$@"
"""
    _write(stage / "usr/bin/zeroprobe", cli_wrapper, 0o755)
    desktop = """[Desktop Entry]
Name=ZeroProbe
Comment=Safe GPIO interface explorer
Exec=/usr/share/ZeroProbe/bin/zeroprobe
Terminal=false
Icon=share/images/zeroprobe.png
Type=Application
"""
    _write(stage / "usr/share/APPLaunch/applications/zeroprobe.desktop", desktop)
    icon_target = stage / "usr/share/APPLaunch/share/images/zeroprobe.png"
    icon_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "packaging/debian/assets/zeroprobe.png", icon_target)
    readme = root / "README.md"
    doc_root = stage / f"usr/share/doc/{PACKAGE}"
    if readme.exists():
        doc = doc_root / "README.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(readme, doc)
        readme_icon = root / "packaging/debian/assets/zeroprobe.png"
        if readme_icon.is_file():
            icon_doc = doc_root / "packaging/debian/assets/zeroprobe.png"
            icon_doc.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(readme_icon, icon_doc)
        screenshots = root / "screenshots"
        if screenshots.is_dir():
            shutil.copytree(screenshots, doc_root / "screenshots")
    license_file = root / "LICENSE"
    if license_file.exists():
        doc_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(license_file, doc_root / "LICENSE")
    installed_bytes = sum(p.stat().st_size for p in (stage / "usr").rglob("*") if p.is_file())
    installed_kib = max(1, (installed_bytes + 1023) // 1024)
    control = f"""Package: {PACKAGE}
Version: {VERSION}-1
Section: utils
Priority: optional
Architecture: arm64
Maintainer: GainSec <gainsec@users.noreply.github.com>
Depends: python3 (>= 3.11), python3-pygame, gpiod
Installed-Size: {installed_kib}
Description: Safe interface explorer for M5Stack CardputerZero
 Read-only GPIO edge capture, explicitly armed UART transmit/receive, guarded
 external I2C scanning, optional interface-bound web control, decoded terminal
 output, waveform display, and VCD export.
"""
    _write(stage / "DEBIAN/control", control)
    postinst = """#!/bin/sh
set -e
python3 -m compileall -q /usr/share/ZeroProbe || true
exit 0
"""
    _write(stage / "DEBIAN/postinst", postinst, 0o755)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--stage", type=Path, default=Path("build/deb-root"))
    parser.add_argument("--output", type=Path, default=Path(f"dist/{PACKAGE}_{VERSION}-1_arm64.deb"))
    parser.add_argument("--stage-only", action="store_true")
    args = parser.parse_args()
    stage_package(args.root, args.stage)
    if args.stage_only:
        print(args.stage)
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["dpkg-deb", "--build", "--root-owner-group", str(args.stage), str(args.output)], check=True)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
