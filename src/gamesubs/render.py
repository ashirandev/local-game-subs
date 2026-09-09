# -*- coding: utf-8 -*-
"""Draw the subtitle into an image, instead of letting the window toolkit lay out the text.

WHY. tkinter on Windows does not do complex text layout. For Latin that is invisible; for Thai it
is not. A live frame read off the screen showed `เข้า E-Store เพื่อ` drawn as `เขา È-Store เพอ` --
the tone marks had come off their own consonants and one of them had landed on the **E of
E-Store**. The same line was correct in the console a few centimetres away, which is what says the
model, the translation and the transport were all fine and only the drawing was wrong.

Marks that attach to a base letter -- Thai, Lao, Khmer, Devanagari, Arabic -- are where a naive
text layout stops being "slightly off" and starts being unreadable.

Pillow places them correctly, so the text is drawn here and the window just shows the picture.

That buys a second thing, and it is the reason the fonts folder can exist at all: PIL opens a font
**file**, while tkinter can only name a font the operating system has already installed. Dropping
a .ttf into a folder and using it needs this path.
"""
import os

from PIL import Image, ImageDraw, ImageFont

from . import shape

# 🛑 The paragraph above says Pillow "places them correctly". Measured 2026-09-09, that is true of
# tkinter and false of the font: Pillow on Windows reports features.check("raqm") == False, so it
# lays out with LAYOUT_BASIC and applies NEITHER GSUB NOR GPOS. Every Thai font in reach swaps the
# tone mark for a raised variant when a vowel already sits on the consonant -- Google Sans
# 3209 -> 3248, Noto 47 -> 49, Leelawadee 319 -> 342, Tahoma 1174 -> 1144 -- and none of those
# substitutions happen without a shaper. That is the whole of เพื่อ drawn เพือ.
#
# So the text is shaped by HarfBuzz and drawn glyph by glyph (see shape.py). Pillow still owns the
# plate, the compositing and the Latin fallback path; it no longer owns where the marks go.

# OPAQUE, and that is the whole job. At 190 the sentence underneath is dimmed, not hidden -- and
# a dimmed English line under a Thai one is exactly the "same thing twice in two languages" this
# plate exists to remove. Measured on a two-line RE4R subtitle: at 190 both English lines were
# still readable straight through it.
PLATE = (0, 0, 0, 255)
TEXT = (255, 255, 255, 255)
SPEAKER = (207, 211, 216, 255)
OUTLINE = (0, 0, 0, 255)
PAD_X, PAD_Y, GAP = 16, 8, 2


def _rgba(spec, fallback):
    """"#rrggbb" -> an opaque RGBA tuple. Anything else -> the fallback. -> tuple

    Alpha is not taken from the caller and not offered in the panel. A plate you can read
    the original through is the bug this tool started with: the same sentence on screen
    twice, in two languages, and it looked deliberate enough that nobody called it a bug
    for an hour.
    """
    if not isinstance(spec, str) or len(spec) != 7 or spec[0] != "#":
        return fallback
    try:
        return (int(spec[1:3], 16), int(spec[3:5], 16), int(spec[5:7], 16), 255)
    except ValueError:
        return fallback


class Face(object):
    """A font at a size, carrying the FILE PATH as well as the Pillow object.

    The path is the part that matters: a shaper needs the file, and Pillow's font object does not
    reliably give one back. Everything the rest of this module already called on a Pillow font --
    `getlength`, `size` -- still works, so wrapping and measuring did not have to change.
    """

    __slots__ = ("path", "size", "pil", "shaped")

    def __init__(self, path, size, pil):
        self.path = path
        self.size = size
        self.pil = pil
        # Per face, not global: a path Pillow opened is not automatically one HarfBuzz can shape
        # (a .ttc collection, a bitmap-only font), and the answer must be about THIS file.
        self.shaped = bool(path) and shape.HAVE_SHAPER and shape.can_draw(path, "ก")

    def getlength(self, text):
        if self.shaped:
            try:
                return shape.advance(self.path, self.size, text)
            except Exception:                                # noqa: BLE001
                pass                     # a width is not worth losing the line over; fall through
        return self.pil.getlength(text)

    def getbbox(self, *a, **k):
        return self.pil.getbbox(*a, **k)

    def __getattr__(self, name):
        """Anything this class does not define is asked of the Pillow font underneath.

        🛑 THIS IS NOT CONVENIENCE, IT IS THE BUG THAT SHIPPED TWICE IN ONE HOUR. Wrapping the
        font in a class quietly broke every `ImageDraw.text(..., font=...)` in the project at
        once -- six call sites across four modules -- and each one only announces itself when a
        person reaches that screen:

            AttributeError: 'Face' object has no attribute 'getmask'

        The first user to run it hit the font chooser, which died drawing its own row labels.
        Patching that one line would have left the other five waiting, one screen further in.

        What it does NOT do is make Pillow draw Thai correctly -- Pillow has no shaper here, see
        the note at the top of this file. Pillow draws the chrome (labels, Latin); complex text
        goes through `draw_line`, which draws by glyph id.
        """
        if name == "pil":                    # never recurse while __init__ is still running
            raise AttributeError(name)
        return getattr(self.pil, name)


def _face(f):
    """Accept either a Face or a bare Pillow font. -> Face

    Callers outside this module -- and the tests -- hand `draw_line` whatever `ImageFont.truetype`
    gave them, and there is no reason for a drawing function to refuse a font. A bare Pillow font
    simply has no file path attached, so it draws the old way.
    """
    if isinstance(f, Face):
        return f
    path = getattr(f, "path", None)
    size = int(getattr(f, "size", 0) or 28)
    return Face(path if path and os.path.isfile(str(path)) else None, size, f)


_WARNED = []


def load(path_or_family, size):
    """A font at a size. Falls back to PIL's built-in only as a last resort."""
    if not shape.HAVE_SHAPER and not _WARNED:
        _WARNED.append(1)
        # Loud, once. A renderer that quietly loses mark positioning produces text that looks
        # deliberate and reads as broken -- the failure mode this whole module exists to remove.
        print("WARNING: no text shaper installed, so Thai marks will sit where the font's default\n"
              "         glyphs put them rather than where the font says they belong.\n"
              "         %s" % shape.missing_reason())
    try:
        pil = ImageFont.truetype(path_or_family, size)
    except Exception:
        return Face(None, size, ImageFont.load_default())
    return Face(path_or_family if os.path.isfile(str(path_or_family)) else None, size, pil)


def _bitmap(font, ch):
    """What this font actually paints for one character.

    Takes a Face or a bare Pillow font. Coverage is a question about the FILE -- does it have a
    glyph for this codepoint at all -- so it is asked through Pillow either way; where the mark
    ends up is a different question and belongs to the shaper.
    """
    pil = getattr(font, "pil", font)
    n = int(getattr(font, "size", 32)) * 3
    im = Image.new("L", (n, n), 0)
    ImageDraw.Draw(im).text((n // 4, n // 4), ch, font=pil, fill=255)
    return im.tobytes()


def has_glyphs(font, text):
    """True when the font really has every character in `text`.

    Each character is painted and compared against what the font paints for a codepoint that
    cannot exist -- the empty box. A font without Thai does not refuse: it draws boxes, or the
    system quietly substitutes another font, and either way it looks deliberate in a screenshot
    and wrong to a reader.

    Painting rather than measuring, because width is the question that is easy to ask and not the
    one that matters: two fonts can measure identically and draw completely different things.
    """
    missing = _bitmap(font, "\ufffe")
    blank = _bitmap(font, " ")
    for ch in set(text):
        if ch.isspace() or ord(ch) < 128:
            continue
        try:
            got = _bitmap(font, ch)
        except Exception:
            return False
        if got == missing or got == blank:
            return False
    return True


# Words where two marks stack on ONE consonant. These are the hard case, and there is deliberately
# NO automatic check for them here: three were tried and all three were wrong.
#
#   "do the pictures differ"      -- yes for every font, including ones that drop the mark
#   "is the ink taller"           -- no for every font, including ones that place it correctly,
#                                    because a good Thai font LOWERS the vowel when a tone mark
#                                    joins it, so the total height is unchanged by design
#
# Each of those measured something next to the question instead of the question. Whether a mark
# is in the right place is a thing you look at, so these words go in the font chooser and a person
# decides. Automating it wrongly is worse than not automating it: the wrong answer arrives with
# the same confidence as the right one.
STACKED_SAMPLES = ["ซื้อ", "เพื่อ", "ที่", "ผู้", "น้ำ", "เข้า"]


def wrap(text, font, max_width):
    """Greedy wrap that also works on scripts without spaces.

    Thai does not put spaces between words, so wrapping on spaces alone leaves one very long line
    that runs off the screen. Anything that does not fit on its own is broken by character.
    """
    lines = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        cur = ""
        for word in para.split(" "):
            trial = (cur + " " + word).strip() if cur else word
            if font.getlength(trial) <= max_width:
                cur = trial
                continue
            if cur:
                lines.append(cur)
                cur = ""
            while font.getlength(word) > max_width:
                cut = len(word)
                while cut > 1 and font.getlength(word[:cut]) > max_width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            cur = word
        if cur:
            lines.append(cur)
    return lines or [""]


def draw_line(text, speaker="", font=None, small=None, max_width=1100,
              text_colour=None, plate_colour=None):
    """Render one subtitle. Returns an RGBA image, or None when there is nothing to show.

    The plate is the size of the SENTENCE, and `max_width` is where a line wraps -- the caller
    passes the width of the box, so lines break in the same place every time and the plate can
    never come out wider than the region being read.

    It was the size of the BOX for about an hour, which is a fixed black slab with the words
    floating somewhere inside it. Watching it run, that reads as the text being unstable even
    though nothing is moving: a short line and a two-line one start at different places inside a
    frame that never changes. Fitting the plate to the words puts them in the same position
    relative to their own plate every time, and the window is centred in the box by the caller.

    The two colours arrive as "#rrggbb" from the settings window and are None everywhere
    else, which means the constants. The OUTLINE is not one of them: it is what keeps the
    text readable where the plate does not reach -- the tail of a glyph that hangs past its
    own line -- and offering it as a choice is offering a way to make the subtitle vanish
    against a bright scene.
    """
    plate = _rgba(plate_colour, PLATE)
    ink = _rgba(text_colour, TEXT)
    text = (text or "").replace("\\n", "\n").strip()
    if not text:
        return None
    font = _face(font or ImageFont.load_default())
    small = _face(small) if small else font

    lines = wrap(text, font, max_width - 2 * PAD_X)

    def metrics(f):
        try:
            asc, desc = f.pil.getmetrics()
        except Exception:                                    # noqa: BLE001
            asc, desc = int(f.size * 0.8), int(f.size * 0.25)
        return asc, desc

    # Heights come from the FONT's own ascent/descent, not from the bounding box of this
    # particular string. A box measured per line makes the plate jump between lines depending on
    # whether that line happened to contain a tall mark -- and Thai lines differ in exactly that.
    asc, desc = metrics(font)
    line_h = asc + desc + GAP
    sp_asc, sp_desc = metrics(small)
    sp_h = (sp_asc + sp_desc) if speaker else 0

    body_w = max(font.getlength(s) for s in lines)
    sp_w = small.getlength(speaker) if speaker else 0

    w = int(max(body_w, sp_w)) + 2 * PAD_X
    h = int(len(lines) * line_h + (sp_h + GAP * 2 if speaker else 0) + 2 * PAD_Y)

    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w - 1, h - 1], fill=plate)

    plan = []
    y = PAD_Y
    if speaker:
        plan.append((speaker, small, sp_asc, y, SPEAKER, 2))
        y += sp_h + GAP * 2
    for s in lines:
        plan.append((s, font, asc, y, ink, 3))
        y += line_h

    if font.shaped:
        import numpy as np
        arr = np.array(im)
        for s, f, a, top, fill, stroke in plan:
            if not s:
                continue
            x = (w - f.getlength(s)) / 2.0
            base = top + a
            # The outline is what keeps white text readable over a bright scene: without it the
            # line disappears against snow, sky or a muzzle flash exactly when someone is talking.
            # Pillow draws one for free; drawing by glyph means drawing it, so the text is stamped
            # around itself first and then over the top.
            for dx in range(-stroke, stroke + 1):
                for dy in range(-stroke, stroke + 1):
                    if dx or dy:
                        shape.draw(arr, f.path, f.size, s, (x + dx, base + dy), fill=OUTLINE[:3])
            shape.draw(arr, f.path, f.size, s, (x, base), fill=fill[:3])
        return Image.fromarray(arr)

    for s, f, a, top, fill, stroke in plan:
        d.text((w / 2.0, top), s, font=f.pil, fill=fill, anchor="ma",
               stroke_width=stroke, stroke_fill=OUTLINE)
    return im


def preview(font_path, size, sample, width=560):
    """One row for the font chooser: the sample drawn in this font, or a note that it cannot."""
    f = load(font_path, size)
    ok = has_glyphs(f, sample)
    im = Image.new("RGB", (width, size + 18), (14, 23, 26) if ok else (26, 14, 14))
    d = ImageDraw.Draw(im)
    d.text((8, 4), sample if ok else "this font cannot draw that text",
           font=f if ok else ImageFont.load_default(),
           fill=(255, 255, 255) if ok else (255, 138, 128))
    return im, ok


# Tried in this order when nobody has said which font to use. Leelawadee UI and Tahoma first
# because they were checked BY EYE on stacked marks and place them correctly without a shaper.
# Google Sans is deliberately not here: it owns every Thai glyph and draws them beautifully, and
# it still loses the tone mark from ซื้อ, because it positions stacked marks through OpenType
# GPOS and nothing in this stack applies GPOS. Available with --font, not chosen for you.
PREFERRED = ["leelawui", "leelawad", "tahoma", "notosansthai", "ibmplexsansthai", "sarabun"]


def resolve_font(name_or_path, sample, extra_dir=None):
    """A usable font FILE for `sample`, from a path, a name, or by searching. None if none fits.

    Searched in the order that respects what the user asked for: an exact file, then a font whose
    filename or family they named, then whatever is in the tool's own fonts folder, then the
    system. Only fonts that can actually draw the sample are returned -- offering one that cannot
    is how you end up with a screenful of boxes and no explanation.
    """
    cands = []
    if name_or_path:
        if os.path.isfile(name_or_path):
            cands.append(name_or_path)
        key = os.path.splitext(os.path.basename(name_or_path))[0].replace(" ", "").lower()
    else:
        key = None
    pool = (folder_fonts(extra_dir) if extra_dir else []) + system_fonts()
    if key:
        cands += [p for p in pool
                  if os.path.splitext(os.path.basename(p))[0].replace(" ", "").lower() == key]
        cands += [p for p in pool
                  if key in os.path.splitext(os.path.basename(p))[0].replace(" ", "").lower()]
    else:
        if extra_dir:
            cands += folder_fonts(extra_dir)
        low = {os.path.basename(p).lower(): p for p in pool}
        for want in PREFERRED:
            cands += [p for n, p in low.items() if n.startswith(want)]
        cands += pool
    seen = set()
    for p in cands:
        if p in seen:
            continue
        seen.add(p)
        try:
            if has_glyphs(load(p, 28), sample):
                return p
        except Exception:
            continue
    return None


def folder_fonts(d):
    """Font files a user dropped into the tool's own fonts folder."""
    try:
        return [os.path.join(d, f) for f in sorted(os.listdir(d))
                if f.lower().endswith((".ttf", ".otf"))]
    except OSError:
        return []


def system_fonts():
    """Font files installed on this machine, plus whatever is in the tool's own fonts folder."""
    out = []
    for d in (r"C:\Windows\Fonts", os.path.join(os.path.expanduser("~"),
                                                r"AppData\Local\Microsoft\Windows\Fonts")):
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.lower().endswith((".ttf", ".otf")):
                out.append(os.path.join(d, f))
    return out
