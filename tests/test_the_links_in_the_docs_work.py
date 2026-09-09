# -*- coding: utf-8 -*-
"""Every relative link and image in the docs points at something that exists.

A broken link in a README is the first thing a stranger hits, and it is invisible to everyone who
already has the repo: the file is there on the machine that wrote the link. It goes wrong the
ordinary way -- a file gets renamed, a screenshot is replaced with a differently numbered one, a
second README is added in another language and the two drift.

Cheap enough to run every time, and it covers the one part of this project that is read more
often than it is executed.
"""
import io
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def markdown_files():
    for name in sorted(os.listdir(ROOT)):
        if name.lower().endswith(".md"):
            yield name


def targets(name):
    """Relative link targets in this file, with any #anchor stripped. -> list"""
    text = io.open(os.path.join(ROOT, name), encoding="utf-8").read()
    out = []
    for href in LINK.findall(text):
        href = href.split(" ")[0].strip()
        if href.startswith(("http://", "https://", "mailto:", "#")):
            continue
        out.append((href, href.split("#")[0]))
    return out


class TheDocsDoNotPointAtNothing(unittest.TestCase):

    def test_there_are_docs_to_check(self):
        """The test that stops this whole file from passing by finding nothing to look at."""
        names = list(markdown_files())
        self.assertIn("README.md", names)
        self.assertIn("README.th.md", names)

    def test_every_relative_link_resolves(self):
        missing = []
        for name in markdown_files():
            for href, path in targets(name):
                if path and not os.path.exists(os.path.join(ROOT, path)):
                    missing.append("%s -> %s" % (name, href))
        self.assertEqual(missing, [], "; ".join(missing))

    def test_the_two_readmes_point_at_each_other(self):
        """A translation nobody can find from the page they landed on is a translation nobody
        reads."""
        en = io.open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        th = io.open(os.path.join(ROOT, "README.th.md"), encoding="utf-8").read()
        self.assertIn("README.th.md", en, "the English README does not offer the Thai one")
        self.assertIn("README.md", th, "the Thai README does not offer the English one")

    def test_the_thai_readme_is_near_the_top(self):
        """Below the fold it may as well not be there."""
        en = io.open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        self.assertLess(en.index("README.th.md"), 200)

    def test_the_pictures_the_guide_promises_are_there(self):
        """The guide is the page for people who do not want a command line, and it is mostly
        pictures."""
        shots = [p for _h, p in targets("GUIDE.md") if p.startswith("docs/")]
        self.assertGreaterEqual(len(shots), 4, "the guide has lost its screenshots")
        for p in shots:
            self.assertTrue(os.path.exists(os.path.join(ROOT, p)), p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
