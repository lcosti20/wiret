#!/usr/bin/env python3
"""Build a double-clickable Wiret editor for the current OS.

    python build.py            build dist/Wiret (Windows/Linux) or dist/Wiret.app (macOS)
    python build.py --zip      ...and pack it as dist/Wiret-<os>.zip for sharing
    python build.py --no-test  skip the test suite

PyInstaller cannot cross-compile: build the Windows version on Windows and the
macOS version on a Mac. Installs PyInstaller into the current Python if it is missing.
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "dist")


def run(*cmd):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=HERE, check=True)


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        run(sys.executable, "-m", "pip", "install", "pyinstaller")


def os_tag() -> str:
    return {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "linux")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", action="store_true", help="also create dist/Wiret-<os>.zip")
    ap.add_argument("--no-test", action="store_true", help="skip the unit tests")
    args = ap.parse_args()

    if not args.no_test:
        run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q")
    ensure_pyinstaller()
    run(sys.executable, "-m", "PyInstaller", "wiret.spec", "--noconfirm", "--clean")

    target = os.path.join(DIST, "Wiret.app" if os_tag() == "macos" else "Wiret")
    if not os.path.exists(target):
        sys.exit(f"build finished but {target} is missing")
    print(f"\nBuilt {target}")
    if args.zip:
        base = os.path.join(DIST, f"Wiret-{os_tag()}")
        if os_tag() == "macos":     # ditto keeps the .app's symlinks and permissions
            run("ditto", "-c", "-k", "--keepParent", target, base + ".zip")
        else:
            shutil.make_archive(base, "zip", DIST, "Wiret")
        print(f"Packed {base}.zip")


if __name__ == "__main__":
    main()
