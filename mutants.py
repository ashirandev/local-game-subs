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
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src", "gamesubs")
TESTS = ["test_capture.py", "test_vision.py", "test_service.py", "test_server.py",
         "test_no_phone_home.py"]

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
    ("capture.py", 't = m["top"] + m["height"] - h', 't = m["top"]',
     "default band moves to the top of the screen"),
    ("capture.py", 'l = m["left"] + (m["width"] - w) // 2', 'l = m["left"]',
     "default band stops being centred and hugs the left edge"),
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
    ("server.py", 'if have and getattr(r, "status", 200) != 206:', "if False:",
     "a server that ignores Range gets its whole file APPENDED to the partial one -- right size, "
     "wrong bytes"),
    ("server.py", "    if total is None:", "    if False:",
     "a download with no declared size is guessed at instead of refused"),
    ("server.py", "return (m, p) if os.path.isfile(m) and os.path.isfile(p) else (None, None)",
     "return (m, p) if os.path.isfile(m) else (None, None)",
     "half a setup passes: weights without the projector, which fails only on images"),
    ("server.py", 'IMG_UB = IMG_CEIL + 32', "IMG_UB = 560",
     "batch size no longer covers one image, so the encode silently caps"),
    ("server.py", 'out = [n for n in names if want in n and n.startswith("llama-")]',
     "out = [n for n in names if want in n]",
     "cuda picks the 373 MB runtime package instead of the build, and gets no llama-server"),
    # (An earlier mutant here swapped startswith for `in` on the runtime prefix. It survived, and
    # correctly: on a name that specific the two are the same test. Equivalent mutants get
    # deleted rather than papered over with a test written to catch them.)
    ("server.py", "if out and runtime:", "if runtime:",
     "a release with only the runtime looks like a usable download: 373 MB, no llama-server"),
    ("server.py", "        os.remove(path)", "        pass",
     "a file that fails its checksum is left on disk and gets used anyway"),
    ("server.py", "    if expected and got != expected.lower():", "    if False:",
     "checksums are computed and then not compared to anything"),
    ("service.py", 'ThreadingHTTPServer(("127.0.0.1", port), H)',
     'ThreadingHTTPServer(("0.0.0.0", port), H)',
     "what is on your screen becomes readable from the rest of the network"),
]


def drop_bytecode():
    """Delete every __pycache__ under the repo. NOT optional, and the reason is nasty.

    Python decides a .pyc is current from the source's SIZE and its mtime IN WHOLE SECONDS.
    Several mutants here replace a fragment with one of exactly the same length -- `> thr` becomes
    `> 127` -- and mutate, test and restore all happen inside one second. So the restore puts the
    original source back and Python goes on running the MUTANT's bytecode: the suite then fails on
    code that is correct, and stays failing until something touches the file again.

    It cost one confusing run to find, and it did not present as a caching problem. It presented
    as a flaky test.
    """
    for base, dirs, _ in os.walk(ROOT):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(base, d), ignore_errors=True)
                dirs.remove(d)


def run_tests():
    for t in TESTS:
        # -B as well as the sweep above: belt and braces, because a stale .pyc does not look like
        # a caching problem here -- it looks like the mutant survived.
        p = subprocess.run([sys.executable, "-B", "-X", "utf8", os.path.join("tests", t)],
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
        drop_bytecode()
        try:
            alive, broke = run_tests()
        finally:
            io.open(path, "w", encoding="utf-8", newline="\n").write(src)
            drop_bytecode()
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
