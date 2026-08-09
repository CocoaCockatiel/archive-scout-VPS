from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ToolTip:
    def __init__(self, widget: tk.Misc, text: str, delay_ms: int = 500) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.after_id: str | None = None
        self.window: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add=True)
        widget.bind("<Leave>", self.hide, add=True)
        widget.bind("<ButtonPress>", self.hide, add=True)

    def _schedule(self, _event=None) -> None:
        self.hide()
        self.after_id = self.widget.after(self.delay_ms, self.show)

    def show(self) -> None:
        self.after_id = None
        if self.window or not self.text:
            return
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        window.wm_geometry(f"+{x}+{y}")
        ttk.Label(window, text=self.text, padding=(8, 5), wraplength=420, style="Status.TLabel").pack()
        self.window = window

    def hide(self, _event=None) -> None:
        if self.after_id:
            try:
                self.widget.after_cancel(self.after_id)
            except tk.TclError:
                pass
            self.after_id = None
        if self.window:
            self.window.destroy()
            self.window = None


class CollapsibleFrame(ttk.Frame):
    def __init__(self, master, text: str, initially_open: bool = False, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.open_var = tk.BooleanVar(value=initially_open)
        self.button = ttk.Checkbutton(self, text=text, variable=self.open_var, command=self._toggle, style="Toolbutton")
        self.button.grid(row=0, column=0, sticky="w")
        self.body = ttk.Frame(self)
        self.body.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.columnconfigure(0, weight=1)
        self._toggle()

    def _toggle(self) -> None:
        if self.open_var.get():
            self.body.grid()
        else:
            self.body.grid_remove()
