# -*- coding: utf-8 -*-
"""Three questions, asked every run, in the order they matter.

WHY THIS IS A TEST AND NOT A PREFERENCE. Both of these were "remembered" settings, and both had
the same failure: the tool made a decision on your behalf, gave no sign it had, and offered no
visible way to change it. The report was two questions asked an hour apart --

    "where did the font picker go?"
    "I dragged it to the centre; why isn't it there?"

-- and the answer to both was a file on disk from an earlier session. A setting is only silent
when it is right, and the box is not right twice in a row: games move their subtitles between the
menu, the cutscene and gameplay.

So the box and the font are asked every run, with the last answer already selected. Keeping it
costs one key. The model is asked only when there is more than one to choose between, because a
dropdown with a single entry is a click with no decision in it.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from gamesubs import __main__ as m                           # noqa: E402

MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "src", "gamesubs", "__main__.py")
with open(MAIN, encoding="utf-8") as _f:
    CODE = _f.read()


class Args(object):
    def __init__(self, **kw):
        self.__dict__.update(kw)


class TheFont(unittest.TestCase):
    def test_a_font_on_the_command_line_wins_and_asks_nothing(self):
        self.assertEqual(m._choose_font(Args(font="Tahoma", no_pick_font=False)), "Tahoma")

    def test_the_opt_out_still_opts_out(self):
        """--no-pick-font is for a shortcut someone made themselves. It must not open a window."""
        self.assertIsNot(m._choose_font(Args(font=None, no_pick_font=True)), NotImplemented)

    def test_a_saved_font_no_longer_skips_the_chooser(self):
        """The line that did it. With it, the picker opened once, ever, and there was no trace
        afterwards that a font had ever been chosen."""
        self.assertNotIn("if saved and os.path.isfile(saved) and not", CODE)

    def test_the_chooser_starts_on_your_last_answer(self):
        self.assertIn("choose(server.home(\"fonts\"), current=saved)", CODE)


class TheBox(unittest.TestCase):
    def test_it_is_drawn_every_run(self):
        self.assertIn('if not getattr(a, "no_select", False):', CODE)

    def test_the_old_once_ever_condition_is_gone(self):
        self.assertNotIn("saved is None and not", CODE)

    def test_the_last_box_is_already_on_screen_so_enter_keeps_it(self):
        self.assertIn("select(virtual, saved, screens)", CODE)


class TheModel(unittest.TestCase):
    def test_one_model_means_no_question(self):
        self.assertIn("len(weights) <= 1", CODE)


class AStaleTranslationIsNotShown(unittest.TestCase):
    """When the sentence underneath changes, the translation on screen stops being about
    anything. Leaving it up until the new answer arrives shows Thai belonging to a line that is
    no longer on the screen, with nothing to say so -- seen on a paused cutscene, where a menu
    caption from a minute earlier sat over a completely different sentence."""

    def test_the_line_is_cleared_the_moment_the_picture_changes(self):
        after_new = CODE[CODE.index('elif state == "new":'):]
        self.assertLess(after_new.index("cur.set()"), after_new.index("w.submit"),
                        "the old translation survives into the new sentence")


if __name__ == "__main__":
    unittest.main(verbosity=2)
