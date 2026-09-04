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

WHERE THE LINE GOES IS NOT A CONSTANT. It depends on where the game draws its own subtitle in
that scene, and nothing outside the game can know that. Drag-then-lock deletes the question
instead of answering it wrongly for every game at once.

THREE THINGS THAT LOOK LIKE BUGS AND ARE NOT:
  * empty text means HIDE, not "draw an empty box"
  * a literal newline in the text is the GAME's own line break -- honour it as a hard break; a
    renderer that assumes one paragraph either prints the escape or welds two sentences together
  * the block is measured and laid out bottom-up, never at a fixed y, because most lines are
    short and the long one that wraps is the minority that breaks a fixed layout

FONTS FAIL SILENTLY. A font without glyphs for your language does not refuse to render; it
substitutes, and the result looks fine in a screenshot and wrong to a reader. `has_glyphs()`
below measures a string in the candidate font and in a font known to lack the script: equal
widths mean both are drawing the same fallback, so the candidate is not really being used.
"""
import json
import os
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
import urllib.request

POLL_MS = 150
KEY = "#0b0c0d"        # chroma key: these pixels vanish entirely (Windows)
PLATE = "#000000"      # the subtitle backing. Must stay clear of KEY -- a plate that drifts to
                       # the key colour becomes invisible, which looks like the subtitle broke.
STATE = os.path.join(os.path.expanduser("~"), ".local-game-subs-pos.json")
IS_WIN = sys.platform == "win32"

# Ordered by preference. The first one present AND carrying the script's glyphs wins.
FONT_CANDIDATES = ["Noto Sans Thai", "Leelawadee UI", "Tahoma", "Noto Sans", "Segoe UI", "Arial"]
NO_GLYPH_PROBE = "Wingdings"       # a font that has no Thai and no Latin text shaping to speak of


def has_glyphs(root, family, sample):
    """True when `family` is really drawing `sample` rather than silently substituting."""
    try:
        a = tkfont.Font(root=root, family=family, size=24).measure(sample)
        b = tkfont.Font(root=root, family=NO_GLYPH_PROBE, size=24).measure(sample)
    except tk.TclError:
        return False
    return a != b and a > 0


def pick_font(root, sample, preferred=None):
    fams = set(tkfont.families(root))
    for f in ([preferred] if preferred else []) + FONT_CANDIDATES:
        if f and f in fams and has_glyphs(root, f, sample):
            return f
    return "TkDefaultFont"


class Overlay:
    def __init__(self, url, font=None, size=28, sample="ทดสอบ"):
        self.url = url
        self.line = {"speaker": "", "text": ""}
        self.locked = False
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        if IS_WIN:
            self.root.attributes("-transparentcolor", KEY)
        self.root.configure(bg=KEY)

        fam = pick_font(self.root, sample, font)
        self.font = tkfont.Font(root=self.root, family=fam, size=size, weight="bold")
        self.small = tkfont.Font(root=self.root, family=fam, size=max(10, int(size * 0.55)))
        print("font: %s" % fam)

        self.frame = tk.Frame(self.root, bg=KEY)
        self.frame.pack()
        self.spk = tk.Label(self.frame, text="", font=self.small, fg="#cfd3d8", bg=PLATE,
                            padx=10, pady=2)
        self.txt = tk.Label(self.frame, text="", font=self.font, fg="#ffffff", bg=PLATE,
                            padx=14, pady=6, justify="center", wraplength=1100)

        x, y = self._load_pos()
        self.root.geometry("+%d+%d" % (x, y))
        for w in (self.root, self.frame, self.spk, self.txt):
            w.bind("<Button-1>", self._grab)
            w.bind("<B1-Motion>", self._drag)

        threading.Thread(target=self._poll, daemon=True).start()
        self.root.after(80, self._hotkeys)
        self.root.after(POLL_MS, self._render)

    # ---------------------------------------------------------------- position
    def _load_pos(self):
        try:
            d = json.load(open(STATE, encoding="utf-8"))
            return int(d["x"]), int(d["y"])
        except Exception:
            return self.root.winfo_screenwidth() // 2 - 400, \
                   int(self.root.winfo_screenheight() * 0.78)

    def _save_pos(self):
        try:
            json.dump({"x": self.root.winfo_x(), "y": self.root.winfo_y()},
                      open(STATE, "w", encoding="utf-8"))
        except Exception:
            pass

    def _grab(self, e):
        self._off = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag(self, e):
        if not self.locked:
            self.root.geometry("+%d+%d" % (e.x_root - self._off[0], e.y_root - self._off[1]))

    # ---------------------------------------------------------------- locking
    def _click_through(self, on):
        if not IS_WIN:
            return                       # everything else still works; only pass-through is lost
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
            if down(0x11) and down(0x12):                       # Ctrl+Alt
                if down(0x4C) and not getattr(self, "_l", False):    # L
                    self.locked = not self.locked
                    self._click_through(self.locked)
                    self._save_pos()
                    print("locked" if self.locked else "unlocked -- drag it, Ctrl+Alt+L to lock")
                    self._l = True
                elif down(0x51):                                     # Q
                    self._save_pos()
                    self.root.destroy()
                    return
                elif not down(0x4C):
                    self._l = False
        self.root.after(80, self._hotkeys)

    # ---------------------------------------------------------------- data
    def _poll(self):
        while True:
            try:
                req = urllib.request.Request(self.url, headers={"Cache-Control": "no-store"})
                with urllib.request.urlopen(req, timeout=4) as r:
                    d = json.loads(r.read().decode("utf-8", "replace"))
                self.line = {"speaker": (d.get("speaker") or "").strip(),
                             "text": (d.get("text") or "").strip()}
            except Exception:
                pass                     # a service restart must not take the window with it
            threading.Event().wait(POLL_MS / 1000.0)

    def _render(self):
        spk, txt = self.line["speaker"], self.line["text"]
        if not txt and self.locked:
            self.spk.pack_forget()
            self.txt.pack_forget()
        else:
            # `\\n` twice on purpose: json.loads turns the escape into a real newline, but a
            # service that double-escaped it sends the two characters through literally.
            shown = (txt or "— drag me, then Ctrl+Alt+L —").replace("\\n", "\n")
            self.txt.configure(text=shown)
            if spk:
                self.spk.configure(text=spk)
                self.spk.pack(fill="x")
            else:
                self.spk.pack_forget()
            self.txt.pack()
        self.root.after(POLL_MS, self._render)

    def run(self):
        print("Ctrl+Alt+L lock/unlock   Ctrl+Alt+Q quit")
        self.root.mainloop()
