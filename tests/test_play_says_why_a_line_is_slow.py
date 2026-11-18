# -*- coding: utf-8 -*-
"""When every line takes seconds, play says once why, and what to do -- and stays quiet when it is fast.

WHY. A player on 1.0.4 (2026-11-18): every line took 9 to 11 s, against 0.7 s on a graphics card.
They asked whether it was their card or something they forgot to download, and the console had the
answer nowhere. llama.cpp fits the model into the card memory that is FREE when it starts, so a
game already holding the card leaves the model on the processor, and nothing errors.

WHAT MUST STAY TRUE.
  - Three reads with a middle time above SLOW_S: one note, with the card and its memory in use.
  - A fast PC never sees it, and neither does one slow first read (the first can be slow alone).
  - Said once per run, not on every line.

    python tests/test_play_says_why_a_line_is_slow.py
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from gamesubs import __main__ as m                              # noqa: E402

CARD = {"name": "NVIDIA GeForce GTX 1650", "vendor": "NVIDIA", "integrated": False,
        "total_mb": 4096, "used_mb": 3890}
BUILT_IN = {"name": "Intel(R) UHD Graphics", "vendor": "Intel", "integrated": True}


class TheNote(unittest.TestCase):

    def test_the_players_times_get_the_note_with_their_card(self):
        text = "\n".join(m.slow_note([10.8, 10.8, 9.4], [CARD]))
        self.assertIn("about 10.8 s", text)
        self.assertIn("NVIDIA GeForce GTX 1650 | 4.0 GB, 3.8 GB in use now", text)
        self.assertIn("start play.bat BEFORE the game", text)

    def test_a_graphics_card_is_quiet(self):
        self.assertEqual(m.slow_note([0.7, 0.6, 1.1], [CARD]), [])

    def test_one_slow_first_read_is_not_a_slow_pc(self):
        self.assertEqual(m.slow_note([6.0, 0.7, 0.8], [CARD]), [])

    def test_exactly_the_limit_is_still_quiet(self):
        self.assertEqual(m.slow_note([m.SLOW_S] * 3, [CARD]), [])

    def test_two_reads_are_too_few_to_say_anything(self):
        self.assertEqual(m.slow_note([9.0, 9.0], [CARD]), [])

    def test_no_card_of_its_own_says_so_instead_of_blaming_a_game(self):
        text = "\n".join(m.slow_note([4.0, 4.0, 4.0], [BUILT_IN]))
        self.assertIn("built into the processor", text)
        self.assertNotIn("texture", text)

    def test_the_built_in_one_is_not_taken_for_the_card(self):
        text = "\n".join(m.slow_note([4.0, 4.0, 4.0], [BUILT_IN, CARD]))
        self.assertIn("NVIDIA GeForce GTX 1650", text)

    def test_a_card_windows_will_not_measure_still_gets_named(self):
        text = "\n".join(m.slow_note([4.0, 4.0, 4.0], [dict(CARD, used_mb=None)]))
        self.assertIn("NVIDIA GeForce GTX 1650 | 4.0 GB", text)
        self.assertNotIn("in use now", text)


class SaidOnce(unittest.TestCase):

    def setUp(self):
        self.was = (m._cards, dict(m.SLOW), m.LAST.copy())
        m._cards = lambda: [CARD]
        m.SLOW.update(secs=[], said=False)

    def tearDown(self):
        m._cards = self.was[0]
        m.SLOW.clear()
        m.SLOW.update(self.was[1])
        m.LAST.clear()
        m.LAST.update(self.was[2])

    def run_lines(self, times):
        out = io.StringIO()
        with redirect_stdout(out):
            for i, s in enumerate(times):
                m._log(secs=s, source="line %d" % i, text="t %d" % i, tokens=700)
        return out.getvalue()

    def test_six_slow_lines_say_it_once(self):
        self.assertEqual(self.run_lines([9.8, 10.8, 9.4, 10.0, 9.9, 10.1]).count("Each line is taking"), 1)

    def test_six_fast_lines_never_say_it(self):
        self.assertNotIn("Each line is taking", self.run_lines([0.7] * 6))

    def test_errors_do_not_count_as_reads(self):
        out = io.StringIO()
        with redirect_stdout(out):
            m._log(error="ConnectionError: refused")
            m._log(error="ConnectionError: refused")
            m._log(secs=9.0, source="a", text="a")
            m._log(secs=9.0, source="b", text="b")
        self.assertNotIn("Each line is taking", out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
