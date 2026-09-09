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
import glob
import io
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src", "gamesubs")
# Found, not listed. The hand-written list had drifted three files behind what is in tests/ --
# including test_the_loop_starts.py, which exists because a bug reached the user -- and a
# mutation score computed without a test is a score for a suite nobody has.
TESTS = sorted(os.path.basename(p)
               for p in glob.glob(os.path.join(ROOT, "tests", "test_*.py")))

# (file, what it says now, what the mutant makes it say, what the mutant breaks)
# A newline, written without an escape: a few mutants below replace a fragment that
# spans two lines, and a literal backslash-n here matches nothing -- the run said SKIP
# rather than failing, which is the quiet way for a mutant to stop existing.
NL = chr(10)

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
    ("service.py",
     'if self._d["text"] and now - self.at > ttl and now >= self._until:',
     "if now - self.at > ttl:",
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
    ("server.py", '"--reasoning", "off"]', "]",
     "reasoning left on: every answer still correct, every line 4x too slow to keep up"),
    ("vision.py", '"chat_template_kwargs": {"enable_thinking": False}}', "}",
     "the per-request half of the same 4x, which the server flag alone does not guarantee"),
    ("overlay.py", "sample=SAMPLE, in_capture=False, max_width=1100):",
     "sample=SAMPLE, in_capture=True, max_width=1100):",
     "the overlay becomes visible to capture again and translates its own output forever"),
    ("server.py", "    if marker and os.access(root, os.W_OK):", "    if False:",
     "downloads escape to a hidden folder under home, and survive deleting the tool"),
    ("server.py", "    elif len(weights) == 1:", "    elif True:",
     "several models silently resolve to whichever sorts first, instead of asking"),
    ("region.py", "return min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)",
     "return x0, y0, x1 - x0, y1 - y0",
     "dragging up or left selects nothing, and says nothing about it"),
    ("region.py", 'return l + virtual["left"], t + virtual["top"], w, h', "return l, t, w, h",
     "the box is right on one monitor and off by a screen width on two"),
    ("server.py", "and r[2] > 0 and r[3] > 0", "and True",
     "a zero-width saved box is accepted and then never sees anything"),
    ("service.py", 'ThreadingHTTPServer(("127.0.0.1", port), H)',
     'ThreadingHTTPServer(("0.0.0.0", port), H)',
     "what is on your screen becomes readable from the rest of the network"),
    # --- 2026-09-09: the shaper, the plate, and the one box ----------------------------------
    ("shape.py", "    hb.shape(font, buf)", "    pass",
     "nothing is shaped at all: no GSUB, no GPOS, and the tone mark keeps the form that belongs "
     "on a bare consonant -- which is the state Pillow was already in, and the reason this "
     "module exists"),
    ("shape.py", "    buf.guess_segment_properties()", "    pass",
     "the buffer is shaped with no script, direction or language, so the Thai rules are not the "
     "ones that run"),
    # (A mutant here removed the `pil = getattr(font, "pil", font)` unwrap in `_bitmap` -- the
    # bug that shipped on 2026-09-09 and told a machine with 133 usable fonts that it had none.
    # It SURVIVES, and correctly: `Face.__getattr__` now delegates `getmask` to the Pillow font,
    # so the unwrap is belt to that braces and removing it changes no behaviour. The mutant below
    # covers the same ground by cutting the delegation instead. Equivalent mutants get deleted
    # rather than papered over with a test written to catch them.)
    ("render.py", "        return getattr(self.pil, name)", "        raise AttributeError(name)",
     "six places draw the chrome through Pillow, and all six die at the screen they belong to"),
    ("render.py", "PLATE = (0, 0, 0, 255)", "PLATE = (0, 0, 0, 190)",
     "the sentence underneath is dimmed instead of hidden: the same line twice, in two languages"),
    ("region.py", "    m = monitor_for(x, t + h / 2.0, monitors)", "    m = None",
     "the instruction goes back under the box -- off the bottom of the monitor for every "
     "subtitle there has ever been, on a desktop whose virtual rectangle has holes in it"),
    ("region.py", "    for bx, by in banner_spots(mons):",
     "    for bx, by in [(virtual[\"width\"] // 2, 40)]:",
     "one banner in the middle of the virtual screen, which on three unequal monitors is a "
     "point on none of them"),
    ("__main__.py", '    region = _grown(region, m, getattr(a, "pad", 0))', "    region = region",
     "the box is used exactly as dragged, so a drag one pixel inside the sentence hands the "
     "model a clipped word -- which it translates perfectly, as the wrong word"),
    ("__main__.py", 'if not getattr(a, "no_select", False):',
     "if saved is None and not getattr(a, \"no_select\", False):",
     "back to asking once ever: the box from another game is reused in silence"),
    ("overlay.py", "        return max(200, int(w)) if w else self.max_width",
     "        return self.max_width",
     "lines wrap at a width unrelated to the box, so the plate comes out wider than the region "
     "it is drawn for"),
    ("overlay.py", "                self._place(im.size)", "                pass",
     "a short line and a long one are anchored at the same left edge instead of the same centre, "
     "which is the movement that reads as broken"),
    ("overlay.py", "        if not box or self._moved:", "        if not box:",
     "re-centring on every line takes the window back off anyone who dragged it"),
    ("overlay.py", "        box = self.box" + NL + "        if box:",
     "        box = None" + NL + "        if box:",
     "a position saved on another day beats the box drawn one minute ago"),
    ("service.py", 'n = len("".join((text or "").split()))',
     'n = len((text or "").split())',
     "the obvious answer: word count, which is 1 for almost every Thai sentence"),
    ("service.py", "return max(lo, min(hi, eye + n / float(speed)))",
     "return min(hi, eye + n / float(speed))",
     "the floor goes, so a two-character line is allowed to flash past"),
    ("service.py", "return max(lo, min(hi, eye + n / float(speed)))",
     "return max(lo, min(hi, eye))",
     "every line gets the same time, so length stops buying reading room"),
    ('service.py', 'if self._d["text"] and now < self._until:',
     'if False:',
     "a clear during the floor lands at once again -- the flash comes back"),
    ("service.py", "                    self._owed = True" + NL + "                    return False",
     "                    return False",
     "the deferred clear is never owed, so the line stays up until something replaces it"),
    ("service.py", "if self._owed and now >= self._until:",
     "if self._owed:",
     "the owed clear is paid the instant it is asked for, which is the flash again"),
    ("service.py", "            self._until = now + self.hold_for(text)",
     "            self._until = now",
     "a new line arms no floor at all"),
    ("service.py", "            self._owed = False" + NL + "            return True" + NL + NL + "    def get",
     "            return True" + NL + NL + "    def get",
     "a pending clear survives the line that replaced it and takes the new one off early"),
    ("server.py", '        if st.st_mtime_ns <= before:',
     '        if False:',
     'two writes inside one filesystem tick look like no write, so a second colour change never reaches the overlay'),
    ("server.py", '        if k.endswith("_colour") and not is_colour(v):',
     '        if False:',
     'any string is accepted as a colour, and the renderer silently falls back while the panel shows the choice as made'),
    ("server.py", '        if isinstance(v, bool) or not isinstance(v, (int, float)):',
     '        if not isinstance(v, (int, float)):',
     'True is a number in Python, so a JSON true becomes a text size of 1'),
    ("render.py", '    if not isinstance(spec, str) or len(spec) != 7 or spec[0] != "#":',
     '    if False:',
     'a malformed colour in the settings file raises inside the draw instead of falling back'),
    ("render.py", '        return (int(spec[1:3], 16), int(spec[3:5], 16), int(spec[5:7], 16), 255)',
     '        return (int(spec[1:3], 16), int(spec[3:5], 16), int(spec[5:7], 16), 190)',
     'the plate goes translucent again: the English shows through its own translation'),
    ("overlay.py", '        if path and path != self.font_path:',
     '        if path:',
     'the font is reloaded on every write, so moving any slider costs two font loads'),
    ("overlay.py", '        if stamp == self._stamp:',
     '        if False:',
     'settings.json is parsed several times a second for ever, to learn nothing'),
    ("server.py", '    return left[0] if len(left) == 1 else None',
     '    return None',
     "adding a second model unpairs the first, so following the folder's own instructions breaks the setup that was working"),
    ("server.py", '    proj = match_projector(weight, projectors, weights)',
     '    proj = match_projector(weight, projectors)',
     'the fix exists and the one caller does not use it'),
    ("server.py", '            "mmproj": "mmproj-BF16.gguf", "save_as": "mmproj-E2B-BF16.gguf",',
     '            "mmproj": "mmproj-BF16.gguf", "save_as": "mmproj-BF16.gguf",',
     "the second model's projector is saved over the first one's: same name, near enough the same size, and the model that worked now reads every frame as blank"),
    ("server.py", 'os.path.join(d, e["save_as"]),',
     'os.path.join(d, e["mmproj"]),',
     "the table renames the projector and the downloader ignores it, so the second model overwrites the projector of the first"),
    ("__main__.py", '    server.fetch_model(a.dir, getattr(a, "model_name", None))',
     '    server.fetch_model(a.dir)',
     '--model-name is accepted, printed in the help, and does nothing'),
    ("__main__.py", '        print("      %s" % (server.HF % e["repo"]))',
     '        pass',
     'the models list stops saying where any of them come from'),
    ("__main__.py", '        if raw.strip() == b"RUN":',
     '        if b"RUN" in raw:',
     'any line mentioning RUN starts the run, so a warning from a graphics driver launches a model nobody asked for'),
    ("__main__.py", '    return False\n\n\ndef _drain(pn):',
     '    return True\n\n\ndef _drain(pn):',
     'closing the settings window starts everything anyway'),
    ("__main__.py", '        pn.stdin.write(("STATUS " + text + chr(10)).encode("utf-8"))',
     '        pass',
     'the status bar never moves, so the minute the model spends loading looks like a window that did nothing'),
    ("panel.py", '        if self.started or not self.launcher:',
     '        if not self.launcher:',
     'pressing Start twice sends two RUNs and commits twice'),
    ("panel.py", '                    self.root.after(0, self.set_status, line[7:])',
     '                    self.set_status(line[7:])',
     'Tk is driven from the reader thread, which crashes minutes later somewhere unrelated'),
    ("panel.py", '            value="used when you press Start" if launcher else',
     '            value="takes effect the next time you start" if launcher else',
     'the launcher says the model choice is for NEXT time while it is deciding this one'),
    ("__main__.py", '        ASKED["redraw"] = False\n        return True',
     '        return True',
     'one press of Move box redraws the box on every tick of the loop for ever'),
    ("__main__.py", '                if _hotkey_redraw() or _take_redraw():',
     '                if _hotkey_redraw():',
     'the Move box button is drawn, is clickable, and does nothing'),
    ("service.py", '    kind = _label_kind(en, speaker)',
     '    kind = _label_kind(th, speaker)',
     'the label is looked for in the TRANSLATION, where the name is transliterated and can never match, so no label is ever found'),
    ("service.py", '    return bool(n) and s == n',
     '    return bool(n) and n in s',
     "a line whose first word happens to be the speaker's name is cut as if it were a label"),
    ("service.py", '        if _is(parts[-1], speaker) and LF_CHAR.join(parts[:-1]).strip():',
     '        if False:',
     'a game that puts the name BELOW the line keeps it in the translation'),
    ("service.py", '    if _lead_colon(th) and ":" not in (en or ""):',
     '    if _lead_colon(th):',
     'an English sentence containing a colon makes the Thai lose its first clause'),
    ("service.py", '        return speaker, _cut(en, kind), _cut(th, kind)',
     '        return speaker, _cut(en, kind), th',
     'the English is cleaned and the translation still carries the name -- which is the half the player actually reads'),
    ("region.py", 'DEFAULT_BOTTOM = 0.88',
     'DEFAULT_BOTTOM = 0.75',
     'the default box sits above the line RE4R actually draws, and reads empty picture'),
    ("region.py", 'DEFAULT_H = 0.16',
     'DEFAULT_H = 0.06',
     'too short for a two-line subtitle, which is the first cutscene of the game it was measured on'),
    ("region.py", '    left = int(mon["left"]) + (int(mon["width"]) - w) // 2',
     '    left = int(mon["left"])',
     'the default is jammed against the left edge instead of centred'),
    ("region.py", '    top = int(mon["top"]) + int(mon["height"] * DEFAULT_BOTTOM) - h',
     '    top = int(mon["top"]) + int(mon["height"] * DEFAULT_BOTTOM)',
     'the box hangs off the bottom of the screen, watching pixels no display has'),
    ("region.py", '    m = centred_on(box, monitors, tol)\n    if not m:',
     '    m = centred_on(box, monitors, 10 ** 6)\n    if not m:',
     'every box is dragged to the centre whether it was aimed there or not'),
    ("region.py", '    return (int(m["left"] + (m["width"] - w) // 2), t, w, h)',
     '    return (int(m["left"] + (m["width"] - w) // 2), int(m["top"]), w, h)',
     'snapping sideways also throws away the vertical aim it was helping with'),
    ("region.py", '    return l <= x <= l + w and t <= y <= t + h',
     '    return l <= x and t <= y',
     'everything below and right of the box counts as inside it, so a new drag never starts'),
    ("region.py", '            drag["mode"] = "move"',
     '            drag["mode"] = "draw"',
     'dragging inside the box redraws it from that point instead of moving it'),
    ("region.py", '            moved = snap_x(moved, mons)',
     '            pass',
     'the centre can be approached and never reached'),
    ("__main__.py", '        saved = server.load_region() or default_box(m)',
     '        saved = server.load_region()',
     'the first run opens on an empty screen again'),
    ("service.py", '                if first:',
     '                if False:',
     'the same sentence is re-translated on every read, so the words on screen change while the English behind them has not moved'),
    ("service.py", '                    spk, th = first',
     '                    spk = first[0]',
     'the speaker is kept from the first reading and the wording from the newest, which is the flicker again with a stable name over it'),
    ("service.py", '                        self.said.popitem(last=False)',
     '                        pass',
     'the memo grows for the whole session, one entry per line of the game'),
    ("service.py", '    return " ".join((line or "").split()).strip().rstrip(" .!?…").casefold()',
     '    return line',
     'a trailing full stop makes it a different sentence, and both spellings arrived on the same menu seconds apart'),
    ("service.py", '            key = normalise(en)',
     '            key = en',
     'the key stops being normalised, so spacing and case split one sentence into several'),
    ("__main__.py", '    if (speaker, source, text) == LAST["line"]:',
     '    if False:',
     'the console prints the same caption once per read -- 88 times in one measured run'),
    ("service.py", '    "1. Copy the text you can read in it EXACTLY into `en`.',
     '    "1. Copy the gist of the text you can read in it into `en`.',
     'the English stops being a copy of the screen, so a bad translation and a bad READ look the same and there is nothing to tell them apart with'),
    ("service.py", '    "4. If there is NO readable text at all, return all three fields empty. An empty answer "',
     '    "4. Always answer with something. An empty answer "',
     'a quiet scene gets a black plate with an invented line on it'),
    ("fonts.py", '    if all(getattr(f, "shaped", False) for _, f, _, _, _ in plan):',
     '    if False:',
     'the font sheet draws every row unshaped, so every font fails the one column it exists for'),
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
    print("%d test files, %d mutants" % (len(TESTS), len(MUTANTS)))
    ok, where = run_tests()
    if not ok:
        print("the suite is already red in %s -- fix that before mutating." % where)
        return 1

    # --only N runs a single mutant. Without it the only question you can ask costs 37 minutes,
    # which is how mutant 80 kept a dead anchor for a day with nobody noticing.
    only = None
    for a in sys.argv[1:]:
        if a.startswith("--only"):
            only = int(a.split("=", 1)[1] if "=" in a else sys.argv[sys.argv.index(a) + 1])

    killed = survived = 0
    for i, (fname, old, new, what) in enumerate(MUTANTS, 1):
        if only is not None and i != only:
            continue
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

    print("\n%d/%d killed" % (killed, (killed + survived) if only is not None else len(MUTANTS)))
    if survived:
        print("A survivor is a behaviour nothing checks. Either it does not matter -- say so and\n"
              "drop the mutant -- or there is a test missing.")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
