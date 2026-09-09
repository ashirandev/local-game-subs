# -*- coding: utf-8 -*-
"""The font's own rules decide where a Thai mark goes -- not the renderer, and not a default.

WHAT THIS GUARDS. Without a shaper, Pillow lays text out with LAYOUT_BASIC: glyphs in sequence at
their default advances, with GSUB and GPOS never applied. Measured on this machine, Pillow 12.3.0,
11.3.0 and 10.4.0 all report features.check("raqm") == False, so that is not a corner case, it is
the default state of the tool on Windows.

And the thing that makes it fatal rather than untidy: every Thai font in reach SUBSTITUTES the tone
mark for a different glyph when a vowel already sits on the consonant.

    Google Sans     3209 -> 3248        Noto Sans Thai    47 -> 49
    Leelawadee UI    319 ->  342        Tahoma          1174 -> 1144

No shaper means the tall form is drawn on top of the vowel, which a live frame showed as เพื่อ
rendered เพือ. So the assertion that matters is not "does it look different" -- four attempts to
measure mark placement by geometry all answered a different question than the one asked (see
reference_local_game_subs) -- it is "did the substitution happen at all".
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from gamesubs import render, shape                           # noqa: E402

# so + sara uee + mai tho + o-ang. The tone mark has to clear the vowel underneath it.
STACKED = "\u0e0b\u0e37\u0e49\u0e2d"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(HERE, "fonts")


def thai_fonts():
    if not os.path.isdir(FONTS):
        return []
    return [os.path.join(FONTS, f) for f in sorted(os.listdir(FONTS))
            if f.lower().endswith((".ttf", ".otf")) and shape.can_draw(os.path.join(FONTS, f),
                                                                      STACKED)]


@unittest.skipUnless(shape.HAVE_SHAPER, "no shaper installed")
class Shaping(unittest.TestCase):

    def setUp(self):
        self.fonts = thai_fonts()
        if not self.fonts:
            self.skipTest("no Thai font in fonts/ to shape")

    def test_the_tone_mark_is_a_different_glyph_once_a_vowel_is_under_it(self):
        """The substitution is the whole fix. If this passes with the shaper removed, the test is
        measuring nothing -- which is why it compares against the font's own unshaped answer
        rather than against a number written down here."""
        for path in self.fonts:
            got = [g for g, _x, _y in shape.shape(path, 40, STACKED)[0]]
            alone = [shape.shape(path, 40, ch)[0][0][0] for ch in STACKED]
            self.assertEqual(len(got), len(alone), path)
            self.assertNotEqual(got, alone,
                                "%s: shaping changed no glyph, so GSUB did not run" % path)

    def test_marks_do_not_advance_the_pen(self):
        """A combining mark sits on its base letter and takes no width of its own. If it took any,
        the word would come out spaced like ซ ื ้ อ -- visibly wrong long before mark HEIGHT
        matters at all.

        Asserted on each mark directly. The first version of this test compared the whole word
        against the sum of its characters, and they were exactly equal -- because a mark shaped on
        its own already reports zero advance, so the sum was never larger. A test built on that
        assumption would have passed for the wrong reason on every font that has the bug.
        """
        for path in self.fonts:
            for mark in "ื้":                      # sara uee, mai tho
                self.assertEqual(shape.advance(path, 40, mark), 0.0,
                                 "%s: %r advances the pen" % (path, mark))
            self.assertGreater(shape.advance(path, 40, STACKED), 0.0)

    def test_width_comes_from_the_shaper_so_wrapping_matches_what_is_drawn(self):
        f = render.load(self.fonts[0], 40)
        self.assertTrue(f.shaped, "a Thai font in fonts/ was not recognised as shapeable")
        self.assertAlmostEqual(f.getlength(STACKED), shape.advance(self.fonts[0], 40, STACKED),
                               places=3)

    def test_a_font_that_cannot_draw_the_text_says_so(self):
        """.notdef is glyph 0. A font without Thai does not refuse -- it draws empty boxes, which
        looks deliberate in a screenshot and is unreadable to a person."""
        latin = r"C:\Windows\Fonts\georgia.ttf"
        if not os.path.isfile(latin):
            self.skipTest("no Latin-only font to test with")
        self.assertFalse(shape.can_draw(latin, STACKED))
        self.assertTrue(shape.can_draw(self.fonts[0], STACKED))

    def test_drawing_puts_ink_where_nothing_was(self):
        import numpy as np
        arr = np.zeros((90, 320, 4), dtype=np.uint8)
        shape.draw(arr, self.fonts[0], 40, STACKED, (10, 60), fill=(255, 255, 255))
        self.assertGreater(int(arr[..., 3].sum()), 0, "the shaper drew nothing at all")
        # The marks live ABOVE the baseline the text was drawn on, so there must be ink up there.
        self.assertGreater(int(arr[:40, :, 3].sum()), 0, "nothing was drawn above the vowel line")


class TheFontSearchAcceptsWhatLoadReturns(unittest.TestCase):
    """The seam between the two halves of this change, which is where it broke.

    `load()` started returning a `Face` (a Pillow font plus the file path a shaper needs) and every
    unit on both sides of that stayed green -- because no test ever called one with the other.
    `has_glyphs` paints a character through Pillow, a `Face` is not a Pillow font, and so the very
    first thing a new user does raised AttributeError inside a `try: ... except: continue` that was
    there to skip broken fonts. Every font on the machine got skipped, and the program said:

        no font on this machine can draw 'ซื้อ  เพื่อ  ที่  ผู้'.

    on a machine with 137 fonts that can. All three callers -- the picker, the font list and
    `resolve_font` -- reach it as this exact pair, so the pair is what gets asserted.
    """

    def setUp(self):
        self.fonts = thai_fonts()
        if not self.fonts:
            self.skipTest("no Thai font in fonts/")
        self.sample = "  ".join(render.STACKED_SAMPLES[:4])

    def test_a_loaded_font_can_be_asked_what_it_covers(self):
        self.assertTrue(render.has_glyphs(render.load(self.fonts[0], 22), self.sample))

    def test_the_shipped_folder_alone_answers_the_first_run(self):
        """A new user has whatever is in the repo and nothing else installed. If that folder cannot
        satisfy the search on its own, the first double-click ends at the error above."""
        got = render.resolve_font(None, self.sample, FONTS)
        self.assertTrue(got and os.path.isfile(got), "the shipped fonts did not resolve")

    def test_a_face_can_be_handed_to_pillows_own_drawing(self):
        """Six places draw the chrome around the subtitle with Pillow -- the picker's row labels,
        the comparison sheet's header, the preview strip. All six broke at once when the font
        became a Face, and each announces itself only when a person reaches that screen. This is
        the contract that keeps them working, asserted once instead of six times."""
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (240, 48))
        ImageDraw.Draw(im).text((4, 4), "this font", font=render.load(self.fonts[0], 16),
                                fill=(255, 255, 255))
        self.assertGreater(sum(im.convert("L").getextrema()), 0, "nothing was drawn")

    def test_the_two_screens_past_the_picker_still_render(self):
        """`gamesubs fonts` and the preview strip. Reached after the chooser, so a crash here is
        a crash the first two screens do not predict."""
        import tempfile
        from gamesubs import fonts as fontsheet
        self.assertTrue(render.preview(self.fonts[0], 24, self.sample))
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "sheet.png")
            self.assertTrue(os.path.isfile(fontsheet.sheet(self.fonts[:2], 28, out_path=out)))

    def test_the_picker_has_something_to_show(self):
        """The picker builds its list inside `except Exception: continue`, so a raise here does not
        crash -- it empties the list, which is the same screen as having no fonts at all."""
        cands = [q for q in render.folder_fonts(FONTS)
                 if render.has_glyphs(render.load(q, 22), self.sample)]
        self.assertGreaterEqual(len(cands), 1)


class WithoutAShaper(unittest.TestCase):
    """The tool still runs without uharfbuzz -- it just says so instead of quietly being wrong."""

    def test_the_missing_reason_names_what_to_install(self):
        if shape.HAVE_SHAPER:
            self.assertEqual(shape.missing_reason(), "")
        else:
            self.assertIn("uharfbuzz", shape.missing_reason())

    def test_a_bare_pillow_font_is_still_accepted(self):
        from PIL import ImageFont
        im = render.draw_line("hello", font=ImageFont.load_default())
        self.assertIsNotNone(im)


if __name__ == "__main__":
    unittest.main(verbosity=2)
