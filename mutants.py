# -*- coding: utf-8 -*-
"""Break the code on purpose and check the tests notice.

A green suite proves the tests ran. It does not prove they would have gone red if the code were
wrong, and those are very different claims. Each mutant below is a plausible edit -- several are
literally what this code used to say -- and every one must turn at least one test red.

    python mutants.py

The first mutant is the bug that actually shipped in this repo: the tests were green while the
gate reported "same line" for four completely different subtitles, because the fixtures compared
filled rectangles and rectangles survive being shrunk. It is first on the list as a reminder that
the suite has been wrong before.
"""
import io
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src", "gamesubs")
TESTS = ["test_capture.py", "test_vision.py", "test_service.py"]

# (file, what it says now, what the mutant makes it say, what the mutant breaks)
MUTANTS = [
    ("capture.py", "return np.asarray(im) > thr", "return np.asarray(im) > 127",
     "the shipped bug: thin glyphs vanish in the downscale, every line looks the same"),
    ("capture.py", "def coarse(mask, w=COARSE_W, thr=25):", "def coarse(mask, w=COARSE_W, thr=90):",
     "threshold raised until real lines stop separating from jitter"),
    ("capture.py", "return (rgb[:, :, 0] >= bright) & (rgb[:, :, 1] >= bright)",
     "return (rgb[:, :, 0] >= bright)",
     "mask stops testing green, so a red HUD marker counts as text"),
    ("capture.py", "def __init__(self, bright=185, min_ink=700, change=30, off_ticks=3):",
     "def __init__(self, bright=185, min_ink=700, change=300, off_ticks=3):",
     "change threshold above a real line change -- nothing is ever read twice"),
    ("capture.py", "if self.off == self.off_ticks:", "if self.off >= 1:",
     "no debounce: a one-frame dropout clears the line and makes it flicker"),
    ("capture.py", "            self.last = None      # the next line starts fresh",
     "            pass                  # the next line starts fresh",
     "comparing across a gap, so a repeated line is silently swallowed"),
    ("capture.py", "h = int(m[\"height\"] * frac)\n            l, t, w = m[\"left\"], m[\"top\"] + m[\"height\"] - h, m[\"width\"]",
     "h = int(m[\"height\"] * frac)\n            l, t, w = m[\"left\"], m[\"top\"], m[\"width\"]",
     "default band moves to the top of the screen"),
    ("service.py", "dropped = self.job is not None", "dropped = False",
     "a replaced frame is no longer reported, so falling behind is invisible"),
    ("service.py", "if th and spk and th.strip().lower() == spk.strip().lower():",
     "if False:",
     "a failed read that returns the speaker's name gets shown as dialogue"),
    ("service.py", 'self.send_header("Cache-Control", "no-store")', "pass",
     "/current becomes cacheable and the subtitle freezes on screen"),
    ("service.py", 'if self._d["text"] and time.time() - self.at > ttl:',
     "if time.time() - self.at > ttl:",
     "expiring an already-empty line reports as an event"),
    ("vision.py", "for cand in sorted(objects(txt), key=len, reverse=True):",
     "import re\n        for cand in sorted(re.findall(r\"\\{.*\\}\", txt, re.S), key=len, reverse=True):",
     "back to the greedy regex: one span, so JSON after a stray {} is unrecoverable"),
    ("vision.py", "raise EmptyAnswer(", "return {} if schema else \"\"  # noqa\n            raise EmptyAnswer(",
     "an empty answer is swallowed instead of raised"),
    ("vision.py", "raise ValueError(\"unrecognised image format", "return \"image/jpeg\"  # noqa\n    raise ValueError(\"unrecognised image format",
     "unknown bytes are labelled JPEG and the server is left to guess"),
    ("vision.py", "content = [{\"type\": \"image_url\",", "content = [{\"type\": \"text\", \"text\": prompt}, {\"type\": \"image_url\",",
     "prompt put before the image"),
    ("vision.py", "raise RuntimeError(\"%s -- %s\" % (e, e.read().decode(\"utf-8\", \"replace\")[:400]))",
     "raise RuntimeError(str(e))",
     "HTTP error loses the body, which is the only part that says what went wrong"),
]


def run_tests():
    for t in TESTS:
        p = subprocess.run([sys.executable, "-X", "utf8", os.path.join("tests", t)],
                           cwd=ROOT, capture_output=True)
        if p.returncode != 0:
            return False, t
    return True, None


def main():
    ok, where = run_tests()
    if not ok:
        print("the suite is already red in %s -- fix that before mutating." % where)
        return 1

    killed = survived = 0
    for i, (fname, old, new, what) in enumerate(MUTANTS, 1):
        path = os.path.join(SRC, fname)
        src = io.open(path, encoding="utf-8").read()
        if src.count(old) != 1:
            print("%2d. SKIP  %-11s anchor appears %d times: %r"
                  % (i, fname, src.count(old), old[:50]))
            survived += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(src.replace(old, new, 1))
        try:
            alive, broke = run_tests()
        finally:
            io.open(path, "w", encoding="utf-8", newline="\n").write(src)
        if alive:
            survived += 1
            print("%2d. SURVIVED  %-11s %s" % (i, fname, what))
        else:
            killed += 1
            print("%2d. killed    %-11s %s  (%s)" % (i, fname, what, broke))

    print("\n%d/%d killed" % (killed, len(MUTANTS)))
    if survived:
        print("A survivor is a behaviour nothing checks. Either it does not matter -- say so and\n"
              "drop the mutant -- or there is a test missing.")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
