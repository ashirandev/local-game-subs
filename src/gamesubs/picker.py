# -*- coding: utf-8 -*-
"""A small window for choosing which model to translate with.

The models folder is a drop box: put any vision GGUF in it, with its `mmproj-*.gguf` projector,
and it appears here. That is the whole point of keeping everything in one folder -- swapping the
brain should be copying a file in, not editing a config.

Shown only when there is a choice to make. One model in the folder and it starts straight away,
because a dialog whose dropdown has one entry is a dialog that only wastes a click.
"""
import os
import tkinter as tk
from tkinter import ttk

from .server import list_models, match_projector

BG = "#14171a"
FG = "#e8eaed"
DIM = "#9aa0a6"
ACCENT = "#3fa7ff"


def _mb(path):
    try:
        return os.path.getsize(path) / 1048576.0
    except OSError:
        return 0.0


def choose(models_dir, title="Choose a model"):
    """Returns (weight_path, projector_path), or None if the window was closed."""
    weights, projectors = list_models(models_dir)
    if not weights:
        return None

    picked = {"v": None}
    root = tk.Tk()
    root.title(title)
    root.configure(bg=BG)
    root.resizable(False, False)

    labels, pairs = [], {}
    for w in weights:
        p = match_projector(w, projectors)
        label = "%s   (%.1f GB)%s" % (w, _mb(os.path.join(models_dir, w)) / 1024.0,
                                      "" if p else "   -- no projector, cannot see")
        labels.append(label)
        pairs[label] = (os.path.join(models_dir, w),
                        os.path.join(models_dir, p) if p else None)

    tk.Label(root, text="Which model should read your screen?", bg=BG, fg=FG,
             font=("Segoe UI", 12, "bold")).pack(padx=20, pady=(18, 2), anchor="w")
    tk.Label(root, text=models_dir, bg=BG, fg=DIM, font=("Segoe UI", 8)).pack(padx=20, anchor="w")

    var = tk.StringVar(value=labels[0])
    box = ttk.Combobox(root, textvariable=var, values=labels, state="readonly", width=58)
    box.pack(padx=20, pady=(12, 4))

    note = tk.Label(root, text="", bg=BG, fg=DIM, font=("Segoe UI", 9), justify="left")
    note.pack(padx=20, pady=(0, 10), anchor="w")

    def refresh(*_):
        m, p = pairs[var.get()]
        note.configure(
            text=("projector: %s" % os.path.basename(p)) if p else
            "This model has no mmproj-*.gguf beside it. A vision model is two files, and without\n"
            "the second one the server starts, answers text, and fails on every picture.",
            fg=DIM if p else "#ff8a80")
        start.configure(state="normal" if p else "disabled")

    def go(*_):
        picked["v"] = pairs[var.get()]
        root.destroy()

    row = tk.Frame(root, bg=BG)
    row.pack(padx=20, pady=(0, 18), fill="x")
    start = tk.Button(row, text="Start", command=go, bg=ACCENT, fg="#04121f",
                      font=("Segoe UI", 10, "bold"), relief="flat", padx=18, pady=4)
    start.pack(side="right")
    tk.Button(row, text="Cancel", command=root.destroy, bg=BG, fg=DIM, relief="flat",
              padx=12, pady=4).pack(side="right", padx=(0, 8))

    box.bind("<<ComboboxSelected>>", refresh)
    root.bind("<Return>", go)
    root.bind("<Escape>", lambda *_: root.destroy())
    refresh()

    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    root.geometry("+%d+%d" % ((root.winfo_screenwidth() - w) // 2,
                              (root.winfo_screenheight() - h) // 3))
    root.attributes("-topmost", True)
    box.focus_set()
    root.mainloop()
    return picked["v"]
