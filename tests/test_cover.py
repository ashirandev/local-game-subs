# -*- coding: utf-8 -*-
"""The plate fits the sentence, wraps at the box, and is not there when nobody is speaking.

WHAT THIS GUARDS, AND THE TWO WRONG ANSWERS BEFORE IT. The user drags one box around the game's
own subtitle. That box says what to read, how wide a line may get, and where the translation
goes -- and until 2026-09-09 it said none of those: the window opened at a hardcoded centre-screen
78%, so every run meant dragging a box and then dragging a second window to the same place by
hand, with the same sentence on screen twice, in two languages, until you did.

Then the plate became the box exactly: a fixed black slab with the words floating inside it. That
covers the original perfectly and looks wrong, because a short line and a wrapped one sit in
different places inside a frame that never moves. Watching it run: "ข้อความไม่นิ่งเลยแฮะ".

So the plate is the size of the SENTENCE, wrapped at the width of the box and centred in it. It
grows and shrinks with the words -- the one kind of movement that reads as correct -- and it can
never come out wider than the region being read.

Three separate things, and they need separate tests, because fixing one looks like fixing all
three right up to the moment the sentence changes length:

  * the plate must fit the words       -> draw_line takes no box any more
  * lines must break at the box width  -> Overlay._wrap_width
  * it must vanish when nobody speaks  -> draw_line returns None and the window unpacks itself
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from gamesubs import overlay, render, service                 # noqa: E402

FONTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
BOX = {"left": 826, "top": 1086, "width": 908, "height": 158}
SHORT = "ไปกันเถอะ"
LONG = "และคืนนั้นเอง แรคคูนซิตี้ก็ถูกล้างจนไม่เหลืออะไร เพราะอาวุธชีวภาพที่อัมเบรลลาสร้างขึ้น"


def thai_font(size=28):
    p = render.resolve_font(None, LONG, FONTS)
    if not p:
        return None, None
    return render.load(p, size), render.load(p, int(size * 0.6))


class ThePlateFitsTheSentence(unittest.TestCase):

    def setUp(self):
        self.f, self.sm = thai_font()
        if self.f is None:
            self.skipTest("no Thai font")

    def draw(self, text, width=908):
        return render.draw_line(text, "Leon", self.f, self.sm, width)

    def test_a_short_line_gets_a_small_plate(self):
        self.assertLess(self.draw(SHORT).width, 400)

    def test_a_long_one_gets_a_bigger_plate(self):
        self.assertGreater(self.draw(LONG).width, self.draw(SHORT).width)

    def test_the_plate_is_solid_to_its_own_edges(self):
        """No transparent border. The plate IS the image now, so anything not opaque at the edge
        is a gap the original shows through."""
        self.assertEqual(self.draw(LONG).getchannel("A").getextrema(), (255, 255))

    def test_nothing_can_be_read_through_it(self):
        """At 75% the sentence underneath is dimmed, not hidden -- still the same sentence twice,
        in two languages. Measured on a two-line RE4R subtitle: both English lines stayed
        legible straight through the plate."""
        self.assertEqual(render.PLATE[3], 255)

    def test_a_chosen_colour_is_still_completely_opaque(self):
        """The panel offers a background colour, not a transparency. Alpha below 255 is
        the bug this tool started with -- the same sentence on screen twice, in two
        languages -- and it is invisible in every test that only measures size."""
        from gamesubs.render import _rgba
        for spec in ("#000000", "#101828", "#ffffff", "nonsense", None):
            self.assertEqual(_rgba(spec, render.PLATE)[3], 255, spec)
        self.assertEqual(self.draw(LONG).getchannel("A").getextrema(), (255, 255))

    def test_it_never_comes_out_wider_than_the_box(self):
        """The wrap width is the box, so this holds for any sentence -- which is what stops the
        plate spilling past the region it is drawn for."""
        for text in (SHORT, LONG, LONG + " " + LONG):
            self.assertLessEqual(self.draw(text).width, BOX["width"])

    def test_a_longer_sentence_wraps_instead_of_stretching(self):
        self.assertGreater(self.draw(LONG).height, self.draw(SHORT).height,
                           "it did not wrap onto a second line")

    def test_the_same_sentence_always_draws_the_same_plate(self):
        """The stability claim as a test: nothing in here may depend on the frame, the clock, or
        what was on screen before."""
        self.assertEqual(self.draw(LONG).size, self.draw(LONG).size)

    def test_no_speaker_means_no_room_kept_for_one(self):
        self.assertLess(render.draw_line(SHORT, "", self.f, self.sm, 908).height,
                        render.draw_line(SHORT, "Leon", self.f, self.sm, 908).height)

    def test_silence_draws_nothing_at_all(self):
        """Not an empty plate. The window unpacks its label when this returns None, and that is
        the only thing keeping a black rectangle off a quiet scene now that the placeholder --
        "drag me, Ctrl+Alt+L to lock" -- is gone."""
        self.assertIsNone(render.draw_line(""))
        self.assertIsNone(render.draw_line("   "))


class TheBoxDecidesTheWrap(unittest.TestCase):
    """`Overlay._wrap_width`: the one place the box reaches the renderer."""

    class Fake(object):
        def __init__(self, box, fallback=1100):
            self.box, self.max_width = box, fallback

    def width(self, box, fallback=1100):
        return overlay.Overlay._wrap_width(self.Fake(box, fallback))

    def test_the_box_wins(self):
        self.assertEqual(self.width(BOX), 908)

    def test_no_box_falls_back_to_the_setting(self):
        self.assertEqual(self.width(None), 1100)
        self.assertEqual(self.width({}, 1400), 1400)

    def test_a_misdragged_box_does_not_produce_a_one_word_line(self):
        """A box 12 px wide is a misclick, and breaking every character onto its own line is a
        worse answer than a plate that overhangs it."""
        self.assertGreaterEqual(self.width({"width": 12}), 200)


class ThePlateIsCentredInTheBox(unittest.TestCase):
    """`Overlay._place`: why the plate does not jump about when the sentence changes length."""

    def place(self, size, box=BOX, moved=False, record=False):
        calls = []

        class Fake(object):
            pass

        f = Fake()
        f.box, f._moved, f.record = box, moved, record
        f.root = type("R", (), {"geometry": lambda _self, g: calls.append(g)})()
        overlay.Overlay._place(f, size)
        return calls

    @staticmethod
    def centre(geom, w):
        return int(geom.split("+")[1]) + w / 2.0

    def test_a_small_plate_and_a_large_one_share_a_centre(self):
        self.assertAlmostEqual(self.centre(self.place((200, 90))[0], 200),
                               self.centre(self.place((880, 135))[0], 880), delta=1)

    def test_that_centre_is_the_box(self):
        self.assertAlmostEqual(self.centre(self.place((200, 90))[0], 200),
                               BOX["left"] + BOX["width"] / 2.0, delta=1)

    def test_recording_mode_puts_it_above_the_box(self):
        """Recording stops this window hiding from screen capture, and the window sits in
        the strip being watched -- so left where it is, the tool reads its own translation
        and translates that. The move is the other half of the same switch."""
        g = self.place((400, 90), record=True)[0]
        top = int(g.split("+")[2])
        self.assertLess(top + 90, BOX["top"], "the plate is still inside the watched box")

    def test_and_keeps_the_same_centre(self):
        """Only the height changes. A plate that also jumps sideways when you tick a box
        for OBS reads as two settings, not one."""
        self.assertAlmostEqual(self.centre(self.place((400, 90), record=True)[0], 400),
                               self.centre(self.place((400, 90))[0], 400), delta=1)

    def test_a_box_at_the_top_of_the_screen_does_not_go_off_it(self):
        top_box = {"left": 100, "top": 10, "width": 900, "height": 120}
        g = self.place((400, 90), box=top_box, record=True)[0]
        self.assertGreaterEqual(int(g.split("+")[2]), 0)

    def test_a_hand_drag_is_never_overruled(self):
        """Once someone has put the window somewhere, re-centring on the next line takes it back
        off them."""
        self.assertEqual(self.place((200, 90), moved=True), [])

    def test_no_box_means_no_placement(self):
        self.assertEqual(self.place((200, 90), box=None), [])


class BandEndpoint(unittest.TestCase):
    """The overlay is a separate process, so the box has to travel over HTTP to reach it."""

    def setUp(self):
        self.cur = service.Current()
        self.norm = {"x": 0.1, "y": 0.8, "w": 0.5, "h": 0.1}
        self.rect = {"left": 2816, "top": 1152, "width": 1280, "height": 144}
        self.srv = service.serve_http(self.cur, 0, self.norm, self.rect)
        self.port = self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()

    def _get(self, path):
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (self.port, path), timeout=4) as r:
            return json.loads(r.read().decode("utf-8"))

    def test_the_box_is_published_in_absolute_pixels(self):
        """Fractions of a monitor cannot place a window: they say nothing about where that monitor
        starts. On a second screen at x=2560 they land the overlay a whole screen width away --
        the same class of bug this repo already has a killed mutant for in the box selector."""
        got = self._get("/band")
        self.assertEqual(got["rect"], self.rect)
        self.assertGreater(got["rect"]["left"], 2560, "an absolute box, not a fraction")

    def test_the_fractions_are_still_there_for_anything_that_used_them(self):
        self.assertEqual(sorted(self._get("/band")["band"]), ["h", "w", "x", "y"])

    def test_a_run_with_no_box_publishes_null_rather_than_lying(self):
        srv = service.serve_http(service.Current(), 0, None, None)
        try:
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:%d/band" % srv.server_address[1],
                                        timeout=4) as r:
                self.assertIsNone(json.loads(r.read().decode("utf-8"))["rect"])
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main(verbosity=2)
