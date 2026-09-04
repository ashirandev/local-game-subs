# -*- coding: utf-8 -*-
"""A borderless always-on-top subtitle window that polls `/current`.

Shaped like a speedrun timer, for the same reason those are shaped that way: it sits on top of a
game, you drag it where you want it once, and then it must stop being a window.

THE CONTROL SCHEME FOLLOWS FROM ONE FACT. A locked window is click-through -- that is the entire
point of locking it -- so the unlock control CANNOT be on the window. If it were, the first lock
would be permanent. Hence global hotkeys, and hence no close button either:

    Ctrl+Alt+L   lock <-> unlock
    Ctrl+Alt+Q   quit (saves position)

And while UNLOCKED it stays visible with a placeholder even when there is no subtitle, because
you cannot drag something that is not on screen.

THE TEXT IS DRAWN INTO AN IMAGE, NOT LAID OUT BY THE TOOLKIT -- see render.py. tkinter does not do
complex text layout, and on Thai that is not a rough edge, it is unreadable: a live frame showed
`เข้า E-Store เพื่อ` drawn as `เขา È-Store เพอ`, with a tone mark that had come off its own
consonant and landed on the E of E-Store. The console showed the same line correctly, which is
what proved the model and the transport were fine and only the drawing was wrong.

That also lets you use a font FILE rather than only a font the system has installed, which is what
makes the fonts folder work.

TWO THINGS THAT LOOK LIKE BUGS AND ARE NOT:
  * empty text means HIDE, not "draw an empty box"
  * a literal newline in the text is the GAME's own line break, honoured as a hard break
"""
import json
import os
import sys
import threading
import tkinter as tk
import urllib.request

from PIL import ImageTk

from . import render
from .server import app_dir, home

POLL_MS = 150
# How long the service may be unreachable before this window gives up and closes itself.
# Long enough to sit through a restart, short enough that a stranded overlay is not permanent.
ORPHAN_S = 40.0
KEY = "#0b0c0d"        # chroma key: these pixels vanish entirely (Windows)
STATE = os.path.join(app_dir(), "overlay-position.json")
IS_WIN = sys.platform == "win32"
SAMPLE = "เข้า E-Store เพื่อซื้อ"


class Overlay:
    def __init__(self, url, font=None, size=28, sample=SAMPLE, in_capture=False, max_width=1100):
        self.url = url
        self.in_capture = in_capture
        self.size = size
        self.max_width = max_width
        self.line = {"speaker": "", "text": ""}
        self.locked = False
        self._img = None
        self._shown = None

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        if IS_WIN:
            self.root.attributes("-transparentcolor", KEY)
        self.root.configure(bg=KEY)

        path = render.resolve_font(font, sample, home("fonts"))
        if not path:
            raise SystemExit(
                "no font on this machine can draw %r.\n"
                "Drop a .ttf or .otf that covers your language into:\n  %s"
                % (sample, home("fonts")))
        self.font = render.load(path, size)
        self.small = render.load(path, max(11, int(size * 0.55)))
        print("font: %s" % os.path.basename(path))

        self.label = tk.Label(self.root, bg=KEY, bd=0, highlightthickness=0)
        self.label.pack()

        x, y = self._load_pos()
        self.root.geometry("+%d+%d" % (x, y))
        for w in (self.root, self.label):
            w.bind("<Button-1>", self._grab)
            w.bind("<B1-Motion>", self._drag)

        threading.Thread(target=self._poll, daemon=True).start()
        self.root.after(80, self._hotkeys)
        self.root.after(POLL_MS, self._render)
        # After the window exists: it has no handle to set this on before then.
        self.root.after(50, lambda: self._hide_from_capture(not self.in_capture))

    # ---------------------------------------------------------------- position
    def _load_pos(self):
        try:
            with open(STATE, encoding="utf-8") as f:
                d = json.load(f)
            return int(d["x"]), int(d["y"])
        except Exception:
            return (self.root.winfo_screenwidth() // 2 - 400,
                    int(self.root.winfo_screenheight() * 0.78))

    def _save_pos(self):
        try:
            with open(STATE, "w", encoding="utf-8") as f:
                json.dump({"x": self.root.winfo_x(), "y": self.root.winfo_y()}, f)
        except Exception:
            pass

    def _grab(self, e):
        self._off = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag(self, e):
        if not self.locked:
            self.root.geometry("+%d+%d" % (e.x_root - self._off[0], e.y_root - self._off[1]))

    # ---------------------------------------------------------------- locking
    def _hide_from_capture(self, on=True):
        """Make this window invisible to screen capture while staying visible on the monitor.

        Without it the tool reads its own output. The overlay is always-on-top and belongs at the
        bottom centre of the screen -- which is exactly the strip being watched -- so the
        translated line lands inside the next frame, gets read as a new subtitle, and gets
        translated again. Seen in the very first end-to-end run.

        Also hides it from OBS, so a streamer who wants the subtitle in the broadcast passes
        --in-capture and keeps the overlay outside the watched band.
        """
        if not IS_WIN:
            return False
        import ctypes
        WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x00, 0x11
        u = ctypes.windll.user32
        hwnd = u.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        ok = bool(u.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE if on else WDA_NONE))
        if on and not ok:
            print("could not hide the overlay from screen capture (needs Windows 10 2004 or\n"
                  "newer). Drag the overlay ABOVE the watched strip, or it will read its own\n"
                  "output and translate it again.")
        return ok

    def _click_through(self, on):
        if not IS_WIN:
            return                       # everything else works; only pass-through is lost
        import ctypes
        GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT = -20, 0x00080000, 0x00000020
        u = ctypes.windll.user32
        hwnd = u.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style = (style | WS_EX_TRANSPARENT | WS_EX_LAYERED) if on \
            else (style & ~WS_EX_TRANSPARENT)
        u.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

    def _hotkeys(self):
        """Polled rather than registered: a dozen lines instead of a message pump, and the cost
        is one GetAsyncKeyState per key every 80 ms."""
        if IS_WIN:
            import ctypes
            g = ctypes.windll.user32.GetAsyncKeyState
            down = lambda k: g(k) & 0x8000
            if down(0x11) and down(0x12):                        # Ctrl+Alt
                if down(0x4C) and not getattr(self, "_l", False):     # L
                    self.locked = not self.locked
                    self._click_through(self.locked)
                    self._save_pos()
                    print("locked" if self.locked else "unlocked -- drag it, Ctrl+Alt+L to lock")
                    self._l = True
                elif down(0x51):                                      # Q
                    self._save_pos()
                    self.root.destroy()
                    return
                elif not down(0x4C):
                    self._l = False
        self.root.after(80, self._hotkeys)

    # ---------------------------------------------------------------- data
    def _poll(self):
        """Read /current forever, and close the window if the service is gone for good.

        A short outage is a restart and must not take the window with it. A long one means the
        thing that opened this window is not coming back -- and an overlay that outlives its
        service is a piece of text stuck on top of everything with no visible way to remove it.
        That happened: cancelling out of setup left "drag me, then Ctrl+Alt+L" on the screen.
        """
        gone = 0.0
        while True:
            try:
                req = urllib.request.Request(self.url, headers={"Cache-Control": "no-store"})
                with urllib.request.urlopen(req, timeout=4) as r:
                    d = json.loads(r.read().decode("utf-8", "replace"))
                self.line = {"speaker": (d.get("speaker") or "").strip(),
                             "text": (d.get("text") or "").strip()}
                gone = 0.0
            except Exception:
                gone += POLL_MS / 1000.0
                if gone > ORPHAN_S:
                    print("the translator is gone -- closing the overlay.")
                    try:
                        self.root.after(0, self.root.destroy)
                    except Exception:
                        pass
                    return
            threading.Event().wait(POLL_MS / 1000.0)

    def _render(self):
        spk, txt = self.line["speaker"], self.line["text"]
        if not txt and not self.locked:
            spk, txt = "", "— drag me · Ctrl+Alt+L to lock · Ctrl+Alt+Q to quit —"
        key = (spk, txt)
        if key != self._shown:
            self._shown = key
            im = render.draw_line(txt, spk, self.font, self.small, self.max_width)
            if im is None:
                self.label.pack_forget()
            else:
                # Composited against the chroma key rather than left transparent: the key colour
                # is what the window manager punches out, and an RGBA image handed to Tk keeps
                # its alpha against whatever is behind the label instead.
                from PIL import Image
                flat = Image.new("RGB", im.size, KEY)
                flat.paste(im, (0, 0), im)
                self._img = ImageTk.PhotoImage(flat)
                self.label.configure(image=self._img)
                self.label.pack()
        self.root.after(POLL_MS, self._render)

    def run(self):
        print("Ctrl+Alt+L lock/unlock   Ctrl+Alt+Q quit")
        self.root.mainloop()
