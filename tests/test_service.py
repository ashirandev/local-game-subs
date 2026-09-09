# -*- coding: utf-8 -*-
"""Tests for the pipeline: the single job slot, the hold timer, and what /current publishes."""
import io
import json
import os
import sys
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, __file__.rsplit("tests", 1)[0] + "src")
from gamesubs import service
from gamesubs.service import Current, Worker, serve_http, split_speaker

NL = chr(10)


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


class TheNameIsNotSaidTwice(unittest.TestCase):
    """A character's name belongs in the label, not at the front of the line as well.

    Seen on screen: the plate carried `Leon` on one line and `ลืออน: ...` on the next -- the same
    name, once as itself and once transliterated, because that is how it is written on the frame
    the model is reading. The prompt asks for it in `speaker` only, and the model mostly complies.
    "Mostly" is a rate, and a rate on every line of dialogue is something the player sees several
    times an hour, so there is a deterministic half as well.
    """

    def split(self, en, th, spk):
        """Just the two text fields: every assertion in these classes is about what the
        player reads. The speaker it may hand back has its own class below."""
        return split_speaker(en, th, spk)[1:]

    def test_a_thai_transliteration_of_the_name_is_removed(self):
        """The English gives the label away; the Thai is then cut in the same place. It cannot be
        found in the Thai by looking for it -- ลืออน and Leon share no characters."""
        self.assertEqual(self.split("Leon: I made it out.", "ลืออน: ฉันรอดมาได้", "Leon"),
                         ("I made it out.", "ฉันรอดมาได้"))

    def test_the_model_writing_it_into_the_translation_only(self):
        """No colon in the English at all. The two fields are the same sentence, so a colon in one
        of them and not the other belongs to a label rather than to the speech."""
        self.assertEqual(self.split("I made it out.", "ลืออน: ฉันรอดมาได้", "Leon"),
                         ("I made it out.", "ฉันรอดมาได้"))

    def test_the_name_on_its_own_line_above(self):
        """The layout RE4R uses. Only the colon form was handled until 2026-09-09, and the hole
        was invisible because both models happened to get that frame right the day it was
        measured -- which is the thing this function exists so nobody has to depend on."""
        self.assertEqual(self.split("LEON" + NL + "I made it out.", "ลีออน" + NL + "ฉันรอดมาได้",
                                    "LEON"),
                         ("I made it out.", "ฉันรอดมาได้"))

    def test_and_on_its_own_line_below(self):
        """Games do not agree about which side the name goes."""
        self.assertEqual(self.split("I made it out." + NL + "LEON", "ฉันรอดมาได้" + NL + "ลีออน",
                                    "LEON"),
                         ("I made it out.", "ฉันรอดมาได้"))


class BeingSpokenToIsNotBeingTheSpeaker(unittest.TestCase):
    """The regression this class exists for, found by being asked the right question:

        "ถ้าคนอื่นเรียกชื่อ ลีออน กลางประโยคพังไหม"

    It did. For one hour on 2026-09-09 the rule was POSITIONAL -- cut the first segment if it is
    short and does not end in a full stop -- and a wrapped subtitle puts the person being
    addressed alone on the first line, looking exactly like a label. Three frames in four were
    being eaten. Position is not identity: the segment has to BE the speaker's name, which can
    only be checked in the field that still holds the original spelling.
    """

    def split(self, en, th, spk):
        """Just the two text fields: every assertion in these classes is about what the
        player reads. The speaker it may hand back has its own class below."""
        return split_speaker(en, th, spk)[1:]

    def test_ada_saying_leons_name_across_two_lines(self):
        en, th = "Leon" + NL + "we have to move", "ลีออน" + NL + "เราต้องไปแล้ว"
        self.assertEqual(self.split(en, th, "ADA"), (en, th))

    def test_a_name_in_the_middle_of_a_line_is_speech(self):
        """Nothing is ever removed from the middle. There is no search for the name inside the
        text, and there must not be one: that is somebody being spoken to."""
        en, th = "Leon, behind you!", "ลีออน ระวังข้างหลัง!"
        self.assertEqual(self.split(en, th, "ADA"), (en, th))

    def test_talking_about_a_third_character(self):
        en, th = "Ashley" + NL + "is still inside", "แอชลีย์" + NL + "ยังอยู่ข้างใน"
        self.assertEqual(self.split(en, th, "LEON"), (en, th))

    def test_a_colon_whose_head_is_not_the_speaker(self):
        en, th = "Leon: it is me", "ลีออน: นี่ฉันเอง"
        self.assertEqual(self.split(en, th, "ADA"), (en, th))

    def test_two_short_lines_of_real_speech(self):
        en, th = "Wait." + NL + "Something is here.", "เดี๋ยว" + NL + "มีบางอย่างอยู่ตรงนี้"
        self.assertEqual(self.split(en, th, "LEON"), (en, th))

    def test_nothing_happens_without_a_speaker(self):
        """No name on the frame means every one of these is speech. The guard that stops the
        whole thing eating subtitles."""
        en, th = "LEON" + NL + "I made it out.", "ลีออน" + NL + "ฉันรอดมาได้"
        self.assertEqual(self.split(en, th, ""), (en, th))

    def test_a_name_the_speakers_name_is_only_part_of(self):
        """Identity, not containment. Games are full of names that contain other names --
        Leonhardt, Adalind -- and a subtitle that opens with one of them is a subtitle,
        not a label. Mutation found this: swapping the comparison to `in` left every test
        green."""
        en, th = "Leonhardt" + NL + "was here first", "ลีออนฮาร์ท" + NL + "มาก่อน"
        self.assertEqual(self.split(en, th, "Leon"), (en, th))

    def test_nor_a_first_line_that_merely_starts_with_the_name(self):
        en, th = "Ada Wong sent me" + NL + "to find you", "อาดา หว่อง ส่งฉันมา" + NL + "ตามหาคุณ"
        self.assertEqual(self.split(en, th, "ADA"), (en, th))

    def test_nor_a_colon_head_that_only_contains_it(self):
        en, th = "Leonhardt: it was me", "ลีออนฮาร์ท: ฉันเอง"
        self.assertEqual(self.split(en, th, "Leon"), (en, th))

    def test_a_line_with_no_name_in_front_is_untouched(self):
        self.assertEqual(self.split("We have to go now.", "เราต้องไปเดี๋ยวนี้", "Leon"),
                         ("We have to go now.", "เราต้องไปเดี๋ยวนี้"))

    def test_the_comparison_ignores_case_and_punctuation(self):
        """`LEON:` on screen, `Leon` in the field, and one of them with a stray full stop is the
        same name. Requiring identity must not mean requiring an exact string."""
        self.assertEqual(self.split("leon: run", "ลีออน: หนี", "LEON."), ("run", "หนี"))

    def test_a_leading_name_is_promoted_when_the_model_reported_none(self):
        """Caught live: `Hunnigan: -- chopper-` with `speaker` EMPTY, twice in 83 lines of
        one session, during a scene where the radio breaks up. Every guard in this file
        correctly stayed out of it -- they all require a reported speaker -- and the name
        went to screen transliterated into Thai, which is the duplication they exist to
        stop."""
        self.assertEqual(split_speaker("Hunnigan: -- chopper-", "ฮันนิแกน: -- ชอปเปอร์-", ""),
                         ("Hunnigan", "-- chopper-", "-- ชอปเปอร์-"))

    def test_which_costs_an_odd_label_on_a_line_that_opens_with_a_word_and_a_colon(self):
        """The price, stated rather than hidden. "Listen: we have to go" has no name in it,
        and this promotes "Listen" to the label.

        It is a PROMOTION and not a deletion for exactly this reason: when the guess is
        wrong the words are still on screen, in their original spelling, which is more than
        cutting them would leave. The failure it replaces -- the name transliterated into
        the middle of the translation -- is wrong every time; this one is wrong sometimes."""
        self.assertEqual(split_speaker("Listen: we have to go", "ฟังนะ: เราต้องไป", ""),
                         ("Listen", "we have to go", "เราต้องไป"))

    def test_thai_before_a_colon_is_never_promoted(self):
        """The guard that keeps it narrow: a name is checked in ENGLISH, which is the field
        that still holds the original spelling. Thai text before a colon is a sentence."""
        en, th = "we have to go now", "ฟังนะ: เราต้องไป"
        self.assertEqual(split_speaker(en, th, "")[1:], (en, th))

    def test_and_neither_is_a_long_head(self):
        en = "there is only one way out of here: forward"
        self.assertEqual(split_speaker(en, "ทางออกมีทางเดียว: ไปข้างหน้า", "")[0], "")

    def test_a_colon_further_along_is_not_a_name(self):
        """A long run of words before a colon is a sentence with a colon in it."""
        en = "a very long line with no name in front of it at all: in the middle"
        th = "บทสนทนายาวมาก: อยู่ตรงกลาง"
        self.assertEqual(self.split(en, th, "Ada"), (en, th))

    def test_a_line_that_is_only_a_name_is_left_alone(self):
        """Stripping it would leave an empty subtitle, which reads as the tool losing the
        line -- worse than showing a name, because there is nothing on screen to look at."""
        self.assertEqual(self.split("Leon:", "ลีออน:", "Leon"),
                         ("Leon:", "ลีออน:"))

    def test_the_prompt_still_asks_for_it_as_well(self):
        """Both halves, on purpose: the model is told, and then the output is checked. Either one
        alone leaves the failure in place some of the time."""
        self.assertIn("NOT ", service.PROMPT)
        self.assertIn("`speaker`", service.PROMPT)

    def test_the_prompt_does_not_try_to_decide_what_counts_as_a_subtitle(self):
        """It used to tell the model to return nothing for a menu, an inventory or a HUD,
        and both models ignored it -- 3/3 each on an inventory screen, and caught live on a
        Windows panel that opened over the box. An instruction nothing obeys is a longer
        prompt and no behaviour.

        The box is the decision. Somebody aimed it; whatever is inside it is what they
        asked for."""
        for gone in ("a menu", "health bar", "only gameplay"):
            self.assertNotIn(gone, service.PROMPT, gone)
        self.assertIn("the part they want translated", service.PROMPT)

    def test_thai_gets_a_pronoun_rule_and_other_languages_do_not(self):
        """Thai pronouns carry gender, age, rank and how close two people are. A subtitle
        shows none of that, so picking one is a claim about the speaker made from pixels."""
        thai = service.prompt_for("Thai")
        self.assertIn("ฉัน", thai)
        self.assertIn("คุณ", thai)
        self.assertNotIn("ฉัน", service.prompt_for("French"))

    def test_the_language_is_matched_however_it_was_typed(self):
        for spelling in ("Thai", "thai", "  THAI  "):
            self.assertIn("ฉัน", service.prompt_for(spelling), spelling)

    def test_the_rule_names_the_pronouns_it_is_refusing(self):
        """Measured at 23/24 with them named. "Be neutral" is not an instruction a model
        can act on; a list of words is."""
        thai = service.prompt_for("Thai")
        for banned in ("ผม", "เธอ", "นาย", "กู"):
            self.assertIn(banned, thai, banned)

    def test_no_language_at_all_does_not_crash(self):
        self.assertTrue(service.prompt_for(None))
        self.assertTrue(service.prompt_for(""))

    def test_there_is_no_search_and_replace_on_thai_output(self):
        """The deterministic half that exists everywhere else in this file must NOT exist
        here. Thai writes no spaces and every candidate pronoun is a substring of ordinary
        words: ผม is also hair, ข้า sits inside ข้าว and ข้าง, กู begins กู้, แก begins แกง.
        And เธอ means both "you" and "she", so even the one that looks safe is not."""
        src = io.open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "src", "gamesubs", "service.py"),
            encoding="utf-8").read()
        body = src[src.index("class Worker"):]
        for pronoun in ("ผม", "เธอ", "นาย"):
            self.assertNotIn('replace("%s"' % pronoun, body)

    def test_but_a_frame_with_no_text_still_answers_with_nothing(self):
        """The one rule that has to stay. Without it a quiet scene gets a black plate with
        something invented on it, and the model does obey this one."""
        self.assertIn("NO readable text at all", service.PROMPT)
        self.assertIn("An empty answer is a correct answer", service.PROMPT)


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
        t0 = time.time()
        c.set("", "hi", "สวัสดี", now=t0)
        self.assertTrue(c.expire(15.0, now=t0 + 100))
        self.assertEqual(c.get(now=t0 + 100)["text"], "")

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
        # min_hold=0: these tests are about what goes over the wire. With the reading-time floor
        # on, a clear here is deferred rather than applied, and the failure looks like an HTTP
        # bug. The floor has its own suite -- test_hold.py.
        cls.cur = Current(min_hold=0)
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
