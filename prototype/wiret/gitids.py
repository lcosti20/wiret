"""`wiretc ids --check BASE..HEAD`: the CI check that every deleted id was retired in
`wiret.ids` and that no retired id came back (sections 2.4 and 7.3)."""
from __future__ import annotations

import os
import subprocess
from typing import Optional

from .ids import Project, ids_of, parse_registry, retired_between
from .parser import ParseError, parse


class GitError(Exception):
    pass


def git(args: list, cwd: str, ok_fail=False) -> Optional[str]:
    r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8")
    if r.returncode != 0:
        if ok_fail:
            return None
        raise GitError(r.stderr.strip() or f"git {' '.join(args)} failed")
    return r.stdout


def file_at(top: str, rev: Optional[str], rel: str) -> Optional[str]:
    """A file's text at a revision, or in the working tree when `rev` is None."""
    if rev is None:
        path = os.path.join(top, rel)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()
    return git(["show", f"{rev}:{rel}"], top, ok_fail=True)


def check_range(project: Project, spec: str, record=False, out=print) -> int:
    """Returns the exit code: 0 when every deleted id is retired and none is reused."""
    base, _, head = spec.partition("..")
    head = head or None
    top = git(["rev-parse", "--show-toplevel"], project.root).strip()
    # git reports symlink-resolved paths (macOS: /var -> /private/var), so resolve ours too
    root_rel = os.path.relpath(os.path.realpath(project.root), top).replace(os.sep, "/")
    ids_rel = "wiret.ids" if root_rel == "." else f"{root_rel}/wiret.ids"
    diff = ["diff", "--name-only", base] + ([head] if head else []) + ["--", "*.wiret"]
    files = [f for f in git(diff, top).splitlines()
             if root_rel == "." or f.startswith(root_rel + "/")]
    registry = set(parse_registry(file_at(top, head, ids_rel) or ""))
    missing, problems = [], 0
    for rel in files:
        models = []
        for rev in (base, head):
            text = file_at(top, rev, rel)
            try:
                models.append(parse(text) if text is not None else None)
            except ParseError as e:
                out(f"{rel}: error: does not parse at {rev or 'the working tree'}: {e}")
                models.append(None)
                problems += 1
        old, new = models
        for r in retired_between(old, new):
            if r not in registry:
                missing.append(r)
                if not record:
                    out(f"{rel}: error: {r.describe()} was deleted without being retired in "
                        f"wiret.ids (run with --record to add it)")
        if new is not None:
            for r in sorted(ids_of(new) & registry, key=lambda r: (r.graph, r.id)):
                problems += 1
                out(f"{rel}: error E0140: {r.describe()} is retired in wiret.ids but used again")
    if missing and record:
        written = project.retire(missing)
        out(f"recorded {len(written)} retired id(s) in {project.ids_path}")
        for r in written:
            out(f"  {r.line()}")
        missing = []
    if not missing and not problems:
        out(f"ok: {len(files)} file(s) checked")
    return 1 if missing or problems else 0
