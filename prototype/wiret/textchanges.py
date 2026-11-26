"""Where a graph edit changed the source text, so the Source pane can flash it.

`changes(old, new)` compares the text before and after an edit and returns the lines of `new`
that changed and, on those lines, the columns that changed. Both editors use it: the desktop
editor tags those ranges, and the web page draws strips under them (webapi.changes).
"""
from __future__ import annotations

from difflib import SequenceMatcher

MERGE_GAP = 2   # changed runs on a line this close together are shown as one, so a renamed
                # word does not break up around the letters the old and new names share


def changes(old: str, new: str) -> dict:
    """{"lines": [line, ...], "spans": [[line, start, end], ...]} for the text `new`, with
    1-based lines and 0-based, end-exclusive columns, both in order."""
    a, b = old.split("\n"), new.split("\n")
    lines: set = set()
    spans: list = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        if op == "delete":                  # lines went away: mark where they were
            at = min(j1, len(b) - 1)
            if at >= 0 and b[at].strip():
                lines.add(at + 1)
            elif at > 0:
                lines.add(at)
            continue
        if op == "insert":                  # whole new lines: everything but the indent
            for j in range(j1, j2):
                text = b[j]
                if text.strip():
                    start = len(text) - len(text.lstrip())
                    spans.append([j + 1, start, len(text.rstrip())])
                    lines.add(j + 1)
            continue
        found = _block_spans(a[i1:i2], b[j1:j2], j1)
        spans.extend(found)
        lines.update(s[0] for s in found)
        if not found:                       # only characters were removed
            lines.add(j1 + 1)
    return {"lines": sorted(lines), "spans": _merged([_whole_words(b[s[0] - 1], *s)
                                                      for s in spans])}


def _word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _whole_words(text: str, line: int, start: int, end: int) -> list:
    """Widen a span to the words it touches, so 200 -> 220 shows 220 and not just the 2."""
    while start > 0 and _word(text[start - 1]) and _word(text[start]):
        start -= 1
    while end < len(text) and _word(text[end]) and _word(text[end - 1]):
        end += 1
    return [line, start, end]


def _block_spans(old_lines: list, new_lines: list, first: int) -> list:
    """The changed columns of the replaced lines `new_lines` (the first is line first + 1)."""
    a, b = "\n".join(old_lines), "\n".join(new_lines)
    starts = [0]
    for text in new_lines:
        starts.append(starts[-1] + len(text) + 1)
    out = []
    for op, _i1, _i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal" or j1 == j2:
            continue
        for k, text in enumerate(new_lines):    # cut the run at line ends
            lo, hi = max(j1, starts[k]), min(j2, starts[k] + len(text))
            if lo < hi and b[lo:hi].strip():
                out.append([first + k + 1, lo - starts[k], hi - starts[k]])
    return out


def _merged(spans: list) -> list:
    out: list = []
    for line, start, end in sorted(spans):
        if out and out[-1][0] == line and start - out[-1][2] <= MERGE_GAP:
            out[-1][2] = max(out[-1][2], end)
        else:
            out.append([line, start, end])
    return out
