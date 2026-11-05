#!/usr/bin/env python3
"""wiretc: the Wiret command-line toolchain (spec section 7), prototype subset.

  wiretc check [--json] FILE           diagnostics (with E0140/W0202 inside a project)
  wiretc fmt [--check] [--assign-ids] [--convert-comments | --drop-comments] FILE
  wiretc build FILE [-o OUT.wbc] [--no-source]
  wiretc dis FILE.wbc                  disassemble with node ids
  wiretc verify FILE.wbc               run only the verifier
  wiretc run FILE.wiret|FILE.wbc FUNC [ARGS...]
  wiretc hash FILE                     semantic and layout hashes
  wiretc view --flow FILE              reading view in flow order
  wiretc schema --json                 the node registry
  wiretc edit FILE REQUEST.json|- [--dry-run]
                                       apply JSON edit operations (section 7.2)
  wiretc ids --check BASE[..HEAD] [--record] [--project DIR]
                                       every deleted id retired in wiret.ids, none reused
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wiret.checker import check, has_errors  # noqa: E402
from wiret.compiler import compile_module  # noqa: E402
from wiret.disasm import disassemble  # noqa: E402
from wiret.flow import view_flow  # noqa: E402
from wiret.ids import assign_ids, find_project  # noqa: E402
from wiret.ops import convert_comments  # noqa: E402
from wiret.parser import ParseError, parse  # noqa: E402
from wiret.printer import layout_hash, print_module, semantic_hash  # noqa: E402
from wiret.registry import registry_json  # noqa: E402
from wiret.runner import parse_args_for, format_results  # noqa: E402
from wiret.vm import VM, WiretError  # noqa: E402


def load(path):
    text = open(path, encoding="utf-8").read()
    try:
        return parse(text), text
    except ParseError as e:
        print(f"{path}:{e.line}:{e.col}: error: {e.msg}", file=sys.stderr)
        sys.exit(2)


def build(path, out=None, embed=True):
    m, text = load(path)
    r = compile_module(m, text, embed)
    for d in r.diags:
        print(d, file=sys.stderr)
    if not r.ok:
        sys.exit(1)
    out = out or os.path.splitext(path)[0] + ".wbc"
    with open(out, "wb") as f:
        f.write(r.wbc)
    return m, out, r.wbc


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wiretc", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check")
    p.add_argument("file")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("fmt")
    p.add_argument("file")
    p.add_argument("--check", action="store_true")
    p.add_argument("--assign-ids", action="store_true",
                   help="give an @id to every element that has none (section 2.4)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--convert-comments", action="store_true")
    g.add_argument("--drop-comments", action="store_true")
    p = sub.add_parser("build")
    p.add_argument("file")
    p.add_argument("-o", "--output")
    p.add_argument("--no-source", action="store_true")
    p = sub.add_parser("dis")
    p.add_argument("file")
    p = sub.add_parser("verify")
    p.add_argument("file")
    p = sub.add_parser("run")
    p.add_argument("file")
    p.add_argument("func")
    p.add_argument("args", nargs="*")
    p.add_argument("--fuel", type=int, default=50_000_000)
    p = sub.add_parser("hash")
    p.add_argument("file")
    p = sub.add_parser("view")
    p.add_argument("--flow", action="store_true", required=True)
    p.add_argument("file")
    p = sub.add_parser("schema")
    p.add_argument("--json", action="store_true", required=True)
    p = sub.add_parser("edit")
    p.add_argument("file")
    p.add_argument("request", help="a JSON request file, or - for standard input")
    p.add_argument("--dry-run", action="store_true", help="reply, but do not write the file")
    p = sub.add_parser("ids")
    p.add_argument("--check", metavar="BASE[..HEAD]", required=True,
                   help="compare two revisions; without ..HEAD, BASE and the working tree")
    p.add_argument("--record", action="store_true",
                   help="append ids deleted without being retired to wiret.ids")
    p.add_argument("--project", default=".", help="a directory inside the project")
    a = ap.parse_args(argv)

    if a.cmd == "check":
        m, _ = load(a.file)
        diags = check(m, project=find_project(a.file))
        for d in diags:
            print(d.to_json() if a.json else d)
        return 1 if has_errors(diags) else 0
    if a.cmd == "fmt":
        m, text = load(a.file)
        if m.comments:
            if a.convert_comments:
                for msg in convert_comments(m):
                    print(f"warning W0603: {msg}", file=sys.stderr)
            elif a.drop_comments:
                m.comments = []
            else:
                for c in m.comments:
                    print(f"{a.file}:{c.line}: warning W0603: formatting would drop this comment; "
                          f"use --convert-comments or --drop-comments", file=sys.stderr)
                return 1
        if a.assign_ids:
            proj = find_project(a.file)
            retired = {r.id for r in proj.retired} if proj else set()
            for e in assign_ids(m, retired=retired):
                print(f"{e.kind} '{e.name}': @id(\"{e.id}\")", file=sys.stderr)
        out = print_module(m)
        if a.check:
            if out != text:
                print(f"{a.file} is not in canonical form", file=sys.stderr)
                return 1
            return 0
        if out != text:
            with open(a.file, "w", encoding="utf-8", newline="\n") as f:
                f.write(out)
        return 0
    if a.cmd == "edit":
        from wiret.edit import apply_request
        if a.request == "-":
            req_text = sys.stdin.read()
        else:
            with open(a.request, encoding="utf-8") as f:
                req_text = f.read()
        try:
            request = json.loads(req_text)
        except json.JSONDecodeError as e:
            print(json.dumps({"ok": False, "error": {"code": "request",
                                                     "message": f"not JSON: {e}"}}))
            return 2
        with open(a.file, encoding="utf-8") as f:
            text = f.read()
        r = apply_request(text, request, None if a.dry_run else find_project(a.file))
        if r.ok and not a.dry_run and r.text != text:
            with open(a.file, "w", encoding="utf-8", newline="\n") as f:
                f.write(r.text)
        print(json.dumps(r.to_json(), indent=2))
        return 0 if r.ok else 1
    if a.cmd == "ids":
        from wiret.gitids import GitError, check_range
        proj = find_project(os.path.join(a.project, "x.wiret"))
        if proj is None:
            print(f"no wiret.toml in {os.path.abspath(a.project)} or above it; wiret.ids "
                  f"belongs to a project (section 7.3)", file=sys.stderr)
            return 2
        try:
            return check_range(proj, a.check, a.record)
        except GitError as e:
            print(f"git: {e}", file=sys.stderr)
            return 2
    if a.cmd == "build":
        _, out, data = build(a.file, a.output, not a.no_source)
        print(f"wrote {out} ({len(data)} bytes)")
        return 0
    if a.cmd == "dis":
        print(disassemble(open(a.file, "rb").read()), end="")
        return 0
    if a.cmd == "verify":
        try:
            VM().load(open(a.file, "rb").read())
        except WiretError as e:
            print(e, file=sys.stderr)
            return 1
        print("ok")
        return 0
    if a.cmd == "run":
        if a.file.endswith(".wbc"):
            data, m = open(a.file, "rb").read(), None
        else:
            m, _, data = build(a.file)
        vm = VM(fuel=a.fuel)
        try:
            lm = vm.load(data)
            args = parse_args_for(m, a.func, a.args) if m else [int(x) for x in a.args]
            res = vm.call(lm, a.func, args)
        except (WiretError, ValueError) as e:
            print(e, file=sys.stderr)
            return 1
        print(format_results(m, a.func, res))
        return 0
    if a.cmd == "hash":
        m, _ = load(a.file)
        print(f"semantic {semantic_hash(m)}")
        print(f"layout   {layout_hash(m)}")
        return 0
    if a.cmd == "view":
        m, _ = load(a.file)
        print(view_flow(m), end="")
        return 0
    if a.cmd == "schema":
        print(json.dumps(registry_json(), indent=2))
        return 0


if __name__ == "__main__":
    sys.exit(main())
