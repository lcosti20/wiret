#!/usr/bin/env python3
"""Pack the prototype for the browser: writes web/wiret_bundle.zip, which index.html unpacks
into Pyodide's file system. It holds the `wiret` package without the Tkinter modules, plus the
lessons and examples.

  python3 web/build_web.py
  python3 -m http.server -d web 8000     # then open http://localhost:8000

With --site DIR it instead writes the whole static site to DIR: the page, its scripts and
the bundle, and nothing else from web/. The GitHub Pages workflow publishes that folder.

  python3 web/build_web.py --site _site
"""
from __future__ import annotations

import argparse
import os
import shutil
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUNDLE = "wiret_bundle.zip"

TKINTER_MODULES = {"editor.py", "graphview.py", "palettepopup.py"}
SITE_FILES = ["index.html", "debugger.js", "graphview.js", "syntax.js"]   # served as they are


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


def write_bundle(out: str) -> None:
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path, arc in files():
            z.write(path, arc)
            count += 1
    print(f"wrote {os.path.relpath(out)}: {count} files, {os.path.getsize(out) // 1024} KB")


def write_site(site: str) -> None:
    os.makedirs(site, exist_ok=True)
    for name in SITE_FILES:
        shutil.copyfile(os.path.join(HERE, name), os.path.join(site, name))
    write_bundle(os.path.join(site, BUNDLE))
    print(f"site in {os.path.relpath(site)}: {', '.join(sorted(os.listdir(site)))}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--site", metavar="DIR", help="write the whole static site to DIR")
    a = ap.parse_args(argv)
    if a.site:
        write_site(a.site)
    else:
        write_bundle(os.path.join(HERE, BUNDLE))


if __name__ == "__main__":
    main()
