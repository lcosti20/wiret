#!/usr/bin/env python3
"""Pack the prototype for the browser: writes web/wiret_bundle.zip, which index.html unpacks
into Pyodide's file system. It holds the `wiret` package without the Tkinter modules, plus the
lessons and examples.

  python3 web/build_web.py
  python3 -m http.server -d web 8000     # then open http://localhost:8000
"""
from __future__ import annotations

import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "wiret_bundle.zip")

TKINTER_MODULES = {"editor.py", "graphview.py", "palettepopup.py"}


def files():
    for folder, exts in (("wiret", (".py", ".wiret")), ("lessons", (".wiret",)),
                         ("examples", (".wiret",))):
        for dirpath, dirnames, names in os.walk(os.path.join(ROOT, folder)):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
            for name in sorted(names):
                if name.endswith(exts) and not (folder == "wiret" and dirpath.endswith("wiret")
                                                and name in TKINTER_MODULES):
                    path = os.path.join(dirpath, name)
                    yield path, os.path.relpath(path, ROOT).replace(os.sep, "/")


def main():
    count = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for path, arc in files():
            z.write(path, arc)
            count += 1
    print(f"wrote {os.path.relpath(OUT, ROOT)}: {count} files, {os.path.getsize(OUT) // 1024} KB")


if __name__ == "__main__":
    main()
