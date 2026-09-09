# -*- coding: utf-8 -*-
"""Nothing leaves this repository that we do not have the right to pass on.

A font is someone's licensed work. Leelawadee UI and Tahoma come with Windows, Google Sans is
Google's brand face, and none of the three may be redistributed -- yet all of them are exactly the
fonts a developer ends up with in their own `fonts` folder while testing, because they are the
ones already on the machine. That is the whole risk: the mistake is made by a person being
helpful, it produces no error, and the first person to notice is the one whose work was published.

So the check is not "did we mean well", it is "what does git actually track". An allow-list, and
a file added to it on purpose is a decision someone had to write down.

The cost of the two failures is not symmetric: a font that fails to ship is a missing file that
somebody reports in an hour, and a font that ships without the right to is a licence violation in
public, on work that is not ours.
"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Open licences only, and each one named. SIL Open Font Licence, redistribution explicitly allowed.
ALLOWED = {"notosansthai-regular.ttf", "ofl-notosansthai.txt", "put-fonts-here.txt"}

# Not exhaustive -- the allow-list above is what actually decides. These are here so a failure
# says WHY, in the words of the licence that was broken.
KNOWN_UNFREE = {"leelawui": "Leelawadee UI ships with Windows and may not be redistributed",
                "leelauib": "Leelawadee UI ships with Windows and may not be redistributed",
                "tahoma": "Tahoma is Microsoft's and may not be redistributed",
                "googlesans": "Google Sans is Google's brand font, not an open release",
                "segoe": "Segoe UI ships with Windows and may not be redistributed"}


def tracked(path):
    try:
        out = subprocess.run(["git", "ls-files", path], cwd=HERE, capture_output=True, text=True)
    except OSError:
        return None
    if out.returncode != 0:
        return None
    return [l.strip() for l in out.stdout.splitlines() if l.strip()]


class OnlyFreeFontsShip(unittest.TestCase):

    def setUp(self):
        self.files = tracked("fonts")
        if self.files is None:
            self.skipTest("no git here")

    def test_every_tracked_font_is_on_the_allow_list(self):
        for f in self.files:
            name = os.path.basename(f).lower()
            why = next((w for k, w in KNOWN_UNFREE.items() if k in name), None)
            self.assertIn(name, ALLOWED, why or "%s is not on the allow-list" % f)

    def test_the_licence_travels_with_the_font(self):
        """A font shipped without its licence text is a font shipped without its permission."""
        names = {os.path.basename(f).lower() for f in self.files}
        if any(n.endswith((".ttf", ".otf")) for n in names):
            self.assertIn("ofl-notosansthai.txt", names)

    def test_something_actually_ships(self):
        """The other direction. `fonts/` was ignored wholesale for weeks, so the folder in the
        repository was empty and every user's first run said no font could draw their language."""
        self.assertTrue(any(f.lower().endswith((".ttf", ".otf")) for f in self.files),
                        "no font ships at all -- check .gitignore")

    def test_the_shipped_font_can_draw_the_hard_case(self):
        sys.path.insert(0, os.path.join(HERE, "src"))
        from gamesubs import render
        for f in self.files:
            if f.lower().endswith((".ttf", ".otf")):
                p = os.path.join(HERE, f)
                self.assertTrue(render.has_glyphs(render.load(p, 22),
                                                  "".join(render.STACKED_SAMPLES)),
                                "%s cannot draw the sample words it is shipped for" % f)


if __name__ == "__main__":
    unittest.main(verbosity=2)
