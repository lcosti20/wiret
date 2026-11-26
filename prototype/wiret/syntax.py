"""Syntax highlighting for .wiret text: which spans of a line are keywords, strings,
attributes, comments, numbers or node kinds. The desktop editor colours its Source pane with
these rules, and the web page gets the same rules from webapi.syntax (web/syntax.js applies
them as you type)."""
from __future__ import annotations

import re

from .parser import KEYWORDS
from .registry import STATIC_KINDS

# One match per token, applied to one line at a time. `@name` is a decorator and `#count`
# a node's named generic, both coloured as attributes (section 2.4).
TOKEN = (r'"(?:[^"\\]|\\.)*"|//.*$|@[A-Za-z_.]+|#[A-Za-z_]+|'
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
    if token.startswith(("@", "#")):
        return "attr"
    if token[0].isdigit() or token[0] == "-":
        return "num"
    if token in KEYWORDS:
        return "kw"
    if token in KINDS:
        return "kind"
    return None


# Keywords that start a statement inside a body; anywhere else on the line they are names
# (`exec box`, `goto node`). A `!` may stand before `exec`.
_LEAD = re.compile(r"^\s*!?\s*$")


def is_name(line: str, start: int, end: int) -> bool:
    """Keywords are contextual (section 2.1): a keyword is one only where a statement starts,
    first on its line (after a `!`, for `exec`) and not followed by `.`, `(` or a single `:`.
    `extern func`, `extern type` and `class X impl` are the keywords that follow another."""
    before, after = line[:start], line[end:]
    word = line[start:end]
    rest = after.lstrip()
    if after.startswith((".", "(")) or (rest.startswith(":") and not rest.startswith("::")) \
            or rest.startswith("="):
        return True
    if _LEAD.match(before):
        return False
    prev = before.split()
    return not ((prev and prev[-1] == "extern" and word in ("func", "type"))
                or (word == "impl" and prev and prev[0] == "class"))


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


def block_end(lines: list, line: int) -> int:
    """The last line (1-based) of the node written on `line`: where its parenthesised input
    block closes. Parentheses inside its {…} attributes, strings and comments do not count.
    The web page's blockEnd does the same, so both editors mark the same lines."""
    depth = braces = 0
    for i in range(line - 1, len(lines)):
        s = lines[i]
        j = 0
        while j < len(s):
            c = s[j]
            if c == "/" and s[j + 1:j + 2] == "/":
                break
            if c == '"':
                j += 1
                while j < len(s) and s[j] != '"':
                    j += 2 if s[j] == "\\" else 1
            elif c == "{":
                braces += 1
            elif c == "}":
                braces -= 1
            elif braces == 0 and c == "(":
                depth += 1
            elif braces == 0 and c == ")":
                depth -= 1
                if depth == 0:
                    return i + 1
            j += 1
        if depth <= 0:
            return line                     # no input block opened on the node's line
    return line


def rules() -> dict:
    """Everything a highlighter in another language needs: the token pattern, the word lists
    and the colours."""
    return {"pattern": TOKEN, "keywords": sorted(KEYWORDS), "kinds": sorted(KINDS),
            "colors": COLORS}
