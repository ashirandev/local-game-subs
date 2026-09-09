# -*- coding: utf-8 -*-
"""Tests for the change gate -- the part that decides how often a model runs.

Every test here is about a way the gate can be wrong QUIETLY. A gate that fires too often does not
crash; it just spends your GPU re-reading one sentence. A gate that fires too rarely does not
crash either; it silently drops half the dialogue. Neither shows up as an error, so both have to
be pinned by tests.
"""
import sys
import unittest

import numpy as np

sys.path.insert(0, __file__.rsplit("tests", 1)[0] + "src")
from gamesubs.capture import Band, ChangeGate, coarse, ink, ink_span


def band(h=200, w=800, bg=30):
    """A gameplay-coloured strip with no text on it."""
    a = np.full((h, w, 3), bg, np.uint8)
    a[:, :, 1] = bg + 12                       # slightly green, like foliage
    return a


def put(a, colour, x=100, y=80, w=300, h=40):
    a[y:y + h, x:x + w] = colour
    return a


class WhereTheLineIs(unittest.TestCase):
    """The rows the subtitle occupies -- what the plate is placed on.

    This exists because the plate used to be centred in the box the user dragged, and a person
    drags a box around WHERE subtitles appear, not around one line of them. The line sits wherever
    the game puts it inside that box, and on the very first frame anyone looked at closely, that
    was not the middle.
    """

    def test_it_finds_the_rows_the_text_is_on(self):
        a = put(band(), (250, 250, 250), y=120, h=40)
        self.assertEqual(ink_span(ink(a)), (120, 159))

    def test_one_bright_speck_far_away_does_not_stretch_it(self):
        """`ink` is a colour filter, not a text detector -- its own docstring says a snow field
        passes it. Without a density floor a single glint of sky doubles the plate."""
        a = put(band(), (250, 250, 250), y=120, h=40)
        a[8, 700] = (255, 255, 255)
        self.assertEqual(ink_span(ink(a)), (120, 159))

    def test_two_lines_of_dialogue_are_one_span(self):
        a = put(band(), (250, 250, 250), y=100, h=30)
        put(a, (250, 250, 250), y=140, h=30)
        self.assertEqual(ink_span(ink(a)), (100, 169))

    def test_nothing_on_screen_has_no_answer(self):
        self.assertIsNone(ink_span(ink(band())))

    def test_the_gate_reports_it_only_while_there_is_a_line(self):
        g = ChangeGate(min_ink=700)
        g.feed(put(band(), (250, 250, 250), y=120, h=40))
        self.assertEqual(g.span, (120, 159))
        for _ in range(4):
            g.feed(band())
        self.assertIsNone(g.span, "a stale position puts the next plate in the wrong place")


class Ink(unittest.TestCase):
    def n(self, a):
        return int(ink(a, 185).sum())

    def test_empty_gameplay_has_almost_no_ink(self):
        self.assertLess(self.n(band()), 50)

    def test_white_text_is_ink(self):
        self.assertGreater(self.n(put(band(), (240, 240, 240))), 10000)

    def test_yellow_text_is_ink(self):
        self.assertGreater(self.n(put(band(), (235, 210, 60))), 10000)

    def test_light_grey_subtitle_is_ink(self):
        self.assertGreater(self.n(put(band(), (200, 200, 200))), 10000)

    def test_red_hud_marker_is_not_ink(self):
        # The case that motivates testing GREEN as well as red: a red marker is bright in R and
        # dark in G, and a "bright pixel" mask would take it.
        self.assertLess(self.n(put(band(), (240, 60, 60))), 50)

    def test_blue_objective_marker_is_not_ink(self):
        self.assertLess(self.n(put(band(), (60, 90, 240))), 50)

    def test_orange_hud_line_is_not_ink(self):
        self.assertLess(self.n(put(band(), (245, 140, 20))), 50)

    def test_dim_text_below_the_threshold_is_not_ink(self):
        self.assertLess(self.n(put(band(), (150, 150, 150))), 50)

    def test_a_white_sky_passes_the_mask_and_that_is_expected(self):
        # Stated as a test so nobody reads the mask as "text detected". A snow field passes the
        # COLOUR filter. What keeps it out is min_ink plus the change gate -- a sky does not
        # change in the shape of a sentence.
        self.assertGreater(self.n(np.full((200, 800, 3), 235, np.uint8)), 100000)


class Coarse(unittest.TestCase):
    def m(self, **kw):
        return ink(put(band(), (240, 240, 240), **kw), 185)

    def test_a_mask_does_not_differ_from_itself(self):
        a = self.m()
        self.assertEqual(int((coarse(a) ^ coarse(a)).sum()), 0)

    def test_one_pixel_of_jitter_stays_under_the_default_change(self):
        # A static subtitle is re-rendered every frame against a moving background, so its
        # antialiasing wobbles. Without the downscale this reads as a new line every tick.
        self.assertLess(int((coarse(self.m(x=100)) ^ coarse(self.m(x=101))).sum()), 90)

    def test_a_longer_line_exceeds_the_default_change(self):
        self.assertGreater(int((coarse(self.m(w=300)) ^ coarse(self.m(w=520))).sum()), 90)

    def test_same_ink_count_in_a_different_place_is_still_a_change(self):
        # Two different lines can have the SAME number of lit pixels. Counting ink would call
        # them identical; comparing the mask does not.
        a, b = self.m(x=60, w=300), self.m(x=420, w=300)
        self.assertEqual(int(a.sum()), int(b.sum()))
        self.assertGreater(int((coarse(a) ^ coarse(b)).sum()), 90)


class Gate(unittest.TestCase):
    def setUp(self):
        self.g = ChangeGate(min_ink=700, change=90, off_ticks=3)
        self.empty = band()
        self.one = put(band(), (240, 240, 240), x=100, w=300)
        self.two = put(band(), (240, 240, 240), x=100, w=560)

    def test_first_text_is_new(self):
        self.assertEqual(self.g.feed(self.one), "new")

    def test_the_same_text_again_is_not_new(self):
        self.g.feed(self.one)
        self.assertEqual(self.g.feed(self.one), "same")
        self.assertEqual(self.g.feed(self.one), "same")

    def test_different_text_is_new_again(self):
        self.g.feed(self.one)
        self.assertEqual(self.g.feed(self.two), "new")

    def test_an_empty_frame_does_not_clear_immediately(self):
        # A subtitle can drop for one frame on a hard cut. Clearing on the first empty frame
        # makes the line flicker.
        self.g.feed(self.one)
        self.assertEqual(self.g.feed(self.empty), "idle")
        self.assertEqual(self.g.feed(self.empty), "idle")
        self.assertEqual(self.g.feed(self.empty), "gone")

    def test_gone_fires_once_not_every_tick_after(self):
        self.g.feed(self.one)
        [self.g.feed(self.empty) for _ in range(3)]
        self.assertEqual(self.g.feed(self.empty), "idle")

    def test_a_flicker_shorter_than_off_ticks_does_not_reset_the_line(self):
        self.g.feed(self.one)
        self.g.feed(self.empty)
        self.assertEqual(self.g.feed(self.one), "same")     # not re-read

    def test_the_same_line_returning_after_a_real_gap_is_read_again(self):
        # After the text has genuinely gone, the next line must be treated as new even if it
        # happens to look like the previous one -- a repeated line is a real thing in dialogue,
        # and comparing across the gap would swallow it.
        self.g.feed(self.one)
        [self.g.feed(self.empty) for _ in range(3)]
        self.assertEqual(self.g.feed(self.one), "new")

    def test_it_exposes_the_numbers_tune_mode_prints(self):
        self.g.feed(self.one)
        self.assertGreater(self.g.ink_n, 700)
        self.assertEqual(self.g.diff_n, -1)                 # nothing to compare against yet
        self.g.feed(self.two)
        self.assertGreater(self.g.diff_n, 0)


class BandRect(unittest.TestCase):
    MON = {"left": 0, "top": 0, "width": 2560, "height": 1440}

    def test_an_explicit_region_is_used_verbatim(self):
        self.assertEqual(Band(self.MON, [10, 20, 300, 40]).rect,
                         {"left": 10, "top": 20, "width": 300, "height": 40})

    def test_the_default_is_the_bottom_middle_of_the_monitor(self):
        r = Band(self.MON, None, 0.25).rect
        self.assertEqual(r["height"], 360)
        self.assertEqual(r["top"] + r["height"], 1440)          # flush with the bottom edge
        self.assertEqual(r["width"], 1792)                      # 70% of 2560
        self.assertEqual(r["left"] + r["width"] // 2, 1280)     # horizontally centred

    def test_full_width_is_available(self):
        self.assertEqual(Band(self.MON, None, 0.25, wfrac=1.0).rect["width"], 2560)

    def test_a_second_monitor_offset_is_respected(self):
        r = Band({"left": 2560, "top": 0, "width": 1920, "height": 1080}, None, 0.25).rect
        self.assertEqual(r["top"], 810)
        self.assertGreaterEqual(r["left"], 2560)                # stays on that monitor
        self.assertLessEqual(r["left"] + r["width"], 2560 + 1920)

    def test_norm_is_fractions_of_its_own_monitor(self):
        n = Band({"left": 2560, "top": 0, "width": 1920, "height": 1080}, None, 0.25).norm()
        self.assertAlmostEqual(n["x"], 0.15, places=6)          # (1 - 0.7) / 2
        self.assertAlmostEqual(n["w"], 0.7, places=6)
        self.assertAlmostEqual(n["y"] + n["h"], 1.0, places=6)


FONTS = ["arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "FreeSansBold.ttf"]


def _font(size):
    from PIL import ImageFont
    for name in FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return None


def rendered(text, dx=0, w=1280, h=260):
    """A band with REAL TEXT on it, not a rectangle. See the class below for why that matters."""
    from PIL import Image, ImageDraw
    f = _font(40)
    if f is None:
        return None
    im = Image.new("RGB", (w, h), (26, 30, 24))
    d = ImageDraw.Draw(im)
    for i in range(0, w, 40):                       # background structure, not a flat colour
        d.line([(i, 0), (i - 60, h)], fill=(34, 40, 32), width=9)
    d.text((w // 2 + dx, 130), text, font=f, fill=(255, 255, 255), anchor="mm")
    return np.asarray(im)


@unittest.skipIf(_font(40) is None, "no TrueType font available to render test text")
class RealText(unittest.TestCase):
    """The tests above use filled rectangles, and rectangles are the reason a real bug shipped.

    A block of solid colour survives being shrunk. Text does not: a 40px stroke averaged into a
    10px cell lands well under half brightness, so with the old midpoint threshold the glyphs
    vanished and every sentence reduced to the same faint smear. The gate then answered "same
    line" to four completely different subtitles -- verified against the model, which read all
    four correctly when it was finally handed them.

    So these cases exist to keep fixtures honest: any change to the mask, the downscale or the
    threshold has to keep working on actual glyphs, not just on shapes that were easy.
    """

    LINES = ["We should keep moving before it gets dark.",
             "I told you not to follow me.",
             "Take the left path. I'll cover you from here.",
             "Stay behind me."]

    def test_every_different_line_reads_as_new(self):
        g = ChangeGate()
        states = [g.feed(rendered(t)) for t in self.LINES]
        self.assertEqual(states, ["new"] * 4, "the gate stopped reading new subtitles: %s" % states)

    def test_the_same_line_re_rendered_is_not_new(self):
        g = ChangeGate()
        g.feed(rendered(self.LINES[0]))
        self.assertEqual(g.feed(rendered(self.LINES[0], dx=1)), "same")

    def _masks(self, dx=0):
        g = ChangeGate()
        return [coarse(ink(rendered(t, dx=dx), g.bright)) for t in self.LINES]

    def test_the_worst_pair_of_lines_is_well_clear_of_the_threshold(self):
        """The number that has to be safe is the SMALLEST difference between ANY two lines.

        This test used to compare one pair, and that is how the threshold bug survived a green
        suite: the pair it happened to pick differed by 47 while the worst pair differed by 17.
        The gate compares consecutive lines and any two lines can be consecutive in a game, so
        the worst pair is the one that decides whether dialogue gets dropped.

        Twice the threshold, not merely above it: a value sitting just over the line has no room
        for a different font, a different game or a smaller subtitle.
        """
        ms = self._masks()
        worst = min(int((ms[i] ^ ms[k]).sum())
                    for i in range(len(ms)) for k in range(i + 1, len(ms)))
        change = ChangeGate().change
        self.assertGreater(worst, 2 * change,
                           "the two most similar lines differ by %d, and the gate fires at %d -- "
                           "too close, those two would read as one line" % (worst, change))

    def test_jitter_is_well_under_the_threshold(self):
        ms, js = self._masks(), self._masks(dx=1)
        jitter = max(int((ms[i] ^ js[i]).sum()) for i in range(len(ms)))
        change = ChangeGate().change
        self.assertLess(jitter, change / 2,
                        "a static line moves %d cells and the gate fires at %d -- it would "
                        "re-read the same subtitle forever" % (jitter, change))

    def test_text_makes_enough_ink_to_clear_min_ink(self):
        g = ChangeGate()
        g.feed(rendered("Stay behind me."))              # the shortest line in the set
        self.assertGreater(g.ink_n, g.min_ink)


if __name__ == "__main__":
    unittest.main(verbosity=2)
