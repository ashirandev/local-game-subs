# -*- coding: utf-8 -*-
"""The pipeline: watch the band, read it when it changes, publish the line on localhost.

    capture -> change gate -> one vision call -> GET /current

The overlay is a separate process that polls `/current`. Splitting them is not architecture for
its own sake: the reader and the writer have completely different failure modes, and when the
subtitle stops appearing you want to know which half stopped. With two processes you just open
`/current` in a browser and the answer is right there.

LATEST-ONLY, NEVER A QUEUE. A vision call takes seconds; a subtitle is worthless late. If a new
line appears while one is being read, the waiting frame is DROPPED, not queued. A queue here
drifts further behind the game with every line, and it presents as the model getting slower --
which sends you looking in exactly the wrong place.

THE HOLD TIMER LIVES HERE, NOT IN THE OVERLAY. Whoever owns the text owns how long it stays up.
Two components each running their own dwell timer on the same line are two clocks that will
disagree, and the disagreement looks like flicker.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCHEMA = {
    "type": "object",
    "properties": {"speaker": {"type": "string"},
                   "en": {"type": "string"},
                   "th": {"type": "string"}},
    "required": ["speaker", "en", "th"],
}

PROMPT = (
    "This image is a strip from the bottom of a video game screen. It may or may not contain a "
    "subtitle.\n"
    "1. If you see subtitle or dialogue text, copy it EXACTLY into `en`.\n"
    "2. Translate that line into natural spoken {lang} and put it in `th`. Translate the meaning, "
    "not word by word. Keep it short, the way a subtitle is short.\n"
    "3. If a character name is shown above or beside the line, put it in `speaker`. Otherwise "
    "leave `speaker` empty.\n"
    "4. If there is NO subtitle text -- only gameplay, HUD, a menu, numbers or a health bar -- "
    "return all three fields empty. An empty answer is a correct answer here, and it will happen "
    "often.\n"
    "Never invent a line. Never describe the picture. Only what is written on it."
)


class Current:
    """What `/current` says right now. One lock: the HTTP threads read it while the worker writes."""

    def __init__(self):
        self._lk = threading.Lock()
        self._d = {"speaker": "", "source": "", "text": ""}
        self.at = 0.0

    def set(self, speaker="", source="", text=""):
        with self._lk:
            self._d = {"speaker": speaker, "source": source, "text": text}
            self.at = time.time()

    def get(self):
        with self._lk:
            return dict(self._d)

    def expire(self, ttl):
        """Clear a line that has been up too long. True if this call cleared one."""
        with self._lk:
            if self._d["text"] and time.time() - self.at > ttl:
                self._d = {"speaker": "", "source": "", "text": ""}
                return True
        return False


class Worker(threading.Thread):
    """Reads the newest frame and nothing else. See LATEST-ONLY at the top of this file."""

    def __init__(self, client, current, lang="Thai", on_line=None):
        super().__init__(daemon=True)
        self.client, self.cur, self.lang = client, current, lang
        self.on_line = on_line or (lambda **kw: None)
        self.job = None
        self.ev = threading.Event()
        self.lk = threading.Lock()
        self.n = self.blank = self.err = 0

    def submit(self, jpg):
        """Hand over a frame. Returns True if this REPLACED one that was still waiting."""
        with self.lk:
            dropped = self.job is not None
            self.job = jpg
        self.ev.set()
        return dropped

    def run(self):
        while True:
            self.ev.wait()
            self.ev.clear()
            with self.lk:
                jpg, self.job = self.job, None
            if jpg is None:
                continue
            t0 = time.time()
            try:
                d = self.client.ask(PROMPT.format(lang=self.lang), image=jpg, schema=SCHEMA)
            except Exception as e:
                self.err += 1
                # Keep going. One unreadable frame is ordinary; a dead loop is not.
                self.on_line(error="%s: %s" % (type(e).__name__, str(e).split("\n")[0][:120]))
                continue
            dt = time.time() - t0
            spk = (d.get("speaker") or "").strip()
            en = (d.get("en") or "").strip()
            th = (d.get("th") or "").strip()
            # A failed read often comes back as the speaker's name in the translation field. It is
            # a name, not a line, and showing it looks like a hallucination to whoever is watching.
            if th and spk and th.strip().lower() == spk.strip().lower():
                th = ""
            self.n += 1
            if not th:
                self.blank += 1
                self.cur.set()
                self.on_line(secs=dt, blank=True)
                continue
            self.cur.set(spk, en, th)
            self.on_line(secs=dt, speaker=spk, source=en, text=th,
                         tokens=(self.client.last_usage or {}).get("total_tokens"))


def serve_http(current, port, band_norm=None):
    """Publish `/current` (and a little else) on localhost. Returns the server; call .shutdown()."""

    class H(BaseHTTPRequestHandler):
        def _send(self, body, ctype="application/json; charset=utf-8"):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            # The overlay polls several times a second. A cached /current freezes the subtitle on
            # screen while the log keeps scrolling, which reads as "the overlay broke".
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            p = self.path.split("?")[0]
            if p == "/current":
                self._send(json.dumps(current.get(), ensure_ascii=False).encode("utf-8"))
            elif p == "/band":
                self._send(json.dumps({"band": band_norm}).encode("utf-8"))
            elif p == "/snap":
                self._send(SNAP["jpg"], "image/jpeg")
            elif p == "/health":
                self._send(json.dumps({"ok": True, "showing": bool(current.get()["text"]),
                                       "band": band_norm}).encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *a):
            pass          # the overlay polls ~7x/s; one log line each would drown the console

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


SNAP = {"jpg": b""}       # the last band handed to the model, served at /snap to check the region
