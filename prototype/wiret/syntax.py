"""Syntax highlighting for .wiret text: which spans of a line are keywords, strings,
attributes, comments, numbers or node kinds. The desktop editor colours its Source pane with
these rules, and the web page gets the same rules from webapi.syntax (web/syntax.js applies
them as you type)."""
from __future__ import annotations

import re

from .parser import KEYWORDS
from .registry import STATIC_KINDS

# One match per token, applied to one line at a time.
TOKEN = (r'"(?:[^"\\]|\\.)*"|//.*$|@[A-Za-z_.]+|#\[[A-Za-z_.]+|\]$|'
         r'\b[A-Za-z_]\w*\b|-?\b\d[\w.]*')
_TOKEN_RE = re.compile(TOKEN)

# Node kinds that are not in the registry's static kinds, but are coloured as kinds too.
OTHER_KINDS = ("Entry", "Return", "Call", "Macro", "Exit", "Leave", "Sequence", "Switch", "Reroute",
               "GetLocal", "SetLocal", "GetVar", "SetVar", "GetState", "SetState")
KINDS = frozenset(STATIC_KINDS) | frozenset(OTHER_KINDS)

# The desktop Source pane's colours (One Dark), by tag.
COLORS = {"kw": "#c678dd", "str": "#98c379", "attr": "#e5c07b", "comment": "#7f848e",
          "num": "#d19a66", "kind": "#61afef"}
TAGS = tuple(COLORS)


def tag_of(token: str) -> str | None:
    """The tag for one token TOKEN matched, or None to leave it plain."""
    if token.startswith('"'):
        return "str"
    if token.startswith("//"):
        return "comment"
    if token.startswith(("@", "#[")) or token == "]":
        return "attr"
    if token[0].isdigit() or token[0] == "-":
        return "num"
    if token in KEYWORDS:
        return "kw"
    if token in KINDS:
        return "kind"
    return None


def is_name(line: str, start: int, end: int) -> bool:
    """A keyword next to `.`, right before `(`, or before a single `:` is a name there (a
    symbol, pin, field or node; section 2.1). No keyword is ever written in those places."""
    before, after = line[:start].rstrip(), line[end:]
    return (before.endswith(".") or after.startswith((".", "("))
            or (after.lstrip().startswith(":") and not after.lstrip().startswith("::")))


def spans(line: str) -> list:
    """(start, end, tag) for each coloured token in one line."""
    out = []
    for m in _TOKEN_RE.finditer(line):
        tag = tag_of(m.group(0))
        if tag == "kw" and is_name(line, m.start(), m.end()):
            tag = None
        if tag:
            out.append((m.start(), m.end(), tag))
    return out


def rules() -> dict:
    """Everything a highlighter in another language needs: the token pattern, the word lists
    and the colours."""
    return {"pattern": TOKEN, "keywords": sorted(KEYWORDS), "kinds": sorted(KINDS),
            "colors": COLORS}
