# -*- coding: utf-8 -*-
"""The dashboard IS the start of the program, and it says what is happening while it happens.

WHY IT CHANGED. Everything a person has to decide was already in one window -- model, font,
colours, size, how long a line stays up -- and the program still asked two of those questions
again first, in their own dialogs, before opening the window that also asked them. Asked twice in
two places is worse than asked twice: the two can disagree, and only one of them wins, silently.

    "ถ้า C ทำหน้านี้สำเร็จรูปแล้ว ทำไมตอนโหลดครั้งแรกไม่ให้มันเข้าหน้านี้แล้วกด run เอาเลยล่ะ"

So `play` opens the window, and nothing happens until Start. The one thing that is NOT in the
window is the box, because a rectangle on a game is a gesture and not a field.

AND THE MINUTE AFTER START IS THE PART THAT LOOKS BROKEN. Loading the weights takes most of a
minute, in the parent process, out of sight. A window that says nothing for a minute is a window
that did not work, so the parent writes status lines back down the same pipe the Start came up.

THE HANDSHAKE IS TWO WORDS AND A CLOSED PIPE:
  * panel -> parent   "RUN"        the button was pressed
  * parent -> panel   "STATUS ..." one line for the status bar
  * pipe closes                    the window was shut, so start nothing
"""
import io
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from gamesubs import __main__ as m                              # noqa: E402

MAIN = io.open(os.path.join(ROOT, "src", "gamesubs", "__main__.py"), encoding="utf-8").read()
PANEL = io.open(os.path.join(ROOT, "src", "gamesubs", "panel.py"), encoding="utf-8").read()
PLAY = MAIN[MAIN.index("def cmd_play("):MAIN.index("def cmd_fonts(")]
# The branch the window drives. Slicing from `if a.no_panel:` would include the console
# path, which legitimately still calls both dialogs -- and a test that reads the wrong
# half is a test that reports on code nobody runs.
PANEL_PATH = PLAY[PLAY.index("        else:"):PLAY.index("base = a.base_url or")]
CONSOLE_PATH = PLAY[PLAY.index("if a.no_panel:"):PLAY.index("        else:")]


class Fake(object):
    """Enough of a Popen to answer readline/write."""

    def __init__(self, lines=(), broken=False):
        self.stdout = io.BytesIO(b"".join(lines))
        self.stdin = None if broken else io.BytesIO()
        self.written = []

    def flushed(self):
        return self.stdin.getvalue().decode("utf-8") if self.stdin else ""


class TheStartHandshake(unittest.TestCase):

    def test_start_is_recognised(self):
        self.assertTrue(m._wait_for_start(Fake([b"RUN\n"])))

    def test_noise_before_it_does_not_matter(self):
        """The child is a GUI process; a Tk or driver warning on stdout must not read as Start,
        and must not read as a closed window either."""
        self.assertTrue(m._wait_for_start(Fake([b"some warning\n", b"RUN\n"])))

    def test_a_closed_window_is_not_a_start(self):
        """The window was shut instead of pressed. Nothing may be launched, and in particular no
        model may be loaded onto the graphics card for a run nobody asked for."""
        self.assertFalse(m._wait_for_start(Fake([])))

    def test_and_neither_is_something_that_merely_contains_it(self):
        self.assertFalse(m._wait_for_start(Fake([b"NOT A RUN\n"])))


class TheStatusLine(unittest.TestCase):

    def test_it_reaches_the_panel(self):
        f = Fake()
        m._say(f, "loading the model")
        self.assertEqual(f.flushed(), "STATUS loading the model\n")

    def test_no_panel_is_not_an_error(self):
        m._say(None, "loading the model")           # --no-panel, or the console path

    def test_a_panel_that_has_gone_does_not_take_the_run_with_it(self):
        """Reporting progress must never be able to stop the thing it is reporting on. Closing
        the window mid-run is allowed, and the subtitles carry on."""
        class Dead(object):
            stdin = property(lambda self: (_ for _ in ()).throw(IOError("gone")))
        m._say(Dead(), "still going")


class ThePlayCommandUsesIt(unittest.TestCase):
    """The seam. Every piece above can be right while `cmd_play` never calls any of them."""

    def test_the_panel_is_opened_as_the_launcher(self):
        self.assertIn('"panel", "--launcher"', PLAY)

    def test_with_a_pipe_in_both_directions(self):
        self.assertIn("stdout=subprocess.PIPE", PLAY)
        self.assertIn("stdin=subprocess.PIPE", PLAY)

    def test_nothing_starts_until_start_is_pressed(self):
        """The model load has to come AFTER the handshake, or pressing Start decides nothing and
        closing the window still costs a minute and several GB of graphics memory."""
        self.assertIn("_wait_for_start(pn)", PANEL_PATH)
        self.assertLess(PANEL_PATH.index("_wait_for_start(pn)"),
                        PANEL_PATH.index("server.start("),
                        "the model is loaded before anyone has pressed Start")

    def test_the_window_choices_are_what_gets_used(self):
        """Otherwise it is a dashboard that displays a decision and then ignores it."""
        self.assertIn("server.load_tuning()", PLAY)
        self.assertIn("server.load_font()", PLAY)
        self.assertIn('tune.get("model")', PLAY)

    def test_the_two_old_dialogs_are_gone_from_the_panel_path(self):
        """They asked the same two questions the window asks. Both still exist for --no-panel."""
        self.assertNotIn("_choose_font(", PANEL_PATH)
        self.assertNotIn("_choose_model(", PANEL_PATH)
        self.assertIn("_choose_font(", PLAY, "--no-panel lost its font dialog")
        self.assertIn("_choose_model(", PLAY, "--no-panel lost its model dialog")

    def test_the_slow_part_is_reported(self):
        self.assertIn("_say(pn,", PLAY)
        self.assertGreaterEqual(PLAY.count("_say(pn,"), 3, "the run goes quiet somewhere")


class ThePanelEndOfIt(unittest.TestCase):

    def test_start_says_run_exactly_once(self):
        """It is a button a person can hit twice. Two RUNs would leave a word in the pipe that
        the drain thread reads as nothing, which is harmless -- but the second commit is not."""
        body = PANEL[PANEL.index("    def start(self):"):PANEL.index("    # ---", PANEL.index("    def start(self):"))]
        self.assertIn("if self.started or not self.launcher:", body)
        self.assertIn("return", body)

    def test_it_only_exists_in_launcher_mode(self):
        """Opened on its own to adjust a running game, there is nothing to start."""
        self.assertIn("if self.launcher:", PANEL)
        self.assertIn('self.go = tk.Button(foot, text="Start"', PANEL)

    def test_the_status_bar_is_fed_from_stdin(self):
        self.assertIn('line.startswith("STATUS ")', PANEL)

    def test_and_updated_on_the_thread_that_owns_the_window(self):
        """Tk from a reader thread is a crash that happens minutes later, somewhere else."""
        self.assertIn("self.root.after(0, self.set_status", PANEL)

    def test_the_model_note_tells_the_truth_at_both_moments(self):
        """Before Start that choice is THIS run; afterwards it is the next one. The note was a
        constant saying the second thing, displayed while the first was true."""
        self.assertIn('"used when you press Start"', PANEL)
        self.assertIn('self.model_note.set("takes effect the next time you start")', PANEL)


class ItStillRunsWithoutTheWindow(unittest.TestCase):

    def test_no_panel_asks_in_the_console_instead(self):
        self.assertIn("_choose_font(a)", CONSOLE_PATH)
        self.assertIn("_choose_model(a)", CONSOLE_PATH)

    def test_the_panel_subcommand_can_be_a_launcher_or_not(self):
        self.assertIn('pa.add_argument("--launcher"', MAIN)
        self.assertIn('open_panel(launcher=getattr(a, "launcher", False))', MAIN)


class MoveBoxIsTheSameEventAsTheHotkey(unittest.TestCase):
    """Games move their subtitles between the menu, the cutscene and gameplay, and re-aiming
    by restarting means loading the model again. Ctrl+Alt+R has always done it; the button
    says so to somebody who has no reason to know the shortcut exists."""

    def setUp(self):
        m.ASKED["redraw"] = False

    def test_a_request_is_taken_once(self):
        """Consumed on read. Left set, one press would redraw on every tick of the loop --
        twelve selectors a second, over the game."""
        m.ASKED["redraw"] = True
        self.assertTrue(m._take_redraw())
        self.assertFalse(m._take_redraw())

    def test_no_request_is_not_one(self):
        self.assertFalse(m._take_redraw())

    def test_the_drain_thread_is_what_sets_it(self):
        body = MAIN[MAIN.index("def _drain("):MAIN.index("def _say(")]
        self.assertIn('raw.strip() == b"REDRAW"', body)
        self.assertIn('ASKED["redraw"] = True', body)

    def test_the_loop_honours_it_as_well_as_the_hotkey(self):
        """Both, not either: the hotkey works when the window is closed, the button works
        for the person who never learned the hotkey."""
        loop = MAIN[MAIN.index("def _loop("):]
        self.assertIn("_hotkey_redraw() or _take_redraw()", loop)

    def test_the_button_only_exists_after_start(self):
        """Before Start there is no box to move, and the same button is Start."""
        body = PANEL[PANEL.index("    def move_box(self):"):]
        self.assertIn("if not self.started:", body[:400])
        self.assertIn('self.go.configure(text="Move box"', PANEL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
