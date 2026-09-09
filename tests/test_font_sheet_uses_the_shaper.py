# -*- coding: utf-8 -*-
"""The font-comparison sheet must draw through the shaper, or it answers its own question wrong.

The sheet exists for one column: does this font stack a tone mark over a vowel. For a while it
drew every row with `ImageDraw.text`, which on this machine is LAYOUT_BASIC -- no GSUB, no GPOS.
So every font drew the unstacked glyph, every row failed, and the sheet recommended nothing
while looking exactly like a working tool.

Comparing pictures is the wrong assertion here and was tried: a sheet drawn without the shaper is
a perfectly good-looking image. The question is whether the shaper was the thing that drew it, so
that is what is asked -- and asked in a way that goes red if someone puts `d.text` back, which is
the only way this regresses.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PIL import Image                                        # noqa: E402

from gamesubs import fonts, shape                            # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STACKED = "\u0e0b\u0e37\u0e49\u0e2d"


def thai_fonts():
    d = os.path.join(HERE, "fonts")
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, f) for f in sorted(os.listdir(d))
            if f.lower().endswith((".ttf", ".otf")) and shape.can_draw(os.path.join(d, f), STACKED)]


@unittest.skipUnless(shape.HAVE_SHAPER, "no shaper installed")
class TheSheetGoesThroughTheShaper(unittest.TestCase):

    def setUp(self):
        self.fonts = thai_fonts()
        if not self.fonts:
            self.skipTest("no Thai font in fonts/ to draw")
        self.out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "_sheet_under_test.png")
        self.real = shape.draw

    def tearDown(self):
        shape.draw = self.real
        try:
            os.remove(self.out)
        except OSError:
            pass

    def test_every_thai_run_is_drawn_by_glyph_id(self):
        seen = []

        def spy(arr, path, size, text, xy, fill=(255, 255, 255), language="th"):
            seen.append(text)
            return self.real(arr, path, size, text, xy, fill, language)

        shape.draw = spy
        fonts.sheet(self.fonts[:2], 40, [STACKED], self.out)

        self.assertTrue(seen, "the sheet drew no text through the shaper at all")
        rows = [t for t in seen if t == STACKED]
        self.assertEqual(len(rows), len(self.fonts[:2]),
                         "one shaped run per font row expected, got %r" % (seen,))

    def test_the_rows_actually_have_ink_in_them(self):
        """A shaper that is called and paints nothing passes the test above and fails the user."""
        fonts.sheet(self.fonts[:1], 40, [STACKED], self.out)
        im = Image.open(self.out).convert("L")
        row = im.crop((fonts.NAME_W + 8, 56, im.width - 8, 56 + fonts.ROW_H))
        self.assertIsNotNone(row.getbbox(), "the font row came out empty")
        self.assertGreater(sum(row.histogram()[129:]), 100,
                           "the font row has almost no ink in it")


if __name__ == "__main__":
    unittest.main()
