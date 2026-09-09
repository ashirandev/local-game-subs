# -*- coding: utf-8 -*-
"""A translation stays up long enough to be read.

THE GUARANTEE: a line that reaches the screen stays there for at least `min_hold` seconds, and
longer in proportion to how many characters it has -- unless a newer translation replaces it,
which always happens at once.

WHY IT IS NEEDED. The model answers in about 0.9 s (n=172, measured on a real run). By the time
the Thai appears the game has often already changed its own line, so the loop clears the
translation almost as soon as it arrives: the plate flashes for a tenth of a second. Present,
correct, and unreadable -- the most expensive kind of bug, because every part of the system
reports success.

WORD COUNT WAS THE OBVIOUS ANSWER AND IT DOES NOT WORK. Thai does not put spaces between words.
Measured on the same run: "เปลี่ยนการตั้งค่าเกม" is six Thai words, 20 characters, and exactly
ONE space-separated group -- the same count as "OK". A floor built on `text.split()` gives a
sentence the same time as a grunt. Characters are the honest proxy, and they are also what
broadcast subtitles have always been timed on.

THE FLOOR DEFERS A CLEAR, IT NEVER REFUSES ONE. The clear still happens; it happens at the moment
the line has been up long enough to read. Refusing it would leave text on screen with nothing
to take it off again.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from gamesubs import service                                   # noqa: E402
from gamesubs.service import Current, read_seconds             # noqa: E402

SHORT = "ไปกันเถอะ"                                             # 9 characters, 1 space-group
MENU = "เปลี่ยนการตั้งค่าเกม"                                   # 20 characters, 1 space-group
LONG = ("และคืนนั้นเอง แรคคูนซิตี้ก็ถูกล้างจนไม่เหลืออะไร "
        "เพราะอาวุธชีวภาพที่อัมเบรลลาสร้างขึ้น")                # 86 characters, 3 space-groups


class HowLongALineIsEntitledTo(unittest.TestCase):

    def test_a_longer_line_gets_more_time(self):
        self.assertGreater(read_seconds(LONG), read_seconds(MENU))

    def test_words_would_have_called_these_three_the_same_length(self):
        """The reason this is measured in characters. If read_seconds ever starts splitting on
        whitespace, these three collapse onto one value and this test says so."""
        self.assertEqual(len(SHORT.split()), len(MENU.split()))
        self.assertGreater(read_seconds(MENU), read_seconds(SHORT))

    def test_nothing_flashes_past_faster_than_the_floor(self):
        for text in ("ก", SHORT, MENU):
            self.assertGreaterEqual(read_seconds(text), service.MIN_HOLD)

    def test_and_nothing_sits_there_for_ever_either(self):
        self.assertLessEqual(read_seconds(LONG * 20), service.HOLD_CAP)

    def test_silence_is_entitled_to_nothing(self):
        """"ตอนไม่มีแปล ก็ดับไปเลย" -- an empty line has nothing to read, so it waits for
        nothing. Without this the floor would keep a blank plate alive."""
        self.assertEqual(read_seconds(""), 0.0)
        self.assertEqual(read_seconds("   "), 0.0)

    def test_a_zero_floor_turns_the_whole_thing_off(self):
        self.assertEqual(read_seconds(LONG, lo=0), 0.0)

    def test_the_rate_actually_changes_the_answer(self):
        self.assertLess(read_seconds(LONG, speed=40), read_seconds(LONG, speed=10))


class AClearInsideTheFloorIsDeferred(unittest.TestCase):

    def setUp(self):
        self.c = Current()
        self.t0 = time.time()
        self.c.set("Leon", "Let's go", SHORT, now=self.t0)
        self.hold = self.c.hold_for(SHORT)

    def test_the_line_survives_a_clear_that_arrives_too_early(self):
        self.assertFalse(self.c.set(now=self.t0 + 0.1))
        self.assertEqual(self.c.get(now=self.t0 + 0.1)["text"], SHORT)

    def test_and_is_gone_once_it_has_been_readable(self):
        self.c.set(now=self.t0 + 0.1)
        self.assertEqual(self.c.get(now=self.t0 + self.hold + 0.01)["text"], "")

    def test_a_clear_after_the_floor_lands_at_once(self):
        self.assertTrue(self.c.set(now=self.t0 + self.hold + 1))
        self.assertEqual(self.c.get(now=self.t0 + self.hold + 1)["text"], "")

    def test_a_deferred_clear_is_forgotten_when_a_new_line_arrives(self):
        """Otherwise the pending clear fires under the NEW line and takes it off early.

        Read past the NEW line's own floor, not the old one's. Checking any earlier proves
        nothing: the owed clear cannot fire before that moment either way, so the assertion
        passes whether or not the clear was forgotten -- which is exactly what it happened to
        do, and a mutation run is what said so."""
        self.c.set(now=self.t0 + 0.1)
        self.c.set("Ada", "Wait", MENU, now=self.t0 + 0.2)
        past = self.t0 + 0.2 + self.c.hold_for(MENU) + 0.01
        self.assertEqual(self.c.get(now=past)["text"], MENU)

    def test_a_new_translation_is_never_made_to_wait(self):
        """The floor protects a line from vanishing. It must never hold back the line that
        replaces it -- that would be showing Thai for a sentence no longer on screen, on
        purpose."""
        self.assertTrue(self.c.set("", "Wait", MENU, now=self.t0 + 0.1))
        self.assertEqual(self.c.get(now=self.t0 + 0.1)["text"], MENU)

    def test_expire_cannot_undercut_the_floor(self):
        """A minimum and a maximum that disagree is a minimum."""
        self.assertFalse(self.c.expire(0.0, now=self.t0 + 0.1))
        self.assertEqual(self.c.get(now=self.t0 + 0.1)["text"], SHORT)

    def test_min_hold_zero_restores_the_old_instant_clear(self):
        c = Current(min_hold=0)
        t0 = time.time()
        c.set("", "x", SHORT, now=t0)
        self.assertTrue(c.set(now=t0))
        self.assertEqual(c.get(now=t0)["text"], "")


class TheLoopActuallyUsesIt(unittest.TestCase):
    """The seam. Both halves of this feature passed their own tests while nothing connected them
    -- that failure has happened three times in this repo in one day, so it gets its own test."""

    @staticmethod
    def source():
        import io
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "src", "gamesubs", "__main__.py")
        return io.open(p, encoding="utf-8").read()

    def test_the_loop_builds_current_with_the_settings(self):
        body = self.source()
        i = body.index("def _loop(")
        self.assertIn("min_hold=", body[i:i + 1200])
        self.assertIn("read_speed", body[i:i + 1200])

    def test_both_settings_are_reachable_from_the_command_line(self):
        body = self.source()
        self.assertIn('"--min-hold"', body)
        self.assertIn('"--read-speed"', body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
