"""Where the debugger pauses. The desktop editor's VM hook asks DebugState.decide at every
step point; web/debugger.js makes the same decisions over a recorded run, and the tests check
the two agree."""
from __future__ import annotations

import threading
from typing import Optional


class DebugState:
    """Shared between the editor (main thread) and the VM hook (worker thread)."""

    def __init__(self, mode: str, delay: float = 0.0):
        self.mode = mode           # run | step | over | animate
        self.depth = 0             # call depth that `over` stays at
        self.armed = None          # (graph, node, depth) of a breakpoint already hit on arrival
        self.delay = delay         # seconds per node when animating
        self.stop = False
        self.resume = threading.Event()

    def decide(self, graph: str, node: str, depth: int, phase: str, breakpoints,
               graph_names) -> Optional[str]:
        """What the hook does at this point: "pause", "animate" (show it without stopping) or
        None. `graph` is the function's name inside the module, `node` the VM's node id (a
        path for nodes inside macros), `phase` "enter" or "ready" (see VM.hook), `breakpoints`
        a set of (graph, node). The caller sets `depth` when it pauses."""
        top = node.split("/")[0].split("!")[0]
        if phase == "enter":
            # A breakpoint stops on arrival too, so a node whose inputs fault still pauses.
            if (graph, top) in breakpoints and "/" not in node and self.armed != (graph, top, depth):
                self.armed = (graph, top, depth)
                return "pause"
            return None
        # A macro call site is stepped once, at its entry stub (`loop!in`); nodes inside
        # macros and library code are not stepped into.
        if "/" in node or graph not in graph_names:
            return None
        if self.armed == (graph, top, depth):
            self.armed = None
            if self.mode != "step" and not (self.mode == "over" and depth <= self.depth):
                return None
        m = self.mode
        if (graph, top) in breakpoints or m == "step" or (m == "over" and depth <= self.depth):
            return "pause"
        if m == "animate" and depth == 0:
            return "animate"
        return None
