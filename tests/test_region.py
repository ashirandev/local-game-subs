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
from gamesubs.region import MIN_SIDE, norm_box, to_screen


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
