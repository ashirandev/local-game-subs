# -*- coding: utf-8 -*-
"""Tests for the pipeline: the single job slot, the hold timer, and what /current publishes."""
import json
import sys
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, __file__.rsplit("tests", 1)[0] + "src")
from gamesubs.service import Current, Worker, serve_http


class Fake:
    """Stands in for VisionClient. Records what it was handed."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.seen = []
        self.last_usage = {"total_tokens": 42}

    def ask(self, prompt, image=None, schema=None, **kw):
        self.seen.append(image)
        a = self.answers.pop(0) if self.answers else {"speaker": "", "en": "", "th": ""}
        if isinstance(a, Exception):
            raise a
        return a


def settle(pred, secs=3.0):
    end = time.time() + secs
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


class State(unittest.TestCase):
    def test_starts_empty(self):
        self.assertEqual(Current().get()["text"], "")

    def test_set_and_read_back(self):
        c = Current()
        c.set("NAOE", "Let's go", "ไปกันเถอะ")
        self.assertEqual(c.get(), {"speaker": "NAOE", "source": "Let's go", "text": "ไปกันเถอะ"})

    def test_get_returns_a_copy(self):
        c = Current()
        c.set("A", "b", "c")
        c.get()["text"] = "mutated"
        self.assertEqual(c.get()["text"], "c")

    def test_expire_clears_after_the_ttl(self):
        c = Current()
        c.set("", "hi", "สวัสดี")
        c.at = time.time() - 100
        self.assertTrue(c.expire(15.0))
        self.assertEqual(c.get()["text"], "")

    def test_expire_does_nothing_before_the_ttl(self):
        c = Current()
        c.set("", "hi", "สวัสดี")
        self.assertFalse(c.expire(15.0))
        self.assertEqual(c.get()["text"], "สวัสดี")

    def test_expiring_an_already_empty_line_is_not_an_event(self):
        c = Current()
        c.at = time.time() - 100
        self.assertFalse(c.expire(15.0))


class LatestOnly(unittest.TestCase):
    """The single slot is the whole latency story. If it ever becomes a queue, the subtitles fall
    further behind the game with every line, and it presents as the model getting slower."""

    def test_a_second_submit_reports_that_it_replaced_one(self):
        w = Worker(Fake(), Current())
        self.assertFalse(w.submit(b"one"))
        self.assertTrue(w.submit(b"two"))

    def test_the_slot_holds_only_the_newest(self):
        w = Worker(Fake(), Current())
        w.submit(b"one")
        w.submit(b"two")
        w.submit(b"three")
        self.assertEqual(w.job, b"three")

    def test_the_waiting_frame_is_dropped_not_queued(self):
        cur, f = Current(), Fake({"speaker": "NAOE", "en": "Let's go", "th": "ไปกันเถอะ"})
        w = Worker(f, cur)
        w.submit(b"one")
        w.submit(b"two")
        w.start()
        self.assertTrue(settle(lambda: cur.get()["text"]))
        self.assertEqual(cur.get()["text"], "ไปกันเถอะ")
        self.assertEqual(f.seen, [b"two"])              # NOT [b"one", b"two"]

    def test_a_model_error_does_not_kill_the_loop(self):
        cur = Current()
        f = Fake(RuntimeError("no content"), {"speaker": "", "en": "ok", "th": "โอเค"})
        w = Worker(f, cur)
        w.start()
        w.submit(b"a")
        self.assertTrue(settle(lambda: w.err == 1))
        w.submit(b"b")
        self.assertTrue(settle(lambda: cur.get()["text"] == "โอเค"))

    def test_a_blank_answer_clears_the_previous_line(self):
        cur = Current()
        cur.set("NAOE", "old", "เก่า")
        w = Worker(Fake({"speaker": "", "en": "", "th": ""}), cur)
        w.start()
        w.submit(b"a")
        self.assertTrue(settle(lambda: not cur.get()["text"]))
        self.assertEqual(w.blank, 1)

    def test_a_translation_equal_to_the_speaker_name_is_dropped(self):
        # A failed read often comes back as the character's name in the translation field. It is
        # a name, not a line, and putting it on screen looks like a hallucination.
        cur = Current()
        w = Worker(Fake({"speaker": "NAOE", "en": "NAOE", "th": "naoe"}), cur)
        w.start()
        w.submit(b"a")
        self.assertTrue(settle(lambda: w.blank == 1))
        self.assertEqual(cur.get()["text"], "")

    def test_the_callback_reports_a_real_line(self):
        got = {}
        w = Worker(Fake({"speaker": "NAOE", "en": "Let's go", "th": "ไปกันเถอะ"}), Current(),
                   on_line=lambda **kw: got.update(kw))
        w.start()
        w.submit(b"a")
        self.assertTrue(settle(lambda: got.get("text")))
        self.assertEqual(got["speaker"], "NAOE")
        self.assertEqual(got["tokens"], 42)


class Http(unittest.TestCase):
    port = 8933

    @classmethod
    def setUpClass(cls):
        cls.cur = Current()
        cls.srv = serve_http(cls.cur, cls.port, {"x": 0.0, "y": 0.75, "w": 1.0, "h": 0.25})

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def get(self, path):
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (self.port, path), timeout=5) as r:
            return r, r.read()

    def test_current_carries_speaker_and_text(self):
        self.cur.set("NAOE", "Let's go", "ไปกันเถอะ")
        d = json.loads(self.get("/current")[1].decode("utf-8"))
        self.assertEqual(d["speaker"], "NAOE")
        self.assertEqual(d["text"], "ไปกันเถอะ")

    def test_current_is_never_cached(self):
        # The overlay polls several times a second. A cached /current freezes the line on screen
        # while the log keeps scrolling, which reads as "the overlay broke".
        self.assertEqual(self.get("/current")[0].headers.get("Cache-Control"), "no-store")

    def test_non_latin_survives_the_wire(self):
        self.cur.set("", "x", "สวัสดีครับ")
        self.assertEqual(json.loads(self.get("/current")[1].decode("utf-8"))["text"], "สวัสดีครับ")

    def test_health_says_whether_a_line_is_up(self):
        self.cur.set("", "x", "มี")
        self.assertTrue(json.loads(self.get("/health")[1])["showing"])
        self.cur.set()
        self.assertFalse(json.loads(self.get("/health")[1])["showing"])

    def test_band_reports_the_watched_region(self):
        self.assertEqual(sorted(json.loads(self.get("/band")[1])["band"]), ["h", "w", "x", "y"])

    def test_an_unknown_path_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.get("/nope")
        self.assertEqual(e.exception.code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
