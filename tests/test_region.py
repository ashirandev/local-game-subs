# -*- coding: utf-8 -*-
"""The capture box: the maths behind dragging it, and remembering it afterwards.

The window itself is not tested here -- it is thirty lines of tkinter bindings. What is tested is
everything that can be silently wrong: a drag in the "wrong" direction, a second monitor moving
the origin, and a saved box that comes back as something other than what was saved.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, __file__.rsplit("tests", 1)[0] + "src")
from gamesubs import server
from gamesubs.__main__ import _grown
from gamesubs.region import (MIN_SIDE, banner_spots, hint_spot, monitor_for,
                             norm_box, to_screen)


class DragMaths(unittest.TestCase):
    BOX = (300, 900, 800, 220)

    def test_dragging_down_and_right(self):
        self.assertEqual(norm_box(300, 900, 1100, 1120), self.BOX)

    def test_dragging_up_and_left_gives_the_same_box(self):
        # Without this the width comes out negative, which does not raise -- it selects nothing.
        self.assertEqual(norm_box(1100, 1120, 300, 900), self.BOX)

    def test_dragging_up_and_right(self):
        self.assertEqual(norm_box(300, 1120, 1100, 900), self.BOX)

    def test_dragging_down_and_left(self):
        self.assertEqual(norm_box(1100, 900, 300, 1120), self.BOX)

    def test_a_click_has_no_size(self):
        self.assertEqual(norm_box(500, 500, 500, 500), (500, 500, 0, 0))

    def test_a_misclick_threshold_exists(self):
        self.assertGreater(MIN_SIDE, 0)


class Args(object):
    def __init__(self, **kw):
        self.__dict__.update(kw)


class TheBoxGetsALittleAir(unittest.TestCase):
    """A drag that ends one pixel inside the sentence hands the model a clipped word.

    Which it then translates perfectly, as the wrong word, with nothing anywhere reporting a
    problem -- the failure this whole file is about. So the box in use is a little larger than the
    box that was drawn, in both directions, because what is read and what is covered are the same
    rectangle.
    """

    MON = {"left": 0, "top": 0, "width": 2560, "height": 1440}

    def test_it_grows_on_every_side(self):
        self.assertEqual(_grown([100, 200, 400, 60], self.MON, 10), [90, 190, 420, 80])

    def test_a_box_against_the_bottom_edge_has_nowhere_to_grow(self):
        """Subtitles live at the bottom of the screen, so this is the ordinary case."""
        got = _grown([100, 1380, 400, 60], self.MON, 20)
        self.assertEqual(got[1] + got[3], 1440)
        self.assertEqual(got[1], 1360)

    def test_the_corners_clamp_too(self):
        self.assertEqual(_grown([0, 0, 100, 50], self.MON, 30), [0, 0, 130, 80])

    def test_zero_pad_is_the_box_exactly_as_drawn(self):
        self.assertEqual(_grown([100, 200, 400, 60], self.MON, 0), [100, 200, 400, 60])

    def test_no_box_stays_no_box(self):
        self.assertIsNone(_grown(None, self.MON, 14))

    def test_the_band_that_gets_watched_is_the_grown_one(self):
        """Through the real path, not the helper. A test that calls `_grown` directly proves the
        arithmetic and nothing about whether anything uses it -- and a mutant that deleted the
        call from `_band` stayed green until this test existed. It is the same seam that broke
        the font search this morning: both halves correct, nothing joining them."""
        from gamesubs.__main__ import _band
        try:
            b = _band(Args(region="600,1200,400,60", monitor=1, frac=0.25, wfrac=0.7,
                           pad=10, no_select=True))
        except Exception as e:                                # noqa: BLE001
            self.skipTest("no screen here: %s" % e)
        self.assertEqual((b.rect["width"], b.rect["height"]), (420, 80))
        self.assertEqual((b.rect["left"], b.rect["top"]), (590, 1190))

    def test_and_pad_zero_leaves_it_alone(self):
        from gamesubs.__main__ import _band
        try:
            b = _band(Args(region="600,1200,400,60", monitor=1, frac=0.25, wfrac=0.7,
                           pad=0, no_select=True))
        except Exception as e:                                # noqa: BLE001
            self.skipTest("no screen here: %s" % e)
        self.assertEqual((b.rect["left"], b.rect["top"], b.rect["width"], b.rect["height"]),
                         (600, 1200, 400, 60))


class NothingIsDrawnInAHole(unittest.TestCase):
    """The virtual screen is a bounding box, and a bounding box of unequal monitors has holes.

    This is the bug a person actually hit, on 2026-09-09, with the game running: he dragged a box
    around Resident Evil 4's subtitles, and neither instruction was anywhere on any screen. Both
    were drawn at coordinates inside the virtual rectangle and on no display:

        the banner            (2780, 40)      between two monitors, above a third
        "press ENTER"         (1269, 1465)    below the bottom edge of the monitor he used

    He had a dashed box, no way to find out what to press, and his keystrokes went to the game.
    The measurement is the layout of his desk, so the layout is what the tests are written on.
    """

    # 2560x1440 main, a 1920x1080 sitting 358 px lower to its right, a portrait screen past that.
    MONS = [{"left": 0, "top": 0, "width": 2560, "height": 1440},
            {"left": 2560, "top": 358, "width": 1920, "height": 1080},
            {"left": 4480, "top": 0, "width": 1080, "height": 1920}]
    VIRTUAL = {"left": 0, "top": 0, "width": 5560, "height": 1920}
    BOX = (655, 1209, 1228, 230)                    # the box he drew, around the game's subtitles

    def on_a_screen(self, x, y):
        return monitor_for(x, y, self.MONS) is not None

    def test_the_hole_is_real(self):
        """If this ever fails, the rest of this class is guarding nothing."""
        self.assertTrue(self.on_a_screen(1269, 1400))
        self.assertFalse(self.on_a_screen(1269, 1465), "point below the main monitor")
        self.assertFalse(self.on_a_screen(2780, 40), "point above the middle monitor")

    def test_the_instruction_for_a_bottom_of_screen_box_is_visible(self):
        x, y = hint_spot(self.BOX, self.MONS)
        self.assertTrue(self.on_a_screen(x, y), "the instruction landed on no monitor")

    def test_a_subtitle_box_is_always_at_the_bottom_so_test_every_monitor(self):
        """Not a special case: subtitles are at the bottom of the screen on every game there is,
        so 'below the box' is off the monitor in the ORDINARY case."""
        for m in self.MONS:
            box = (m["left"] + 40, m["top"] + m["height"] - 200, m["width"] - 80, 195)
            x, y = hint_spot(box, self.MONS)
            self.assertTrue(self.on_a_screen(x, y), "off-screen for monitor at %s" % m["left"])

    def test_a_box_in_open_space_keeps_the_instruction_below_it(self):
        x, y = hint_spot((300, 300, 600, 100), self.MONS)
        self.assertGreater(y, 400, "with room underneath it belongs underneath")
        self.assertTrue(self.on_a_screen(x, y))

    def test_a_box_taller_than_its_monitor_puts_it_inside(self):
        x, y = hint_spot((10, 0, 2000, 1440), self.MONS)
        self.assertTrue(self.on_a_screen(x, y))

    def test_every_monitor_gets_its_own_banner(self):
        spots = banner_spots(self.MONS)
        self.assertEqual(len(spots), len(self.MONS))
        for x, y in spots:
            self.assertTrue(self.on_a_screen(x, y), "banner at (%s, %s) is on no monitor" % (x, y))

    def test_the_selector_draws_one_banner_per_monitor_through_that_function(self):
        """Through the real path. Asserting on `banner_spots` proves the arithmetic and nothing
        about whether the window uses it -- a mutant that put the banner back in the middle of
        the virtual screen stayed green until this existed. `select` needs a display, so this
        reads the source it would run rather than opening a window nobody is looking at."""
        import inspect

        from gamesubs import region as regmod
        src = inspect.getsource(regmod.select)
        self.assertIn("banner_spots(mons)", src)
        self.assertNotIn('virtual["width"] // 2, 40', src)

    def test_the_middle_of_the_virtual_screen_is_not_a_place(self):
        """The old behaviour, kept as a test so it cannot come back as a 'simplification'."""
        self.assertFalse(self.on_a_screen(self.VIRTUAL["width"] // 2, 40))

    def test_no_monitors_still_works(self):
        """`select` can be called with only the virtual rect -- it must place, not crash."""
        self.assertIsNone(monitor_for(5, 5, None))
        self.assertEqual(banner_spots(None), [])
        self.assertEqual(hint_spot(self.BOX, None), (655 + 614, 1209 + 230 + 30))


class ScreenCoordinates(unittest.TestCase):
    def test_a_single_monitor_changes_nothing(self):
        self.assertEqual(to_screen((10, 20, 100, 50), {"left": 0, "top": 0}), (10, 20, 100, 50))

    def test_a_monitor_to_the_left_has_a_negative_origin(self):
        # The case that makes this function exist. A selector that skips it is correct on the
        # setup that does not need it and wrong on the one that does.
        self.assertEqual(to_screen((10, 20, 100, 50), {"left": -1920, "top": 0}),
                         (-1910, 20, 100, 50))

    def test_a_monitor_above_shifts_the_top(self):
        self.assertEqual(to_screen((10, 20, 100, 50), {"left": 0, "top": -1080}),
                         (10, -1060, 100, 50))

    def test_the_size_is_never_touched(self):
        for virt in ({"left": 0, "top": 0}, {"left": -1920, "top": -1080}, {"left": 2560, "top": 5}):
            self.assertEqual(to_screen((7, 9, 800, 220), virt)[2:], (800, 220))


class Remembering(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.old = os.environ.get("GAMESUBS_HOME")
        os.environ["GAMESUBS_HOME"] = self.d

    def tearDown(self):
        if self.old is None:
            os.environ.pop("GAMESUBS_HOME", None)
        else:
            os.environ["GAMESUBS_HOME"] = self.old
        shutil.rmtree(self.d, ignore_errors=True)

    def test_nothing_saved_yet(self):
        self.assertIsNone(server.load_region())

    def test_a_box_survives_a_round_trip(self):
        server.save_region((840, 1035, 880, 235))
        self.assertEqual(server.load_region(), (840, 1035, 880, 235))

    def test_a_negative_origin_survives_too(self):
        server.save_region((-1910, 20, 800, 220))
        self.assertEqual(server.load_region(), (-1910, 20, 800, 220))

    def test_saving_a_box_keeps_other_settings(self):
        server.save_settings({"something": "else"})
        server.save_region((1, 2, 3, 4))
        self.assertEqual(server.load_settings()["something"], "else")

    def test_a_broken_settings_file_is_ignored_rather_than_fatal(self):
        io.open(os.path.join(self.d, server.SETTINGS), "w").write("{not json")
        self.assertEqual(server.load_settings(), {})
        self.assertIsNone(server.load_region())

    def test_a_zero_sized_box_is_not_accepted(self):
        # Otherwise the tool watches a strip with no pixels in it and simply never sees anything.
        io.open(os.path.join(self.d, server.SETTINGS), "w").write(
            json.dumps({"region": [10, 10, 0, 200]}))
        self.assertIsNone(server.load_region())

    def test_a_malformed_box_is_not_accepted(self):
        for bad in ([1, 2, 3], "840,1035", {"l": 1}, [1, 2, 3, "4"]):
            io.open(os.path.join(self.d, server.SETTINGS), "w").write(
                json.dumps({"region": bad}))
            self.assertIsNone(server.load_region(), bad)

    def test_no_temp_file_is_left_behind(self):
        # Written to a temp file and moved into place, so an interruption cannot leave a
        # half-written settings.json -- which would silently drop the box the user chose.
        server.save_region((1, 2, 3, 4))
        self.assertEqual([f for f in os.listdir(self.d) if f.endswith(".tmp")], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
