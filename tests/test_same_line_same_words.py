# -*- coding: utf-8 -*-
"""One English sentence gets one Thai wording, for as long as it is remembered.

WHAT IT LOOKS LIKE WITHOUT THIS. A vision model is sampling, so a line read twice comes back
translated twice -- close, not identical -- and the words on screen change while the English
behind them has not moved. Counted from one real run's log:

    "Play through the main story and experience the nightmare"   88 reads, 2 different Thai
    "View bonus content"                                          2 reads, 2 different Thai

Nothing is wrong with either wording. Watching them swap is still the tool looking broken, and it
is the second time the same complaint has arrived about this screen -- the first was the plate
changing size, which was fixed by making the plate fit the words. This is the words themselves.

FIRST ANSWER WINS. Not the best answer: there is no way to tell which of two good translations is
better, and "sometimes better" bought with "always moving" is a bad trade for text being read at
a glance while someone plays.

WHY THE GATE DOES NOT ALREADY STOP IT. The gate compares PICTURES, and a menu with an animated
background is a different picture several times a second while the caption on it is identical.
The sentence is only knowable after the model has read it, so the memo lives here.
"""
import io
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from gamesubs.service import MEMO_MAX, Current, Worker, normalise      # noqa: E402


class Fake(object):
    """A client that answers with the next scripted reply each time."""

    def __init__(self, replies):
        self.replies, self.i, self.last_usage = list(replies), 0, {}

    def ask(self, *_a, **_kw):
        r = self.replies[min(self.i, len(self.replies) - 1)]
        self.i += 1
        return r


def run_once(w, jpg=b"x"):
    w.submit(jpg)
    w.ev.wait(2)
    import time
    time.sleep(0.05)


class OneSentenceOneWording(unittest.TestCase):

    def worker(self, replies):
        cur = Current()
        w = Worker(Fake(replies), cur)
        w.start()
        return w, cur

    def test_the_second_reading_keeps_the_first_wording(self):
        """The exact pair from the log: the model added a word the second time."""
        w, cur = self.worker([
            {"speaker": "", "en": "Play through the main story", "th": "เล่นเนื้อเรื่องหลัก"},
            {"speaker": "", "en": "Play through the main story", "th": "เล่นเนื้อเรื่องหลักนี้"},
        ])
        run_once(w)
        first = cur.get()["text"]
        run_once(w)
        self.assertEqual(cur.get()["text"], first)
        self.assertEqual(w.repeats, 1)

    def test_a_full_stop_does_not_make_it_a_different_sentence(self):
        """Both spellings arrived within seconds of each other on the same menu."""
        w, cur = self.worker([
            {"speaker": "", "en": "Change game settings", "th": "เปลี่ยนการตั้งค่าเกม"},
            {"speaker": "", "en": "Change game settings.", "th": "ปรับตั้งค่าเกม"},
        ])
        run_once(w)
        run_once(w)
        self.assertEqual(cur.get()["text"], "เปลี่ยนการตั้งค่าเกม")

    def test_a_genuinely_new_sentence_still_gets_through(self):
        """The memo must not become a reason the next line never appears."""
        w, cur = self.worker([
            {"speaker": "", "en": "Change game settings", "th": "เปลี่ยนการตั้งค่าเกม"},
            {"speaker": "", "en": "View bonus content", "th": "ดูเนื้อหาโบนัส"},
        ])
        run_once(w)
        run_once(w)
        self.assertEqual(cur.get()["text"], "ดูเนื้อหาโบนัส")
        self.assertEqual(w.repeats, 0)

    def test_the_speaker_is_kept_with_the_wording(self):
        """Otherwise a repeat shows the first translation under the second reading's name."""
        w, cur = self.worker([
            {"speaker": "LEON", "en": "Behind you", "th": "ข้างหลังคุณ"},
            {"speaker": "", "en": "Behind you", "th": "ระวังหลัง"},
        ])
        run_once(w)
        run_once(w)
        self.assertEqual(cur.get()["speaker"], "LEON")

    def test_an_empty_read_is_not_remembered_as_a_sentence(self):
        """Otherwise the first blank frame would poison the memo under an empty key."""
        w, cur = self.worker([{"speaker": "", "en": "", "th": ""}])
        run_once(w)
        self.assertEqual(len(w.said), 0)


class TheMemoIsBounded(unittest.TestCase):
    """A session runs for hours. Unbounded, this becomes a dictionary of every line in the
    game, and the sentence worth keeping is the one just said."""

    def test_the_oldest_sentence_is_dropped(self):
        """Driven through the worker, not by filling the dict by hand: mutation showed a
        hand-filled test passing with the eviction removed, because it was testing the
        eviction it had written itself."""
        from gamesubs import service
        keep = service.MEMO_MAX
        service.MEMO_MAX = 3
        try:
            replies = [{"speaker": "", "en": "line %d" % i, "th": "th %d" % i}
                       for i in range(6)]
            w = Worker(Fake(replies), Current())
            w.start()
            for _ in replies:
                run_once(w)
            self.assertEqual(len(w.said), 3, sorted(w.said))
            self.assertNotIn(normalise("line 0"), w.said)
            self.assertIn(normalise("line 5"), w.said)
        finally:
            service.MEMO_MAX = keep


class TheConsoleDoesNotScroll(unittest.TestCase):
    """A menu with an animated background wakes the gate several times a second, and the
    same caption was printed 88 times in one run. A console scrolling that fast is a
    console nobody reads, and a NEW sentence goes past in the middle of eighty copies of
    the old one."""

    def capture(self, calls):
        import contextlib
        from gamesubs.__main__ import LAST, _log
        LAST["line"], LAST["n"] = None, 0
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            for kw in calls:
                _log(**kw)
        return buf.getvalue()

    def test_the_same_line_is_printed_once(self):
        same = dict(secs=0.8, source="Change game settings", text="เปลี่ยนการตั้งค่าเกม")
        out = self.capture([same] * 5)
        self.assertEqual(out.count("Change game settings"), 1, out)

    def test_a_new_line_still_prints_and_says_how_many_were_skipped(self):
        out = self.capture(
            [dict(secs=0.8, source="Change game settings", text="เปลี่ยน")] * 4
            + [dict(secs=0.9, source="View bonus content", text="ดูโบนัส")])
        self.assertIn("View bonus content", out)
        self.assertIn("3 more times", out)

    def test_a_repeat_says_it_kept_the_first_wording(self):
        out = self.capture([dict(secs=0.8, source="a", text="b", repeat=True)])
        self.assertIn("kept the first wording", out)

    def test_an_error_is_never_swallowed(self):
        out = self.capture([dict(error="boom"), dict(error="boom")])
        self.assertEqual(out.count("boom"), 2, "a repeated error is still an error")


class TheKey(unittest.TestCase):

    def test_spacing_and_case_and_trailing_stops_all_collapse(self):
        for a, b in (("Wait here", "wait here"),
                     ("Wait here", "Wait  here"),
                     ("Wait here", "Wait here."),
                     ("Wait here", "Wait here!"),
                     ("Wait here", "  Wait here  ")):
            self.assertEqual(normalise(a), normalise(b), (a, b))

    def test_but_different_sentences_stay_different(self):
        self.assertNotEqual(normalise("Wait here"), normalise("Wait there"))

    def test_nothing_is_an_empty_key(self):
        self.assertEqual(normalise(""), "")
        self.assertEqual(normalise("   "), "")
        self.assertEqual(normalise(None), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
