# -*- coding: utf-8 -*-
"""Draw the same words in every available font, so you can pick one by looking at them.

Drawn with the SAME code that draws the subtitles -- Pillow, from a font file. A chooser that
previews through a different renderer than the one doing the work will happily recommend a font
that then looks wrong in the overlay, which is exactly what happened here once already.

The samples are the hard case on purpose: Thai words where two marks stack on one consonant.
`ซื้อ` needs a vowel and a tone mark on the same ซ, and a font that cannot stack them silently
draws `ซือ` -- a different word, rendered confidently, with nothing reporting a problem.

There is no automatic verdict on that column, and not for want of trying. Three checks were
written and all three were wrong: comparing pictures says every font passes, and comparing ink
height says every font fails, because a well-made Thai font lowers the vowel when a tone mark
joins it and the total height does not change by design. Whether a mark sits where it belongs is
something you look at.
"""
import os

from PIL import Image, ImageDraw

from .render import STACKED_SAMPLES, folder_fonts, has_glyphs, load, system_fonts

ROW_H = 74
NAME_W = 260
BG = (12, 14, 16)
OK_BG = (0, 0, 0)
BAD_BG = (26, 14, 14)


def candidates(extra_dir=None, sample=None):
    """Every font file that can draw `sample`, folder fonts first."""
    sample = sample or "".join(STACKED_SAMPLES)
    seen, out = set(), []
    for p in (folder_fonts(extra_dir) if extra_dir else []) + system_fonts():
        key = os.path.basename(p).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            if has_glyphs(load(p, 24), sample):
                out.append(p)
        except Exception:
            continue
    return out


def sheet(paths, size=40, words=None, out_path="font-comparison.png"):
    """One image, one row per font, the same words in each. Returns the path written."""
    words = words or STACKED_SAMPLES
    text = "   ".join(words)
    rows = paths or []
    if not rows:
        raise SystemExit("no font on this machine can draw those words. Drop a .ttf that covers "
                         "your language into the fonts folder.")
    width = NAME_W + 40 * len(text)
    im = Image.new("RGB", (width, ROW_H * len(rows) + 60), BG)
    d = ImageDraw.Draw(im)
    # The header names the Thai words, so it has to be drawn in a font that HAS Thai -- PIL's
    # built-in default does not, and would print the explanation as a row of boxes.
    hf = load(rows[0], 15)
    d.text((16, 12), "Same words, every usable font. Look at the marks above the letters.",
           font=hf, fill=(232, 234, 237))
    d.text((16, 32), "A font that cannot stack them draws  ซือ  where it should draw  ซื้อ.",
           font=hf, fill=(154, 160, 166))
    y = 56
    for p in rows:
        f = load(p, size)
        d.rectangle([NAME_W - 8, y, width - 8, y + ROW_H - 6], fill=OK_BG)
        d.text((16, y + ROW_H // 3), os.path.basename(p)[:34], fill=(120, 180, 255))
        d.text((NAME_W + 8, y + 8), text, font=f, fill=(255, 255, 255))
        y += ROW_H
    im.save(out_path)
    return out_path
