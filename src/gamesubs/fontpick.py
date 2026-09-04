# -*- coding: utf-8 -*-
"""Choose a font by looking at it, in the style it will actually appear in.

The preview is drawn by the same code that draws the real subtitles -- same Pillow path, same
plate, same outline, same size. A chooser that previews through a different renderer will
recommend a font that then looks wrong in the overlay, and that is not hypothetical: the first
version of this compared fonts through tkinter, which is the renderer that could not place Thai
marks in the first place.

The sample words are the hard case on purpose. `ซื้อ` needs a vowel and a tone mark stacked on one
consonant; a font that cannot do it draws `ซือ`, which is a different word, rendered confidently,
with nothing anywhere reporting a problem. There is no automatic verdict on that -- three were
written and all three were wrong -- so the words go on screen at readable size and a person looks.
"""
import os
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

from . import render

BG = "#14171a"
FG = "#e8eaed"
DIM = "#9aa0a6"
ACCENT = "#3fa7ff"
PREVIEW_BG = "#1d2126"

# Drawn under every candidate as a second opinion. Chosen because it was checked by eye on words
# where a tone mark stacks on a vowel, and it places them correctly without a text shaper.
REFERENCE = "LeelawUI"


def _label(path):
    return os.path.splitext(os.path.basename(path))[0]


def choose(fonts_dir, sample=None, size=30, current=None):
    """Returns the chosen font's path, or None if the window was closed."""
    sample = sample or "  ".join(render.STACKED_SAMPLES[:4])
    paths = []
    seen = set()
    for p in render.folder_fonts(fonts_dir) + render.system_fonts():
        k = os.path.basename(p).lower()
        if k in seen:
            continue
        seen.add(k)
        try:
            if render.has_glyphs(render.load(p, 22), sample):
                paths.append(p)
        except Exception:
            continue
    if not paths:
        raise SystemExit(
            "no font on this machine can draw %r.\n"
            "Drop a .ttf or .otf that covers your language into:\n  %s" % (sample, fonts_dir))

    # Fonts you put in the folder yourself come first: you put them there for a reason.
    infolder = [p for p in paths if os.path.dirname(p).lower() == fonts_dir.lower()]
    rest = [p for p in paths if p not in infolder]
    paths = infolder + rest

    picked = {"v": None}
    root = tk.Tk()
    root.title("Choose a font")
    root.configure(bg=BG)
    root.resizable(False, False)

    tk.Label(root, text="Which font should the subtitles use?", bg=BG, fg=FG,
             font=("Segoe UI", 12, "bold")).pack(padx=20, pady=(18, 2), anchor="w")
    tk.Label(root, text="Look at the marks ABOVE the letters. A font that cannot stack them "
                        "draws  ซือ  where it should draw  ซื้อ.",
             bg=BG, fg=DIM, font=("Segoe UI", 9)).pack(padx=20, anchor="w")

    labels = [_label(p) + ("   (fonts folder)" if p in infolder else "") for p in paths]
    by_label = dict(zip(labels, paths))
    # Start on something known to work, so a person who does not look closely still gets a font
    # that draws their language correctly.
    start = next((lab for lab, q in zip(labels, paths)
                  if os.path.basename(q).lower().startswith(REFERENCE.lower())), labels[0])
    if current:
        for lab, p in by_label.items():
            if os.path.basename(p).lower() == os.path.basename(current).lower():
                start = lab
                break

    var = tk.StringVar(value=start)
    box = ttk.Combobox(root, textvariable=var, values=labels, state="readonly", width=54)
    box.pack(padx=20, pady=(12, 8))

    canvas = tk.Label(root, bg=PREVIEW_BG, bd=0)
    canvas.pack(padx=20, pady=(0, 6))
    keep = {}

    reference = render.resolve_font(REFERENCE, sample, fonts_dir)

    def refresh(*_):
        """Draw the candidate, and a font known to place marks correctly, one above the other.

        Side by side is the whole trick. Four automatic checks for "are the marks in the right
        place" were written and all four were wrong -- they agree on every font, correct or not,
        because the mark IS drawn either way, just at the wrong height. Put the same word in two
        fonts one line apart and the difference is obvious in half a second, with no metric at all.

        This exists because it went wrong for real: the picker allowed a font that draws เพื่อ with
        the tone mark collapsed onto the vowel, the small preview did not make that visible, and it
        was only caught by reading the subtitles in a live game.
        """
        p = by_label[var.get()]
        rows = [("this font", p)]
        if reference and os.path.basename(reference).lower() != os.path.basename(p).lower():
            rows.append(("known good", reference))
        ims = [(tag, render.draw_line(sample, "", render.load(q, size), render.load(q, 16), 900))
               for tag, q in rows]
        w = max(im.width for _, im in ims) + 130
        h = sum(im.height for _, im in ims) + 16 * len(ims) + 8
        flat = Image.new("RGB", (max(w, 600), h), PREVIEW_BG)
        d = ImageDraw.Draw(flat)
        small = render.load(reference or p, 13)
        y = 8
        for tag, im in ims:
            d.text((10, y + im.height // 2 - 8), tag, font=small, fill="#9aa0a6")
            flat.paste(im, (120, y), im)
            y += im.height + 16
        keep["img"] = ImageTk.PhotoImage(flat)
        canvas.configure(image=keep["img"])

    def go(*_):
        picked["v"] = by_label[var.get()]
        root.destroy()

    row = tk.Frame(root, bg=BG)
    row.pack(padx=20, pady=(6, 18), fill="x")
    tk.Button(row, text="Use this font", command=go, bg=ACCENT, fg="#04121f",
              font=("Segoe UI", 10, "bold"), relief="flat", padx=18, pady=4).pack(side="right")
    tk.Button(row, text="Cancel", command=root.destroy, bg=BG, fg=DIM, relief="flat",
              padx=12, pady=4).pack(side="right", padx=(0, 8))
    tk.Label(row, text="%d fonts can draw it" % len(paths), bg=BG, fg=DIM,
             font=("Segoe UI", 9)).pack(side="left")

    box.bind("<<ComboboxSelected>>", refresh)
    root.bind("<Return>", go)
    root.bind("<Escape>", lambda *_: root.destroy())
    refresh()

    root.update_idletasks()
    root.geometry("+%d+%d" % ((root.winfo_screenwidth() - root.winfo_width()) // 2,
                              (root.winfo_screenheight() - root.winfo_height()) // 3))
    root.attributes("-topmost", True)
    box.focus_set()
    root.mainloop()
    return picked["v"]
