# -*- coding: utf-8 -*-
"""Overlay behaviour that can be checked without opening a window.

The one that matters is the feedback loop. The overlay is always-on-top and belongs at the bottom
centre of the screen, which is exactly the strip being watched -- so unless it is hidden from
screen capture, the translated line lands in the next frame, is read as a new subtitle, and is
translated again. The first end-to-end run did precisely that: the placeholder text came back as
Thai, and then the Thai came back again.
"""
import inspect
import os
import sys
import unittest

sys.path.insert(0, __file__.rsplit("tests", 1)[0] + "src")
from gamesubs import overlay

SRC = os.path.join(__file__.rsplit("tests", 1)[0], "src", "gamesubs", "overlay.py")
with open(SRC, encoding="utf-8") as _f:
    CODE = _f.read()


class NoFeedbackLoop(unittest.TestCase):
    def test_hiding_from_capture_is_the_default(self):
        # in_capture=True is the opt-out, for a streamer who wants OBS to record the subtitle and
        # who therefore has to keep the overlay outside the watched band.
        d = inspect.signature(overlay.Overlay.__init__).parameters["in_capture"].default
        self.assertIs(d, False)

    def test_it_uses_the_windows_call_that_actually_hides_it(self):
        # Not transparency, not moving it out of the way: the window stays fully visible on the
        # monitor and disappears only from anything capturing the screen.
        self.assertIn("SetWindowDisplayAffinity", CODE)
        self.assertIn("0x11", CODE)          # WDA_EXCLUDEFROMCAPTURE

    def test_it_is_applied_after_the_window_exists(self):
        # There is no window handle before the window is created, so this cannot run in __init__.
        self.assertIn("_hide_from_capture(not self.in_capture)", CODE)

    def test_a_failure_to_hide_tells_you_what_to_do(self):
        # On Windows before 2004 the call fails, and then the loop is real. Silence there would
        # look like the model repeating itself.
        self.assertIn("read its own", CODE)


class Contract(unittest.TestCase):
    def test_it_reads_the_two_fields_the_service_publishes(self):
        from gamesubs.service import Current
        keys = set(Current().get())
        self.assertIn("speaker", keys)
        self.assertIn("text", keys)
        self.assertIn('d.get("speaker")', CODE)
        self.assertIn('d.get("text")', CODE)

    def test_empty_text_hides_rather_than_drawing_a_blank_box(self):
        # Behaviour, not a source string: nothing to say means nothing on screen.
        from gamesubs import render
        self.assertIsNone(render.draw_line(""))
        self.assertIsNone(render.draw_line("   "))
        self.assertIsNotNone(render.draw_line("something"))

    def test_it_polls_localhost_only(self):
        self.assertNotIn("http://", CODE.replace("http://127.0.0.1", ""))

    def test_the_text_is_drawn_by_pillow_not_by_the_toolkit(self):
        # The whole reason this module stopped using tk fonts: tkinter has no complex text
        # layout, so Thai tone marks came off their consonants -- one of them landed on the E
        # of "E-Store" in a live frame.
        self.assertIn("render.draw_line", CODE)
        self.assertNotIn("tkfont", CODE)

    def test_a_font_that_cannot_draw_the_language_is_refused_at_startup(self):
        # Rather than starting and showing a window full of boxes.
        self.assertIn("no font on this machine can draw", CODE)

    def test_the_plate_colour_never_matches_the_chroma_key(self):
        # A plate that drifts to the key colour becomes invisible, and that reads as "the
        # subtitle broke" rather than "two constants collided in a way nobody looked at".
        from gamesubs import render
        key = overlay.KEY.lstrip("#")
        key_rgb = tuple(int(key[i:i + 2], 16) for i in (0, 2, 4))
        self.assertNotEqual(render.PLATE[:3], key_rgb)

    def test_a_polled_error_does_not_kill_the_window(self):
        # Restarting the service must not take the overlay with it.
        self.assertIn("except Exception:", CODE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
