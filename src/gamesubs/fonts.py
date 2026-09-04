# -*- coding: utf-8 -*-
"""Show the same line in every font that can actually draw it, so you can pick one by eye.

A font either has your script's glyphs or it does not, and that part is measurable: render the
same string in the candidate and in a font that definitely lacks the script, and if the two widths
are identical you are looking at the same fallback in both. That check is worth running -- a
silently substituted font looks fine in a screenshot and wrong to a reader.

BUT IT ONLY ANSWERS THE EASY HALF. Having the glyphs is not the same as placing them, and for Thai,
Devanagari, Arabic and anything else with marks that attach to a base letter, placement is where it
goes wrong. Windows will happily stitch a missing Thai vowel in from some other font mid-line, and
what you get is marks that float away from the letters they belong to.

There is no width you can measure that catches that. So this puts the candidates on screen at the
size the overlay uses and lets you look, which is the only judge that works.
"""
import tkinter as tk
import tkinter.font as tkfont

# A font with no Thai and essentially no text shaping: whatever it measures is the fallback.
PROBE = "Wingdings"

# Ordered by how they have held up in practice; the list is a starting point, not a verdict.
CANDIDATES = [
    "Noto Sans Thai", "Noto Sans Thai Looped", "Leelawadee UI", "Leelawadee", "Tahoma",
    "IBM Plex Sans Thai", "Sarabun", "Prompt", "Kanit", "Angsana New", "Cordia New",
    "Noto Sans", "Segoe UI", "Arial", "Google Sans",
]

SAMPLE = "ที่นี่มีสระอิอีอูและวรรณยุกต์ไม้โท"


def survey(root, sample=SAMPLE, families=None):
    """[(family, width, has_own_glyphs)] for every installed candidate."""
    have = set(tkfont.families(root))
    probe = tkfont.Font(root=root, family=PROBE, size=24).measure(sample)
    out = []
    for f in (families or CANDIDATES):
        if f not in have:
            continue
        w = tkfont.Font(root=root, family=f, size=24).measure(sample)
        out.append((f, w, w != probe))
    return out


def show(sample=SAMPLE, size=28, families=None):
    """A window with the sample drawn in each candidate. Returns nothing; you are the judge."""
    root = tk.Tk()
    root.title("Which of these is drawn correctly?")
    root.configure(bg="#14171a")

    rows = survey(root, sample, families)
    tk.Label(root, text="Same line, every font that can draw it. Look at where the marks sit.",
             bg="#14171a", fg="#e8eaed", font=("Segoe UI", 11, "bold")
             ).pack(padx=20, pady=(16, 2), anchor="w")
    tk.Label(root, text="Greyed-out rows are not really drawing it -- they measure the same as a "
                        "font with no glyphs at all,\nso Windows is substituting, and substitution "
                        "is what makes marks float away from their letters.",
             bg="#14171a", fg="#9aa0a6", font=("Segoe UI", 9), justify="left"
             ).pack(padx=20, pady=(0, 12), anchor="w")

    for fam, w, own in rows:
        line = tk.Frame(root, bg="#14171a")
        line.pack(fill="x", padx=20, pady=2)
        tk.Label(line, text="%-22s" % fam, bg="#14171a", fg="#e8eaed" if own else "#5f6368",
                 font=("Consolas", 9), width=24, anchor="w").pack(side="left")
        tk.Label(line, text=sample, bg="#000000" if own else "#1a1c1e",
                 fg="#ffffff" if own else "#6b6f73", font=(fam, size), padx=10, pady=3
                 ).pack(side="left")
        tk.Label(line, text="%4d px%s" % (w, "" if own else "  (fallback)"), bg="#14171a",
                 fg="#5f6368", font=("Consolas", 8)).pack(side="left", padx=8)

    tk.Label(root, text="Pick one and start with:   --font \"<name>\"", bg="#14171a", fg="#3fa7ff",
             font=("Consolas", 10)).pack(padx=20, pady=(14, 16), anchor="w")
    root.bind("<Escape>", lambda *_: root.destroy())
    root.attributes("-topmost", True)
    root.mainloop()
    return rows
