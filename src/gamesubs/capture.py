# -*- coding: utf-8 -*-
"""Watch a strip of the screen and decide when the text on it has changed.

This is the part that decides how often a vision model runs, so it is the part that decides
whether the whole thing is usable. A model call takes seconds. Firing one per frame is not slow,
it is broken.

THE MISTAKE TO AVOID: diff the frames. A subtitle sits on top of live gameplay, so a pixel diff
over the band fires on every explosion, every camera pan and every blade of moving grass, and
almost none of those frames contain a new word. The first version of this gate did exactly that
and spent its entire budget re-reading the same sentence over different backgrounds.

WHAT WORKS: diff the TEXT, not the frame. Mask the band down to subtitle-coloured pixels first,
then compare masks. Gameplay disappears from the comparison because it was never in it.

The mask here is "red AND green both bright", which is white text and yellow text -- between them,
close to every game's subtitles. A red HUD marker fails it (green too low). A blue objective
marker fails it (red too low). Foliage, smoke, skin and muzzle flash all fail it.

An earlier version keyed on YELLOW specifically, because the game in front of us at the time had
yellow subtitles. That constant did not survive contact with the second game. The lesson is worth
more than the constant: gate on what the thing you want is made of, and pick the loosest property
that still excludes everything else.
"""
import numpy as np
from PIL import Image

COARSE_W = 128     # masks are compared at this width, so antialiasing wobble is not "a new line"


def ink(rgb, bright=185):
    """Boolean mask of subtitle-coloured pixels.

    White passes (all channels high). Yellow passes (blue is low and is never tested). Anything
    that is bright in only one channel fails.

    This is a colour filter and nothing more. A snow field and a white sky pass it too -- that is
    expected, and it is why a minimum ink count and the change gate exist. Do not read the mask as
    "text detected"; read it as "gameplay removed".
    """
    return (rgb[:, :, 0] >= bright) & (rgb[:, :, 1] >= bright)


def coarse(mask, w=COARSE_W, thr=25):
    """Shrink a mask so sub-pixel rendering differences on a STATIC line are not read as a change.

    Without this, a subtitle that is simply sitting there re-triggers every tick: text is
    antialiased, antialiasing depends on what is behind it, and what is behind it is moving.

    `thr` IS THE WHOLE THING, and the obvious value for it is wrong. Shrinking is an average, and
    text is thin: a 40px letter stroke averaged into a 10px cell lands well under half brightness.
    Threshold at the midpoint (>127) and most of the glyph disappears, so every sentence shrinks
    to the same faint smear and the gate reports "same line" forever -- one subtitle gets
    translated and the tool then goes quiet, looking like the model stopped rather than the gate.

    Measured on four rendered subtitles, comparing "same line shifted 1px" against "a genuinely
    different line" -- the ratio between those two is the only thing that matters:

        threshold >127   jitter  6   different  17    x2.8   unusable
        threshold  >60   jitter 10   different  62    x6.2
        threshold  >25   jitter  9   different  84    x9.3   <- shipped
        threshold   >8   jitter  8   different  66    x8.2

    Low threshold = "did any ink land in this cell", which keeps the glyph skeleton.
    """
    h = max(1, int(w * mask.shape[0] / mask.shape[1]))
    im = Image.fromarray((mask * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR)
    return np.asarray(im) > thr


class Band:
    """The rectangle to watch, in absolute screen pixels."""

    def __init__(self, monitor_rect, region=None, frac=0.25, wfrac=0.7):
        """`monitor_rect` is an mss-style dict: left, top, width, height.

        Default: the bottom `frac` of the monitor, `wfrac` of its width, centred. Games centre
        their subtitles, so the outer edges are HUD and scenery -- cropping them costs nothing
        and makes the image the model reads about a third smaller.

        The risk of narrowing is a clipped first word, which is much harder to notice than a
        slightly large crop, so `--wfrac 1.0` takes the full width back and `/snap` shows exactly
        what is being read.
        """
        m = self.mon = monitor_rect
        if region:
            l, t, w, h = region
        else:
            h = int(m["height"] * frac)
            w = int(m["width"] * wfrac)
            l = m["left"] + (m["width"] - w) // 2
            t = m["top"] + m["height"] - h
        self.rect = {"left": int(l), "top": int(t), "width": int(w), "height": int(h)}

    def norm(self):
        """The band as fractions of its monitor. Handy for placing an overlay over it."""
        m, r = self.mon, self.rect
        return {"x": (r["left"] - m["left"]) / m["width"],
                "y": (r["top"] - m["top"]) / m["height"],
                "w": r["width"] / m["width"],
                "h": r["height"] / m["height"]}


class ChangeGate:
    """Feed it frames; it says when to spend a model call.

    Returns one of:
        "new"   text is present and differs from the last text we acted on  -> read this frame
        "same"  text is present and is the line we already read             -> do nothing
        "gone"  text has been absent long enough to clear the display       -> clear the subtitle
        "idle"  no text, and nothing to clear yet

    `off_ticks` debounces the disappearance. A subtitle can drop out for a single frame during a
    hard cut, and clearing on the first empty frame makes the line flicker.
    """

    # change=30 sits between the two numbers measured in coarse(): 1px jitter on a static line
    # moves ~9 cells, a genuinely different sentence moves ~84. Anywhere in between works; 30 is
    # roughly 3x the noise and a third of the signal.
    def __init__(self, bright=185, min_ink=700, change=30, off_ticks=3):
        self.bright, self.min_ink, self.change, self.off_ticks = bright, min_ink, change, off_ticks
        self.last = None
        self.off = 0
        self.ink_n = 0
        self.diff_n = 0

    def feed(self, rgb):
        m = ink(rgb, self.bright)
        self.ink_n = int(m.sum())
        if self.ink_n < self.min_ink:
            self.off += 1
            if self.off == self.off_ticks:
                self.last = None      # the next line starts fresh; do not compare across a gap
                return "gone"
            return "idle"
        self.off = 0
        c = coarse(m)
        self.diff_n = int((c ^ self.last).sum()) if self.last is not None else -1
        if self.last is not None and self.diff_n < self.change:
            return "same"
        self.last = c
        return "new"
