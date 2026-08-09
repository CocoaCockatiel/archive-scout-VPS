from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import ttk

LIGHT = {
    "bg": "#f4f6f8",
    "panel": "#ffffff",
    "sidebar": "#172033",
    "sidebar_hover": "#26344f",
    "sidebar_text": "#f7f9fc",
    "text": "#18202d",
    "muted": "#667085",
    "border": "#d0d5dd",
    "accent": "#2563eb",
    "accent_active": "#1d4ed8",
    "success": "#15803d",
    "warning": "#b45309",
    "danger": "#b42318",
    "selection": "#dbeafe",
    "input": "#ffffff",
}

DARK = {
    "bg": "#111827",
    "panel": "#182235",
    "sidebar": "#0b1220",
    "sidebar_hover": "#24324a",
    "sidebar_text": "#f8fafc",
    "text": "#e5e7eb",
    "muted": "#9ca3af",
    "border": "#344054",
    "accent": "#60a5fa",
    "accent_active": "#93c5fd",
    "success": "#4ade80",
    "warning": "#fbbf24",
    "danger": "#f87171",
    "selection": "#1e3a5f",
    "input": "#101827",
}

REVIEW_COLORS = {
    "relevant": "#dcfce7",
    "possibly_relevant": "#fef3c7",
    "false_positive": "#fee2e2",
    "duplicate": "#e0e7ff",
    "dead_end": "#e5e7eb",
    "needs_follow_up": "#ffedd5",
    "unreviewed": "#f8fafc",
}


def detect_system_theme(root: tk.Misc | None = None) -> str:
    env = os.environ.get("ARCHIVE_SCOUT_THEME", "").strip().casefold()
    if env in {"light", "dark"}:
        return env
    if sys.platform == "darwin" and root is not None:
        try:
            value = root.tk.call("exec", "defaults", "read", "-g", "AppleInterfaceStyle")
            if str(value).casefold() == "dark":
                return "dark"
        except Exception:
            pass
    return "light"


def palette_for(root: tk.Misc, requested: str) -> tuple[str, dict[str, str]]:
    name = requested.strip().casefold()
    if name == "system":
        name = detect_system_theme(root)
    if name not in {"light", "dark"}:
        name = "light"
    return name, DARK if name == "dark" else LIGHT


def apply_theme(root: tk.Tk, requested: str = "system", font_scale: float = 1.0) -> tuple[str, dict[str, str]]:
    resolved, colors = palette_for(root, requested)
    scale = min(1.75, max(0.8, float(font_scale)))
    root.tk.call("tk", "scaling", scale)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.configure(background=colors["bg"])
    base_font = ("TkDefaultFont", 10)
    style.configure(".", background=colors["bg"], foreground=colors["text"], font=base_font)
    style.configure("TFrame", background=colors["bg"])
    style.configure("Panel.TFrame", background=colors["panel"], relief="flat")
    style.configure("TLabel", background=colors["bg"], foreground=colors["text"])
    style.configure("Panel.TLabel", background=colors["panel"], foreground=colors["text"])
    style.configure("Muted.TLabel", background=colors["bg"], foreground=colors["muted"])
    style.configure("Title.TLabel", background=colors["bg"], foreground=colors["text"], font=("TkDefaultFont", 20, "bold"))
    style.configure("Section.TLabel", background=colors["bg"], foreground=colors["text"], font=("TkDefaultFont", 12, "bold"))
    style.configure("CardValue.TLabel", background=colors["panel"], foreground=colors["accent"], font=("TkDefaultFont", 19, "bold"))
    style.configure("CardTitle.TLabel", background=colors["panel"], foreground=colors["muted"])
    style.configure("TLabelFrame", background=colors["bg"], foreground=colors["text"], bordercolor=colors["border"], relief="solid")
    style.configure("TLabelFrame.Label", background=colors["bg"], foreground=colors["text"], font=("TkDefaultFont", 10, "bold"))
    style.configure("TButton", padding=(10, 6), background=colors["panel"], foreground=colors["text"], bordercolor=colors["border"])
    style.map("TButton", background=[("active", colors["selection"]), ("pressed", colors["selection"])])
    style.configure("Accent.TButton", background=colors["accent"], foreground="#ffffff", bordercolor=colors["accent"], font=("TkDefaultFont", 10, "bold"))
    style.map("Accent.TButton", background=[("active", colors["accent_active"]), ("pressed", colors["accent_active"])])
    style.configure("Danger.TButton", foreground=colors["danger"])
    style.configure("Sidebar.TFrame", background=colors["sidebar"])
    style.configure("Sidebar.TLabel", background=colors["sidebar"], foreground=colors["sidebar_text"])
    style.configure("Sidebar.TButton", background=colors["sidebar"], foreground=colors["sidebar_text"], borderwidth=0, anchor="w", padding=(14, 9))
    style.map("Sidebar.TButton", background=[("active", colors["sidebar_hover"]), ("pressed", colors["sidebar_hover"])])
    style.configure("SidebarActive.TButton", background=colors["accent"], foreground="#ffffff", borderwidth=0, anchor="w", padding=(14, 9), font=("TkDefaultFont", 10, "bold"))
    style.map("SidebarActive.TButton", background=[("active", colors["accent_active"])])
    style.configure("Status.TLabel", background=colors["panel"], foreground=colors["text"], padding=(8, 5))
    style.configure("TEntry", fieldbackground=colors["input"], foreground=colors["text"], insertcolor=colors["text"], bordercolor=colors["border"])
    style.configure("TCombobox", fieldbackground=colors["input"], foreground=colors["text"], background=colors["panel"], arrowcolor=colors["text"])
    style.map("TCombobox", fieldbackground=[("readonly", colors["input"])], foreground=[("readonly", colors["text"])])
    style.configure("Treeview", background=colors["panel"], fieldbackground=colors["panel"], foreground=colors["text"], rowheight=max(24, int(24 * scale)), bordercolor=colors["border"])
    style.map("Treeview", background=[("selected", colors["accent"])], foreground=[("selected", "#ffffff")])
    style.configure("Treeview.Heading", background=colors["bg"], foreground=colors["text"], font=("TkDefaultFont", 10, "bold"), padding=(6, 6))
    style.configure("TNotebook", background=colors["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", padding=(10, 6))
    style.layout("Sidebar.TNotebook.Tab", [])
    style.configure("Sidebar.TNotebook", background=colors["bg"], borderwidth=0)
    style.configure("Horizontal.TProgressbar", background=colors["accent"], troughcolor=colors["border"], bordercolor=colors["border"])
    return resolved, colors


def apply_text_theme(widget: tk.Misc, colors: dict[str, str]) -> None:
    for child in widget.winfo_children():
        if isinstance(child, (tk.Text, tk.Listbox)):
            try:
                child.configure(
                    background=colors["input"],
                    foreground=colors["text"],
                    insertbackground=colors["text"],
                    selectbackground=colors["accent"],
                    selectforeground="#ffffff",
                    highlightbackground=colors["border"],
                    highlightcolor=colors["accent"],
                    relief="flat",
                )
            except tk.TclError:
                pass
        apply_text_theme(child, colors)
