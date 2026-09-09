# -*- coding: utf-8 -*-
"""Draw the same words in every available font, so you can pick one by looking at them.

Drawn through the SAME shaper that draws the subtitles. A chooser that previews through a
different renderer than the one doing the work will happily recommend a font that then looks
wrong in the overlay -- and for a while this file was that chooser. It called
`ImageDraw.text` directly, which on this machine means LAYOUT_BASIC: no GSUB, no GPOS. So it
drew every row with the unstacked glyph, every font failed the one column the sheet exists
for, and the sheet could not tell a good Thai font from a bad one. A tool doing the exact
opposite of its job while looking like it works.

The samples are the hard case on purpose: Thai words where two marks stack on one consonant.
`ซื้อ` needs a vowel and a tone mark on the same ซ, and a font that cannot stack them silently
draws `ซือ` -- a different word, rendered confidently, with nothing reporting a problem.

There is no automatic verdict on that column, and not for want of trying. Three checks were
written and all three were wrong: comparing pictures says every font passes, and comparing ink
height says every font fails, because a well-made Thai font lowers the vowel when a tone mark
joins it and the total height does not change by design. Whether a mark sits where it belongs is
something you look at -- which is only worth anything if what you are looking at is what the
overlay will draw.
"""
import os

from PIL import Image, ImageDraw

from . import shape as shaper
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


def _ascent(face):
    """Where the baseline sits below the top of a line in this font. -> int

    From the font's own metrics rather than from this particular string: a baseline measured off
    the bounding box moves between rows depending on whether that row happened to contain a tall
    mark, and rows that do not share a baseline cannot be compared by eye, which is the entire
    point of the sheet.
    """
    try:
        return face.pil.getmetrics()[0]
    except Exception:                                        # noqa: BLE001
        return int(getattr(face, "size", 40) * 0.8)


def sheet(paths, size=40, words=None, out_path="font-comparison.png"):
    """One image, one row per font, the same words in each. Returns the path written."""
    words = words or STACKED_SAMPLES
    text = "   ".join(words)
    rows = paths or []
    if not rows:
        raise SystemExit("no font on this machine can draw those words. Drop a .ttf that covers "
                         "your language into the fonts folder.")
    width = NAME_W + 40 * len(text)
    im = Image.new("RGBA", (width, ROW_H * len(rows) + 60), BG + (255,))
    d = ImageDraw.Draw(im)
    # The header names the Thai words, so it has to be drawn in a font that HAS Thai -- PIL's
    # built-in default does not, and would print the explanation as a row of boxes.
    hf = load(rows[0], 15)

    # Latin chrome first, through Pillow, which handles it correctly and needs no shaping. Every
    # run of Thai is collected instead and drawn in one pass below, because drawing by glyph id
    # means working on the pixels rather than through ImageDraw.
    d.text((16, 12), "Same words, every usable font. Look at the marks above the letters.",
           font=hf.pil, fill=(232, 234, 237))
    plan = [("A font that cannot stack them draws  \u0e0b\u0e37\u0e2d  where it should draw  "
             "\u0e0b\u0e37\u0e49\u0e2d.", hf, 16, 32 + _ascent(hf), (154, 160, 166))]

    y = 56
    for p in rows:
        f = load(p, size)
        d.rectangle([NAME_W - 8, y, width - 8, y + ROW_H - 6], fill=OK_BG)
        d.text((16, y + ROW_H // 3), os.path.basename(p)[:34], fill=(120, 180, 255))
        plan.append((text, f, NAME_W + 8, y + 8 + _ascent(f), (255, 255, 255)))
        y += ROW_H

    if all(getattr(f, "shaped", False) for _, f, _, _, _ in plan):
        import numpy as np
        arr = np.array(im)
        for s, f, x, base, fill in plan:
            shaper.draw(arr, f.path, f.size, s, (x, base), fill=fill)
        im = Image.fromarray(arr)
    else:
        # No shaper installed. The rows are then all wrong in the same way, so say so on the
        # image itself rather than let someone pick a font from a picture that cannot be read.
        for s, f, x, base, fill in plan:
            d.text((x, base - _ascent(f)), s, font=f.pil, fill=fill)
        d.text((16, im.height - 18),
               "NO SHAPER INSTALLED -- every row above is drawn without the font's own rules, "
               "so this sheet cannot tell a good Thai font from a bad one. %s"
               % shaper.missing_reason(), font=hf.pil, fill=(255, 138, 128))

    im.convert("RGB").save(out_path)
    return out_path
