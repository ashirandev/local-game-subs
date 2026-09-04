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

from .capture import Band, ChangeGate
from .service import Current, PROMPT, SCHEMA, SNAP, Worker, serve_http
from .vision import VisionClient


def _sct():
    """mss renamed mss.mss to mss.MSS and deprecated the old spelling. Support both, so the tool
    neither opens with a warning on one version nor fails outright on the other."""
    import mss
    return getattr(mss, "MSS", None) or mss.mss


def _band(a):
    """Which strip of screen to watch, in order: --region, then the box you dragged, then a
    sensible default across the bottom.

    The selector opens by itself the first time, because the alternative is a tool that starts,
    watches the wrong part of the screen, and says nothing about it.
    """
    from . import server
    with _sct()() as sct:
        mons = sct.monitors
        if a.monitor >= len(mons):
            raise SystemExit("monitor %d does not exist (found %d)" % (a.monitor, len(mons) - 1))
        m = dict(mons[a.monitor])
        virtual = dict(mons[0])              # every monitor, so the box can be dragged anywhere

    region = None
    if a.region:
        region = [int(x) for x in a.region.split(",")]
    else:
        saved = server.load_region()
        want = getattr(a, "select", False) or (saved is None and not getattr(a, "no_select", False))
        if want:
            from .region import select
            got = select(virtual, saved)
            if got:
                server.save_region(got)
                region = list(got)
                print("box saved -- it will be used from now on. Change it with --select.")
            elif saved:
                region = list(saved)         # cancelled: keep the one that was already there
        elif saved:
            region = list(saved)

    b = Band(m, region, a.frac, a.wfrac)
    r = b.rect
    print("band: %dx%d at (%d,%d)%s"
          % (r["width"], r["height"], r["left"], r["top"],
             "" if region else "   (default strip -- run with --select to draw your own)"))
    return b


def _grab(sct, rect):
    import numpy as np
    return np.asarray(sct.grab(rect))[:, :, :3][:, :, ::-1]      # BGRA -> RGB


def _choose_model(a):
    """Which weights and projector to load.

    The dropdown appears only when there is a decision to make. With one model in the folder it
    starts straight away -- a dialog whose list has a single entry is just a click to lose.
    """
    from . import server
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
    """Which font to draw with: --font, then the one saved, then the picker, then automatic.

    Like the capture box, the chooser opens by itself the first time and never again, because the
    answer only changes when you want it to.
    """
    from . import server
    if getattr(a, "font", None):
        return a.font
    saved = server.load_font()
    if saved and os.path.isfile(saved) and not getattr(a, "pick_font", False):
        return saved
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

def cmd_setup(a):
    """Everything needed to run, in one command: llama.cpp, then the model."""
    from . import server
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
    server.fetch_model(a.dir)
    _fonts_folder(server)
    print("\neverything is ready.  Next:  python -m gamesubs check")
    return 0


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
    from . import server
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
                d = vc.ask(PROMPT.format(lang=a.lang), image=buf.getvalue(), schema=SCHEMA)
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


def _log(secs=None, blank=False, error=None, speaker="", source="", text="", tokens=None):
    if error:
        print("  [model] %s" % error)
    elif blank:
        print("  [%5.1fs] (no subtitle in that frame)" % secs)
    else:
        print("  [%5.1fs] %s%s\n           -> %s%s"
              % (secs, (speaker + ": ") if speaker else "", source[:90], text[:90],
                 "   (%s tok)" % tokens if tokens else ""))


def _loop(a, base_url):
    """Watch the band and translate. Shared by `run` and `play`."""
    b = _band(a)
    cur = Current()
    srv = serve_http(cur, a.port, b.norm())
    print("serving http://127.0.0.1:%d/current   (also /snap /health /band)" % a.port)
    w = Worker(VisionClient(base_url, a.model, a.api_key), cur, a.lang, on_line=_log)
    w.start()
    g = ChangeGate(a.bright, a.min_ink, a.change, a.off_ticks)
    sent = 0
    print("watching the band -- Ctrl+C to stop.\n")
    try:
        with _sct()() as sct:
            while True:
                time.sleep(a.interval)
                state = g.feed(_grab(sct, b.rect))
                if state == "gone":
                    if cur.get()["text"]:
                        cur.set()
                        print("  (subtitle gone)")
                elif state == "same":
                    cur.expire(a.max_hold)
                elif state == "new":
                    SNAP["jpg"] = _jpg(_grab(sct, b.rect), a.max_width, a.quality)
                    sent += 1
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


def cmd_play(a):
    """Model, translator and overlay, from one command."""
    import subprocess
    from . import server
    proc = ov = None
    try:
        base = a.base_url
        if not base:
            m, mp = _choose_model(a)
            proc = server.start(model=m, mmproj=mp, exe=a.llama_server, port=a.server_port)
            base = "http://127.0.0.1:%d/v1" % a.server_port
            print("waiting for it to answer a question about a picture...")
            server.wait_until_it_can_see(base, a.model, proc=proc)
            print("ready.\n")
        font = _choose_font(a)
        ov = subprocess.Popen([sys.executable, "-u", "-m", "gamesubs", "overlay",
                               "--port", str(a.port)]
                              + (["--font", font] if font else [])
                              + (["--in-capture"] if a.in_capture else []))
        print("overlay opened -- drag it onto the game, then Ctrl+Alt+L to lock it.\n")
        return _loop(a, base)
    finally:
        # Both are children of this process and would otherwise outlive it: a window polling a
        # dead port, and a model sitting on the GPU.
        for p in (ov, proc):
            if p:
                p.terminate()


def cmd_fonts(a):
    """Write one image with the same words in every usable font, and open it."""
    from . import server
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


def cmd_overlay(a):
    from .overlay import Overlay
    Overlay("http://127.0.0.1:%d/current" % a.port, font=a.font, size=a.size,
            sample=a.sample, in_capture=a.in_capture).run()


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
        q.add_argument("--select", action="store_true",
                       help="draw the capture box on screen, replacing the saved one")
        q.add_argument("--no-select", action="store_true",
                       help="never open the box selector; use the saved box or the default strip")

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
        q.add_argument("--max-hold", type=float, default=15.0, help="seconds a line may stay up")

    s = sub.add_parser("setup", help="download llama.cpp and the model (resumable)")
    s.add_argument("--dir", default=None, help="where to put the model")
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
    pl.add_argument("--pick-font", action="store_true",
                    help="open the font chooser, replacing the saved choice")
    pl.add_argument("--no-pick-font", action="store_true",
                    help="never open the font chooser")
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

    o = sub.add_parser("overlay", help="the on-screen window alone")
    o.add_argument("--port", type=int, default=8914)
    o.add_argument("--font", default=None, help="force a font family")
    o.add_argument("--size", type=int, default=28)
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
