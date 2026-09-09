# -*- coding: utf-8 -*-
"""Aiming the box: a sensible default, moving it without redrawing it, and finding the centre.

THREE THINGS THAT WERE MISSING, all of them the same complaint in different words -- the tool
made you do work it could have done.

  * NO DEFAULT AT ALL. The selector opened on an empty screen, so the first thing a new person
    had to do was invent a rectangle, for a tool they had not yet watched work. There was a
    fallback, but only if you CANCELLED, and it was the bottom 28% of the screen at full width:
    not centred, not a subtitle strip, and wide enough to take in the whole HUD -- everything it
    takes in being something the model reads out and translates.

  * NO WAY TO MOVE IT. Every adjustment meant dragging both corners again. After the first
    attempt the size is right and it is the POSITION that is wrong, over and over.

  * NO WAY TO CENTRE IT. Subtitles are centred on every game that has them, and a hand on a
    mouse lands three pixels off and stays there. Wanting it and not being able to have it.

THE DEFAULT IS MEASURED, NOT CHOSEN. Two independent readings on a 2560x1440 screen:

    the box a person dragged by hand : centre 0.488, spans 0.756 - 0.849 down
    RE4R's own cutscene line         : centre 0.501, spans ~0.745 - 0.775 down

The first draft covered 0.75 - 0.86 and would have clipped the real line by a hair. A clipped
line is the failure nobody can see: the model reads the half it was handed and translates that
half perfectly.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from gamesubs.region import (SNAP, centred_on, default_box, inside,     # noqa: E402
                             keep_on_screen, snap_x)

WIDE = {"left": 0, "top": 0, "width": 2560, "height": 1440}
SIDE = {"left": 2560, "top": 358, "width": 1920, "height": 1080}
TALL = {"left": 4480, "top": 0, "width": 1080, "height": 1920}
MONS = [WIDE, SIDE, TALL]
VIRTUAL = {"left": 0, "top": 0, "width": 5560, "height": 1920}


def frac(box, mon):
    l, t, w, h = box
    return ((l + w / 2.0 - mon["left"]) / mon["width"],
            (t - mon["top"]) / mon["height"], (t + h - mon["top"]) / mon["height"])


class TheDefaultBox(unittest.TestCase):

    def test_it_is_centred(self):
        for mon in MONS:
            self.assertAlmostEqual(frac(default_box(mon), mon)[0], 0.5, delta=0.002,
                                   msg=str(mon))

    def test_it_is_low_but_not_at_the_very_bottom(self):
        """Games put a prompt bar under the subtitle -- Skip Cutscene, Photo Mode -- and reading
        that is reading the HUD."""
        for mon in MONS:
            _c, top, bottom = frac(default_box(mon), mon)
            self.assertGreater(top, 0.6, "too high up the screen")
            self.assertLess(bottom, 0.95, "into the prompt bar at the bottom")

    def test_it_covers_the_line_re4r_actually_draws(self):
        """From a screenshot of the game: the cutscene line spans 0.745 to 0.775 down and 0.428
        to 0.574 across. This is the measurement the first draft failed."""
        l, t, w, h = default_box(WIDE)
        self.assertLessEqual(t / 1440.0, 0.745)
        self.assertGreaterEqual((t + h) / 1440.0, 0.775)
        self.assertLessEqual(l / 2560.0, 0.428)
        self.assertGreaterEqual((l + w) / 2560.0, 0.574)

    def test_and_the_box_a_person_drew_by_hand(self):
        l, t, w, h = default_box(WIDE)
        self.assertLessEqual(t / 1440.0, 0.756)
        self.assertGreaterEqual((t + h) / 1440.0, 0.849)

    def test_it_is_tall_enough_for_two_lines(self):
        """A box drawn round a one-line subtitle is short by exactly one line the moment the game
        shows two, which RE4R does in its first cutscene."""
        _l, _t, _w, h = default_box(WIDE)
        self.assertGreater(h, 2 * 0.092 * 1440 * 0.8)

    def test_it_lands_on_the_monitor_it_was_given(self):
        """Not on the primary, and not in the middle of the virtual desktop -- which on unequal
        monitors is a point on no display at all."""
        for mon in MONS:
            l, t, w, h = default_box(mon)
            self.assertGreaterEqual(l, mon["left"])
            self.assertLessEqual(l + w, mon["left"] + mon["width"])
            self.assertGreaterEqual(t, mon["top"])
            self.assertLessEqual(t + h, mon["top"] + mon["height"])


class MovingItWithoutRedrawingIt(unittest.TestCase):

    def test_a_point_in_the_box_is_a_move(self):
        box = default_box(WIDE)
        self.assertTrue(inside(box, box[0] + 5, box[1] + 5))
        self.assertTrue(inside(box, box[0] + box[2], box[1] + box[3]), "the edge counts")

    def test_a_point_outside_it_is_a_new_box(self):
        box = default_box(WIDE)
        self.assertFalse(inside(box, box[0] - 1, box[1] + 5))
        self.assertFalse(inside(box, box[0] + 5, box[1] + box[3] + 1))

    def test_nothing_is_inside_nothing(self):
        self.assertFalse(inside(None, 10, 10))

    def test_it_cannot_be_dragged_off_the_desktop(self):
        """Off the edge it would be a box that watches pixels there is no screen for, and the
        capture reads black for ever with nothing to say why."""
        self.assertEqual(keep_on_screen((9000, 100, 400, 200), VIRTUAL), (5160, 100, 400, 200))
        self.assertEqual(keep_on_screen((-300, -80, 400, 200), VIRTUAL), (0, 0, 400, 200))

    def test_but_it_may_be_dragged_onto_another_screen(self):
        """Clamping to one monitor would fight the person moving it to the one the game is on."""
        box = (2700, 500, 400, 200)
        self.assertEqual(keep_on_screen(box, VIRTUAL), box)


class FindingTheCentre(unittest.TestCase):

    def test_close_enough_snaps_exactly(self):
        box = default_box(WIDE)
        for off in (1, SNAP - 1, -(SNAP - 1)):
            near = (box[0] + off, box[1], box[2], box[3])
            self.assertEqual(snap_x(near, MONS), box, "off by %d" % off)

    def test_far_away_is_left_where_it_was(self):
        """Snapping something that was not aimed at the centre is the tool overruling the person."""
        box = default_box(WIDE)
        far = (box[0] + 200, box[1], box[2], box[3])
        self.assertEqual(snap_x(far, MONS), far)

    def test_it_only_moves_sideways(self):
        """Vertical position is the whole point of aiming at a subtitle; snapping it would undo
        the aim the snap is supposed to help with."""
        box = default_box(WIDE)
        near = (box[0] + 5, box[1] + 137, box[2], box[3])
        self.assertEqual(snap_x(near, MONS)[1], box[1] + 137)

    def test_each_monitor_has_its_own_centre(self):
        for mon in MONS:
            self.assertIs(centred_on(default_box(mon), MONS), mon)

    def test_a_box_between_two_screens_is_centred_on_neither(self):
        self.assertIsNone(centred_on((2400, 900, 400, 200), MONS))

    def test_the_default_is_already_centred(self):
        """Otherwise the guide line opens unlit on a box that was placed to be centred, which
        reads as the guide being broken."""
        for mon in MONS:
            self.assertIsNotNone(centred_on(default_box(mon), MONS))


class TheSelectorUsesAllOfIt(unittest.TestCase):
    """The seam. Every helper above is pure and could be perfect while the window calls none."""

    @staticmethod
    def source():
        import io
        return io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                    "src", "gamesubs", "region.py"), encoding="utf-8").read()

    def setUp(self):
        self.body = self.source()
        self.body = self.body[self.body.index("def select("):]

    def test_pressing_inside_the_box_moves_it(self):
        self.assertIn('drag["mode"] = "move"', self.body)
        self.assertIn("inside(box, e.x + ox, e.y + oy)", self.body)

    def test_a_move_snaps_and_stays_on_screen(self):
        self.assertIn("snap_x(moved, mons)", self.body)
        self.assertIn("keep_on_screen(", self.body)

    def test_the_centre_line_is_drawn_for_every_monitor(self):
        self.assertIn("for m in mons:", self.body)
        self.assertIn("GUIDE", self.body)

    def test_and_lights_up_when_the_box_agrees_with_it(self):
        """The signal that turns "I think that is centred" into "it is"."""
        self.assertIn("HIT if", self.body)

    def test_the_hint_says_the_new_gestures(self):
        self.assertIn("drag inside to move", self.body)
        self.assertIn("C = centre", self.body)

    def test_the_band_opens_the_selector_on_the_default(self):
        import io
        main = io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                    "src", "gamesubs", "__main__.py"), encoding="utf-8").read()
        band = main[main.index("def _band("):main.index("def _log(")]
        self.assertIn("server.load_region() or default_box(m)", band,
                      "a first run still opens on an empty screen")


if __name__ == "__main__":
    unittest.main(verbosity=2)
