# -*- coding: utf-8 -*-
"""A borderless always-on-top subtitle window that polls `/current`.

IT HAS NO CONTROLS, AND THAT IS THE FEATURE. It opens on the box that was just dragged, it is
click-through from the first frame, and it is on screen only while the game is saying something.
There is nothing to aim, nothing to lock, and nothing to dismiss.

It was not always like that. It used to open at a hardcoded centre-screen 78%, so you dragged a
box around the subtitle and then dragged a SECOND window to the same place by hand -- which is
why it had a lock (a window you have to drag cannot be click-through) and why it sat there
showing "drag me, Ctrl+Alt+L to lock" over the picture even with nothing to translate (you cannot
drag what is not on screen). Every one of those existed to support the drag. The box removed the
drag, and all of it went with it. The report that got it removed was one word: "มันงง".

The hotkeys that remain are the ones with nowhere else to live, on a window that has no border to
put a button on:

    Ctrl+Alt+Q   close it
    Ctrl+Alt+L   unlock, if you want to drag it somewhere other than the box

🔑 The general shape: a control that exists to serve a step is not a feature, it is a cost of that
step, and it has to be removed WITH the step. Left behind it looks deliberate, so nobody deletes
it -- they write documentation for it instead.

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
from .server import app_dir, home, load_font, load_tuning, settings_stamp

POLL_MS = 150
# How long the service may be unreachable before this window gives up and closes itself.
# Long enough to sit through a restart, short enough that a stranded overlay is not permanent.
ORPHAN_S = 40.0
KEY = "#0b0c0d"        # chroma key: these pixels vanish entirely (Windows)
STATE = os.path.join(app_dir(), "overlay-position.json")
IS_WIN = sys.platform == "win32"
# The font test text follows the OUTPUT language, because that is the language the
# font has to be able to draw. It used to be this string whatever you asked for.
SAMPLE = render.sample_for(load_tuning().get("lang"))


class Overlay:
    def __init__(self, url, font=None, size=None, sample=SAMPLE, in_capture=False, max_width=1100):
        self.url = url
        self.in_capture = in_capture
        self.size = size
        self.max_width = max_width
        self.line = {"speaker": "", "text": ""}
        # LOCKED FROM THE START, AND INVISIBLE UNTIL THERE IS SOMETHING TO SAY.
        #
        # Both were off, and both for the same reason: you had to drag this window onto the
        # game yourself. You do not any more -- it opens on the box -- so all that was left
        # of it was a black plate sitting on the picture reading "drag me, Ctrl+Alt+L to
        # lock", plus a keystroke to remember every single run. The report was one word:
        # "มันงง".
        #
        # A subtitle overlay has nothing to show when nobody is speaking, so it shows
        # nothing. Ctrl+Alt+L is still there for anyone who wants to drag it somewhere else;
        # it is no longer something you have to know about to use the tool.
        self.locked = True
        self._img = None
        self._shown = None
        self._moved = False

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
        saved = load_tuning()
        self.font_path = path
        self._stamp = settings_stamp()
        self.colours = (saved["text_colour"], saved["plate_colour"])
        self._set_size(saved["size"] if size is None else size)
        print("font: %s" % os.path.basename(path))

        self.label = tk.Label(self.root, bg=KEY, bd=0, highlightthickness=0)
        self.label.pack()

        # Asked once, before the first placement and before the first draw: both need it, and the
        # service already knows it.
        self.box = self._watched_box()
        x, y = self._load_pos()
        self.root.geometry("+%d+%d" % (x, y))
        for w in (self.root, self.label):
            w.bind("<Button-1>", self._grab)
            w.bind("<B1-Motion>", self._drag)

        threading.Thread(target=self._poll, daemon=True).start()
        self.root.after(80, self._hotkeys)
        self.root.after(POLL_MS, self._render)
        # Both of these need a window handle, which does not exist until after __init__.
        self.root.after(50, lambda: self._hide_from_capture(not self.in_capture))
        self.root.after(60, lambda: self._click_through(True))

    # ---------------------------------------------------------------- position
    def _watched_box(self):
        """The region being read, in absolute screen pixels. -> dict or None

        Asked of the service rather than guessed. The box is the one thing that says where the
        game's own subtitle is -- the user drew it around exactly that -- so it is also the answer
        to where the translation belongs and how wide the plate has to be to hide the original.
        """
        try:
            url = self.url.rsplit("/", 1)[0] + "/band"
            with urllib.request.urlopen(url, timeout=3) as r:
                return (json.loads(r.read().decode("utf-8")) or {}).get("rect")
        except Exception:                                    # noqa: BLE001
            return None                                      # no box is not a reason to not start

    def _load_pos(self):
        """Where to put the window. -> (x, y)

        THE BOX WINS. It is the rectangle someone dragged around their game's subtitles in this
        very run, and it is what is being read and what is being covered -- so a window anywhere
        else is a plate that does not cover the thing it was drawn for. A position saved on a
        different day, for a different game, at a different resolution, is exactly that: on
        2026-09-09 a stale one put the plate a third of the way to the left of a two-line
        subtitle, hiding half of it.

        The saved position is the fallback for a run with no box at all.
        """
        box = self.box
        if box:
            return int(box["left"]), int(box["top"])
        try:
            with open(STATE, encoding="utf-8") as f:
                d = json.load(f)
            return int(d["x"]), int(d["y"])
        except Exception:
            pass
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
            self._moved = True         # from here on this window is where they put it, not where
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
        That happened: cancelling out of setup left a subtitle plate on the screen with
        no visible way to remove it.
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

    def _wrap_width(self):
        """How wide a line may get before it wraps. -> px

        The box, when there is one. It is the width someone chose for their own game, so lines
        break in the same place every time and the plate can never end up wider than the region
        it is covering. `--text-width` is the fallback for a run with no box.
        """
        w = (self.box or {}).get("width", 0)
        return max(200, int(w)) if w else self.max_width

    def _place(self, size):
        """Centre the plate in the box. Does nothing once the window has been dragged by hand.

        Called on every new line because the plate is a different size for every line -- that is
        the point of it fitting the text. Anchoring it by its top-left instead would make a short
        line and a long one start at the same x, which is the one thing that actually looks
        unstable on screen.
        """
        box = self.box
        if not box or self._moved:
            return
        w, h = size
        self.root.geometry("+%d+%d" % (int(box["left"]) + (int(box["width"]) - w) // 2,
                                       int(box["top"]) + (int(box["height"]) - h) // 2))

    def _set_size(self, size):
        """Point the renderer at a new text size. The small face is the speaker label."""
        self.size = int(size)
        self.font = render.load(self.font_path, self.size)
        self.small = render.load(self.font_path, max(11, int(self.size * 0.55)))

    def _retune(self):
        """Pick up anything the settings window changed. True if something moved. -> bool

        Polled rather than pushed. The panel is a separate process that may not be running,
        and an overlay that needs something to tell it what to look like is an overlay that
        looks wrong whenever that something is absent.

        The stamp is checked first because this runs several times a second and reading a
        JSON file that many times, for ever, to learn nothing is not free.
        """
        stamp = settings_stamp()
        if stamp == self._stamp:
            return False
        self._stamp = stamp
        d = load_tuning()
        moved = False
        want = (d["text_colour"], d["plate_colour"])
        if want != self.colours:
            self.colours = want
            moved = True
        path = render.resolve_font(load_font(),
                                   render.sample_for(d.get("lang")), home("fonts"))
        if path and path != self.font_path:
            # A font that cannot draw the language is worse than the wrong font: nothing
            # appears at all. resolve_font has already refused it, so keep what works.
            self.font_path = path
            self._set_size(d["size"])
            return True
        if d["size"] != self.size:
            self._set_size(d["size"])
            moved = True
        return moved

    def _render(self):
        spk, txt = self.line["speaker"], self.line["text"]
        if self._retune():
            # Forget what is on screen. Without this the cache says "same line, already drawn"
            # and a new size never reaches the screen until the game says something else.
            self._shown = None
        key = (spk, txt)
        if key != self._shown:
            self._shown = key
            im = render.draw_line(txt, spk, self.font, self.small, self._wrap_width(),
                                  *self.colours)
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
                self._place(im.size)
        self.root.after(POLL_MS, self._render)

    def run(self):
        print("the subtitle appears on your box when the game says something, and there is\n"
              "nothing on screen when it does not. Clicks go straight through to the game.\n"
              "  Ctrl+Alt+Q  close it         Ctrl+Alt+R  draw a new box\n"
              "  Ctrl+Alt+L  only if you want to drag this window somewhere else")
        self.root.mainloop()
