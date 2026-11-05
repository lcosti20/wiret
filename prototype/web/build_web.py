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
import hashlib
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


def write_bundle(out: str, build: str = "dev") -> None:
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path, arc in files():
            z.write(path, arc)
            count += 1
        z.writestr("BUILD", build + "\n")       # the page checks it got the bundle of its build
    print(f"wrote {os.path.relpath(out)}: {count} files, {os.path.getsize(out) // 1024} KB")


def build_id() -> str:
    """A short id that changes whenever anything the site serves changes."""
    h = hashlib.sha256()
    for path, arc in sorted(files(), key=lambda x: x[1]):
        h.update(arc.encode() + b"\0")
        with open(path, "rb") as f:
            h.update(f.read() + b"\0")
    for name in SITE_FILES:
        with open(os.path.join(HERE, name), "rb") as f:
            h.update(name.encode() + b"\0" + f.read() + b"\0")
    return h.hexdigest()[:12]


def stamp(page: str, build: str) -> str:
    """The page with its build id, and that id in the URLs of its scripts and bundle. GitHub
    Pages lets browsers cache every file for 10 minutes, and a reload fetches the page again
    but not its scripts; versioned URLs keep a new page from running with old ones."""
    swaps = [('const BUILD = "dev";', f'const BUILD = "{build}";'),
             (f'fetch("{BUNDLE}")', f'fetch("{BUNDLE}?v={build}")')]
    swaps += [(f'from "./{name}"', f'from "./{name}?v={build}"')
              for name in SITE_FILES if name.endswith(".js")]
    for old, new in swaps:
        if page.count(old) != 1:
            raise SystemExit(f"index.html: expected exactly one {old!r} to stamp")
        page = page.replace(old, new)
    return page


def write_site(site: str) -> None:
    os.makedirs(site, exist_ok=True)
    build = build_id()
    for name in SITE_FILES:
        if name == "index.html":
            with open(os.path.join(HERE, name), encoding="utf-8") as f:
                page = stamp(f.read(), build)
            with open(os.path.join(site, name), "w", encoding="utf-8", newline="\n") as f:
                f.write(page)
        else:
            shutil.copyfile(os.path.join(HERE, name), os.path.join(site, name))
    write_bundle(os.path.join(site, BUNDLE), build)
    print(f"site in {os.path.relpath(site)} (build {build}): {', '.join(sorted(os.listdir(site)))}")


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
