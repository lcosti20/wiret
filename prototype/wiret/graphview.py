"""The graph canvas of the editor: draws one graph and turns mouse input into edits."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass, field

from .checker import GraphInfo
from .model import Graph, PinRef, note_detached, note_text
from .ops import note_key
from .viewmodel import (HEADER, ROW, add_pin_label, add_pin_side, can_remove, display_title, has_add_pin,
                        header_color,
                        input_editor, input_label, output_label, pin_rows, type_color)

REMOVE_W = 18    # the circled − beside a removable pin's label, with its gap
ADD_PAD = 30     # the Add pin button around its text: the circled +, gaps and edges

FIELD_BG = "#1d1f23"
FIELD_EDGE = "#3a3e46"
FIELD_H = 15     # height of a value field, in graph units
ACCENT = "#6aa0ff"

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

@dataclass
class Geom:
    x: float
    y: float
    w: float
    h: float
    pins: dict = field(default_factory=dict)   # (dir, name) -> (x, y, type)
    fields: dict = field(default_factory=dict)  # input name -> (x, y, width, input_editor)
    add_pin: float = None       # the y of its Add pin button (Sequence, Switch), or None
    rule: float = None          # the y of the line above the outputs after indexed ones


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
        self.notes_open = None       # the graph's notes unfolded; None: only on a wide canvas
        self._notes_shown = False
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
            title = display_title(g, n)
            editors = {p.name: input_editor(n, p, self.app.idx) for p in ins}
            in_w, fields = 0, {}
            for p in ins:
                ed = editors[p.name]
                label = input_label(n, p)
                # an indexed input that can be removed has a circled − after it
                extra = REMOVE_W if can_remove(n, p.name, "in") else 0
                if ed is None:
                    in_w = max(in_w, f_pin.measure(label) / s + extra)
                    continue
                lw = (f_pin.measure(p.name) / s + 6) if label else 0
                fw = self.field_width(ed, f_pin) / s
                fields[p.name] = (lw, fw, ed)
                in_w = max(in_w, lw + fw + extra)
            # an indexed output that can be removed has a circled − before its label
            out_w = max([f_pin.measure(output_label(sig, p)) / s
                         + (REMOVE_W if can_remove(n, p.name, "out") else 0)
                         for p in outs] or [0])
            add_w = (f_pin.measure(add_pin_label(n)) / s + ADD_PAD) if has_add_pin(n) else 0
            w = max(f_title.measure(title) / s + 28, in_w + out_w + 46, add_w + 22, 96)
            lay = pin_rows(n, sig)
            gm = Geom(x, y, w, lay["height"])
            gm.add_pin = (y + lay["add"]) if lay["add"] is not None else None
            gm.rule = (y + lay["rule"]) if lay["rule"] is not None else None
            for p, o, ry in lay["rows"]:
                if p is not None:
                    gm.pins[("in", p.name)] = (x, y + ry, p.type)
                    if p.name in fields:
                        fx, fw, ed = fields[p.name]
                        gm.fields[p.name] = (x + 16 + fx, y + ry, fw, ed)
                if o is not None:
                    gm.pins[("out", o.name)] = (x + w, y + ry, o.type)
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
        mark = getattr(self.app, "mark_selected_source", None)
        if mark:
            mark()

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
                color = SELECT if self.selected == key else type_color(ty.type if ty else "", self.app.idx)
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
        hcolor = header_color(self.app.graph, n, sig)
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
            col = type_color(ty, self.app.idx)
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
                b = n.binding(name)
                fill = TEXT if b is not None else DIM
                labelled = bool(input_label(n, pin)) if pin else True
                lx = sx + 2.2 * r
                if name in gm.fields:
                    if labelled:
                        self.create_text(lx, sy, anchor="w", text=name, fill=fill, font=fpin,
                                         tags=tag)
                        lx += fpin.measure(name) + 6 * s
                    fdata = gm.fields[name]
                    self.draw_field(n.id, name, lx, sy, fdata, fpin, tag)
                    end = lx + (FIELD_H if fdata[3]["kind"] == "bool" else fdata[2]) * s
                else:
                    label = input_label(n, pin) if pin else name
                    self.create_text(lx, sy, anchor="w", text=label, fill=fill, font=fpin,
                                     tags=tag)
                    end = lx + fpin.measure(label)
                if can_remove(n, name, "in"):   # the circled − that removes this input
                    self.draw_circled(end + 10 * s, sy, "-",
                                      ("removepin", f"m={n.id}|in|{name}"))
            else:
                pin = sig.output(name)
                label = output_label(sig, pin) if pin else name
                lx = sx - 2.2 * r
                self.create_text(lx, sy, anchor="e", text=label, fill=TEXT, font=fpin, tags=tag)
                if can_remove(n, name, "out"):  # the circled − that removes this output
                    cx = lx - fpin.measure(label) - 10 * s
                    self.draw_circled(cx, sy, "-", ("removepin", f"m={n.id}|out|{name}"))
        if gm.rule is not None:          # the line between indexed outputs and the rest
            _, ry = self.to_screen(gm.x, gm.rule)
            self.create_line(x0 + 4 * s, ry, x1 - 4 * s, ry, fill=FIELD_EDGE, tags=tag)
        if gm.add_pin is not None:       # the Add pin button, on the side its pins are on
            _, ay = self.to_screen(gm.x, gm.add_pin)
            atag = ("addpin", f"a={n.id}")
            text = add_pin_label(n)
            bw = fpin.measure(text) + (ADD_PAD - 8) * s
            if add_pin_side(n) == "left":    # "Add item ⊕", under the inputs
                left = x0 + 11 * s
                right = left + bw
                self.create_rectangle(left, ay - 9 * s, right, ay + 9 * s,
                                      fill=FIELD_BG, outline=FIELD_EDGE, tags=atag)
                self.create_text(left + 5 * s, ay, anchor="w", text=text, fill=DIM,
                                 font=fpin, tags=atag)
                self.draw_circled(right - 10 * s, ay, "+", atag)
            else:                             # "⊕ Add case", under the outputs
                right = x1 - 11 * s
                left = right - bw
                self.create_rectangle(left, ay - 9 * s, right, ay + 9 * s,
                                      fill=FIELD_BG, outline=FIELD_EDGE, tags=atag)
                self.draw_circled(left + 10 * s, ay, "+", atag)
                self.create_text(right - 5 * s, ay, anchor="e", text=text, fill=DIM,
                                 font=fpin, tags=atag)
        if (self.app.graph_name, n.id) in self.app.breakpoints:
            self.create_oval(x0 - 7 * s, y0 - 7 * s, x0 + 7 * s, y0 + 7 * s, fill=BREAK,
                             outline="white", width=1, tags=tag)
        if diag:
            self.create_oval(x1 - 9 * s, y0 - 7 * s, x1 + 7 * s, y0 + 9 * s,
                             fill=ERROR if diag == "error" else WARN, outline="", tags=tag)
            self.create_text(x1 - 1 * s, y0 + 1 * s, text="!", fill="white",
                             font=self.font(10, True), tags=tag)

    # -- value fields on unwired inputs (viewmodel.input_editor) -----------------------
    @staticmethod
    def field_text(ed) -> tuple:
        """(text, is the placeholder) shown in a field."""
        if ed["kind"] == "bool":
            return "", ed["value"] is None
        if ed["value"] is not None:
            return str(ed["value"]), False
        return (str(ed["placeholder"]) if ed["placeholder"] is not None else ""), True

    def field_width(self, ed, font) -> float:
        """The width of a field, in screen units at the font's size."""
        if ed["kind"] == "bool":
            return font.metrics("linespace") * 0.9
        text, _ = self.field_text(ed)
        if ed["kind"] == "enum":
            text = max([text] + ed["options"], key=len) + " ▾"
        elif ed["kind"] in ("int", "float"):
            text = max(text, "00000", key=len) + " ±"
        return min(font.measure(text[:24] or "    "), font.measure("0" * 24)) + 10

    def draw_circled(self, cx, cy, sign, tags):
        """A small circle with + or − in it, the Add and Remove pin buttons."""
        s = self.scale
        r, a = 6 * s, 3.2 * s
        self.create_oval(cx - r, cy - r, cx + r, cy + r, outline=DIM, fill=NODE_BG, width=1,
                         tags=tags)
        self.create_line(cx - a, cy, cx + a, cy, fill=DIM, width=max(1, s), tags=tags)
        if sign == "+":
            self.create_line(cx, cy - a, cx, cy + a, fill=DIM, width=max(1, s), tags=tags)

    def draw_field(self, nid, pin, x, y, fdata, font, tag):
        s = self.scale
        _, _, fw, ed = fdata
        w, h = fw * s, FIELD_H * s
        ftag = tag + (f"f={nid}|{pin}",)
        if ed["kind"] == "bool":
            on = ed["value"] if ed["value"] is not None else bool(ed["placeholder"])
            self.create_rectangle(x, y - h / 2, x + h, y + h / 2, fill=FIELD_BG,
                                  outline=ACCENT if on else FIELD_EDGE, width=1, tags=ftag)
            if on:
                self.create_line(x + h * 0.2, y, x + h * 0.42, y + h * 0.25, x + h * 0.8,
                                 y - h * 0.28, fill=ACCENT if ed["value"] is not None else DIM,
                                 width=max(1.5, 2 * s), tags=ftag)
            return
        self.create_rectangle(x, y - h / 2, x + w, y + h / 2, fill=FIELD_BG, outline=FIELD_EDGE,
                              tags=ftag)
        text, ph = self.field_text(ed)
        if len(text) > 24:
            text = text[:23] + "…"
        self.create_text(x + 4 * s, y, anchor="w", text=text, fill=DIM if ph else TEXT,
                         font=font, tags=ftag)
        if ed["kind"] == "enum":
            self.create_text(x + w - 4 * s, y, anchor="e", text="▾", fill=DIM, font=font, tags=ftag)
        elif ed["kind"] in ("int", "float"):
            self.create_text(x + w - 4 * s, y, anchor="e", text="±", fill=DIM, font=font, tags=ftag)

    def field_rect(self, nid, pin):
        items = self.find_withtag(f"f={nid}|{pin}")
        return self.bbox(*items) if items else None

    def edit_field(self, nid, pin, e):
        """Clicked a value field: toggle a checkbox, list an enum's members, or type in place."""
        gm = self.geoms.get(nid)
        if not gm or pin not in gm.fields or not self.app.can_edit():
            return
        ed = gm.fields[pin][3]
        if ed["kind"] == "bool":
            cur = ed["value"] if ed["value"] is not None else bool(ed["placeholder"])
            new = not cur
            # the default needs no line in the source
            self.app.set_pin_text(nid, pin, "" if ed["placeholder"] is not None
                                  and new == ed["placeholder"] else str(new).lower())
            return
        if ed["kind"] == "enum":
            m = tk.Menu(self, tearoff=0)
            if ed["placeholder"] is not None:
                m.add_command(label=f"{ed['placeholder']} (default)",
                              command=lambda: self.app.set_pin_text(nid, pin, ""))
                m.add_separator()
            for name in ed["options"]:
                m.add_command(label=name, command=lambda v=name: self.app.set_pin_text(nid, pin, v))
            m.tk_popup(e.x_root, e.y_root)
            return
        rect = self.field_rect(nid, pin)
        if rect is None:
            return
        x0, y0, x1, y1 = rect
        var = tk.StringVar(value="" if ed["value"] is None else str(ed["value"]))
        if ed["kind"] == "text":
            box = tk.Entry(self, textvariable=var)
        else:
            lo, hi = (ed.get("min", -1e308), ed.get("max", 1e308))
            box = tk.Spinbox(self, textvariable=var, from_=lo, to=hi,
                             increment=1 if ed["kind"] == "int" else 0.1,
                             format="" if ed["kind"] == "int" else "%.6g")
            var.set("" if ed["value"] is None else str(ed["value"]))
        box.configure(font=self.font(10), bg=FIELD_BG, fg=TEXT, insertbackground=TEXT,
                      relief="flat", highlightthickness=1, highlightcolor=ACCENT)
        win = self.create_window(x0, (y0 + y1) / 2, anchor="w", window=box,
                                 width=max(x1 - x0, 90), height=y1 - y0 + 4)
        done = [False]

        def finish(save):
            if done[0]:
                return
            done[0] = True
            text = var.get()
            self.delete(win)
            box.destroy()
            if save and text != ("" if ed["value"] is None else str(ed["value"])):
                self.app.set_pin_text(nid, pin, text, verbatim=ed["kind"] == "text")
            self.focus_set()

        box.bind("<Return>", lambda _e: finish(True))
        box.bind("<Escape>", lambda _e: finish(False))
        box.bind("<FocusOut>", lambda _e: finish(True))
        box.focus_set()
        box.select_range(0, "end")

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
                text = format_value(pin.type, self.pin_values[key], self.app.idx)
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
        """Notes under their node, and the graph's own notes at the top left of the view. Those
        can be folded away with the button below them, and start folded on a narrow canvas."""
        graph_notes = []
        for on, i, nt in g.all_notes():
            key = note_key(on, i)
            if on and on in self.geoms:
                gm = self.geoms[on]
                sx, sy = self.to_screen(gm.x, gm.y + gm.h + 6)
                self.create_text(sx, sy, anchor="nw", text="✎ " + note_text(nt), fill="#f7dc6f",
                                 width=max(140, gm.w * self.scale * 1.4), font=self.font(9),
                                 tags=("note", f"t={key}"))
            else:
                graph_notes.append((key, nt))
        if not graph_notes:
            return
        is_open = self.notes_open if self.notes_open is not None else self.winfo_width() >= 600
        y = 10
        for key, nt in graph_notes if is_open else []:
            gone = note_detached(nt)
            detached = gone is not None
            text = ("✎ (detached from %s) " % gone if detached else "✎ ") + note_text(nt)
            item = self.create_text(10, y, anchor="nw", text=text, width=460,
                                    fill=DIM if detached else "#f7dc6f",
                                    font=("Helvetica", 12),
                                    tags=("note", "graphnote", f"t={key}"))
            y = self.bbox(item)[3] + 8
        label = "Hide notes" if is_open else f"✎ Notes ({len(graph_notes)})"
        t = self.create_text(18, y + 4, anchor="nw", text=label, fill=DIM,
                             font=("Helvetica", 11), tags=("graphnote", "notestoggle"))
        bx = self.bbox(t)
        r = self.create_rectangle(10, y, bx[2] + 8, bx[3] + 4, fill="#2b2e35", outline="#3a3e47",
                                  tags=("graphnote", "notestoggle"))
        self.tag_raise(t, r)
        self._notes_shown = is_open

    def on_notes_toggle(self, x, y) -> bool:
        """Fold or unfold the graph's notes if (x, y) is on their button. The view stays where
        it is, so the graph does not jump each time."""
        items = self.find_overlapping(x, y, x, y)
        if not any("notestoggle" in self.gettags(it) for it in items):
            return False
        self.notes_open = not self._notes_shown
        self.drag = None
        self.redraw()
        return True

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
        if "f" in found:
            nid, name = found["f"].split("|")
            return ("field", nid, name)
        if "a" in found:
            return ("addpin", found["a"])
        if "m" in found:
            nid, _d, pin = found["m"].split("|", 2)
            return ("removepin", nid, pin)
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
        if self.on_notes_toggle(e.x, e.y):
            return
        h = self.hit(e.x, e.y)
        if h and h[0] == "field":
            self.drag = None
            self.edit_field(h[1], h[2], e)
            return
        if h and h[0] == "addpin":
            self.drag = None
            self.app.add_pin(h[1])
            return
        if h and h[0] == "removepin":
            self.drag = None
            self.app.remove_pin(h[1], h[2])
            return
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
