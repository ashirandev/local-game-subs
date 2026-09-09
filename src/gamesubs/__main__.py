# -*- coding: utf-8 -*-
"""Command line.

    setup     download the model (about 5.7 GB, resumable)
    check     prove your setup works, without launching a game
    play      start the model, the translator and the overlay -- one command
    tune      find the two thresholds for your game
    run       the translator alone, against a server you started yourself
    overlay   the on-screen window alone

`check` before `play` is worth the minute it takes. It renders subtitles, sends them to your
model and prints what came back, so a broken setup fails there -- with an error you can read --
instead of showing up as "nothing appears" while you are in a game.
"""
import argparse
import io
import os
import sys
import time

from . import server
from .capture import Band, ChangeGate
from .service import (MIN_HOLD, READ_SPEED, SCHEMA, SNAP, Current, Worker, prompt_for,
                      serve_http)
from .vision import VisionClient


def _sct():
    """mss renamed mss.mss to mss.MSS and deprecated the old spelling. Support both, so the tool
    neither opens with a warning on one version nor fails outright on the other."""
    import mss
    return getattr(mss, "MSS", None) or mss.mss


def _grown(region, mon, pad):
    """The drawn box, with a little air around it. -> [L, T, W, H] or None

    A box is dragged by eye, around letters whose edges are softer than they look, and a drag that
    ends one pixel inside the sentence hands the model a clipped word -- which it translates
    perfectly, as the wrong word, with nothing reporting a problem. So the box in use is a little
    larger than the box that was drawn.

    Grown at the point of USE, not when saved: saving the grown one would show a slightly bigger
    box in the selector next run, and grow again from there, and again.

    Both halves grow together, because they are the same rectangle -- what is read is what is
    covered. Clamped to the monitor, since a box dragged to the bottom edge has nowhere to grow.
    """
    if not region or not pad:
        return region
    l, t, w, h = region
    l2, t2 = max(mon["left"], l - pad), max(mon["top"], t - pad)
    r2 = min(mon["left"] + mon["width"], l + w + pad)
    b2 = min(mon["top"] + mon["height"], t + h + pad)
    return [l2, t2, max(1, r2 - l2), max(1, b2 - t2)]


def _band(a):
    """Which strip of screen to watch, in order: --region, then the box you dragged, then a
    sensible default across the bottom.

    The selector opens by itself the first time, because the alternative is a tool that starts,
    watches the wrong part of the screen, and says nothing about it.
    """
    with _sct()() as sct:
        mons = sct.monitors
        if a.monitor >= len(mons):
            raise SystemExit("monitor %d does not exist (found %d)" % (a.monitor, len(mons) - 1))
        m = dict(mons[a.monitor])
        virtual = dict(mons[0])              # every monitor, so the box can be dragged anywhere
        screens = [dict(x) for x in mons[1:]]   # the real ones, for placing the on-screen hints

    region = None
    if a.region:
        region = [int(x) for x in a.region.split(",")]
    else:
        from .region import default_box, select
        # There is a box on screen from the very first run. It used to open on an empty
        # screen, so the first thing a new person had to do was invent a rectangle for a
        # tool they had not yet seen work. Centred and low, where subtitles are.
        saved = server.load_region() or default_box(m)
        # Asked every run, with that box already drawn: Enter accepts it, a drag replaces
        # it. Games move their subtitles between menus, cutscenes and gameplay, and a box
        # that is silently reused is a box that is silently wrong.
        if not getattr(a, "no_select", False):
            got = select(virtual, saved, screens)
            if got:
                server.save_region(got)
                region = list(got)
                print("box saved.")
            else:
                region = list(saved)         # cancelled: keep what was on screen
        else:
            region = list(saved)

    region = _grown(region, m, getattr(a, "pad", 0))
    b = Band(m, region, a.frac, a.wfrac)
    r = b.rect
    print("band: %dx%d at (%d,%d)%s"
          % (r["width"], r["height"], r["left"], r["top"],
             "" if region else "   (default strip -- nothing was drawn)"))
    return b


def _grab(sct, rect):
    import numpy as np
    return np.asarray(sct.grab(rect))[:, :, :3][:, :, ::-1]      # BGRA -> RGB


# Set by the panel's "Move box" button, read by the watch loop. A dict rather than a global
# rebind so the reader thread and the loop are looking at the same object.
ASKED = {"redraw": False}


def _take_redraw():
    """True once per request. Consumed on read, so one press draws one box. -> bool"""
    if ASKED["redraw"]:
        ASKED["redraw"] = False
        return True
    return False


def _hotkey_redraw():
    """True when Ctrl+Alt+R is held down right now. Windows only; False everywhere else.

    A global hotkey rather than a menu, for the same reason the overlay's lock is one: the window
    you would put a button on is either not there or is click-through by then. And re-drawing the
    box has to work WITHOUT restarting -- a restart means loading the model again, and nobody is
    going to sit through that because a cutscene put the subtitles somewhere else.
    """
    if sys.platform != "win32":
        return False
    import ctypes
    g = ctypes.windll.user32.GetAsyncKeyState
    return all(g(k) & 0x8000 for k in (0x11, 0x12, 0x52))        # Ctrl, Alt, R


def _choose_model(a):
    """Which weights and projector to load.

    The dropdown appears only when there is a decision to make. With one model in the folder it
    starts straight away -- a dialog whose list has a single entry is just a click to lose.
    """
    d = server.home("models")
    weights, _ = server.list_models(d)
    if getattr(a, "model_file", None) or getattr(a, "no_pick", False) or len(weights) <= 1:
        return server.resolve_model(getattr(a, "model_file", None), d)
    from .picker import choose
    got = choose(d)
    if not got:
        raise SystemExit("no model chosen.")
    return got


def _choose_font(a):
    """Which font to draw with. --font wins; otherwise the chooser opens, on your last answer.

    ASKED EVERY RUN, like the box. A setting that is remembered silently is a setting nobody can
    find again: the chooser used to open once, ever, and the next run started with no visible
    trace that a font had ever been chosen -- "where did the font picker go" is not a question a
    person should have to ask their own tool. Your last choice is pre-selected, so accepting it
    is one key. `--no-pick-font` skips it for a shortcut you make yourself.
    """
    if getattr(a, "font", None):
        return a.font
    saved = server.load_font()
    if getattr(a, "no_pick_font", False):
        return saved
    from .fontpick import choose
    got = choose(server.home("fonts"), current=saved)
    if got:
        server.save_font(got)
        print("font saved: %s" % os.path.basename(got))
        return got
    return saved


def _jpg(rgb, max_width=1280, quality=88):
    from PIL import Image
    im = Image.fromarray(rgb)
    if im.width > max_width:
        im = im.resize((max_width, int(im.height * max_width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


# --------------------------------------------------------------------------- setup / check

def _catalog():
    return server.CATALOG


def _default_model():
    return server.DEFAULT_MODEL


def cmd_models(a):
    """List what `setup` can download, with the link, so nobody has to go looking."""
    d = server.home("models")
    here, _proj = server.list_models(d)
    print("in %s right now:" % d)
    for w in here or ["  (nothing yet)"]:
        print("  %s" % w)
    print("")
    for key in sorted(server.CATALOG):
        e = server.CATALOG[key]
        got = " -- already here" if e["weights"] in here else ""
        print("%-5s %.1f GB%s" % (key, e["gb"], got))
        print("      %s" % e["note"])
        print("      %s" % (server.HF % e["repo"]))
        print("      python -m gamesubs setup --model-name %s" % key)
        print("")
    return 0


def cmd_setup(a):
    """Everything needed to run, in one command: llama.cpp, then the model."""
    exe = server.find_server(a.llama_server)
    if exe and a.backend != "auto" and server.backend_of(exe) != a.backend:
        exe = None            # asked for a specific build and this is not it -- fetch that one
    if exe:
        print("llama-server already here: %s\n" % exe)
    else:
        # Vulkan for everyone, and this reversed once. The first comparison put CUDA at 0.6 s a
        # line and Vulkan at 3.6 s, which looked decisive -- but both arms were measured with the
        # model's reasoning left on, and that turned out to dominate everything else. With it off:
        # CUDA 0.6 s, Vulkan 0.7 s. A tenth of a second, for a download fifteen times smaller
        # that also works on AMD and Intel and never has to match a CUDA runtime to a driver.
        # The lesson is not about backends: two arms differing in a variable neither of them is
        # about will happily produce a confident, wrong architectural decision.
        backend = "vulkan" if a.backend == "auto" else a.backend
        exe = server.fetch_llama(backend)
        print("llama-server: %s\n" % exe)
    server.fetch_model(a.dir, getattr(a, "model_name", None))
    _models_folder(server)
    _fonts_folder(server)
    print("\neverything is ready.  Next:  python -m gamesubs check")
    return 0


MODELS_README = """Drop a vision model in here and it appears in the chooser next time you start.

WHAT TO DROP: two files, not one.

    something.gguf          the model itself
    mmproj-*.gguf           its vision projector -- what lets it SEE

Get both from the same place. A model with no projector beside it is offered and then cannot be
started: without one the server loads happily, answers questions about text, and fails on every
single frame -- which looks like this tool is broken rather than like a file is missing.

It must be a model that takes IMAGES. A text-only GGUF, however good, has nothing to read the
screen with. The default here is gemma-4-E4B (Q4_K_M, about 4.7 GB + 0.9 GB projector), which is
small enough to leave the graphics card to the game.

Bigger is not automatically better for this job: the work is reading one short line off a picture
and saying it in another language, and a model twice the size mostly buys you a slower subtitle.
Measured here, 21 reads each over seven scenes: E2B answers in 0.66 s and E4B in 1.07 s,
and they read the same words. E4B is steadier on names it has to spell (E2B wrote "Racoon
City"); E2B leaves 1.6 GB more of the card to the game. Try the small one first.

EASIEST WAY TO GET EITHER ONE -- it downloads both files and names them so they cannot clash:

    python -m gamesubs models                  what is here, what else there is, and the links
    python -m gamesubs setup --model-name e2b  the small fast one
    python -m gamesubs setup --model-name e4b  the default

IF YOU FETCH ONE BY HAND, RENAME ITS PROJECTOR. They are all published as `mmproj-BF16.gguf`,
so saving a second one in here either lands on top of the first model's projector or leaves
two files with the same name and nothing to say which model each belongs to. Put the model in
the name -- `mmproj-E2B-BF16.gguf` -- and both pairs are unambiguous. Getting this wrong is
quiet: the server starts, answers text, and reads every frame as though it were blank. That is
the whole reason `setup --model-name` exists rather than a link on its own.

Anything you drop here is yours -- nothing in this folder is ever uploaded anywhere.
"""


def _models_folder(server):
    d = server.home("models")
    p = os.path.join(d, "PUT-MODELS-HERE.txt")
    if not os.path.isdir(d):
        os.makedirs(d)
    if not os.path.isfile(p):
        with open(p, "w", encoding="utf-8") as f:
            f.write(MODELS_README)
    print("models folder: %s" % d)


FONTS_README = """Drop font files (.ttf or .otf) in here and they become available to the overlay.

Why you might: the subtitle is drawn with whatever font is chosen, and a font without your
language's glyphs does not refuse to draw -- it shows boxes, or the system quietly substitutes
another font and the marks that sit above and below letters drift away from them.

Anything in this folder is tried before the fonts installed on the machine. Pick one with:

    python -m gamesubs fonts        see them all drawn, side by side
    python -m gamesubs play --font "<name or filename>"

Good free ones for Thai: Noto Sans Thai, IBM Plex Sans Thai, Sarabun (all open licences).
On Windows, Leelawadee UI and Tahoma are already installed and both work.

Nothing is shipped in here on purpose: a font is someone's licensed work, and plenty of the
good-looking ones may not be redistributed.
"""


def _fonts_folder(server):
    d = server.home("fonts")
    p = os.path.join(d, "PUT-FONTS-HERE.txt")
    if not os.path.isfile(p):
        with open(p, "w", encoding="utf-8") as f:
            f.write(FONTS_README)
    print("fonts folder: %s" % d)


CHECK_LINES = [("", "We should keep moving before it gets dark."),
               ("NAOE", "I told you not to follow me."),
               ("", "Take the left path. I'll cover you from here."),
               ("YASUKE", "Stay behind me."),
               (None, None)]                # no subtitle: the model must return empty


def _render(speaker, text, w=1280, h=260):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (w, h), (26, 30, 24))
    d = ImageDraw.Draw(im)
    for i in range(0, w, 40):                       # background structure, not a flat colour
        d.line([(i, 0), (i - 60, h)], fill=(34, 40, 32), width=9)
    if text is None:
        d.rectangle([40, 30, 300, 54], fill=(200, 60, 40))       # a HUD bar, no dialogue
        return im
    f = fs = None
    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"):
        try:
            f, fs = ImageFont.truetype(name, 40), ImageFont.truetype(name, 24)
            break
        except OSError:
            continue
    if f is None:
        f = fs = ImageFont.load_default()
    if speaker:
        d.text((w // 2, 70), speaker, font=fs, fill=(210, 214, 220), anchor="mm")
    d.text((w // 2, 130), text, font=f, fill=(255, 255, 255), anchor="mm")
    return im


def cmd_check(a):
    """Render subtitles, send them to the model, and say plainly whether this setup works."""
    proc = None
    try:
        base = a.base_url
        if not base:
            m, mp = _choose_model(a)
            proc = server.start(model=m, mmproj=mp, exe=a.llama_server, port=a.server_port)
            base = "http://127.0.0.1:%d/v1" % a.server_port
            print("waiting for it to answer a question about a picture...")
            server.wait_until_it_can_see(base, a.model, proc=proc)
            print("it can see.\n")
        vram = server.gpu_used_mb()
        if vram:
            print("GPU memory in use: %.1f GB\n" % (vram / 1024.0))

        vc = VisionClient(base, a.model)
        read = blank_ok = 0
        times = []
        for spk, txt in CHECK_LINES:
            buf = io.BytesIO()
            _render(spk, txt).save(buf, "JPEG", quality=88)
            t0 = time.time()
            try:
                d = vc.ask(prompt_for(a.lang), image=buf.getvalue(), schema=SCHEMA)
            except Exception as e:
                print("  FAILED  %s: %s" % (type(e).__name__, str(e).split("\n")[0][:140]))
                return 1
            dt = time.time() - t0
            times.append(dt)
            en, th = (d.get("en") or "").strip(), (d.get("th") or "").strip()
            if txt is None:
                blank_ok = 0 if th else 1
                print("  [%4.1fs] no subtitle on screen -> %s"
                      % (dt, "correctly returned nothing" if not th
                         else "WRONG, it invented %r" % th[:40]))
            else:
                hit = en.rstrip(".").lower() == txt.rstrip(".").lower()
                read += hit
                print("  [%4.1fs] %s\n           read %s\n           -> %s"
                      % (dt, txt, "exactly" if hit else "as %r" % en[:60], th[:70] or "(nothing)"))

        n = len(CHECK_LINES) - 1
        print("\n  read verbatim           : %d/%d" % (read, n))
        print("  empty frame stayed empty: %s" % ("yes" if blank_ok else "NO -- it invents lines"))
        print("  seconds per line        : %.1f   (fastest %.1f, slowest %.1f)"
              % (sum(times) / len(times), min(times), max(times)))
        print("  schema honoured         : %s" % vc.schema_honoured)
        ok = read >= n - 1 and blank_ok
        print("\n%s" % ("PASS -- this setup works.  Next:  python -m gamesubs play" if ok else
                        "Something is off. A model that misreads clean rendered text will do worse\n"
                        "on a real game -- try a larger model, or point --base-url at another "
                        "server."))
        return 0 if ok else 1
    finally:
        if proc:
            proc.terminate()


# --------------------------------------------------------------------------- the pipeline

def cmd_tune(a):
    from PIL import Image
    b = _band(a)
    g = ChangeGate(a.bright, a.min_ink, a.change, a.off_ticks)
    print("\nTUNE -- no model, nothing published. Play the game and watch these two numbers.\n"
          "  ink : with a subtitle up vs with none. --min-ink goes between the two.\n"
          "  chg : when the line CHANGES vs while it sits there. --change goes between those.\n"
          "  band.png is the exact crop being read -- open it and check the text is inside it.\n")
    with _sct()() as sct:
        while True:
            rgb = _grab(sct, b.rect)
            state = g.feed(rgb)
            Image.fromarray(rgb).save("band.png")
            print("  ink=%-8d chg=%-7s %s" % (g.ink_n, g.diff_n if g.diff_n >= 0 else "-", state))
            time.sleep(a.interval)


def _or_saved(flag, saved):
    """The flag when it was given, otherwise the saved setting. -> float

    Not `flag or saved`. `--min-hold 0` means "turn the hold off", and `or` reads that
    as "nothing was given" and quietly restores the very setting being switched off.
    """
    return saved if flag is None else flag


LAST = {"line": None, "n": 0}


def _log(secs=None, blank=False, error=None, speaker="", source="", text="",
         tokens=None, repeat=False):
    """One line per SENTENCE, not one per read.

    A menu screen with an animated background wakes the gate several times a second, so
    the same caption was printed 88 times in one run. A console that scrolls that fast is
    a console nobody reads, and the thing worth seeing -- a NEW sentence -- goes past in
    the middle of eighty copies of the old one.
    """
    if error:
        print("  [model] %s" % error)
        return
    if blank:
        print("  [%5.1fs] (no subtitle in that frame)" % secs)
        LAST["line"] = None
        return
    if (speaker, source, text) == LAST["line"]:
        LAST["n"] += 1
        return
    if LAST["n"]:
        print("           (same line read %d more times)" % LAST["n"])
    LAST["line"], LAST["n"] = (speaker, source, text), 0
    print("  [%5.1fs] %s%s\n           -> %s%s%s"
          % (secs, (speaker + ": ") if speaker else "", source[:90], text[:90],
             "   (%s tok)" % tokens if tokens else "",
             "   [kept the first wording]" if repeat else ""))


def _loop(a, base_url, band=None):
    """Watch the band and translate. Shared by `run` and `play`.

    `band` is passed in by `play`, which asks for it up front while the model loads. `run` has
    nothing to overlap with, so it asks here.
    """
    b = band or _band(a)
    tune = server.load_tuning()
    stamp = server.settings_stamp()
    cur = Current(speed=_or_saved(getattr(a, "read_speed", None), tune["read_speed"]),
                  min_hold=_or_saved(getattr(a, "min_hold", None), tune["min_hold"]))
    srv = serve_http(cur, a.port, b.norm(), b.rect)
    print("serving http://127.0.0.1:%d/current   (also /snap /health /band)" % a.port)
    w = Worker(VisionClient(base_url, a.model, a.api_key), cur, a.lang, on_line=_log)
    w.start()
    g = ChangeGate(a.bright, a.min_ink, a.change, a.off_ticks)
    sent = 0
    warned = [False]                     # about a box too small for the line, once per box
    print("watching the band -- Ctrl+Alt+R to draw a new box, Ctrl+C to stop.\n")
    try:
        with _sct()() as sct:
            while True:
                time.sleep(a.interval)
                if _hotkey_redraw() or _take_redraw():
                    from .region import select
                    with _sct()() as s2:
                        virtual = dict(s2.monitors[0])
                        screens = [dict(x) for x in s2.monitors[1:]]
                    print("\n  drawing a new box -- Enter to accept, Esc to keep the old one")
                    got = select(virtual, tuple(b.rect[k] for k in
                                                ("left", "top", "width", "height")), screens)
                    if got:
                        server.save_region(got)
                        b = Band(b.mon, list(got), a.frac, a.wfrac)
                        # The gate remembers what the last frame looked like, and that memory is
                        # about the OLD rectangle. Kept, it would compare the first frame of a new
                        # region against the last frame of a different one and call it unchanged.
                        g = ChangeGate(a.bright, a.min_ink, a.change, a.off_ticks)
                        warned[0] = False
                        srv.shutdown()
                        srv = serve_http(cur, a.port, b.norm(), b.rect)
                        cur.set()
                        print("  new box: %dx%d at (%d,%d)\n"
                              % (b.rect["width"], b.rect["height"], b.rect["left"], b.rect["top"]))
                    else:
                        print("  kept the old box\n")
                    continue
                if server.settings_stamp() != stamp:
                    stamp = server.settings_stamp()
                    tune = server.load_tuning()
                    if a.read_speed is None:
                        cur.speed = tune["read_speed"]
                    if a.min_hold is None:
                        cur.min_hold = tune["min_hold"]
                state = g.feed(_grab(sct, b.rect))
                if state == "gone":
                    if cur.get()["text"]:
                        cur.set()
                        print("  (subtitle gone)")
                elif state == "same":
                    # "same" means the PICTURE in the box has not changed, so the sentence being
                    # translated is still on the screen -- and a translation that disappears while
                    # the line it belongs to is still there is just a missing translation. Seen on
                    # a paused cutscene: the English sat there and the Thai vanished after 15 s.
                    # Kept as an opt-in for anyone whose game leaves bright pixels in the box for
                    # ever; 0 means "as long as the line is there", which is what "gone" is for.
                    if a.max_hold:
                        cur.expire(a.max_hold)
                elif state == "new":
                    SNAP["jpg"] = _jpg(_grab(sct, b.rect), a.max_width, a.quality)
                    sent += 1
                    # THE OLD TRANSLATION IS NOW ABOUT NOTHING. The sentence it was a translation
                    # of has just been replaced, so leaving it up while the model reads the new
                    # one shows Thai that belongs to a line no longer on the screen. It happened
                    # on a paused cutscene: a menu caption from a minute earlier sat over a
                    # completely different sentence.
                    #
                    # `Current` may DEFER this clear -- see the reading-time floor there. That is
                    # not a contradiction of the paragraph above, it is the bound on it: the case
                    # this line was written for was a caption a MINUTE stale, and the floor is a
                    # few seconds. Without it the common case is worse -- the model answers in
                    # about a second, the game has usually moved on by then, and the translation
                    # is cleared a tenth of a second after it appeared. Nobody can read that, and
                    # every part of the system reports success while it happens.
                    if cur.get()["text"]:
                        cur.set()
                    if g.span:
                        # A line touching the edge of the box probably continues past it. This is
                        # the failure a person cannot see: the model is handed half a sentence,
                        # translates that half perfectly, and nothing anywhere reports a problem.
                        # It arrives the first time a game shows TWO lines -- a box drawn around a
                        # one-line subtitle is too short by exactly one line, and RE4R does this
                        # in its very first cutscene.
                        if not warned[0] and (g.span[0] <= 1
                                              or g.span[1] >= b.rect["height"] - 2):
                            warned[0] = True
                            print("  the text reaches the EDGE of your box, so part of it is probably")
                            print("  outside it. Ctrl+Alt+R draws a new one -- make it tall enough for a")
                            print("  TWO-line subtitle, which is when this usually happens.")

                    if w.submit(SNAP["jpg"]):
                        print("  (dropped a waiting frame -- the model is behind the game)")
    except KeyboardInterrupt:
        print("\n%d frames sent | %d answered | %d had no subtitle | %d errors"
              % (sent, w.n, w.blank, w.err))
    finally:
        srv.shutdown()
    return 0


def cmd_run(a):
    return _loop(a, a.base_url or "http://127.0.0.1:8080/v1")


def _wait_for_start(pn):
    """Block until the settings window says Start. False if it was closed instead. -> bool

    The panel is a child process and prints one word down the pipe it already has. Closing the
    window ends the pipe, which is how "they changed their mind" arrives without anyone having to
    design a way to say it.
    """
    for raw in iter(pn.stdout.readline, b""):
        if raw.strip() == b"RUN":
            return True
    return False


def _drain(pn):
    """Keep reading the panel's stdout: it must never block on a full pipe, and after
    Start the only thing it says is that somebody pressed Move box."""
    import threading

    def pump():
        try:
            for raw in iter(pn.stdout.readline, b""):
                if raw.strip() == b"REDRAW":
                    ASKED["redraw"] = True
        except Exception:
            pass
    threading.Thread(target=pump, daemon=True).start()


def _say(pn, text):
    """Put one line on the panel's status bar. Silent if there is no panel or it has gone.

    Everything this reports happens in THIS process, out of sight: the model loading takes most
    of a minute, and a window that says nothing during it is a window that looks broken. Failing
    to deliver a status line must never stop the thing the status is about, hence the bare except.
    """
    print("  %s" % text)
    try:
        # The guard is INSIDE the try. Reaching for `.stdin` on a process that has gone
        # can raise by itself, and a status line that can kill the run it is describing is
        # worse than no status line -- which is what the sentence above promised and what
        # the code did not do until a test asked it.
        if pn is None or pn.stdin is None:
            return
        pn.stdin.write(("STATUS " + text + chr(10)).encode("utf-8"))
        pn.stdin.flush()
    except Exception:
        pass


def cmd_play(a):
    """Model, translator and overlay, from one command.

    ONE WINDOW, NOT THREE DIALOGS. Which model, which font, what it looks like and how long a line
    stays up are all in the settings window, and it opens first with a Start button. It used to
    ask the same two questions in their own dialogs before opening that window as well -- which is
    the same question twice, in two places that can disagree.

    What is NOT in the window is the box, because a rectangle on the game is a gesture, not a
    field: you point at it. So Start opens the selector, and the model begins loading at the same
    moment. Loading takes the better part of a minute and drawing a box takes a few seconds, so
    the wait mostly disappears into something you were doing anyway.

    Then the same window stays open as the live panel: every control in it reaches the subtitle
    while the game runs, and its status bar says which of those stages is happening -- otherwise
    the minute the model spends loading is a minute of a window that looks like it did nothing.
    `--no-panel` skips all of this and asks in the console dialogs instead.
    """
    import subprocess
    proc = ov = pn = None
    try:
        if a.no_panel:
            font = _choose_font(a)
            if not a.base_url:
                m, mp = _choose_model(a)
                proc = server.start(model=m, mmproj=mp, exe=a.llama_server, port=a.server_port)
        else:
            pn = subprocess.Popen([sys.executable, "-u", "-m", "gamesubs", "panel", "--launcher"],
                                  stdout=subprocess.PIPE, stdin=subprocess.PIPE)
            print("the settings window is open -- choose a model, a font and the colours,")
            print("then press Start.")
            if not _wait_for_start(pn):
                print(chr(10) + "the settings window was closed, so nothing was started.")
                return 0
            _drain(pn)
            tune = server.load_tuning()
            font = server.load_font()
            if not a.base_url:
                m, mp = server.resolve_model(tune.get("model") or a.model_file,
                                             server.home("models"))
                _say(pn, "loading %s ..." % os.path.basename(m))
                proc = server.start(model=m, mmproj=mp, exe=a.llama_server, port=a.server_port)

        base = a.base_url or "http://127.0.0.1:%d/v1" % a.server_port
        _say(pn, "drag a box round the game's subtitles, then press Enter")
        band = _band(a)                          # the one thing that is a gesture, not a field
        if proc:
            _say(pn, "the model is loading -- this is the slow part, about a minute")
            server.wait_until_it_can_see(base, a.model, proc=proc)
        _say(pn, "running -- the subtitle appears on your box when the game speaks")
        ov = subprocess.Popen([sys.executable, "-u", "-m", "gamesubs", "overlay",
                               "--port", str(a.port)]
                              + (["--size", str(a.size)] if a.size else [])
                              + ["--text-width", str(a.text_width)]
                              + (["--font", font] if font else [])
                              + (["--in-capture"] if a.in_capture else []))
        print("")
        return _loop(a, base, band)
    finally:
        # All three are children of this process and would otherwise outlive it: a window
        # polling a dead port, a settings panel for nothing, and a model on the GPU.
        for p in (pn, ov, proc):
            if p:
                p.terminate()


def cmd_fonts(a):
    """Write one image with the same words in every usable font, and open it."""
    from .fonts import candidates, sheet
    paths = candidates(server.home("fonts"))
    out = os.path.join(server.app_dir(), "font-comparison.png")
    sheet(paths, a.size, a.sample.split() if a.sample else None, out)
    print("%d fonts can draw those words. Written to:\n  %s\n" % (len(paths), out))
    for p in paths[:40]:
        print("   %s" % os.path.basename(p))
    print("\nOpen that image and look at the marks ABOVE the letters -- a font that cannot stack\n"
          "them draws  ซือ  where it should draw  ซื้อ. Then start with:\n"
          '   python -m gamesubs play --font "<filename>"')
    try:
        os.startfile(out)
    except Exception:
        pass
    return 0


def cmd_panel(a):
    """The settings window on its own, for adjusting without a game running."""
    from .panel import open_panel
    return open_panel(launcher=getattr(a, "launcher", False))


def cmd_overlay(a):
    from .overlay import Overlay
    Overlay("http://127.0.0.1:%d/current" % a.port, font=a.font, size=a.size,
            sample=a.sample, in_capture=a.in_capture, max_width=a.text_width).run()


# --------------------------------------------------------------------------- arguments

def main(argv=None):
    p = argparse.ArgumentParser("gamesubs", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    def screen(q):
        q.add_argument("--region", help="L,T,W,H in screen pixels. Default: bottom of --monitor")
        q.add_argument("--monitor", type=int, default=1)
        q.add_argument("--frac", type=float, default=0.25, help="height of the default band")
        q.add_argument("--wfrac", type=float, default=0.7,
                       help="width of the default band, centred. 1.0 = full width")
        q.add_argument("--bright", type=int, default=185, help="R and G at least this = ink")
        q.add_argument("--min-ink", type=int, default=700, help="fewer ink pixels = no text")
        q.add_argument("--change", type=int, default=30, help="coarse pixels changed = new line")
        q.add_argument("--off-ticks", type=int, default=3, help="empty ticks before clearing")
        q.add_argument("--interval", type=float, default=1 / 12.0,
                       help="seconds between looks. Default 12 fps")
        q.add_argument("--no-select", action="store_true",
                       help="skip the box selector and reuse the last box (it is asked every run)")
        q.add_argument("--pad", type=int, default=14,
                       help="pixels of air added around the box you drew, so a letter at its "
                            "edge is not cut in half. 0 uses the box exactly as drawn")

    def model(q, with_server=True):
        q.add_argument("--base-url", default=None,
                       help="an OpenAI-compatible server you started yourself. Omit it and one "
                            "is started for you")
        q.add_argument("--model", default="local", help="model name your server expects")
        q.add_argument("--lang", default="Thai", help="target language, written as you would say it")
        if with_server:
            q.add_argument("--llama-server", default=None, help="path to llama-server")
            q.add_argument("--server-port", type=int, default=8080)
            q.add_argument("--model-file", default=None,
                           help="filename of the .gguf to use, from the models folder")
            q.add_argument("--no-pick", action="store_true",
                           help="never show the model chooser, even with several models")

    def output(q):
        q.add_argument("--port", type=int, default=8914)
        q.add_argument("--api-key", default=None)
        q.add_argument("--max-width", type=int, default=1280, help="downscale before sending")
        q.add_argument("--quality", type=int, default=88)
        q.add_argument("--max-hold", type=float, default=0.0,
                       help="seconds a line may stay up while the picture behind it is unchanged."
                            " 0 = for as long as the game keeps it there")
        q.add_argument("--min-hold", type=float, default=None,
                       help="the shortest a translation may be on screen, in seconds."
                            " 0 = clear it the moment the game moves on."
                            " Overrides the settings window for this run")
        q.add_argument("--read-speed", type=float, default=None,
                       help="characters read per second: it decides how much longer a long line"
                            " stays up than a short one. Overrides the settings window")

    s = sub.add_parser("setup", help="download llama.cpp and the model (resumable)")
    s.add_argument("--dir", default=None, help="where to put the model")
    s.add_argument("--model-name", default=None,
                   choices=sorted(_catalog()),
                   help="which model to download (%s). Default %s"
                        % ("/".join(sorted(_catalog())), _default_model()))
    s.add_argument("--llama-server", default=None, help="use this llama-server instead")
    s.add_argument("--backend", default="auto", choices=["auto", "cuda", "vulkan", "cpu"],
                   help="auto picks cuda when an NVIDIA card is present, else vulkan")
    s.set_defaults(fn=cmd_setup)

    c = sub.add_parser("check", help="prove the setup works, no game needed")
    model(c)
    c.set_defaults(fn=cmd_check)

    pl = sub.add_parser("play", help="model + translator + overlay, one command")
    screen(pl)
    model(pl)
    output(pl)
    pl.add_argument("--in-capture", action="store_true",
                    help="let screen capture see the overlay, e.g. so OBS records it")
    pl.add_argument("--font", default=None, help="font file or name to draw the subtitles with")
    pl.add_argument("--size", type=int, default=None,
                    help="subtitle text size, overriding the panel for this run"
                         " (default: whatever the panel was left on)")
    pl.add_argument("--text-width", type=int, default=1100,
                    help="how wide a line may get before it wraps onto a second one")
    pl.add_argument("--no-panel", action="store_true",
                    help="do not open the settings window")
    pl.add_argument("--no-pick-font", action="store_true",
                    help="skip the font chooser and reuse the last font (it is asked every run)")
    pl.set_defaults(fn=cmd_play)

    t = sub.add_parser("tune", help="find --min-ink and --change for your game. No model.")
    screen(t)
    t.set_defaults(fn=cmd_tune)

    r = sub.add_parser("run", help="the translator alone, against your own server")
    screen(r)
    model(r, with_server=False)
    output(r)
    r.set_defaults(fn=cmd_run)

    f = sub.add_parser("fonts", help="compare fonts on your own screen and pick one by eye")
    f.add_argument("--sample", default=None, help="the line to draw; defaults to a Thai one")
    f.add_argument("--size", type=int, default=28)
    f.set_defaults(fn=cmd_fonts)

    md = sub.add_parser("models", help="what is installed, and what setup can download")
    md.set_defaults(fn=cmd_models)

    pa = sub.add_parser("panel", help="the settings window alone (sliders, no game)")
    pa.add_argument("--launcher", action="store_true",
                    help="show a Start button and report progress on stdout/stdin"
                         " (what `play` opens)")
    pa.set_defaults(fn=cmd_panel)

    o = sub.add_parser("overlay", help="the on-screen window alone")
    o.add_argument("--port", type=int, default=8914)
    o.add_argument("--font", default=None, help="force a font family")
    o.add_argument("--size", type=int, default=None)
    o.add_argument("--text-width", type=int, default=1100,
                   help="how wide a line may get before it wraps onto a second one")
    o.add_argument("--sample", default="ทดสอบ",
                   help="text used to check the font really has your script's glyphs")
    o.add_argument("--in-capture", action="store_true",
                   help="let screen capture see the overlay, e.g. so OBS records it. Off by "
                        "default: the overlay sits in the strip being watched, so a visible one "
                        "gets read as a new subtitle and translated again")
    o.set_defaults(fn=cmd_overlay)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
