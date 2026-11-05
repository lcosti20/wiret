// Steps through a run recorded by wiret.webapi.debug_run, pausing where the desktop debugger
// (DebugState and the VM hook in wiret/editor.py) would pause. It has no DOM code, so Node can
// test it.
//
// A recording is a list of steps. An "enter" step is a node being reached, before its inputs
// are worked out; a "ready" step is the same node with its inputs known, about to run.
//   step     pauses at the next ready step
//   over     pauses at the next ready step at the same call depth or shallower
//   run      pauses only at breakpoints
//   animate  like run, but also shows each ready step at depth 0 without pausing
// A breakpoint pauses on the enter step (so a node whose inputs fault still stops), and the
// node's own ready step after it is then skipped unless stepping.

export const nodeKey = (s) => `${s.graph}\t${s.node}`;

export class Session {
  /** trace: the parsed debug_run result; breakpoints: a Set of nodeKey strings. */
  constructor(trace, breakpoints) {
    this.trace = trace;
    this.breakpoints = breakpoints;
    this.pos = -1;          // index of the step shown; steps.length once the run is over
    this.armed = null;      // the breakpoint already stopped at on its enter step
    this.depth = 0;         // call depth of the last pause, which `over` stays at
    this.history = [];     // [pos, armed, depth] before each move, for back()
  }

  get steps() { return this.trace.steps; }
  get current() { return this.steps[this.pos] ?? null; }
  get finished() { return this.pos >= this.steps.length; }

  /** Move on in `mode`. Returns {pos, paused, breakpoint} or null when the run is over. */
  advance(mode) {
    const steps = this.steps;
    this.history.push([this.pos, this.armed, this.depth]);
    for (let j = this.pos + 1; j < steps.length; j++) {
      const s = steps[j];
      const at = `${nodeKey(s)}\t${s.depth}`;
      const bp = this.breakpoints.has(nodeKey(s));
      if (s.phase === "enter") {
        if (bp && this.armed !== at) {
          this.armed = at;
          return this.#pause(j, true);
        }
        continue;
      }
      if (this.armed === at) {
        this.armed = null;
        if (mode !== "step" && !(mode === "over" && s.depth <= this.depth)) continue;
      }
      if (bp || mode === "step" || (mode === "over" && s.depth <= this.depth)) {
        return this.#pause(j, bp);
      }
      if (mode === "animate" && s.depth === 0) {
        this.pos = j;
        return { pos: j, paused: false, breakpoint: false };
      }
    }
    this.pos = steps.length;
    return null;
  }

  /** Go back to where the last advance() started. Returns false at the start. */
  back() {
    const h = this.history.pop();
    if (!h || h[0] < 0) {
      if (h) this.history.push(h);
      return false;
    }
    [this.pos, this.armed, this.depth] = h;
    return true;
  }

  #pause(j, breakpoint) {
    this.pos = j;
    this.depth = this.steps[j].depth;
    return { pos: j, paused: true, breakpoint };
  }
}
