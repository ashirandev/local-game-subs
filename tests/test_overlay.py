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


class TheKnobsReachTheWindow(unittest.TestCase):
    """`play` starts the overlay as a SEPARATE PROCESS, so every setting has to be handed over on
    a command line. Anything not on it silently uses the default -- which is how `--size` came to
    exist on two subcommands and do nothing on the one people actually run.
    """

    MAIN = os.path.join(__file__.rsplit("tests", 1)[0], "src", "gamesubs", "__main__.py")

    def setUp(self):
        with open(self.MAIN, encoding="utf-8") as f:
            self.code = f.read()

    def test_play_offers_the_two_that_describe_the_subtitle(self):
        for flag in ('pl.add_argument("--size"', 'pl.add_argument("--text-width"'):
            self.assertIn(flag, self.code, "play cannot set it")

    def test_and_passes_both_on_to_the_overlay_process(self):
        """Read the argv being built, not one line of it. The two flags were on a single
        line until --size became conditional, and a test pinned to that line goes red for
        the formatting rather than for the thing it is guarding."""
        i = self.code.index('"gamesubs", "overlay"')
        argv = self.code[i:self.code.index("))", i)]
        self.assertIn('"--size", str(a.size)', argv)
        self.assertIn('"--text-width", str(a.text_width)', argv)

    def test_the_overlay_accepts_them(self):
        self.assertIn('o.add_argument("--text-width"', self.code)
        self.assertIn("max_width=a.text_width", self.code)

    def test_the_window_uses_the_width_it_was_given(self):
        d = inspect.signature(overlay.Overlay.__init__).parameters
        self.assertIn("max_width", d)
        self.assertIn("self.max_width", CODE)


class TheWindowGoesWhereTheBoxIs(unittest.TestCase):
    """One box, and the window is on it.

    The plate has to sit exactly where the reading happens, and the box is where the reading
    happens, so nothing else may decide. A position saved on another day -- another game, another
    resolution -- is the thing that put a plate a third of a screen to the left of a two-line
    subtitle on 2026-09-09, hiding half of it and covering scenery with the rest.

    It stays a fallback for a run with no box at all, which is the only case where there is
    nothing better to say.
    """

    def test_the_box_is_consulted_first(self):
        order = CODE[CODE.index("def _load_pos"):CODE.index("def _save_pos")]
        self.assertLess(order.index("self.box"), order.index("STATE"),
                        "a saved position is being preferred over the box")

    def test_the_box_is_asked_of_the_service_not_guessed(self):
        self.assertIn("_watched_box", CODE)
        self.assertIn("/band", CODE)

    def test_there_is_still_a_fallback_when_no_box_exists(self):
        self.assertIn("winfo_screenwidth", CODE)


class NothingToDrive(unittest.TestCase):
    """No placeholder, no lock to remember: the window is either a subtitle or it is not there.

    Every control this window had existed to support dragging it onto the game, and the box
    removed the drag. A control that outlives the step it served does not look like leftovers --
    it looks deliberate, so nobody deletes it, and the next person writes documentation for it.
    """

    def test_it_starts_locked(self):
        src = CODE[CODE.index("def __init__"):CODE.index("def _watched_box")]
        self.assertIn("self.locked = True", src)
        self.assertNotIn("self.locked = False", src)

    def test_click_through_is_applied_without_being_asked_for(self):
        self.assertIn("_click_through(True)", CODE)

    def test_there_is_no_placeholder_left(self):
        """The plate used to sit on the picture with instructions in it whenever the game was
        quiet, which is most of the time. Checked inside _render, because the history of why it
        is gone is written in the comments and should stay there."""
        body = CODE[CODE.index("    def _render(self):"):CODE.index("    def run(self):")]
        self.assertNotIn("drag me", body)
        self.assertEqual(body.count("txt"), body.count("txt =") + body.count("txt)")
                         + body.count("txt,"), "something still substitutes the text")

    def test_an_empty_line_still_means_hide(self):
        """draw_line returns None for empty text and the window unpacks itself. With the
        placeholder gone this is the ONLY thing keeping the plate off a silent scene."""
        self.assertIn("if im is None:", CODE)
        self.assertIn("pack_forget()", CODE)

    def test_the_render_places_every_plate_it_draws(self):
        """The seam, for the third time today. `_place` is tested directly in test_cover, which
        proves the arithmetic and says nothing about whether anything calls it -- and a mutant
        that deleted the call from `_render` stayed green. The plate is a different size for
        every line, so a plate that is never re-placed is a plate anchored by its top-left
        corner, which is exactly the drift this design was meant to remove."""
        body = CODE[CODE.index("    def _render(self):"):CODE.index("    def run(self):")]
        self.assertIn("self._place(im.size)", body)

    def test_the_unlock_key_is_still_there_for_anyone_who_wants_it(self):
        """Removed the requirement, not the capability."""
        self.assertIn("0x4C", CODE)


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
        self.assertIn("_hide_from_capture(not self.record)", CODE)

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
