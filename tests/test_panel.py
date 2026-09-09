# -*- coding: utf-8 -*-
"""The settings window, and the two processes that have to notice it moved.

WHY THERE IS A WINDOW AT ALL. Every number here was already a command-line flag, which is the
same as saying most people would never change it. The report was one sentence, and it is right:
nobody remembers flags. The flags still work and are now overrides; the panel is the front door.

THE PART THAT BREAKS IS NOT THE WINDOW. A slider that moves and a file that gets written are the
easy half. The half that fails silently is the other two processes noticing -- the overlay is a
separate process and the translator loop is a third, and neither has any reason to re-read a file
unless somebody wrote the line that makes it. That seam has failed three times in this repo in a
single day, so each end of it is tested here on its own.
"""
import io
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from gamesubs import overlay, server                             # noqa: E402


class WhatTheFileMayContain(unittest.TestCase):
    """`clamp_tuning` is the only way in. settings.json is a file a person can open and type in."""

    def test_an_empty_file_gives_the_defaults(self):
        self.assertEqual(server.clamp_tuning({}), server.TUNING)
        self.assertEqual(server.clamp_tuning(None), server.TUNING)

    def test_a_number_out_of_range_is_pulled_back_to_the_slider(self):
        self.assertEqual(server.clamp_tuning({"size": 9999})["size"], server.LIMITS["size"][1])
        self.assertEqual(server.clamp_tuning({"size": -5})["size"], server.LIMITS["size"][0])

    def test_a_read_speed_of_zero_cannot_get_through(self):
        """It is a divisor. A hand-typed 0 here would be a crash in the translator, in a process
        that is not the one the file was edited in."""
        self.assertGreater(server.clamp_tuning({"read_speed": 0})["read_speed"], 0)

    def test_text_and_booleans_are_not_numbers(self):
        for junk in ("28", None, True, [30], {"a": 1}):
            self.assertEqual(server.clamp_tuning({"size": junk})["size"], server.TUNING["size"])

    def test_something_that_is_not_a_colour_is_refused(self):
        """The panel only ever sends #rrggbb, but the file is hand-editable and the value
        is read by a different process. "red" would be dropped by the renderer, silently,
        while the settings file went on saying red."""
        for junk in ("red", "#fff", "#12345g", "ffffff", ""):
            self.assertEqual(server.clamp_tuning({"text_colour": junk})["text_colour"],
                             server.TUNING["text_colour"], junk)

    def test_a_real_colour_gets_through(self):
        self.assertEqual(server.clamp_tuning({"text_colour": "#FFd400"})["text_colour"],
                         "#FFd400")

    def test_unknown_keys_are_dropped(self):
        self.assertNotIn("nonsense", server.clamp_tuning({"nonsense": 1}))

    def test_size_stays_a_whole_number(self):
        self.assertIsInstance(server.clamp_tuning({"size": 30.7})["size"], int)


class WritingItDoesNotLoseTheRest(unittest.TestCase):
    """settings.json also holds the font and the box. Those took a person real effort to choose."""

    def setUp(self):
        self.p = os.path.join(server.app_dir(), server.SETTINGS)
        self.backup = io.open(self.p, encoding="utf-8").read() if os.path.exists(self.p) else None

    def tearDown(self):
        if self.backup is None:
            if os.path.exists(self.p):
                os.remove(self.p)
        else:
            io.open(self.p, "w", encoding="utf-8").write(self.backup)

    def test_the_font_and_the_box_survive_a_slider(self):
        server.save_settings({"font": "C:/x.ttf", "region": [1, 2, 3, 4]})
        server.save_tuning({"size": 40})
        d = server.load_settings()
        self.assertEqual(d["font"], "C:/x.ttf")
        self.assertEqual(d["region"], [1, 2, 3, 4])
        self.assertEqual(d["tuning"]["size"], 40)

    def test_what_was_saved_is_what_comes_back(self):
        server.save_tuning({"size": 44, "min_hold": 2.5, "read_speed": 22})
        got = server.load_tuning()
        self.assertEqual((got["size"], got["min_hold"], got["read_speed"]), (44, 2.5, 22.0))

    def test_the_stamp_moves_when_the_file_does(self):
        """What the other two processes poll. If it did not move, nothing would ever reload."""
        server.save_tuning({"size": 20})
        before = server.settings_stamp()
        server.save_tuning({"size": 48})
        self.assertNotEqual(server.settings_stamp(), before)

    def test_the_stamp_moves_even_for_a_write_the_clock_cannot_separate(self):
        """The one above passes by luck: two saves usually land in different filesystem
        ticks. Usually is not a guarantee, and the failure is invisible -- the overlay
        keeps the old colour and nothing anywhere says why. So force the case: put the
        timestamp in the future and require the next write to beat it anyway."""
        server.save_tuning({"size": 20})
        ahead = os.stat(self.p).st_mtime_ns + 5 * 10 ** 9
        os.utime(self.p, ns=(ahead, ahead))
        server.save_tuning({"size": 20})
        self.assertGreater(os.stat(self.p).st_mtime_ns, ahead,
                           "the write left the timestamp where it was or moved it back")

    def test_a_hand_edited_file_full_of_junk_still_starts(self):
        io.open(self.p, "w", encoding="utf-8").write(json.dumps({"tuning": {"size": "big"}}))
        self.assertEqual(server.load_tuning(), server.TUNING)


class TheOverlayNoticesTheSliderMoved(unittest.TestCase):
    """`Overlay._retune`, without opening a window."""

    class Fake(object):
        def __init__(self, size=28, stamp=(1, 1)):
            self.size, self._stamp, self.sized = size, stamp, []
            self.font_path = "x.ttf"
            self.colours = (server.TUNING["text_colour"], server.TUNING["plate_colour"])

        def _set_size(self, n):
            self.size = n
            self.sized.append(n)

    def run_retune(self, fake, stamp, font=None, **tune):
        """Drive _retune with the two things it reads from outside itself stubbed out."""
        saved = (overlay.settings_stamp, overlay.load_tuning, overlay.load_font,
                 overlay.render.resolve_font)
        overlay.settings_stamp = lambda: stamp
        overlay.load_tuning = lambda: dict(server.TUNING, **tune)
        overlay.load_font = lambda: font or fake.font_path
        overlay.render.resolve_font = lambda f, _s, _d: f
        try:
            return overlay.Overlay._retune(fake)
        finally:
            (overlay.settings_stamp, overlay.load_tuning, overlay.load_font,
             overlay.render.resolve_font) = saved

    def test_a_new_size_is_picked_up(self):
        f = self.Fake()
        self.assertTrue(self.run_retune(f, (2, 2), size=44))
        self.assertEqual(f.sized, [44])

    def test_an_untouched_file_is_not_re_read(self):
        f = self.Fake()
        self.assertFalse(self.run_retune(f, f._stamp, size=44))
        self.assertEqual(f.sized, [], "reloaded the font for a file nobody wrote")

    def test_a_write_that_did_not_change_anything_reloads_nothing(self):
        """The panel writes every setting at once, so most writes are about a different one."""
        f = self.Fake(size=28)
        self.assertFalse(self.run_retune(f, (9, 9), size=28))
        self.assertEqual(f.sized, [])

    def test_a_new_colour_is_picked_up(self):
        f = self.Fake()
        self.assertTrue(self.run_retune(f, (3, 3), text_colour="#ffd400"))
        self.assertEqual(f.colours[0], "#ffd400")

    def test_a_new_font_is_picked_up(self):
        f = self.Fake()
        self.assertTrue(self.run_retune(f, (4, 4), font="other.ttf"))
        self.assertEqual(f.font_path, "other.ttf")
        self.assertEqual(f.sized, [server.TUNING["size"]], "the new face was never loaded")

    def test_a_font_that_resolves_to_nothing_is_not_adopted(self):
        """resolve_font returns None when the file cannot draw the language. Taking it
        anyway means no subtitle at all, which is worse than the wrong typeface."""
        f = self.Fake()
        self.run_retune(f, (5, 5), font=None)
        self.assertEqual(f.font_path, "x.ttf")

    def test_the_render_throws_away_what_is_on_screen_when_it_does(self):
        """Otherwise the cache says "same line, already drawn" and the new size never appears
        until the game happens to say something else."""
        body = io.open(os.path.join(ROOT, "src", "gamesubs", "overlay.py"), encoding="utf-8").read()
        body = body[body.index("    def _render(self):"):body.index("    def run(self):")]
        self.assertIn("self._retune()", body)
        self.assertIn("self._shown = None", body)


class TheLoopNoticesToo(unittest.TestCase):

    @staticmethod
    def main_source():
        return io.open(os.path.join(ROOT, "src", "gamesubs", "__main__.py"),
                       encoding="utf-8").read()

    def test_the_watch_loop_re_reads_the_file(self):
        body = self.main_source()
        body = body[body.index("def _loop("):]
        self.assertIn("server.settings_stamp()", body)
        self.assertIn("cur.min_hold =", body)
        self.assertIn("cur.speed =", body)

    def test_zero_from_a_flag_is_an_answer_not_a_missing_one(self):
        """`--min-hold 0` means turn the hold off. `flag or saved` reads that as "nothing given"
        and restores the setting the user just switched off."""
        from gamesubs.__main__ import _or_saved
        self.assertEqual(_or_saved(0, 1.2), 0)
        self.assertEqual(_or_saved(None, 1.2), 1.2)
        self.assertEqual(_or_saved(2.5, 1.2), 2.5)

    def test_play_opens_the_panel(self):
        body = self.main_source()
        i = body.index("def cmd_play(")
        self.assertIn('"gamesubs", "panel"', body[i:body.index("def cmd_fonts(")])

    def test_and_closes_it_again(self):
        """It is a child process. Left running it is a window with sliders that change nothing."""
        body = self.main_source()
        i = body.index("def cmd_play(")
        self.assertIn("for p in (pn, ov, proc):", body[i:body.index("def cmd_fonts(")])


class ThePanelAndTheSettingsAgree(unittest.TestCase):
    """One list of keys, in three files. This is the drift that produces a slider for a setting
    nothing reads."""

    def test_every_slider_is_a_real_setting(self):
        from gamesubs import panel
        for key, _t, _f, _s, _w in panel.ROWS:
            self.assertIn(key, server.TUNING)

    def test_every_number_has_a_range(self):
        self.assertEqual(sorted(list(server.LIMITS) + list(server.CHOICES)),
                         sorted(server.TUNING))

    def test_the_defaults_are_inside_their_own_ranges(self):
        for k, (lo, hi) in server.LIMITS.items():
            self.assertTrue(lo <= server.TUNING[k] <= hi,
                            "%s default %r is outside %r" % (k, server.TUNING[k], (lo, hi)))

    def test_the_hold_defaults_are_not_a_second_copy(self):
        """`service` owns these two numbers. Typed again here they would drift, and the panel
        would open on a value the translator was not using."""
        from gamesubs import service
        self.assertEqual(server.TUNING["min_hold"], service.MIN_HOLD)
        self.assertEqual(server.TUNING["read_speed"], service.READ_SPEED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
