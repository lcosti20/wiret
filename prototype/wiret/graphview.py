"""The graph canvas of the editor: draws one graph and turns mouse input into edits."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass, field

from .checker import GraphInfo
from .model import Graph, Lit, PinRef
from .printer import fmt_lit
from .registry import FLOAT_TYPES, INT_TYPES

BG = "#1d1f23"
GRID = "#25282e"
NODE_BG = "#2b2e35"
NODE_EDGE = "#111214"
TEXT = "#e8e8e8"
DIM = "#8a8f98"
SELECT = "#f5b041"
ERROR = "#e74c3c"
WARN = "#f39c12"
RAN = "#2ecc71"
CURRENT = "#00e5ff"
BREAK = "#ff3b30"

HEADER_COLORS = {"Arrays": "#b9770e", "Flow": "#566573", "Call": "#2471a3", "Math": "#1e8449", "Compare": "#138d75",
                 "Logic": "#9a7d0a", "Bits": "#873600", "Variables": "#6c3483", "Macro": "#7d3c98",
                 "Other": "#566573"}


def type_color(ty: str) -> str:
    if ty == "exec":
        return "#ffffff"
    if ty == "bool":
        return "#e74c3c"
    if ty in ("i64", "u64"):
        return "#48c9b0"
    if ty in INT_TYPES:
        return "#1abc9c"
    if ty in FLOAT_TYPES:
        return "#a3d65c"
    if ty == "string":
        return "#e056fd"
    if ty.startswith("array<"):
        return "#f0a830"        # arrays: orange, whatever they hold
    return "#95a5a6"


HEADER = 24
ROW = 20


@dataclass
class Geom:
    x: float
    y: float
    w: float
    h: float
    pins: dict = field(default_factory=dict)   # (dir, name) -> (x, y, type)


def node_title(n) -> str:
    t = n.kind
    if n.symbol:
        t += " " + n.symbol.split(".")[-1] if n.kind == "Call" and n.symbol.startswith("std.") \
            else " " + n.symbol
    if n.targs:
        t += "<" + ", ".join(n.targs) + ">"
    return t


class GraphView(tk.Canvas):
    def __init__(self, master, app):
        super().__init__(master, bg=BG, highlightthickness=0)
        self.app = app
        self.scale = 1.0
        self.ox, self.oy = 80.0, 320.0
        self.geoms: dict[str, Geom] = {}
        self.selected = None
        self.drag = None
        self.run_counts: dict = {}
        self.fault_node = None
        self.current_node = None     # the node the debugger is paused before
        self.pin_values: dict = {}   # (node, output pin) -> value at the pause
        self._fonts = {}
        self.bind("<ButtonPress-1>", self.on_press)
        self.bind("<B1-Motion>", self.on_motion)
        self.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Double-Button-1>", self.on_double)
        for seq in ("<Button-2>", "<Button-3>", "<Control-Button-1>"):
            self.bind(seq, self.on_context)
        self.bind("<MouseWheel>", self.on_wheel)
        self.bind("<Button-4>", lambda e: self.zoom_at(e.x, e.y, 1.1))
        self.bind("<Button-5>", lambda e: self.zoom_at(e.x, e.y, 1 / 1.1))
        self.bind("<Motion>", self.on_hover)
        self.auto_fit = False   # re-fit on resize until the user pans or zooms
        self.bind("<Configure>", self.on_configure)
        self.last_mouse = (200, 200)
        self.bind("<Tab>", self.on_tab)
        for key in ("<Delete>", "<BackSpace>"):
            self.bind(key, lambda e: self.delete_selection())

    # -- coordinates --------------------------------------------------------------
    def to_screen(self, x, y):
        return x * self.scale + self.ox, y * self.scale + self.oy

    def to_world(self, sx, sy):
        return (sx - self.ox) / self.scale, (sy - self.oy) / self.scale

    def font(self, size, bold=False):
        px = max(5, int(round(size * self.scale)))
        key = (px, bold)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(family="Helvetica", size=px,
                                           weight="bold" if bold else "normal")
        return self._fonts[key]

    def on_configure(self, _e=None):
        if self.auto_fit:
            self.fit(keep_auto=True)
        else:
            self.redraw()

    def zoom_at(self, sx, sy, factor):
        self.auto_fit = False
        new = min(2.5, max(0.25, self.scale * factor))
        wx, wy = self.to_world(sx, sy)
        self.scale = new
        self.ox = sx - wx * new
        self.oy = sy - wy * new
        self.redraw()

    def fit(self, keep_auto=False):
        self.auto_fit = keep_auto
        g = self.app.graph
        if g is None:
            return
        self.redraw()
        if not self.geoms:
            return
        xs = [gm.x for gm in self.geoms.values()] + [gm.x + gm.w for gm in self.geoms.values()]
        ys = [gm.y for gm in self.geoms.values()] + [gm.y + gm.h for gm in self.geoms.values()]
        for b in g.boxes:
            xs += [b.x, b.x + b.w]
            ys += [b.y, b.y + b.h]
        w, h = max(self.winfo_width(), 200), max(self.winfo_height(), 200)
        notes = self.bbox("graphnote")          # graph-level notes sit at the top left
        top = notes[3] + 10 if notes else 0
        bw, bh = max(xs) - min(xs) + 260, max(ys) - min(ys) + 200
        self.scale = max(0.3, min(1.3, w / bw, (h - top) / bh))
        self.ox = (w - (max(xs) + min(xs)) * self.scale) / 2
        self.oy = top + (h - top - (max(ys) + min(ys)) * self.scale) / 2 + 20
        self.redraw()

    # -- geometry -----------------------------------------------------------------
    def input_label(self, n, pin) -> str:
        if pin.is_exec:
            return "" if pin.name == "in" else pin.name
        b = n.binding(pin.name)
        if b is not None and isinstance(b.value, Lit):
            text = fmt_lit(b.value)
            if len(text) > 22:
                text = text[:20] + "…\""
            return f"{pin.name} = {text}"
        if b is None and pin.default is not None and n.kind != "Exit":
            return f"{pin.name} ({fmt_lit(pin.default_lit())})"
        return pin.name

    def compute_geoms(self, g: Graph, info: GraphInfo, positions: dict):
        f_title = self.font(11, True)
        f_pin = self.font(10)
        s = self.scale
        self.geoms = {}
        for n in g.nodes:
            sig = info.sigs.get(n.id)
            if sig is None or n.id in self.geoms:
                continue
            x, y = positions.get(n.id, (0, 0))
            ins = sig.exec_ins + sig.data_ins
            outs = sig.exec_outs + sig.data_outs
            place = g.place(n.id)
            label = place.prop("label") if place else None
            title = label.value if label is not None and label.kind == "string" else node_title(n)
            in_w = max([f_pin.measure(self.input_label(n, p)) for p in ins] or [0]) / s
            out_w = max([f_pin.measure("" if p.is_exec and len(sig.exec_outs) == 1 else p.name)
                         for p in outs] or [0]) / s
            w = max(f_title.measure(title) / s + 28, in_w + out_w + 46, 96)
            rows = max(len(ins), len(outs), 1 if not sig.pure else 0)
            h = HEADER + ROW * rows + 6
            gm = Geom(x, y, w, h)
            for i, p in enumerate(ins):
                gm.pins[("in", p.name)] = (x, y + HEADER + ROW * (i + 0.5) + 3, p.type)
            for i, p in enumerate(outs):
                gm.pins[("out", p.name)] = (x + w, y + HEADER + ROW * (i + 0.5) + 3, p.type)
            gm.title = title
            self.geoms[n.id] = gm

    # -- drawing ------------------------------------------------------------------
    def redraw(self):
        self.delete("all")
        g = self.app.graph
        if g is None:
            self.create_text(20, 20, anchor="nw", fill=DIM, text="No graph", font=self.font(12))
            return
        info = self.app.info
        positions = self.app.positions()
        self.compute_geoms(g, info, positions)
        self.draw_grid()
        for b in sorted(g.boxes, key=lambda b: b.id):
            self.draw_box(b)
        self.draw_wires(g, info)
        diag_nodes = self.app.diag_nodes()
        for n in sorted(g.nodes, key=lambda n: n.id):
            if n.id in self.geoms:
                self.draw_node(n, info, diag_nodes.get(n.id))
        self.draw_notes(g)
        if self.pin_values:
            self.draw_values(g, info)
        if self.drag and self.drag[0] == "wire":
            _, nid, d, pin, sx, sy, cx, cy = self.drag
            self.draw_curve(sx, sy, cx, cy, SELECT, 2, d == "in", tags=("temp",))

    def draw_grid(self):
        w, h = self.winfo_width(), self.winfo_height()
        step = 40 * self.scale
        if step < 12:
            return
        x0 = self.ox % step
        y0 = self.oy % step
        x = x0
        while x < w:
            self.create_line(x, 0, x, h, fill=GRID)
            x += step
        y = y0
        while y < h:
            self.create_line(0, y, w, y, fill=GRID)
            y += step

    def draw_box(self, b):
        x0, y0 = self.to_screen(b.x, b.y)
        x1, y1 = self.to_screen(b.x + b.w, b.y + b.h)
        c = b.prop("color")
        color = c.value if c is not None and c.kind == "string" else "#7f8c8d"
        sel = self.selected == ("box", b.id)
        self.create_rectangle(x0, y0, x1, y1, outline=SELECT if sel else color, width=2,
                              fill="#23262c", tags=("box", f"b={b.id}"))
        th = 22 * self.scale
        self.create_rectangle(x0, y0, x1, y0 + th, outline="", fill=color,
                              tags=("boxtitle", f"b={b.id}"))
        self.create_text(x0 + 8 * self.scale, y0 + th / 2, anchor="w", fill="white",
                         text=b.title, font=self.font(11, True), tags=("boxtitle", f"b={b.id}"))

    def draw_curve(self, x0, y0, x1, y1, color, width, reverse=False, tags=(), dash=None):
        if reverse:
            x0, y0, x1, y1 = x1, y1, x0, y0
        dx = max(40 * self.scale, abs(x1 - x0) / 2)
        pts = [x0, y0, x0 + dx, y0, x1 - dx, y1, x1, y1]
        return self.create_line(*pts, smooth=True, splinesteps=24, fill=color, width=width,
                                tags=tags, dash=dash)

    def pin_screen(self, nid, d, name):
        gm = self.geoms.get(nid)
        if gm is None or (d, name) not in gm.pins:
            return None
        x, y, _ = gm.pins[(d, name)]
        return self.to_screen(x, y)

    def draw_wires(self, g, info):
        w = max(1.5, 2.5 * self.scale)
        for n in g.nodes:
            if n.id not in self.geoms:
                continue
            for b in n.bindings:
                if not isinstance(b.value, PinRef):
                    continue
                dst = self.pin_screen(n.id, "in", b.pin)
                src = self.pin_screen(b.value.node, "out", b.value.pin)
                key = ("wire", "d", n.id, b.pin)
                if dst is None:
                    continue
                if src is None:   # dangling wire: keep it visible as an error (section 7.5)
                    self.draw_curve(dst[0] - 60 * self.scale, dst[1] - 20 * self.scale, dst[0],
                                    dst[1], ERROR, w, tags=("wire", "w=d|%s|%s" % (n.id, b.pin)),
                                    dash=(4, 3))
                    self.create_text(dst[0] - 62 * self.scale, dst[1] - 20 * self.scale,
                                     anchor="e", fill=ERROR, font=self.font(9),
                                     text=f"? {b.value.node}.{b.value.pin}")
                    continue
                ty = info.sigs[n.id].input(b.pin)
                color = SELECT if self.selected == key else type_color(ty.type if ty else "")
                self.draw_curve(*src, *dst, color, w, tags=("wire", "w=d|%s|%s" % (n.id, b.pin)))
            for e in n.execs:
                out = info.exec_pin(n, e)
                src = self.pin_screen(n.id, "out", out) if out else None
                dst = self.pin_screen(e.target, "in", e.target_pin or "in")
                if src is None:
                    continue
                key = ("wire", "e", n.id, out)
                tag = ("wire", "w=e|%s|%s" % (n.id, out))
                if dst is None:
                    self.draw_curve(src[0], src[1], src[0] + 60 * self.scale, src[1] - 20 * self.scale,
                                    ERROR, w, tags=tag, dash=(4, 3))
                    self.create_text(src[0] + 62 * self.scale, src[1] - 20 * self.scale, anchor="w",
                                     fill=ERROR, font=self.font(9), text=f"? {e.target}")
                    continue
                color = SELECT if self.selected == key else "#f0f0f0"
                self.draw_curve(*src, *dst, color, w + 1, tags=tag)

    def draw_node(self, n, info, diag):
        gm = self.geoms[n.id]
        sig = info.sigs[n.id]
        s = self.scale
        x0, y0 = self.to_screen(gm.x, gm.y)
        x1, y1 = self.to_screen(gm.x + gm.w, gm.y + gm.h)
        tag = ("node", f"n={n.id}")
        outline, width = NODE_EDGE, 1
        if diag == "error":
            outline, width = ERROR, 3
        elif diag == "warning":
            outline, width = WARN, 2
        if n.id in self.run_counts:
            outline, width = RAN, 3
        if self.fault_node == n.id:
            outline, width = ERROR, 4
        if self.selected == ("node", n.id):
            outline, width = SELECT, 3
        current = self.current_node == n.id
        if current:
            outline, width = CURRENT, 4
            pad = 6 * s
            self.create_rectangle(x0 - pad, y0 - pad, x1 + pad, y1 + pad, outline=CURRENT,
                                  width=1, dash=(3, 3), tags=tag)
            self.create_text(x0 - pad, y1 + pad + 2 * s, anchor="nw", text="▶ runs next",
                             fill=CURRENT, font=self.font(10, True), tags=tag)
        disabled = n.attr("disabled") is not None
        self.create_rectangle(x0 + 3, y0 + 4, x1 + 3, y1 + 4, fill="#101114", outline="", tags=tag)
        self.create_rectangle(x0, y0, x1, y1, fill=NODE_BG, outline=outline, width=width, tags=tag)
        cat = "Flow" if n.kind in ("Entry", "Return") else sig.category
        hcolor = "#a93226" if n.kind in ("Entry", "Return") else HEADER_COLORS.get(cat, "#566573")
        place = self.app.graph.place(n.id)
        c = place.prop("color") if place else None
        if c is not None and c.kind == "string":
            hcolor = c.value
        if disabled:
            hcolor = "#4d4d4d"
        self.create_rectangle(x0 + width / 2, y0 + width / 2, x1 - width / 2, y0 + HEADER * s,
                              fill=hcolor, outline="", tags=tag)
        self.create_text(x0 + 8 * s, y0 + HEADER * s / 2, anchor="w", text=gm.title, fill="white",
                         font=self.font(11, True), tags=tag)
        id_text = n.id + ("  (disabled)" if disabled else "") + ("  pure" if sig.pure else "")
        self.create_text(x0 + 2, y0 - 3 * s, anchor="sw", text=id_text, fill=DIM,
                         font=self.font(9), tags=tag)
        if n.id in self.run_counts:
            self.create_text(x1, y0 - 3 * s, anchor="se", text=f"×{self.run_counts[n.id]}",
                             fill=RAN, font=self.font(9, True), tags=tag)
        r = 5 * s
        fpin = self.font(10)
        connected_in = {b.pin for b in n.bindings if isinstance(b.value, PinRef)}
        exec_targets = self.app.exec_targets()
        out_used = self.app.used_outputs()
        for (d, name), (px, py, ty) in gm.pins.items():
            sx, sy = self.to_screen(px, py)
            ptag = ("pin", f"p={n.id}|{d}|{name}")
            col = type_color(ty)
            if d == "in":
                filled = name in connected_in or (ty == "exec" and (n.id, name) in exec_targets)
            else:
                filled = (n.id, name) in out_used
            if ty == "exec":
                pts = [sx - r, sy - r * 1.2, sx + r, sy, sx - r, sy + r * 1.2]
                self.create_polygon(*pts, fill=col if filled else NODE_BG, outline=col, width=1.5,
                                    tags=ptag)
            else:
                self.create_oval(sx - r, sy - r, sx + r, sy + r, fill=col if filled else NODE_BG,
                                 outline=col, width=1.5, tags=ptag)
            self.create_rectangle(sx - 3 * r, sy - 2 * r, sx + 3 * r, sy + 2 * r, outline="",
                                  fill="", tags=ptag)
            if d == "in":
                pin = sig.input(name)
                label = self.input_label(n, pin) if pin else name
                b = n.binding(name)
                fill = TEXT if b is not None else DIM
                self.create_text(sx + 2.2 * r, sy, anchor="w", text=label, fill=fill, font=fpin,
                                 tags=tag)
            else:
                label = "" if (name == "then" and ty == "exec" and len(sig.exec_outs) == 1) else name
                self.create_text(sx - 2.2 * r, sy, anchor="e", text=label, fill=TEXT, font=fpin,
                                 tags=tag)
        if (self.app.graph_name, n.id) in self.app.breakpoints:
            self.create_oval(x0 - 7 * s, y0 - 7 * s, x0 + 7 * s, y0 + 7 * s, fill=BREAK,
                             outline="white", width=1, tags=tag)
        if diag:
            self.create_oval(x1 - 9 * s, y0 - 7 * s, x1 + 7 * s, y0 + 9 * s,
                             fill=ERROR if diag == "error" else WARN, outline="", tags=tag)
            self.create_text(x1 - 1 * s, y0 + 1 * s, text="!", fill="white",
                             font=self.font(10, True), tags=tag)

    def draw_values(self, g, info):
        """Label each data wire with the value it carried at the debugger's pause."""
        from .runner import format_value
        f = self.font(10, True)
        drawn = set()
        for n in g.nodes:
            for b in n.bindings:
                if not isinstance(b.value, PinRef):
                    continue
                key = (b.value.node, b.value.pin)
                if key not in self.pin_values:
                    continue
                src = self.pin_screen(b.value.node, "out", b.value.pin)
                dst = self.pin_screen(n.id, "in", b.pin)
                sig = info.sigs.get(b.value.node)
                pin = sig.output(b.value.pin) if sig else None
                if src is None or dst is None or pin is None:
                    continue
                text = format_value(pin.type, self.pin_values[key])
                if len(text) > 24:
                    text = text[:22] + "…"
                # one label per source pin, near the source, plus one near each consumer
                spots = [(dst[0] - 30 * self.scale, dst[1])]
                if key not in drawn:
                    drawn.add(key)
                    spots.append((src[0] + 30 * self.scale, src[1]))
                for x, y in spots:
                    t = self.create_text(x, y, text=text, fill="#111", font=f, anchor="center")
                    bx = self.bbox(t)
                    r = self.create_rectangle(bx[0] - 4, bx[1] - 1, bx[2] + 4, bx[3] + 1,
                                              fill="#ffe082", outline="#c9a227")
                    self.tag_raise(t, r)

    def draw_notes(self, g):
        y = 10
        for nt in sorted(g.notes, key=lambda n: n.id):
            if nt.on and nt.on in self.geoms:
                gm = self.geoms[nt.on]
                sx, sy = self.to_screen(gm.x, gm.y + gm.h + 6)
                self.create_text(sx, sy, anchor="nw", text="✎ " + nt.text, fill="#f7dc6f",
                                 width=max(140, gm.w * self.scale * 1.4), font=self.font(9),
                                 tags=("note", f"t={nt.id}"))
            else:
                detached = nt.on is not None and g.box(nt.on) is None
                text = ("✎ (detached from %s) " % nt.on if detached else "✎ ") + nt.text
                item = self.create_text(10, y, anchor="nw", text=text, width=460,
                                        fill=DIM if detached else "#f7dc6f",
                                        font=("Helvetica", 12),
                                        tags=("note", "graphnote", f"t={nt.id}"))
                y = self.bbox(item)[3] + 8

    # -- hit testing --------------------------------------------------------------
    def hit(self, x, y):
        """Return the most specific thing under the cursor."""
        items = self.find_overlapping(x - 3, y - 3, x + 3, y + 3)
        found = {}
        for it in reversed(items):
            for t in self.gettags(it):
                if "=" in t:
                    k, v = t.split("=", 1)
                    found.setdefault(k, v)
        if "p" in found:
            nid, d, name = found["p"].split("|")
            return ("pin", nid, d, name)
        if "n" in found:
            return ("node", found["n"])
        if "w" in found:
            kind, nid, pin = found["w"].split("|")
            return ("wire", kind, nid, pin)
        if "t" in found:
            return ("note", found["t"])
        if "b" in found:
            items_b = [t for it in items for t in self.gettags(it)]
            if "boxtitle" in items_b:
                return ("boxtitle", found["b"])
            return ("box", found["b"])
        return None

    # -- events -------------------------------------------------------------------
    def on_press(self, e):
        self.focus_set()
        h = self.hit(e.x, e.y)
        if h and h[0] == "pin":
            _, nid, d, name = h
            sx, sy = self.pin_screen(nid, d, name)
            self.drag = ("wire", nid, d, name, sx, sy, e.x, e.y)
        elif h and h[0] == "node":
            self.selected = ("node", h[1])
            gm = self.geoms[h[1]]
            wx, wy = self.to_world(e.x, e.y)
            self.drag = ("move", h[1], wx - gm.x, wy - gm.y, False)
            self.redraw()
        elif h and h[0] == "wire":
            self.selected = h
            self.drag = None
            self.redraw()
        elif h and h[0] == "boxtitle":
            self.selected = ("box", h[1])
            b = self.app.graph.box(h[1])
            wx, wy = self.to_world(e.x, e.y)
            self.drag = ("movebox", h[1], wx - b.x, wy - b.y, False)
            self.redraw()
        else:
            self.selected = None
            self.drag = ("pan", e.x, e.y)
            self.redraw()

    def on_motion(self, e):
        if not self.drag:
            return
        kind = self.drag[0]
        if kind == "pan":
            self.auto_fit = False
            _, x, y = self.drag
            self.ox += e.x - x
            self.oy += e.y - y
            self.drag = ("pan", e.x, e.y)
            self.redraw()
        elif kind in ("move", "movebox"):
            if not self.app.can_edit():
                return
            _, nid, dx, dy, _ = self.drag
            wx, wy = self.to_world(e.x, e.y)
            self.app.move(nid, int(round(wx - dx)), int(round(wy - dy)))
            self.drag = (kind, nid, dx, dy, True)
            self.redraw()
        elif kind == "wire":
            self.drag = self.drag[:6] + (e.x, e.y)
            self.redraw()

    def on_release(self, e):
        d, self.drag = self.drag, None
        if not d:
            return
        if d[0] in ("move", "movebox") and d[4]:
            self.app.commit(f"move {d[1]}")
        elif d[0] == "wire":
            _, nid, direction, pin = d[:4]
            h = self.hit(e.x, e.y)
            if h and h[0] == "pin":
                self.app.connect((nid, direction, pin), (h[1], h[2], h[3]))
            elif h and h[0] == "node" and h[1] != nid:
                self.app.connect_to_node((nid, direction, pin), h[1])
            elif h is None or h[0] in ("box", "wire", "note"):
                # dropped on empty canvas: offer nodes that fit this pin, then wire them up
                wx, wy = self.to_world(e.x, e.y)
                self.app.open_palette(int(wx), int(wy), e.x_root, e.y_root,
                                      (nid, direction, pin))
            self.redraw()

    def on_tab(self, e):
        x, y = self.last_mouse
        wx, wy = self.to_world(x, y)
        self.app.open_palette(int(wx), int(wy), self.winfo_rootx() + x, self.winfo_rooty() + y)
        return "break"

    def on_double(self, e):
        h = self.hit(e.x, e.y)
        if h is None or h[0] == "box":
            wx, wy = self.to_world(e.x, e.y)
            self.app.open_palette(int(wx), int(wy), e.x_root, e.y_root)
            return
        if h[0] == "pin" and h[2] == "in":
            self.app.edit_literal(h[1], h[3])
        elif h[0] == "node":
            self.app.open_node(h[1])

    def on_context(self, e):
        h = self.hit(e.x, e.y)
        wx, wy = self.to_world(e.x, e.y)
        if h and h[0] in ("node", "pin", "boxtitle", "box", "wire"):
            if h[0] == "node":
                self.selected = ("node", h[1])
            elif h[0] in ("box", "boxtitle"):
                self.selected = ("box", h[1])
            elif h[0] == "wire":
                self.selected = h
            self.redraw()
        self.app.context_menu(h, int(wx), int(wy), e.x_root, e.y_root)

    def on_wheel(self, e):
        if e.state & 0x0001 or e.state & 0x0004:   # shift/control: pan
            self.auto_fit = False
            self.ox += e.delta * (1 if abs(e.delta) > 10 else 10)
            self.redraw()
            return
        self.zoom_at(e.x, e.y, 1.1 if e.delta > 0 else 1 / 1.1)

    def on_hover(self, e):
        self.last_mouse = (e.x, e.y)
        h = self.hit(e.x, e.y)
        self.app.hover(h)

    def delete_selection(self):
        sel = self.selected
        if not sel or not self.app.can_edit():
            return
        if sel[0] == "node":
            self.app.delete_node(sel[1])
        elif sel[0] == "wire":
            _, kind, nid, pin = sel
            self.app.disconnect(nid, "in" if kind == "d" else "out", pin)
        elif sel[0] == "box":
            self.app.delete_box(sel[1])
        self.selected = None
