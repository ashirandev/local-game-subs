# -*- coding: utf-8 -*-
"""Lay out text the way the font was designed to be laid out, then draw it glyph by glyph.

GUARANTEE, written before the code: for any font that can draw the text at all, every mark lands
where that font's own designer put it -- because the font's OpenType tables are the thing doing the
positioning, not us and not a guess.

WHY THIS FILE EXISTS, measured 2026-09-09 rather than assumed.

`render.py` says Pillow "places them correctly". Against tkinter it does. Against the font, it does
not, and here is the measurement that settles it:

    Pillow 12.3.0 / 11.3.0 / 10.4.0 on this machine -> features.check("raqm") == False

No raqm means no HarfBuzz, which means Pillow falls back to LAYOUT_BASIC: glyphs drawn one after
another at their default advances, with **GSUB and GPOS never applied**. Thai needs both.

Then the part that was genuinely surprising. Shaping the word ซื้อ through HarfBuzz and comparing
the glyph ids against a plain cmap lookup:

    font              tone mark alone -> after a vowel      GPOS moves
    Leelawadee UI     319  -> 342                           2 of 4 glyphs
    Tahoma           1174  -> 1144                          2 of 4
    Google Sans      3209  -> 3248                          2 of 4, both y=0
    Noto Sans Thai     47  ->   49                          2 of 4

EVERY Thai font swaps the tone mark for a DIFFERENT GLYPH when a vowel already sits above the
consonant -- a raised, slightly smaller form that clears it. Google Sans is the clearest case: its
GPOS moves nothing vertically at all (y=0 on both marks), so the whole correction is the
substitution. Without a shaper you get the tall form landing on top of the vowel, which is exactly
what a live frame showed as เพื่อ drawn เพือ.

🔑 The consequence that decides the design: **it is not enough to compute offsets and draw the
original characters.** The character is right and the GLYPH is wrong. So the text has to be drawn
by glyph id, which Pillow cannot do -- hence FreeType directly.

    uharfbuzz   picks the glyphs and their positions   (the font's own rules)
    freetype-py rasterises one glyph by its id         (what Pillow will not do)
    numpy       composites the coverage into an image

Two dependencies for one feature is a real cost, and the alternative was a tool that works with
three hand-picked fonts and silently mangles the other hundred-odd. For a program whose entire
output is Thai text, correct shaping is not a nicety.
"""
import functools
import os

try:
    import freetype
    import uharfbuzz as hb
    HAVE_SHAPER = True
    WHY_NOT = ""
except Exception as _e:                                      # noqa: BLE001
    HAVE_SHAPER = False
    WHY_NOT = "%s: %s" % (type(_e).__name__, _e)

# HarfBuzz reports positions in 26.6 fixed point when the font is scaled in pixels.
SCALE = 64.0


@functools.lru_cache(maxsize=16)
def _hb_font(path, size):
    blob = hb.Blob.from_file_path(path)
    face = hb.Face(blob)
    font = hb.Font(face)
    font.scale = (int(size * SCALE), int(size * SCALE))
    return font


@functools.lru_cache(maxsize=16)
def _ft_face(path, size):
    face = freetype.Face(path)
    face.set_pixel_sizes(0, int(size))
    return face


def shape(path, size, text, language="th"):
    """What to draw and where. -> ([(glyph_id, x, y), ...], advance_width_px)

    x and y are pixel offsets from the pen start, y positive downwards to match image coordinates.
    The list is in draw order; a mark shares its base letter's position rather than following it,
    which is the whole point.
    """
    font = _hb_font(path, size)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    if language:
        try:
            buf.language = language
        except Exception:                                    # noqa: BLE001
            pass                                             # a rejected tag must not lose the line
    hb.shape(font, buf)

    out, pen_x, pen_y = [], 0.0, 0.0
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        out.append((info.codepoint,
                    (pen_x + pos.x_offset) / SCALE,
                    (pen_y - pos.y_offset) / SCALE))         # HarfBuzz y is up, images are down
        pen_x += pos.x_advance
        pen_y += pos.y_advance
    return out, pen_x / SCALE


def advance(path, size, text):
    """Width of `text` as this font will actually draw it. -> float px

    Used for wrapping. Measuring with anything other than the shaper would measure a layout the
    screen never receives -- and wrapping is where a width error becomes visible, because the line
    that breaks wrongly is the long one nobody tested with.
    """
    return shape(path, size, text)[1]


def draw(img_np, path, size, text, xy, fill=(255, 255, 255), language="th"):
    """Composite `text` onto an HxWx4 RGBA numpy array at `xy`. -> the same array

    Each glyph is rendered by FreeType into an 8-bit coverage bitmap and alpha-blended, so a mark
    that overlaps its base letter blends instead of punching a hole in it.
    """
    import numpy as np

    face = _ft_face(path, size)
    glyphs, _ = shape(path, size, text, language)
    ox, oy = xy
    h, w = img_np.shape[:2]
    r, g, b = fill[:3]

    for gid, gx, gy in glyphs:
        face.load_glyph(gid, freetype.FT_LOAD_RENDER)
        bm = face.glyph.bitmap
        if bm.width == 0 or bm.rows == 0:
            continue                                         # a space, or a mark with no ink
        cov = np.array(bm.buffer, dtype=np.uint8)
        # `pitch` is the row stride and is NOT always equal to width -- FreeType pads rows. Slicing
        # by width without honouring it shears the glyph one pixel further left on every row.
        cov = cov.reshape(bm.rows, bm.pitch)[:, :bm.width]

        x0 = int(round(ox + gx)) + face.glyph.bitmap_left
        y0 = int(round(oy + gy)) - face.glyph.bitmap_top
        x1, y1 = x0 + bm.width, y0 + bm.rows
        sx0, sy0 = max(0, -x0), max(0, -y0)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        patch = cov[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0)].astype(np.float32) / 255.0
        dst = img_np[y0:y1, x0:x1]
        a = patch[..., None]
        dst[..., 0] = dst[..., 0] * (1 - patch) + r * patch
        dst[..., 1] = dst[..., 1] * (1 - patch) + g * patch
        dst[..., 2] = dst[..., 2] * (1 - patch) + b * patch
        dst[..., 3] = np.maximum(dst[..., 3], (a[..., 0] * 255)).astype(dst.dtype)
    return img_np


def can_draw(path, text):
    """Does this font have a glyph for every character? -> bool

    Asked of the shaper, so it answers about the glyphs that will actually be drawn. Glyph id 0 is
    .notdef -- the empty box -- and one of those means the font cannot show that character.
    """
    try:
        glyphs, _ = shape(path, 32, text)
    except Exception:                                        # noqa: BLE001
        return False
    return bool(glyphs) and all(gid != 0 for gid, _x, _y in glyphs)


def missing_reason():
    """One line naming what is not installed, for a caller that has to tell the user. -> str"""
    if HAVE_SHAPER:
        return ""
    return ("Thai text needs a shaper: pip install uharfbuzz freetype-py   (%s)" % WHY_NOT)


__all__ = ["HAVE_SHAPER", "shape", "advance", "draw", "can_draw", "missing_reason", "SCALE"]
