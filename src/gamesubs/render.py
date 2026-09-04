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

PLATE = (0, 0, 0, 190)          # subtitle backing, slightly transparent
TEXT = (255, 255, 255, 255)
SPEAKER = (207, 211, 216, 255)
OUTLINE = (0, 0, 0, 255)
PAD_X, PAD_Y, GAP = 16, 8, 2


def load(path_or_family, size):
    """A PIL font from a file path. Falls back to PIL's built-in only as a last resort."""
    try:
        return ImageFont.truetype(path_or_family, size)
    except Exception:
        return ImageFont.load_default()


def _bitmap(font, ch):
    """What this font actually paints for one character."""
    n = int(getattr(font, "size", 32)) * 3
    im = Image.new("L", (n, n), 0)
    ImageDraw.Draw(im).text((n // 4, n // 4), ch, font=font, fill=255)
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


def draw_line(text, speaker="", font=None, small=None, max_width=1100):
    """Render one subtitle. Returns an RGBA image, or None when there is nothing to show."""
    text = (text or "").replace("\\n", "\n").strip()
    if not text:
        return None
    font = font or ImageFont.load_default()
    small = small or font

    lines = wrap(text, font, max_width - 2 * PAD_X)
    probe = Image.new("RGBA", (1, 1))
    d0 = ImageDraw.Draw(probe)

    def box(s, f):
        l, t, r, b = d0.textbbox((0, 0), s or " ", font=f)
        return r - l, b - t, t

    sizes = [box(s, font) for s in lines]
    body_w = max(w for w, _, _ in sizes)
    line_h = max(h for _, h, _ in sizes) + GAP
    sp_w, sp_h, _ = box(speaker, small) if speaker else (0, 0, 0)

    w = max(body_w, sp_w) + 2 * PAD_X
    h = len(lines) * line_h + (sp_h + GAP * 2 if speaker else 0) + 2 * PAD_Y

    im = Image.new("RGBA", (int(w), int(h)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w - 1, h - 1], fill=PLATE)

    y = PAD_Y
    if speaker:
        d.text((w / 2, y), speaker, font=small, fill=SPEAKER, anchor="ma",
               stroke_width=2, stroke_fill=OUTLINE)
        y += sp_h + GAP * 2
    for s in lines:
        # The outline is what keeps white text readable over a bright scene. Without it the line
        # disappears against snow, sky or a muzzle flash exactly when someone is talking.
        d.text((w / 2, y), s, font=font, fill=TEXT, anchor="ma",
               stroke_width=3, stroke_fill=OUTLINE)
        y += line_h
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
