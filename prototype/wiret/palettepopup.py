"""The desktop editor's node palette window (Tkinter). What it lists, and how a search ranks
it, is in palette.py, which the web page uses too."""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from .palette import Item, rank  # noqa: F401  (Item: the type of what on_pick receives)


class PalettePopup(tk.Toplevel):
    """A small search window: type to filter, Enter to add, Escape to close."""

    def __init__(self, master, x_root: int, y_root: int, all_items: list,
                 on_pick: Callable[[Item], None], title: str = "Add node"):
        super().__init__(master)
        self.overrideredirect(True)
        self.configure(bg="#2b2e35", padx=1, pady=1)
        self.items = all_items
        self.on_pick = on_pick
        frame = tk.Frame(self, bg="#1d1f23")
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text=title, bg="#1d1f23", fg="#8a8f98", anchor="w",
                 font=("Helvetica", 11)).pack(fill="x", padx=8, pady=(6, 0))
        self.var = tk.StringVar()
        self.entry = tk.Entry(frame, textvariable=self.var, font=("Helvetica", 14), bg="#15171a",
                              fg="white", insertbackground="white", relief="flat")
        self.entry.pack(fill="x", padx=8, pady=6, ipady=3)
        self.listbox = tk.Listbox(frame, height=12, width=44, font=("Helvetica", 13),
                                  bg="#15171a", fg="#e8e8e8", selectbackground="#2471a3",
                                  activestyle="none", relief="flat", highlightthickness=0)
        self.listbox.pack(fill="both", expand=True, padx=8)
        self.desc = tk.Label(frame, text="", bg="#1d1f23", fg="#f7dc6f", anchor="w",
                             justify="left", wraplength=380, font=("Helvetica", 12))
        self.desc.pack(fill="x", padx=8, pady=6)
        self.shown: list = []
        self.var.trace_add("write", lambda *_: self.refilter())
        self.entry.bind("<Down>", lambda e: self.move(1))
        self.entry.bind("<Up>", lambda e: self.move(-1))
        self.entry.bind("<Return>", lambda e: self.pick())
        self.entry.bind("<Escape>", lambda e: self.destroy())
        self.listbox.bind("<Double-Button-1>", lambda e: self.pick())
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.show_desc())
        self.bind("<FocusOut>", self._focus_out)
        self.refilter()
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry(f"+{min(x_root, sw - w - 10)}+{min(y_root, sh - h - 40)}")
        self.lift()
        self.entry.focus_force()

    def _focus_out(self, _e):
        self.after(100, lambda: self.winfo_exists() and self.focus_get() is None and self.destroy())

    def refilter(self):
        self.shown = rank(self.items, self.var.get())[:200]
        self.listbox.delete(0, "end")
        for it in self.shown:
            self.listbox.insert("end", f"  {it.label}")
            self.listbox.itemconfig("end", foreground="#e8e8e8")
        if self.shown:
            self.listbox.selection_set(0)
        self.show_desc()

    def move(self, d):
        if not self.shown:
            return
        cur = self.listbox.curselection()
        i = max(0, min(len(self.shown) - 1, (cur[0] if cur else 0) + d))
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(i)
        self.listbox.see(i)
        self.show_desc()

    def show_desc(self):
        cur = self.listbox.curselection()
        if cur and self.shown:
            it = self.shown[cur[0]]
            self.desc.config(text=f"{it.category}: {it.description}" if it.description
                             else it.category)
        else:
            self.desc.config(text="No matching nodes." if self.var.get() else "")

    def pick(self):
        cur = self.listbox.curselection()
        if not cur or not self.shown:
            return
        it = self.shown[cur[0]]
        self.destroy()
        self.on_pick(it)
