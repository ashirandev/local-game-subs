# -*- coding: utf-8 -*-
"""Start the watch loop for real and check it reaches the watching state.

WHY THIS EXISTS. 287 tests were green and 67 mutants dead when `_loop` crashed on the first line
that touched `server`, in front of the person running it. Every one of those tests examined a
piece; not one of them started the thing. The loop runs until interrupted, so there was no
obvious way to call it from a test -- and "no obvious way to test it" is exactly the shape of the
code that ships broken.

There is a way: run it in a child process with the band handed in (so no selector opens), no
model behind it, and kill it after a few seconds. What is asserted is that it printed the line it
prints once it is watching, and that it printed no traceback. That is a low bar. It is also
precisely the bar the shipped build failed.

It does grab the screen once or twice, which is what the tool does anyway, and it talks to
nothing on the network -- the vision client points at a port with no server on it, and the worker
is expected to log errors and keep going.
"""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHILD = r'''
import argparse, sys
sys.path.insert(0, r"{src}")
from gamesubs.__main__ import _loop
from gamesubs.capture import Band

mon = {{"left": 0, "top": 0, "width": 1920, "height": 1080}}
band = Band(mon, [40, 900, 600, 120], 0.28, 1.0)
a = argparse.Namespace(port=0, api_key=None, model="local", lang="Thai",
                       interval=0.05, bright=200, min_ink=40, change=12, off_ticks=3,
                       max_width=1280, quality=88, max_hold=0.0, min_hold=None,
                       read_speed=None, frac=0.28, wfrac=1.0, pad=14)
_loop(a, "http://127.0.0.1:9/v1", band)
'''


class TheWatchLoopStarts(unittest.TestCase):

    def run_it(self):
        p = subprocess.Popen(
            [sys.executable, "-u", "-X", "utf8", "-c",
             CHILD.format(src=os.path.join(ROOT, "src"))],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=ROOT)
        try:
            out, _ = p.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            p.kill()
            out, _ = p.communicate()
        return out.decode("utf-8", "replace")

    def test_it_reaches_the_watching_state(self):
        out = self.run_it()
        self.assertIn("watching the band", out,
                      "the loop never got as far as watching:\n%s" % out)

    def test_and_gets_there_without_a_traceback(self):
        """A crash inside the loop still leaves earlier lines on stdout, so 'it printed something'
        is not the test. The absence of a traceback is."""
        out = self.run_it()
        self.assertNotIn("Traceback", out, out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
