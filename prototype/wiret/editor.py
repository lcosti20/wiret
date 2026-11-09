"""The Wiret graph editor: a Tk application that edits a `.wiret` file in real time.

Every graph edit is applied to the model, written back to disk in canonical form and shown in
the source pane. Typing in the source pane re-parses the text and redraws the graph. External
changes to the file are picked up by polling. Run compiles to `.wbc`, then loads the bytecode
from disk into the VM and executes it.
"""
from __future__ import annotations

import csv
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from collections import Counter, deque
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Optional

from . import canvasedit, ops, palette, palettepopup, syntax, viewmodel
from .checker import GraphInfo, check
from .compiler import compile_module
from .debugstate import DebugState
from .disasm import disassemble
from .graphview import BG, DIM, TEXT, GraphView
from .model import Box, Graph, Lit, Local, Module, Param, PinRef, note_text, set_note_text
from .natives import STD
from .parser import ParseError, parse, parse_literal
from .printer import GraphNames, layout_hash, print_module, semantic_hash
from .ids import assign_ids, attach_retired, find_project, retired_between
from .registry import (ModuleIndex, STATIC_KINDS, can_convert, enum_values,
                       type_choices, type_ok)
from .explain import explain, explain_runtime, type_words
from .runner import format_results, format_value, parse_args_for, run_function, split_args
from .vm import STATUS_INTERRUPT, VM, WiretError

NEW_FILE = """wiret 1
module untitled

extern func host.Log(message: string)

func Main() {
  flow {
    entry -> hello
  }

  node entry = Entry()
  node hello = Call host.Log(
    .message <- "Hello, Wiret!",
  )

  layout {
    entry at (0, 0)
    hello at (200, 0)
  }
}
"""

FROZEN = getattr(sys, "frozen", False)          # running from a PyInstaller build
HERE = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LESSONS_DIR = os.path.join(HERE, "lessons")       # read-only originals


def user_dir() -> str:
    """Where a packaged app keeps the student's files: a writable, per-user folder.

    `WIRET_HOME` overrides it. Otherwise ~/Documents/Wiret (easy for students to find),
    or ~/Wiret if there is no Documents folder.
    """
    env = os.environ.get("WIRET_HOME")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    home = os.path.expanduser("~")
    docs = os.path.join(home, "Documents")
    return os.path.join(docs if os.path.isdir(docs) else home, "Wiret")


# Students edit copies, never the originals. Running from source keeps them next to the
# prototype; a packaged app cannot write there (its folder is read-only or temporary).
WORK_DIR = (os.path.join(user_dir(), "my_lessons") if FROZEN or os.environ.get("WIRET_HOME")
            else os.path.join(HERE, "my_lessons"))

COMMON_TYPES = ["i32", "i64", "u8", "u32", "f32", "f64", "bool", "string"]
MONO = ("Menlo", 12)            # replaced by pick_mono once Tk is running

# Monospace families to try, in order: macOS, Windows, then Linux. Tk quietly falls back to a
# proportional font for a family that is not installed, so the editor picks one that is.
MONO_FAMILIES = ("Menlo", "SF Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono",
                 "Liberation Mono", "Ubuntu Mono", "Noto Sans Mono", "Courier New")


def pick_mono(root) -> tuple:
    """The code font: the first installed monospace family, else Tk's own fixed font. Tk
    sizes are points, which Windows draws larger than macOS, so Windows gets a smaller size."""
    from tkinter import font as tkfont
    size = 10 if sys.platform == "win32" else 12
    installed = {f.lower() for f in tkfont.families(root)}
    for family in MONO_FAMILIES:
        if family.lower() in installed:
            return (family, size)
    return (tkfont.nametofont("TkFixedFont", root=root).actual("family"), size)


def remove_lesson_copies(names, work_dir: Optional[str] = None) -> int:
    """Delete the working copies of the named lessons from my_lessons. Returns how many."""
    work_dir = work_dir or WORK_DIR
    removed = 0
    for name in names:
        path = os.path.join(work_dir, name)
        if os.path.exists(path):
            os.remove(path)
            removed += 1
    return removed


class EditorApp:
    def __init__(self, root: tk.Tk, path: Optional[str]):
        global MONO
        MONO = pick_mono(root)
        self.root = root
        self.path: Optional[str] = None
        self.module: Optional[Module] = None
        self.text = ""
        self.disk_text = None
        self.parse_error: Optional[ParseError] = None
        self.graph_name: Optional[str] = None
        self.info: Optional[GraphInfo] = None
        self.idx: Optional[ModuleIndex] = None
        self.diags = []
        self.auto_pos = {}
        self.undo_stack: deque = deque(maxlen=200)
        self.redo_stack: list = []
        self._suppress_text_event = False
        self._parse_job = None
        self.run_thread = None
        self.vm: Optional[VM] = None
        self.out_queue: queue.Queue = queue.Queue()
        self.last_counts: dict = {}
        self.fault: dict = {}
        self.dbg: Optional[DebugState] = None
        self.paused = None          # (graph, node) while the debugger waits
        self.frames: list = []      # FrameViews of the last pause
        self.breakpoints: set = set()   # (graph, node); view state, never saved to the file
        self.fuel = 5_000_000       # instructions per run: an endless loop stops after a few seconds
        self.build_ui()
        if path:
            self.open_path(path)
        elif self.lesson_files():
            self.open_lesson(self.lesson_files()[0], ask=False)
        else:
            self.status("Open a .wiret file or create a new one.")
        self.root.after(1000, self.poll_file)
        self.root.after(50, self.drain_output)

    # -- UI construction ----------------------------------------------------------
    def build_ui(self):
        r = self.root
        r.title("Wiret Graph Editor")
        r.geometry("1500x900")
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        menubar = tk.Menu(r)
        fm = tk.Menu(menubar, tearoff=0)
        fm.add_command(label="New…", command=self.new_file, accelerator="Cmd+N")
        fm.add_command(label="Open…", command=self.open_dialog, accelerator="Cmd+O")
        fm.add_separator()
        fm.add_command(label="Format (canonical)", command=self.format_now)
        fm.add_command(label="Convert // comments to notes", command=self.convert_comments)
        menubar.add_cascade(label="File", menu=fm)
        em = tk.Menu(menubar, tearoff=0)
        em.add_command(label="Undo graph edit", command=self.undo, accelerator="Cmd+Z")
        em.add_command(label="Redo graph edit", command=self.redo, accelerator="Cmd+Shift+Z")
        menubar.add_cascade(label="Edit", menu=em)
        gm = tk.Menu(menubar, tearoff=0)
        gm.add_command(label="New function…", command=lambda: self.new_graph("func"))
        gm.add_command(label="New macro…", command=lambda: self.new_graph("macro"))
        gm.add_command(label="Edit signature…", command=self.edit_signature)
        gm.add_command(label="Add local…", command=lambda: self.add_local("local"))
        gm.add_command(label="Add state…", command=lambda: self.add_local("state"))
        gm.add_command(label="Add graph note…", command=lambda: self.add_note(None))
        gm.add_separator()
        gm.add_command(label="Delete graph", command=self.delete_graph)
        menubar.add_cascade(label="Graph", menu=gm)
        lm = tk.Menu(menubar, tearoff=0)
        for name in self.lesson_files():
            lm.add_command(label=self.lesson_title(name), command=lambda n=name: self.open_lesson(n))
        lm.add_separator()
        lm.add_command(label="Start this lesson over", command=self.reset_lesson)
        lm.add_command(label="Start all lessons over…", command=self.reset_all_lessons)
        menubar.add_cascade(label="Lessons", menu=lm)
        r.config(menu=menubar)
        for seq, fn in (("<Command-n>", self.new_file), ("<Command-o>", self.open_dialog),
                        ("<Control-n>", self.new_file), ("<Control-o>", self.open_dialog)):
            r.bind(seq, lambda e, fn=fn: fn())

        bar = ttk.Frame(r, padding=4)
        bar.pack(side="top", fill="x")
        ttk.Label(bar, text="Graph:").pack(side="left")
        self.graph_var = tk.StringVar()
        self.graph_box = ttk.Combobox(bar, textvariable=self.graph_var, state="readonly", width=18)
        self.graph_box.pack(side="left", padx=4)
        self.graph_box.bind("<<ComboboxSelected>>", lambda e: self.select_graph(
            self.graph_var.get().split(" ", 1)[-1]))
        ttk.Button(bar, text="Fit", width=4, command=lambda: self.view.fit()).pack(side="left", padx=2)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Label(bar, text="Entry:").pack(side="left")
        self.entry_var = tk.StringVar()
        self.entry_box = ttk.Combobox(bar, textvariable=self.entry_var, state="readonly", width=12)
        self.entry_box.pack(side="left", padx=4)
        ttk.Label(bar, text="Args:").pack(side="left")
        self.args_var = tk.StringVar()
        ttk.Entry(bar, textvariable=self.args_var, width=10).pack(side="left", padx=4)
        self.run_btn = ttk.Button(bar, text="▶ Run", width=10, command=self.run_or_continue)
        self.run_btn.pack(side="left", padx=(4, 0))
        self.step_btn = ttk.Button(bar, text="⤵ Step", width=8, command=self.step_into)
        self.step_btn.pack(side="left")
        self.over_btn = ttk.Button(bar, text="↷ Step Over", width=10, command=self.step_over)
        self.over_btn.pack(side="left")
        self.stop_btn = ttk.Button(bar, text="■ Stop", width=6, command=self.stop, state="disabled")
        self.stop_btn.pack(side="left")
        self.animate_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Animate", variable=self.animate_var).pack(side="left", padx=(8, 2))
        self.speed_var = tk.IntVar(value=500)
        speed = ttk.Scale(bar, from_=50, to=1500, variable=self.speed_var, length=90,
                          command=lambda v: setattr(self.dbg, "delay", float(v) / 1000)
                          if self.dbg else None)
        speed.pack(side="left")
        self.file_label = ttk.Label(bar, text="", foreground="#666")

        vpane = ttk.PanedWindow(r, orient="vertical")
        vpane.pack(fill="both", expand=True)
        hpane = ttk.PanedWindow(vpane, orient="horizontal")
        vpane.add(hpane, weight=4)
        self.view = GraphView(hpane, self)
        hpane.add(self.view, weight=3)
        nb = ttk.Notebook(hpane)
        hpane.add(nb, weight=2)
        self.root.after(200, lambda: hpane.sashpos(0, int(hpane.winfo_width() * 0.62)))
        self.notebook = nb

        src_frame = ttk.Frame(nb)
        self.src = tk.Text(src_frame, wrap="none", undo=True, font=MONO, bg="#15171a", fg=TEXT,
                           insertbackground="white", selectbackground="#3a4a63")
        ys = ttk.Scrollbar(src_frame, orient="vertical", command=self.src.yview)
        xs = ttk.Scrollbar(src_frame, orient="horizontal", command=self.src.xview)
        self.src.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        ys.pack(side="right", fill="y")
        xs.pack(side="bottom", fill="x")
        self.src.pack(fill="both", expand=True)
        self.src.bind("<<Modified>>", self.on_text_modified)
        for tag, color in syntax.COLORS.items():
            self.src.tag_configure(tag, foreground=color)
        self.src.tag_configure("err", background="#5c1f1f")
        self.src.tag_configure("hl", background="#3a3f4b")
        nb.add(src_frame, text="Source (.wiret)")

        prob = ttk.Frame(nb)
        cols = ("sev", "code", "graph", "node", "message")
        self.problems = ttk.Treeview(prob, columns=cols, show="headings", height=8)
        for c, w in zip(cols, (60, 55, 80, 90, 300)):
            self.problems.heading(c, text=c)
            self.problems.column(c, width=w, minwidth=40, stretch=(c == "message"))
        self.problems.pack(fill="both", expand=True)
        self.problems.bind("<Double-1>", self.on_problem)
        self.problems.bind("<<TreeviewSelect>>", self.show_problem_detail)
        self.problem_detail = ttk.Label(prob, text="", wraplength=440, justify="left", padding=8,
                                        font=("Helvetica", 13))
        self.problem_detail.pack(fill="x")
        prob.bind("<Configure>", lambda e: self.problem_detail.config(wraplength=e.width - 20))
        nb.add(prob, text="Problems")

        dbgf = ttk.Frame(nb)
        ttk.Label(dbgf, text="Call stack (innermost first)", padding=(4, 4, 4, 0)).pack(anchor="w")
        self.stack_tree = ttk.Treeview(dbgf, columns=("function", "node"), show="headings",
                                       height=5)
        for c, w in (("function", 160), ("node", 160)):
            self.stack_tree.heading(c, text=c)
            self.stack_tree.column(c, width=w)
        self.stack_tree.pack(fill="x", padx=4)
        self.stack_tree.bind("<<TreeviewSelect>>", self.on_stack_select)
        ttk.Label(dbgf, text="Variables", padding=(4, 8, 4, 0)).pack(anchor="w")
        self.vars_tree = ttk.Treeview(dbgf, columns=("name", "kind", "value"), show="headings")
        for c, w in (("name", 120), ("kind", 130), ("value", 220)):
            self.vars_tree.heading(c, text=c)
            self.vars_tree.column(c, width=w, stretch=(c == "value"))
        self.vars_tree.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        ttk.Label(dbgf, wraplength=420, foreground="#555", padding=4, text=(
            "Step (F11) runs one node at a time; Step Over (F10) runs called functions in one go; "
            "Continue (F5) runs until the next breakpoint. Press F9 on a selected node to set a "
            "breakpoint. Values on the wires show what each node received.")).pack(anchor="w")
        nb.add(dbgf, text="Debugger")
        self.debug_tab = dbgf

        bc = ttk.Frame(nb)
        self.bytecode = tk.Text(bc, wrap="none", font=MONO, bg="#15171a", fg=TEXT)
        bys = ttk.Scrollbar(bc, orient="vertical", command=self.bytecode.yview)
        self.bytecode.configure(yscrollcommand=bys.set)
        bys.pack(side="right", fill="y")
        self.bytecode.pack(fill="both", expand=True)
        nb.add(bc, text="Bytecode (.wbc)")

        cons = ttk.Frame(vpane)
        vpane.add(cons, weight=1)
        self.console = tk.Text(cons, height=9, font=MONO, bg="#101114", fg="#d0d0d0",
                               state="disabled")
        cys = ttk.Scrollbar(cons, orient="vertical", command=self.console.yview)
        self.console.configure(yscrollcommand=cys.set)
        cys.pack(side="right", fill="y")
        self.console.pack(fill="both", expand=True)
        for tag, color in (("err", "#ff6b6b"), ("ok", "#2ecc71"), ("dim", "#888"),
                           ("out", "#ffffff")):
            self.console.tag_configure(tag, foreground=color)
        self.status_var = tk.StringVar()
        ttk.Label(r, textvariable=self.status_var, anchor="w", padding=(6, 2)).pack(
            side="bottom", fill="x")
        for seq, fn in (("<F5>", self.run_or_continue), ("<F10>", self.step_over),
                        ("<F11>", self.step_into), ("<Shift-F5>", self.stop),
                        ("<F9>", self.toggle_breakpoint)):
            r.bind(seq, lambda e, fn=fn: fn())
        self.view.bind("<Command-z>", lambda e: self.undo())
        self.view.bind("<Control-z>", lambda e: self.undo())
        self.view.bind("<Command-Z>", lambda e: self.redo())
        self.view.bind("<Command-Shift-z>", lambda e: self.redo())

    # -- messages -----------------------------------------------------------------
    def status(self, msg):
        self.status_var.set(msg)

    def log(self, msg, tag=None):
        self.console.configure(state="normal")
        self.console.insert("end", msg + "\n", tag)
        self.console.see("end")
        self.console.configure(state="disabled")

    # -- files --------------------------------------------------------------------
    def new_file(self):
        path = filedialog.asksaveasfilename(defaultextension=".wiret", initialdir=self.files_dir(),
                                            filetypes=[("Wiret source", "*.wiret")])
        if not path:
            return
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(NEW_FILE)
        self.open_path(path)

    def files_dir(self) -> str:
        """Start file dialogs next to the open file, else in the user's Wiret folder."""
        if self.path:
            return os.path.dirname(self.path)
        if FROZEN:
            d = user_dir()
            os.makedirs(d, exist_ok=True)
            return d
        return os.getcwd()

    def open_dialog(self):
        path = filedialog.askopenfilename(initialdir=self.files_dir(),
                                          filetypes=[("Wiret source", "*.wiret"), ("All", "*")])
        if path:
            self.open_path(path)

    def open_path(self, path):
        path = os.path.abspath(path)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(NEW_FILE)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.path = path
        self.project = find_project(path)       # wiret.toml above the file, or None
        self.session_retired = set()            # ids this session added to wiret.ids
        self.root.title(f"Wiret Graph Editor — {os.path.basename(path)}")
        self.file_label.config(text=path)
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.auto_pos = {}
        self.graph_name = None
        self.disk_text = text
        self.set_text(text, from_disk=True)
        self.after_text_parsed(fit=True)
        if self.module and self.module.comments:
            self.log(f"{len(self.module.comments)} '//' comment(s) are not directly above a "
                     f"statement, so they are attached to nothing: use File > Convert // comments "
                     f"to notes before editing the graph, or they will be offered for conversion "
                     f"on the first graph edit (W0603).",
                     "dim")

    # -- lessons ------------------------------------------------------------------
    @staticmethod
    def lesson_files() -> list:
        if not os.path.isdir(LESSONS_DIR):
            return []
        return sorted(f for f in os.listdir(LESSONS_DIR) if f.endswith(".wiret"))

    @staticmethod
    def lesson_title(name: str) -> str:
        stem = os.path.splitext(name)[0]
        num, _, rest = stem.partition("_")
        return f"{int(num)}. {rest.replace('_', ' ').capitalize()}" if num.isdigit() else stem

    def open_lesson(self, name: str, ask=True):
        """Open a working copy of a lesson, so the original stays untouched."""
        src = os.path.join(LESSONS_DIR, name)
        dst = os.path.join(WORK_DIR, name)
        os.makedirs(WORK_DIR, exist_ok=True)
        with open(src, encoding="utf-8") as f:
            original = f.read()
        fresh = True
        if os.path.exists(dst):
            with open(dst, encoding="utf-8") as f:
                mine = f.read()
            if mine != original:
                fresh = ask and not messagebox.askyesno(
                    "Lesson", f"You have already worked on {self.lesson_title(name)}.\n\n"
                              f"Yes: continue where you left off\nNo: start again from the beginning")
                if not ask:
                    fresh = False
        if fresh:
            with open(dst, "w", encoding="utf-8", newline="\n") as f:
                f.write(original)
        self.open_path(dst)
        self.notebook.select(0)
        self.status(f"{self.lesson_title(name)} — read the yellow notes, then press ▶ Run.")

    def reset_lesson(self):
        if not self.path or os.path.normcase(os.path.dirname(os.path.abspath(self.path))) != os.path.normcase(WORK_DIR):
            self.status("The open file is not a lesson.")
            return
        name = os.path.basename(self.path)
        if messagebox.askyesno("Start over", f"Throw away your changes to "
                                             f"{self.lesson_title(name)} and start again?"):
            os.remove(self.path)
            self.open_lesson(name, ask=False)

    def reset_all_lessons(self):
        """Throw away every lesson's working copy, for instance after updating the prototype
        when the copies still hold the old lessons. Only copies of bundled lessons are
        removed; anything else in my_lessons stays."""
        copies = [n for n in self.lesson_files() if os.path.exists(os.path.join(WORK_DIR, n))]
        if not copies:
            self.status("No lesson has been started yet, so there is nothing to reset.")
            return
        if not messagebox.askyesno(
                "Start all lessons over",
                f"Throw away your changes to all {len(copies)} lessons you have opened and "
                f"start them again from the originals?\n\nThis cannot be undone."):
            return
        open_name = None
        if self.path and os.path.normcase(os.path.dirname(os.path.abspath(self.path))) == \
                os.path.normcase(WORK_DIR):
            open_name = os.path.basename(self.path)
        removed = remove_lesson_copies(copies)
        if open_name in copies:
            self.open_lesson(open_name, ask=False)
        self.status(f"Started {removed} lesson{'s' if removed != 1 else ''} over.")

    def write_file(self, text):
        if not self.path:
            return
        self.track_retired(self.disk_text, text)
        with open(self.path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        self.disk_text = text

    def keep_ids(self, text):
        """In a project, an undo or redo keeps the @ids assigned since that snapshot."""
        if getattr(self, "project", None) is None:
            return text
        try:
            old, cur = parse(text), parse(self.text)
        except ParseError:
            return text
        from .ids import carry_ids
        return print_module(old) if carry_ids(cur, old) else text

    def track_retired(self, old_text, new_text):
        """In a project, every id a save removes is retired in wiret.ids (section 7.5). An
        undo that brings back an id this session retired takes it out again."""
        proj = getattr(self, "project", None)
        if proj is None:
            return
        try:
            old, new = parse(old_text or ""), parse(new_text)
        except ParseError:
            return
        from .ids import ids_of
        back = ids_of(new) & self.session_retired
        if back:
            proj.unretire(back)
            self.session_retired -= back
        written = proj.retire(retired_between(old, new))
        self.session_retired |= set(written)
        for r in written:
            self.log(f"retired {r.kind} id '{r.id}' in wiret.ids", "dim")

    def poll_file(self):
        try:
            if self.path and os.path.exists(self.path):
                with open(self.path, encoding="utf-8") as f:
                    disk = f.read()
                if disk != self.disk_text:
                    self.disk_text = disk
                    self.set_text(disk, from_disk=True)
                    self.after_text_parsed()
                    self.log("Reloaded: the file changed on disk.", "dim")
        except OSError:
            pass
        self.root.after(1000, self.poll_file)

    # -- text <-> model -----------------------------------------------------------
    def set_text(self, text, from_disk=False):
        """Replace the source pane's contents and parse them."""
        self._suppress_text_event = True
        y = self.src.yview()[0]
        ins = self.src.index("insert")
        self.src.delete("1.0", "end")
        self.src.insert("1.0", text)
        self.src.edit_modified(False)
        self.src.yview_moveto(y)
        self.src.mark_set("insert", ins)
        self._suppress_text_event = False
        self.text = text
        self.highlight_source()
        self.parse_text()

    def parse_text(self) -> bool:
        self.src.tag_remove("err", "1.0", "end")
        try:
            self.module = parse(self.text)
            self.parse_error = None
            return True
        except ParseError as e:
            self.parse_error = e
            self.src.tag_add("err", f"{e.line}.0", f"{e.line}.end")
            self.status(f"Parse error at line {e.line}, column {e.col}: {e.msg} "
                        f"(the graph shows the last version that parsed)")
            return False

    def on_text_modified(self, _e=None):
        if not self.src.edit_modified():
            return
        self.src.edit_modified(False)
        if self._suppress_text_event:
            return
        if self._parse_job:
            self.root.after_cancel(self._parse_job)
        self._parse_job = self.root.after(350, self.text_edited)

    def text_edited(self):
        self._parse_job = None
        text = self.src.get("1.0", "end-1c")
        if not text.endswith("\n"):
            text += "\n"
        if text == self.text:
            return
        prev = self.text
        self.text = text
        self.highlight_source()
        if self.parse_text():
            self.push_undo(prev)
            self.write_file(text)
            self.after_text_parsed()
            self.status("Source parsed; graph updated and file saved.")

    def after_text_parsed(self, fit=False):
        m = self.module
        if m is None:
            return
        names = [g.name for g in m.graphs()]
        if self.graph_name not in names:
            self.graph_name = "Main" if "Main" in names else (names[0] if names else None)
        self.graph_box["values"] = [f"{g.kind} {g.name}" for g in
                                    sorted(m.graphs(), key=lambda g: (g.kind != "func", g.name))]
        g = self.graph
        self.graph_var.set(f"{g.kind} {g.name}" if g else "")
        entries = [g.name for g in m.graphs(("func", "event"))]
        self.entry_box["values"] = entries
        if self.entry_var.get() not in entries:
            self.entry_var.set("Main" if "Main" in entries else (entries[0] if entries else ""))
        self.refresh(fit=fit)

    def highlight_source(self):
        t = self.src
        for tag in syntax.TAGS:
            t.tag_remove(tag, "1.0", "end")
        for i, line in enumerate(self.text.split("\n"), start=1):
            for start, end, tag in syntax.spans(line):
                t.tag_add(tag, f"{i}.{start}", f"{i}.{end}")

    def push_undo(self, text):
        self.undo_stack.append(text)
        self.redo_stack.clear()

    def can_edit(self) -> bool:
        if self.running or self.paused:
            self.status("The program is running. Stop it (■) before editing the graph.")
            return False
        if self.parse_error is not None:
            self.status("Fix the parse error in the source pane before editing the graph.")
            return False
        return self.graph is not None

    def commit(self, reason: str):
        """Write the edited model back to disk in canonical form."""
        m = self.module
        if m.comments:
            ans = messagebox.askyesnocancel(
                "Comments would be lost",
                f"The source has {len(m.comments)} '//' comment(s) that are not directly above "
                f"a statement, so saving the graph cannot keep them (W0603).\n\nYes: convert "
                f"them to notes\nNo: drop them\nCancel: undo this edit")
            if ans is None:
                self.parse_text()
                self.refresh()
                return False
            if ans:
                for msg in ops.convert_comments(m):
                    self.log(msg, "dim")
            else:
                m.comments = []
        g = self.graph
        if g is not None:   # auto-placed nodes get a place line when first saved (section 2.3)
            canvasedit.place_unplaced(g, self.auto_pos)
        if getattr(self, "project", None) is not None:   # editors always write @id (2.4)
            assign_ids(m, retired={r.id for r in self.project.retired})
        attach_retired(m, getattr(self, "project", None))
        self.last_counts, self.fault = {}, {}
        self.view.run_counts, self.view.fault_node = {}, None
        sel = self.view.selected
        if g is not None and sel and sel[0] == "node":
            # the text read back knows a node by the name it is written with (section 2.3)
            self.view.selected = ("node", GraphNames(g, ModuleIndex(m)).name(sel[1]))
        text = print_module(m)
        if text != self.text:
            self.push_undo(self.text)
            self.write_file(text)
            self.set_text(text)
        self.status(f"{reason} — saved {os.path.basename(self.path or '')}")
        self.refresh()
        return True

    def undo(self):
        if not self.undo_stack:
            self.status("Nothing to undo.")
            return
        self.redo_stack.append(self.text)
        text = self.keep_ids(self.undo_stack.pop())
        self.write_file(text)
        self.set_text(text)
        self.after_text_parsed()
        self.status("Undone.")

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(self.text)
        text = self.keep_ids(self.redo_stack.pop())
        self.write_file(text)
        self.set_text(text)
        self.after_text_parsed()

    def format_now(self):
        if self.can_edit():
            self.commit("Formatted")

    def convert_comments(self):
        if self.module and self.module.comments and self.can_edit():
            for msg in ops.convert_comments(self.module):
                self.log(msg, "dim")
            self.commit("Converted comments to notes")

    # -- derived state ------------------------------------------------------------
    @property
    def graph(self) -> Optional[Graph]:
        return self.module.graph(self.graph_name) if self.module and self.graph_name else None

    def refresh(self, fit=False):
        m = self.module
        if m is None:
            return
        self.idx = ModuleIndex(m)
        g = self.graph
        self.info = GraphInfo(g, self.idx) if g else None
        self.diags = check(m, project=getattr(self, "project", None))
        self.problems.delete(*self.problems.get_children())
        for i, d in enumerate(self.diags):
            self.problems.insert("", "end", iid=str(i), values=(d.severity, d.code, d.graph or "",
                                                                d.node or "", explain(d)))
        if self.diags:
            self.problems.selection_set("0")
        else:
            self.problem_detail.config(text="No problems. Press ▶ Run.")
        n_err = sum(d.severity == "error" for d in self.diags)
        n_warn = len(self.diags) - n_err
        self.notebook.tab(1, text=f"Problems ({n_err} errors, {n_warn} warnings)")
        if fit:
            self.view.auto_fit = True
            self.root.after(60, lambda: self.view.fit(keep_auto=True))
        self.view.redraw()

    def diag_nodes(self) -> dict:
        out = {}
        for d in self.diags:
            if d.graph == self.graph_name and d.top_node:
                if out.get(d.top_node) != "error":
                    out[d.top_node] = d.severity
        return out

    def exec_targets(self) -> set:
        return viewmodel.exec_targets(self.graph) if self.graph else set()

    def used_outputs(self) -> set:
        return viewmodel.used_outputs(self.graph, self.info)

    def positions(self) -> dict:
        return viewmodel.positions(self.graph, self.info, self.auto_pos)

    # -- graph navigation ---------------------------------------------------------
    def select_graph(self, name, fit=True):
        self.graph_name = name
        g = self.graph
        if g:
            self.graph_var.set(f"{g.kind} {g.name}")
        self.view.selected = None
        if not self.frames:
            self.view.current_node, self.view.pin_values = None, {}
        self.view.run_counts = self.run_counts_for(name)
        self.view.fault_node = self.fault.get(name)
        self.refresh(fit=fit)

    def open_node(self, nid):
        n = self.graph.node(nid)
        if n and n.kind in ("Call", "Macro") and n.symbol:
            target = n.symbol.split(".")[-1] if n.symbol.startswith(self.module.name + ".") \
                else n.symbol
            if self.module.graph(target):
                self.select_graph(target)
                return
        self.set_label(nid)

    def show_problem_detail(self, _e=None):
        sel = self.problems.selection()
        if not sel or int(sel[0]) >= len(self.diags):
            return
        d = self.diags[int(sel[0])]
        where = " → ".join(x for x in (d.graph, d.node, d.pin) if x)
        self.problem_detail.config(text=f"{d.severity.capitalize()} in {where}\n\n{explain(d)}\n\n"
                                        f"({d.code}: {d.message}. Double-click the row to "
                                        f"show it on the graph.)")

    def on_problem(self, _e):
        sel = self.problems.selection()
        if not sel:
            return
        d = self.diags[int(sel[0])]
        if d.graph and self.module.graph(d.graph):
            self.select_graph(d.graph, fit=False)
            if d.top_node:
                self.view.selected = ("node", d.top_node)
                gm = self.view.geoms.get(d.top_node)
                if gm:
                    w, h = self.view.winfo_width(), self.view.winfo_height()
                    self.view.ox = w / 2 - (gm.x + gm.w / 2) * self.view.scale
                    self.view.oy = h / 2 - (gm.y + gm.h / 2) * self.view.scale
                self.view.redraw()
        self.status(f"{d.code}: {d.message}")

    def hover(self, h):
        if h is None:
            return
        if h[0] in ("node", "pin"):
            nid = h[1]
            n = self.graph.node(nid) if self.graph else None
            msgs = [explain(d) for d in self.diags
                    if d.graph == self.graph_name and d.top_node == nid]
            text = nid
            if h[0] == "pin":
                sig = self.info.sigs.get(nid)
                p = (sig.input(h[3]) if h[2] == "in" else sig.output(h[3])) if sig else None
                if p:
                    text += f".{p.name}: {type_words(p.type)}"
                    v = self.view.pin_values.get((nid, p.name)) if h[2] == "out" else None
                    if v is not None:
                        text += f" = {format_value(p.type, v, self.idx)}"
            elif n is not None:
                desc = palette.describe(n.kind, n.symbol, self.idx)
                if desc:
                    text += f"   —   {desc}"
            if msgs:
                text += "   —   " + "   |   ".join(msgs)
            self.status(text)

    # -- edits --------------------------------------------------------------------
    def move(self, nid, x, y):
        ops.place(self.graph, nid, x, y)

    def connect(self, a, b):
        if not self.can_edit():
            return
        try:
            reason = canvasedit.connect(self.graph, self.info, self.idx, a, b, self.geom)
        except canvasedit.Refused as e:
            self.status(str(e))
            return
        if reason:
            self.commit(reason)

    def geom(self, nid):
        gm = self.view.geoms.get(nid)
        return (gm.x, gm.y, gm.w) if gm else None

    def open_palette(self, wx, wy, rx, ry, context=None):
        """The searchable node palette. With a pin `context`, only nodes that fit are listed,
        and the new node is wired to that pin."""
        if not self.can_edit():
            return
        found = canvasedit.palette(self.graph, self.info, self.idx, context)
        if found is None:
            return
        title, candidates = found

        def pick(it):
            try:
                nid, reason = canvasedit.add_node(self.graph, self.idx, it, wx, wy, context,
                                                  self.geom)
            except canvasedit.Refused as e:
                self.status(str(e))
                return
            self.view.selected = ("node", nid)
            self.commit(reason)
            self.view.focus_set()

        return palettepopup.PalettePopup(self.root, rx, ry, candidates, pick, title)

    def connect_to_node(self, a, nid):
        if not self.can_edit():
            return
        try:
            reason = canvasedit.connect_to_node(self.graph, self.info, self.idx, a, nid, self.geom)
        except canvasedit.Refused as e:
            self.status(str(e))
            return
        if reason:
            self.commit(reason)

    def disconnect(self, nid, d, pin):
        if not self.can_edit():
            return
        self.commit(canvasedit.disconnect(self.graph, self.info, nid, d, pin))

    def edit_literal(self, nid, pin):
        if not self.can_edit():
            return
        prompt = canvasedit.literal_prompt(self.graph, self.info, self.idx, nid, pin)
        if prompt is None:
            return
        ty = prompt["type"]
        if ty == "bool":
            self.commit(canvasedit.toggle_bool(self.graph, nid, pin))
            return
        if ty in self.idx.structs:
            if messagebox.askyesno("Set literal", f"A {ty} has no typed value. Add a "
                                   f"'Make {ty}' node wired into {nid}.{pin}?"):
                self.make_for_pin(nid, pin, ty)
            return
        hint = f"\n{prompt['hint']}" if prompt["hint"] else ""
        text = simpledialog.askstring("Set literal", f"{nid}.{pin} : {ty}{hint}\n"
                                      f"(empty: unbind; the pin takes its default)",
                                      initialvalue=prompt["current"], parent=self.root)
        if text is None:
            return
        try:
            reason = canvasedit.set_literal(self.graph, self.info, self.idx, nid, pin, text)
        except canvasedit.Refused as e:
            messagebox.showerror("Invalid literal", str(e))
            return
        self.commit(reason)

    def set_enum_value(self, nid, pin, ty, member):
        if not self.can_edit():
            return
        self.commit(canvasedit.set_enum(self.graph, nid, pin, ty, member))

    def break_struct(self, nid, pin, ty):
        """A BreakStruct to the right of a struct output, wired to it."""
        if not self.can_edit():
            return
        new, reason = canvasedit.break_struct(self.graph, nid, pin, ty, self.geom)
        self.view.selected = ("node", new)
        self.commit(reason)

    def make_for_pin(self, nid, pin, ty):
        """A MakeStruct to the left of a struct input, wired into it."""
        if not self.can_edit():
            return
        new, reason = canvasedit.make_for_pin(self.graph, nid, pin, ty, self.geom)
        self.view.selected = ("node", new)
        self.commit(reason)

    def add_node(self, kind, symbol=None, targs=None, x=0, y=0, attrs=None):
        if not self.can_edit():
            return
        n = ops.create_node(self.graph, kind, symbol, targs, x, y)
        if attrs:
            n.attrs.extend(attrs)
        self.view.selected = ("node", n.id)
        self.commit(f"Added {n.id}")

    def delete_node(self, nid):
        g = self.graph
        n = g.node(nid)
        if n is None:
            return
        if n.kind == "Entry" and not messagebox.askyesno("Delete Entry",
                                                         "Delete the graph's Entry node?"):
            return
        removed = ops.delete_node(g, nid)
        self.commit(f"Deleted {nid}" + (f" and {len(removed)} wire(s): {', '.join(removed)}"
                                        if removed else ""))

    def delete_box(self, bid):
        ops.delete_box(self.graph, bid)
        self.commit(f"Deleted box {bid}")

    def rename_node(self, nid):
        new = simpledialog.askstring("Rename node", f"New id for '{nid}' (renames every wire):",
                                     initialvalue=nid, parent=self.root)
        if not new:
            return
        try:
            reason = canvasedit.rename_node(self.graph, nid, new)
        except canvasedit.Refused as e:
            messagebox.showerror("Rename", str(e))
            return
        if reason is None:
            return
        if self.view.selected == ("node", nid):
            self.view.selected = ("node", new)
        self.commit(reason)

    def set_label(self, nid):
        if not self.can_edit():
            return
        cur = canvasedit.current_prop(self.graph, nid, "label")
        text = simpledialog.askstring("Label", f"Display label for '{nid}' (layout only; empty "
                                               f"to clear):", initialvalue=cur, parent=self.root)
        if text is None:
            return
        self.commit(canvasedit.set_label(self.graph, nid, text, self.auto_pos))

    def set_color(self, nid):
        cur = canvasedit.current_prop(self.graph, nid, "color")
        text = simpledialog.askstring("Colour", "Colour such as #C0392B (empty to clear):",
                                      initialvalue=cur, parent=self.root)
        if text is None:
            return
        try:
            reason = canvasedit.set_color(self.graph, nid, text, self.auto_pos)
        except canvasedit.Refused as e:
            messagebox.showerror("Colour", str(e))
            return
        self.commit(reason)

    def toggle_attr(self, nid, name):
        self.commit(canvasedit.toggle_attr(self.graph, nid, name))

    def set_int_attr(self, nid, name, prompt):
        cur = canvasedit.int_attr(self.graph, nid, name)
        v = simpledialog.askinteger(f"@{name}", prompt, initialvalue=cur, minvalue=1, maxvalue=64,
                                    parent=self.root)
        if v is None:
            return
        self.commit(canvasedit.set_int_attr(self.graph, nid, name, v))

    def set_cases(self, nid):
        prompt, cur = canvasedit.cases_prompt(self.graph, self.idx, nid)
        text = simpledialog.askstring("@cases", prompt, initialvalue=cur, parent=self.root)
        if text is None:
            return
        try:
            reason = canvasedit.set_cases(self.graph, self.idx, nid, text)
        except canvasedit.Refused as e:
            messagebox.showerror("@cases", str(e))
            return
        self.commit(reason)

    def add_note(self, on):
        if not self.can_edit():
            return
        text = simpledialog.askstring("Note", "Note text" + (f" on '{on}'" if on else
                                                               " for the whole graph") + ":",
                                      parent=self.root)
        reason = canvasedit.add_note(self.graph, on, text)
        if reason:
            self.commit(reason)

    def add_box(self, x, y):
        title = simpledialog.askstring("Box", "Box title:", parent=self.root)
        sel = self.view.selected
        reason = canvasedit.add_box(self.graph, x, y, title,
                                    sel[1] if sel and sel[0] == "node" else None)
        if reason:
            self.commit(reason)

    def edit_members(self, bid):
        b = self.graph.box(bid)
        text = simpledialog.askstring("Members", "Member node/box ids, comma separated "
                                                 "(membership is explicit, section 2.3):",
                                      initialvalue=", ".join(b.members()), parent=self.root)
        if text is None:
            return
        self.commit(canvasedit.set_members(self.graph, bid, text))

    def resize_box(self, bid):
        b = self.graph.box(bid)
        text = simpledialog.askstring("Box size", "width, height:", initialvalue=f"{b.w}, {b.h}",
                                      parent=self.root)
        try:
            reason = canvasedit.resize_box(self.graph, bid, text)
        except canvasedit.Refused:
            return
        self.commit(reason)

    def rename_box(self, bid):
        b = self.graph.box(bid)
        text = simpledialog.askstring("Box title", "Title:", initialvalue=b.title, parent=self.root)
        reason = canvasedit.retitle_box(self.graph, bid, text)
        if reason:
            self.commit(reason)

    def new_graph(self, kind):
        if self.module is None or self.parse_error:
            return
        text = simpledialog.askstring(
            f"New {kind}", "Signature, e.g.  Lerp(a: f32, b: f32, t: f32) -> (result: f32)"
            if kind == "func" else "Signature, e.g.  Twice(in: exec) -> (out: exec)",
            parent=self.root)
        if not text:
            return
        try:
            m = parse(f"wiret 1\nmodule x\n{kind} {text} {{\n}}\n")
        except ParseError as e:
            messagebox.showerror("Signature", e.msg)
            return
        g = m.items[0]
        if self.module.graph(g.name):
            messagebox.showerror("Signature", f"'{g.name}' already exists.")
            return
        ops.create_node(g, "Entry", x=0, y=0, nid="entry")
        if kind == "func" and g.results:
            ops.create_node(g, "Return", x=400, y=0, nid="ret")
            g.nodes[0].execs.append(ops.ExecOut(None, "ret"))
        self.module.items.append(g)
        self.graph_name = g.name
        self.commit(f"Created {kind} {g.name}")
        self.after_text_parsed(fit=True)

    def edit_signature(self):
        g = self.graph
        if g is None or not self.can_edit():
            return
        from .printer import fmt_params, fmt_attrs
        cur = g.name + fmt_params(g.params) + (" -> " + fmt_params(g.results) if g.results is not None
                                               else "") + fmt_attrs(g.attrs)
        text = simpledialog.askstring("Signature", "Name, parameters, results and attributes:",
                                      initialvalue=cur, parent=self.root)
        if not text or text == cur:
            return
        try:
            m = parse(f"wiret 1\nmodule x\n{g.kind} {text} {{\n}}\n")
        except ParseError as e:
            messagebox.showerror("Signature", e.msg)
            return
        new = m.items[0]
        g.name, g.params, g.results, g.attrs = new.name, new.params, new.results, new.attrs
        self.graph_name = g.name
        self.commit("Edited signature")
        self.after_text_parsed()

    def add_local(self, kw):
        g = self.graph
        if g is None or not self.can_edit():
            return
        text = simpledialog.askstring(f"Add {kw}", canvasedit.local_prompt(self.idx, kw),
                                      parent=self.root)
        try:
            reason = canvasedit.add_local(g, self.idx, kw, text)
        except canvasedit.Refused as e:
            messagebox.showerror(f"Add {kw}", str(e))
            return
        if reason:
            self.commit(reason)

    def delete_graph(self):
        g = self.graph
        if g is None or not self.can_edit():
            return
        if not messagebox.askyesno("Delete graph", f"Delete {g.kind} {g.name}?"):
            return
        self.module.items.remove(g)
        self.graph_name = None
        self.commit(f"Deleted {g.name}")
        self.after_text_parsed(fit=True)

    # -- context menus ------------------------------------------------------------
    def context_menu(self, h, wx, wy, rx, ry):
        if self.graph is None:
            return
        menu = tk.Menu(self.root, tearoff=0)
        if h is None:
            menu.add_command(label="Search nodes…   (Tab)",
                             command=lambda: self.open_palette(wx, wy, rx, ry))
            menu.add_separator()
            self.fill_add_menu(menu, wx, wy)
            menu.add_separator()
            menu.add_command(label="Add box here…", command=lambda: self.add_box(wx, wy))
            menu.add_command(label="Add graph note…", command=lambda: self.add_note(None))
            menu.add_command(label="Add local…", command=lambda: self.add_local("local"))
        elif h[0] == "node":
            self.node_menu(menu, h[1])
        elif h[0] == "pin":
            _, nid, d, pin = h
            sig = self.info.sigs[nid]
            p = sig.input(pin) if d == "in" else sig.output(pin)
            if d == "in" and p and p.type in self.idx.enums:
                sub = tk.Menu(menu, tearoff=0)
                for member, _ in enum_values(self.idx.enums[p.type]):
                    sub.add_command(label=f"{p.type}::{member}",
                                    command=lambda m=member: self.set_enum_value(nid, pin,
                                                                                 p.type, m))
                menu.add_cascade(label=f"Set '{pin}' to", menu=sub)
            elif d == "in" and p and p.type in self.idx.structs:
                menu.add_command(label=f"Make a {p.type} for '{pin}'",
                                 command=lambda: self.make_for_pin(nid, pin, p.type))
            elif d == "in" and p and not p.is_exec:
                menu.add_command(label=f"Set literal for '{pin}'…",
                                 command=lambda: self.edit_literal(nid, pin))
            if d == "out" and p and p.type in self.idx.structs:
                menu.add_command(label=f"Break '{pin}' into fields",
                                 command=lambda: self.break_struct(nid, pin, p.type))
            menu.add_command(label="Disconnect", command=lambda: self.disconnect(nid, d, pin))
            menu.add_separator()
            self.node_menu(menu, nid)
        elif h[0] in ("box", "boxtitle"):
            bid = h[1]
            menu.add_command(label="Rename title…", command=lambda: self.rename_box(bid))
            menu.add_command(label="Edit members…", command=lambda: self.edit_members(bid))
            menu.add_command(label="Resize…", command=lambda: self.resize_box(bid))
            menu.add_command(label="Colour…", command=lambda: self.set_color(bid))
            menu.add_command(label="Add note…", command=lambda: self.add_note(bid))
            menu.add_separator()
            menu.add_command(label="Delete box", command=lambda: self.delete_box(bid))
            menu.add_separator()
            self.fill_add_menu(menu, wx, wy)
        elif h[0] == "wire":
            _, kind, nid, pin = h
            menu.add_command(label="Delete wire",
                             command=lambda: self.disconnect(nid, "in" if kind == "d" else "out",
                                                             pin))
        elif h[0] == "note":
            nid = h[1]
            menu.add_command(label="Edit note…", command=lambda: self.edit_note(nid))
            menu.add_command(label="Delete note", command=lambda: self.delete_note(nid))
        try:
            menu.tk_popup(rx, ry)
        finally:
            menu.grab_release()

    def edit_note(self, key):
        _, nt = ops.find_note(self.graph, key)
        if nt is None:
            return
        text = simpledialog.askstring("Note", "Text:", initialvalue=note_text(nt), parent=self.root)
        reason = canvasedit.edit_note(self.graph, key, text)
        if reason:
            self.commit(reason)

    def delete_note(self, key):
        self.commit(canvasedit.delete_note(self.graph, key))

    def node_menu(self, menu, nid):
        n = self.graph.node(nid)
        if n is None:
            return
        menu.add_command(label=f"{nid}  ({n.kind})", state="disabled")
        if n.kind in ("Call", "Macro") and n.symbol and self.module.graph(n.symbol.split(".")[-1]):
            menu.add_command(label=f"Open {n.symbol}", command=lambda: self.open_node(nid))
        bp = (self.graph_name, nid) in self.breakpoints
        menu.add_command(label=("Remove breakpoint" if bp else "Set breakpoint") + "  (F9)",
                         command=lambda: self.toggle_breakpoint(nid))
        if "." not in nid:          # an inline node's name says where it is written
            menu.add_command(label="Rename id…", command=lambda: self.rename_node(nid))
        menu.add_command(label="Label…", command=lambda: self.set_label(nid))
        menu.add_command(label="Colour…", command=lambda: self.set_color(nid))
        menu.add_command(label="Add note…", command=lambda: self.add_note(nid))
        if n.kind == "Sequence":
            menu.add_command(label="Set output count (@count)…",
                             command=lambda: self.set_int_attr(nid, "count", "Number of outputs:"))
        if n.kind == "Switch":
            menu.add_command(label="Set cases (@cases)…", command=lambda: self.set_cases(nid))
        if n.kind not in ("Entry",):
            menu.add_command(label=("Enable" if n.attr("disabled") else "Disable") + " (@disabled)",
                             command=lambda: self.toggle_attr(nid, "disabled"))
        menu.add_separator()
        menu.add_command(label="Delete node", command=lambda: self.delete_node(nid))

    def fill_add_menu(self, menu, x, y):
        g, idx = self.graph, self.idx

        def add(m, label, kind, symbol=None, targs=None, attrs=None):
            m.add_command(label=label, command=lambda: self.add_node(kind, symbol, targs, x, y, attrs))

        def typed(m, label, kind, constraint):
            sub = tk.Menu(m, tearoff=0)
            for t in type_choices(constraint, idx):
                add(sub, t, kind, None, [t])
            m.add_cascade(label=label, menu=sub)

        flow = tk.Menu(menu, tearoff=0)
        add(flow, "Branch", "Branch")
        add(flow, "Sequence", "Sequence")
        add(flow, "Try", "Try")
        add(flow, "Throw", "Throw")
        if g.kind != "macro":
            add(flow, "Return", "Return")
        if not any(n.kind == "Entry" for n in g.nodes):
            add(flow, "Entry", "Entry")
        typed(flow, "Select", "Select", "any")
        typed(flow, "Switch", "Switch", "switch")
        sub = tk.Menu(flow, tearoff=0)
        for t in ["exec"] + type_choices("any", idx):
            add(sub, t, "Reroute", None, [t])
        flow.add_cascade(label="Reroute", menu=sub)
        menu.add_cascade(label="Flow", menu=flow)

        time_m = tk.Menu(menu, tearoff=0)
        add(time_m, "Delay (wait seconds)", "Delay")
        add(time_m, "Yield (wait a frame)", "Yield")
        add(time_m, "Await (wait for a signal)", "Await")
        menu.add_cascade(label="Time", menu=time_m)

        math_m = tk.Menu(menu, tearoff=0)
        for k, (cat, _, tps, _) in sorted(STATIC_KINDS.items()):
            if cat == "Math" and k != "Convert":
                typed(math_m, k, k, tps[0])
        conv = tk.Menu(math_m, tearoff=0)
        convertible = type_choices("convertible", idx)
        for f in convertible:
            sub = tk.Menu(conv, tearoff=0)
            for t in convertible:
                if can_convert(f, t, idx):
                    add(sub, t, "Convert", None, [f, t])
            conv.add_cascade(label=f"from {f}", menu=sub)
        math_m.add_cascade(label="Convert", menu=conv)
        menu.add_cascade(label="Math", menu=math_m)

        for cat in ("Compare", "Logic", "Bits"):
            m = tk.Menu(menu, tearoff=0)
            for k, (c, _, tps, _) in sorted(STATIC_KINDS.items()):
                if c == cat:
                    if tps:
                        typed(m, k, k, tps[0])
                    else:
                        add(m, k, k)
            menu.add_cascade(label=cat, menu=m)

        var = tk.Menu(menu, tearoff=0)
        for l in sorted(g.locals, key=lambda l: l.name):
            add(var, f"Get local {l.name}", "GetLocal", l.name)
            add(var, f"Set local {l.name}", "SetLocal", l.name)
        for s in sorted(g.states, key=lambda s: s.name):
            add(var, f"Get state {s.name}", "GetState", s.name)
            add(var, f"Set state {s.name}", "SetState", s.name)
        for v in sorted(idx.vars):
            add(var, f"Get var {v}", "GetVar", v)
            add(var, f"Set var {v}", "SetVar", v)
        for c in sorted(idx.consts):
            add(var, f"Get const {c}", "GetVar", c)
        if var.index("end") is None:
            var.add_command(label="(no locals or variables: Graph > Add local…)", state="disabled")
        menu.add_cascade(label="Variables", menu=var)

        classes = tk.Menu(menu, tearoff=0)
        for name in sorted(idx.classes):
            sub = tk.Menu(classes, tearoff=0)
            add(sub, f"New {name}", "New", name)
            add(sub, f"Cast to {name}", "Cast", name)
            fields = idx.class_fields(name)
            if fields:
                sub.add_separator()
            for _, f in fields:
                add(sub, f"Get {f.name}", "GetField", f"{name}.{f.name}")
            for _, f in fields:
                add(sub, f"Set {f.name}", "SetField", f"{name}.{f.name}")
            classes.add_cascade(label=name, menu=sub)
        for name in sorted(idx.interfaces):
            sub = tk.Menu(classes, tearoff=0)
            add(sub, f"Cast to {name}", "Cast", name)
            sub.add_separator()
            for m in idx.interfaces[name].methods:
                add(sub, f"Call {m.name}", "Call", f"{name}.{m.name}")
            classes.add_cascade(label=f"{name} (interface)", menu=sub)
        if idx.classes:
            classes.add_separator()
            add(classes, "IsValid (not null)", "IsValid")
            menu.add_cascade(label="Classes", menu=classes)

        dlg = tk.Menu(menu, tearoff=0)
        for name in sorted(idx.classes):
            for d in idx.classes[name].dispatchers:
                sub = tk.Menu(dlg, tearoff=0)
                for k in ("Bind", "Unbind", "Broadcast"):
                    add(sub, k, k, f"{name}.{d.name}")
                dlg.add_cascade(label=f"{name}.{d.name}", menu=sub)
        made = tk.Menu(dlg, tearoff=0)
        for name, fg in sorted(idx.graphs.items()):
            if fg.kind == "event" or not fg.has_attr("latent"):
                add(made, name, "CreateDelegate", name)
        if made.index("end") is not None:
            dlg.add_cascade(label="Delegate of", menu=made)
        if dlg.index("end") is not None:
            menu.add_cascade(label="Delegates", menu=dlg)

        structs = tk.Menu(menu, tearoff=0)
        for name in sorted(idx.structs):
            sub = tk.Menu(structs, tearoff=0)
            add(sub, f"Make {name}", "MakeStruct", name)
            add(sub, f"Break {name}", "BreakStruct", name)
            fields = idx.structs[name].fields
            if fields:
                sub.add_separator()
            for f in fields:
                add(sub, f"Get {f.name}", "GetField", f"{name}.{f.name}")
            for f in fields:
                add(sub, f"With {f.name} (changed copy)", "WithField", f"{name}.{f.name}")
            structs.add_cascade(label=name, menu=sub)
        if structs.index("end") is None:
            structs.add_command(label="(no structs: declare one in the Source pane)",
                                state="disabled")
        menu.add_cascade(label="Structs", menu=structs)

        call = tk.Menu(menu, tearoff=0)
        for name in sorted(idx.graphs):
            if idx.graphs[name].kind == "func":
                add(call, name, "Call", name)
        if idx.externs:
            call.add_separator()
            for q in sorted(idx.externs):
                add(call, q, "Call", q)
        by_ns = {}
        for q in sorted(STD):
            by_ns.setdefault(q.rsplit(".", 1)[0], []).append(q)
        for ns, names in by_ns.items():
            sub = tk.Menu(call, tearoff=0)
            for q in names:
                add(sub, q.rsplit(".", 1)[1], "Call", q)
            call.add_cascade(label=ns, menu=sub)
        menu.add_cascade(label="Call", menu=call)

        mac = tk.Menu(menu, tearoff=0)
        for name in sorted(idx.macros):
            if name != g.name:
                add(mac, name, "Macro", name)
        if g.kind == "macro":
            mac.add_separator()
            for r in g.result_list:
                if r.type == "exec":
                    add(mac, f"Exit {r.name}", "Exit", r.name)
                    add(mac, f"Leave {r.name}", "Leave", r.name)
        if mac.index("end") is None:
            mac.add_command(label="(no macros: Graph > New macro…)", state="disabled")
        menu.add_cascade(label="Macro", menu=mac)

    # -- run and debug ------------------------------------------------------------
    def run_counts_for(self, graph_name) -> dict:
        counts = self.last_counts
        return {nid: c for (gname, nid), c in counts.items() if gname == graph_name}

    @property
    def running(self) -> bool:
        return self.run_thread is not None and self.run_thread.is_alive()

    def run_or_continue(self):
        if self.paused:
            self.resume("run")
        elif not self.running:
            self.start("run")

    def step_into(self):
        """Step one node, entering called functions. While running freely, this pauses."""
        if self.paused:
            self.resume("step")
        elif self.running:
            self.dbg.mode = "step"
        else:
            self.start("step")

    def step_over(self):
        """Step one node in the current function, running called functions to completion."""
        if self.paused:
            self.resume("over")
        elif not self.running:
            self.start("over")

    def toggle_breakpoint(self, nid=None):
        if nid is None:
            sel = self.view.selected
            if not sel or sel[0] != "node":
                self.status("Select a node first, then press F9 to toggle a breakpoint on it.")
                return
            nid = sel[1]
        key = (self.graph_name, nid)
        if key in self.breakpoints:
            self.breakpoints.discard(key)
            self.status(f"Removed the breakpoint on {nid}.")
        else:
            self.breakpoints.add(key)
            self.status(f"Breakpoint on {nid}: the program will pause just before it runs.")
        self.view.redraw()

    def start(self, mode):
        if self.module is None or self.path is None:
            return
        if self.parse_error:
            self.log(f"Cannot run: there is a mistake in the text at line {self.parse_error.line}: "
                     f"{self.parse_error.msg}", "err")
            return
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")
        func = self.entry_var.get()
        t0 = time.perf_counter()
        r = compile_module(self.module, self.text, debug=True, project=self.project,
                           export_all=True)     # Run can start any function (section 5.2)
        for d in r.diags:
            where = ".".join(x for x in (d.graph, d.node) if x)
            self.log(f"{d.severity} {d.code} {where}: {explain(d)}",
                     "err" if d.severity == "error" else "dim")
        if not r.ok:
            self.log("The program has errors, so it can't run yet. See the Problems tab.", "err")
            self.notebook.select(1)
            return
        wbc_path = os.path.splitext(self.path)[0] + ".wbc"
        with open(wbc_path, "wb") as f:
            f.write(r.wbc)
        dt = (time.perf_counter() - t0) * 1000
        self.log(f"Compiled {os.path.basename(self.path)} -> {os.path.basename(wbc_path)} "
                 f"({len(r.wbc)} bytes, {dt:.0f} ms)  semantic {semantic_hash(self.module)[:12]}  "
                 f"layout {layout_hash(self.module)[:12]}", "dim")
        self.bytecode.delete("1.0", "end")
        self.bytecode.insert("1.0", disassemble(r.wbc))
        try:
            args = parse_args_for(self.module, func, split_args(self.args_var.get()))
        except ValueError as e:
            self.log(str(e), "err")
            return
        module = self.module
        mod_prefix = module.name + "."
        graph_names = {g.name for g in module.graphs()}
        counts = Counter()
        if mode == "run" and self.animate_var.get():
            mode = "animate"
        dbg = self.dbg = DebugState(mode, self.speed_var.get() / 1000)
        breakpoints = self.breakpoints

        def hook(fname, node, _pending, depth, snapshot, phase):
            g = fname[len(mod_prefix):] if fname.startswith(mod_prefix) else fname
            top = node.split("/")[0].split("!")[0]
            if phase == "enter" and "/" not in node:  # a macro counts once per entry
                counts[(g, top)] += 1
            if phase == "ready" and dbg.stop:
                raise WiretError(STATUS_INTERRUPT, "stopped by the user")
            act = dbg.decide(g, node, depth, phase, breakpoints, graph_names)
            if act == "pause":
                pause(g, top, snapshot, depth, inputs_ready=phase == "ready")
            elif act == "animate":
                self.out_queue.put(("pause", (g, top, snapshot(), False, Counter(counts), True)))
                time.sleep(dbg.delay)

        def pause(g, top, snapshot, depth, inputs_ready):
            dbg.depth = depth
            dbg.resume.clear()
            self.out_queue.put(("pause", (g, top, snapshot(), True, Counter(counts),
                                          inputs_ready)))
            dbg.resume.wait()
            if dbg.stop:
                raise WiretError(STATUS_INTERRUPT, "stopped by the user")

        self.vm = VM(output=lambda s: self.out_queue.put(("out", s)), hook=hook, fuel=self.fuel)
        self.paused = None
        self.set_run_buttons()
        self.src.configure(state="disabled")
        verb = {"step": "Stepping through", "over": "Stepping through",
                "animate": "Animating"}.get(mode, "Running")
        self.log(f"{verb} {func}({', '.join(map(str, args))}) from {os.path.basename(wbc_path)}",
                 "dim")

        def work():
            t1 = time.perf_counter()
            try:
                with open(wbc_path, "rb") as f:
                    data = f.read()
                lm = self.vm.load(data)
                self.loaded = lm
                res = run_function(self.vm, lm, func, args)
                ms = (time.perf_counter() - t1) * 1000
                self.out_queue.put(("done", (format_results(module, func, res), ms, counts, None)))
            except WiretError as e:
                ms = (time.perf_counter() - t1) * 1000
                self.out_queue.put(("done", (None, ms, counts, e)))

        self.run_thread = threading.Thread(target=work, daemon=True)
        self.run_thread.start()

    def resume(self, mode):
        dbg = self.dbg
        if dbg is None or not self.paused:
            return
        dbg.mode = mode
        self.paused = None
        self.set_run_buttons()
        self.status("Running…")
        dbg.resume.set()

    def stop(self):
        if self.dbg:
            self.dbg.stop = True
            self.dbg.resume.set()
        if self.vm:
            self.vm.interrupt()

    def set_run_buttons(self):
        running, paused = self.running or self.paused is not None, self.paused is not None
        self.run_btn.config(text="▶ Continue" if paused else "▶ Run",
                            state="normal" if (paused or not running) else "disabled")
        self.step_btn.config(text="⏸ Pause" if running and not paused else "⤵ Step")
        self.over_btn.config(state="normal" if (paused or not running) else "disabled")
        self.stop_btn.config(state="normal" if running else "disabled")

    def drain_output(self):
        try:
            for _ in range(200):
                kind, payload = self.out_queue.get_nowait()
                if kind == "out":
                    self.log(payload, "out")
                elif kind == "pause":
                    self.show_pause(*payload)
                elif kind == "done":
                    self.finish_run(*payload)
        except queue.Empty:
            pass
        self.root.after(30, self.drain_output)

    def show_pause(self, graph, node, frames, waiting, counts, inputs_ready=True):
        self.frames = frames
        self.paused = (graph, node) if waiting else None
        self.last_counts = dict(counts)
        self.show_frame(len(frames) - 1)
        self.set_run_buttons()
        if waiting:
            self.notebook.select(self.debug_tab)
            n = self.graph.node(node) if self.graph else None
            what = f"{n.kind}{' ' + n.symbol if n and n.symbol else ''}" if n else ""
            why = " (breakpoint)" if (graph, node) in self.breakpoints else ""
            inputs = ("Its inputs are shown on the wires." if inputs_ready else
                      "Its inputs haven't been worked out yet; Step to compute them.")
            self.status(f"Paused{why} just before {node} ({what}) runs. {inputs} Step (F11) runs "
                        f"one node; Step Over (F10) runs calls in one go; Continue (F5).")

    def show_frame(self, i):
        if not self.frames:
            return
        fr = self.frames[i]
        prefix = self.module.name + "."
        g = fr.func.name[len(prefix):] if fr.func.name.startswith(prefix) else fr.func.name
        if g != self.graph_name and self.module.graph(g):
            self.select_graph(g, fit=True)
        top = (fr.node or "").split("/")[0].split("!")[0]
        self.view.current_node = top
        self.view.pin_values = {(n, p): v for (n, p), v in fr.pin_values().items()
                                if "/" not in n and "!" not in n}
        self.view.run_counts = self.run_counts_for(g)
        self.view.redraw()
        self.stack_tree.delete(*self.stack_tree.get_children())
        for k, f in reversed(list(enumerate(self.frames))):
            name = f.func.name[len(prefix):] if f.func.name.startswith(prefix) else f.func.name
            node = (f.node or "").split("/")[0].split("!")[0]
            self.stack_tree.insert("", "end", iid=str(k), values=(name, node))
        self.stack_tree.selection_set(str(i))
        self.vars_tree.delete(*self.vars_tree.get_children())
        gdef = self.module.graph(g)
        values = fr.named_locals()
        if gdef:
            for kind, items in (("parameter", gdef.params), ("local", gdef.locals)):
                for p in items:
                    if p.name in values:
                        self.vars_tree.insert("", "end", values=(
                            p.name, f"{kind} {p.type}", format_value(p.type, values[p.name], self.idx)))
        lm = getattr(self, "loaded", None)
        if lm is not None:
            for v in sorted(self.idx.vars.values(), key=lambda v: v.name):
                gi = lm.global_names.get(v.name)
                if gi is not None:
                    self.vars_tree.insert("", "end", values=(
                        v.name, f"variable {v.type}", format_value(v.type, lm.globals[gi], self.idx)))

    def on_stack_select(self, _e=None):
        """Show the graph and wire values of the frame picked in the call stack."""
        sel = self.stack_tree.selection()
        if not sel or not self.frames:
            return
        fr = self.frames[int(sel[0])]
        prefix = self.module.name + "."
        g = fr.func.name[len(prefix):] if fr.func.name.startswith(prefix) else fr.func.name
        if g != self.graph_name and self.module.graph(g):
            self.select_graph(g, fit=True)
        self.view.current_node = (fr.node or "").split("/")[0].split("!")[0]
        self.view.pin_values = {(n, p): v for (n, p), v in fr.pin_values().items()
                                if "/" not in n and "!" not in n}
        self.view.redraw()

    def finish_run(self, result, ms, counts, err):
        self.paused = None
        self.frames = []
        self.dbg = None
        self.run_thread = None
        self.src.configure(state="normal")
        self.set_run_buttons()
        self.view.current_node = None
        self.view.pin_values = {}
        stats = self.vm.stats if self.vm else {}
        used = (self.vm.fuel_limit - self.vm.fuel) if self.vm else 0
        self.last_counts = dict(counts)
        self.fault = {}
        if err is None:
            self.log(f"Finished: {result}", "ok")
            self.status("The program finished. Green outlines show which nodes ran, and how often.")
        else:
            mod_prefix = self.module.name + "."
            where = ""
            for fn, node in reversed(err.traceback):
                g = fn[len(mod_prefix):] if fn.startswith(mod_prefix) else fn
                if node and self.module.graph(g):
                    top = node.split("/")[0].split("!")[0]
                    self.fault[g] = top
                    where = f"node '{top}' of {g}"
                    break
            friendly = explain_runtime(err.status, err.message, where)
            self.log(friendly, "err" if err.status != "WR_ERR_INTERRUPT" else "dim")
            self.log(str(err), "dim")
            self.status(friendly)
            if self.fault and self.graph_name not in self.fault:
                self.select_graph(next(iter(self.fault)), fit=True)
        self.log(f"{stats.get('instructions', 0)} instructions, {stats.get('calls', 0)} calls, "
                 f"{used} fuel, {ms:.1f} ms", "dim")
        self.view.run_counts = self.run_counts_for(self.graph_name)
        self.view.fault_node = self.fault.get(self.graph_name)
        self.view.redraw()


def main(path=None):
    root = tk.Tk()
    EditorApp(root, path)
    root.mainloop()
