# -*- coding: utf-8 -*-
"""Command line: `tune` to find your thresholds, `run` to translate, `overlay` to show the line.

`tune` exists because every threshold in here is per-game and I would otherwise be shipping you
constants measured on my screen. It loads no model and publishes nothing -- it just prints what
the gate is seeing, so you set `--min-ink` and `--change` from numbers you watched on YOUR game.
Run it first on any new game; it takes about a minute.
"""
import argparse
import io
import sys
import time

from .capture import Band, ChangeGate, ink
from .service import Current, SNAP, Worker, serve_http
from .vision import VisionClient


def _sct():
    """mss renamed mss.mss to mss.MSS and deprecated the old spelling. Support both, so
    the tool does not open with a warning on one version or fail outright on the other."""
    import mss
    return getattr(mss, "MSS", None) or mss.mss


def _band(a):
    with _sct()() as sct:
        mons = sct.monitors
        if a.monitor >= len(mons):
            raise SystemExit("monitor %d does not exist (found %d)" % (a.monitor, len(mons) - 1))
        m = dict(mons[a.monitor])
    region = [int(x) for x in a.region.split(",")] if a.region else None
    b = Band(m, region, a.frac, a.wfrac)
    r = b.rect
    print("band: %dx%d at (%d,%d) on monitor %d"
          % (r["width"], r["height"], r["left"], r["top"], a.monitor))
    return b


def _grab(sct, rect):
    import numpy as np
    return np.asarray(sct.grab(rect))[:, :, :3][:, :, ::-1]      # BGRA -> RGB


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


def cmd_run(a):
    from PIL import Image
    b = _band(a)
    cur = Current()
    srv = serve_http(cur, a.port, b.norm())
    print("serving http://127.0.0.1:%d/current   (also /snap /health /band)" % a.port)
    print("overlay:  python -m gamesubs overlay --port %d\n" % a.port)

    def log(secs=None, blank=False, error=None, speaker="", source="", text="", tokens=None):
        if error:
            print("  [model] %s" % error)
        elif blank:
            print("  [%5.1fs] (no subtitle in that frame)" % secs)
        else:
            print("  [%5.1fs] %s%s\n           -> %s%s"
                  % (secs, (speaker + ": ") if speaker else "", source[:90], text[:90],
                     "   (%s tok)" % tokens if tokens else ""))

    client = VisionClient(a.base_url, a.model, a.api_key)
    w = Worker(client, cur, a.lang, on_line=log)
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
                    im = Image.fromarray(_grab(sct, b.rect))
                    if im.width > a.max_width:
                        im = im.resize((a.max_width, int(im.height * a.max_width / im.width)),
                                       Image.LANCZOS)
                    buf = io.BytesIO()
                    im.save(buf, "JPEG", quality=a.quality)
                    SNAP["jpg"] = buf.getvalue()
                    sent += 1
                    if w.submit(SNAP["jpg"]):
                        print("  (dropped a waiting frame -- the model is behind the game)")
    except KeyboardInterrupt:
        print("\n%d frames sent | %d answered | %d had no subtitle | %d errors"
              % (sent, w.n, w.blank, w.err))
    finally:
        srv.shutdown()


def cmd_overlay(a):
    from .overlay import Overlay
    Overlay("http://127.0.0.1:%d/current" % a.port, font=a.font, size=a.size,
            sample=a.sample).run()


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

    t = sub.add_parser("tune", help="find --min-ink and --change for your game. No model.")
    screen(t)
    t.set_defaults(fn=cmd_tune)

    r = sub.add_parser("run", help="translate the band and publish /current")
    screen(r)
    r.add_argument("--base-url", default="http://127.0.0.1:8080/v1",
                   help="any OpenAI-compatible server (llama.cpp, LM Studio, Ollama, vLLM)")
    r.add_argument("--model", default="local", help="model name your server expects")
    r.add_argument("--api-key", default=None)
    r.add_argument("--lang", default="Thai", help="target language, written as you'd say it")
    r.add_argument("--port", type=int, default=8914)
    r.add_argument("--max-width", type=int, default=1280, help="downscale the band before sending")
    r.add_argument("--quality", type=int, default=88)
    r.add_argument("--max-hold", type=float, default=15.0, help="seconds a line may stay up")
    r.set_defaults(fn=cmd_run)

    o = sub.add_parser("overlay", help="the on-screen window")
    o.add_argument("--port", type=int, default=8914)
    o.add_argument("--font", default=None, help="force a font family")
    o.add_argument("--size", type=int, default=28)
    o.add_argument("--sample", default="ทดสอบ",
                   help="text used to check the font really has your script's glyphs")
    o.set_defaults(fn=cmd_overlay)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
