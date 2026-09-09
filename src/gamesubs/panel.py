# -*- coding: utf-8 -*-
"""A window with sliders, because nobody remembers `--min-hold 2.0`.

Every setting in here was already adjustable from the command line, and that is exactly the
problem: a flag you have to look up is a setting most people will never touch, so they live with
the default or stop using the tool. The report was one sentence -- nobody remembers commands,
make it buttons -- and it is right. The flags still work; they are overrides now, and this is the
front door.

IT CHANGES THINGS WHILE THE GAME IS RUNNING. A subtitle setting cannot be judged in the abstract:
you find out whether a line stays up long enough, or whether yellow reads better than white, by
watching one. So the panel writes `settings.json`, and the two processes that care -- the overlay
and the translator loop -- notice the file changed and pick the new value up on their next tick.
No new port, no new protocol, and if the panel is closed or was never opened, nothing else
behaves differently.

THE MODEL IS THE ONE THING THAT CANNOT CHANGE LIVE, and the row says so rather than pretending.
Swapping it means several gigabytes off and back onto the GPU, which is a restart however it is
dressed up. Choosing one here decides what the NEXT run loads.

THE PREVIEW IS THE REAL RENDERER, not a Tk label. Tk cannot place Thai tone marks (that is the
whole reason `shape.py` exists), so a preview drawn with a Tk font would show the marks in the
wrong place while the actual subtitle was correct -- a preview that lies about the one thing it
is there to show. It calls `render.draw_line`, the same function the overlay calls.
"""
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from . import render, server
from .fonts import candidates
from .server import (CHOICES, LIMITS, PLATE_SWATCHES, TEXT_SWATCHES, TUNING, home, list_models,
                     load_font, load_tuning, save_font, save_tuning)
from .service import read_seconds

# What the preview shows. The Thai line is the one this tool was built and measured
# on; for any other language there is nothing true to show, so it shows that
# language's font-test text rather than a sentence that would be a lie.
THAI_SAMPLE = "และคืนนั้นเอง แรคคูนซิตี้ก็ถูกล้างจนไม่เหลืออะไร"
SPEAKER = "Leon"
PREVIEW_W = 430
BG = "#1b1b1b"
CARD = "#232323"
FG = "#e8e8e8"
DIM = "#9a9a9a"
TROUGH = "#333333"
ACCENT = "#7cc4ff"

# key, label, how the number reads, how far one nudge moves it, what it does
ROWS = [
    ("size", "Text size", "%.0f", 1, "bigger letters on the same box"),
    ("min_hold", "Stay up at least", "%.1f s", 0.1, "the shortest a line may flash past"),
    ("read_speed", "Reading speed", "%.0f chars/s", 1, "higher clears lines sooner"),
]


class Panel:

    def __init__(self, launcher=False):
        self.launcher = launcher
        self.started = False
        self.tune = load_tuning()
        self.lang = self.tune["lang"]
        self.fonts = candidates(home("fonts"), render.sample_for(self.lang)) or []
        self.font_path = load_font() or render.resolve_font(
            None, render.sample_for(self.lang), home("fonts"))
        self._img = None
        self._pending = None
        self.boxes = {}

        self.root = tk.Tk()
        self.root.title("Subtitle settings")
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)

        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("P.TCombobox", fieldbackground=CARD, background=CARD, foreground=FG,
                     arrowcolor=FG, bordercolor=TROUGH, lightcolor=CARD, darkcolor=CARD)
        # A readonly combobox takes its colours from the STATE MAP, not from configure(),
        # and the unmapped default is a grey meant for a light background. Left alone it
        # renders the current model and font as dark grey on dark grey: the control looks
        # disabled, and the one thing it exists to tell you is the thing you cannot read.
        st.map("P.TCombobox",
               foreground=[("readonly", FG), ("disabled", DIM)],
               fieldbackground=[("readonly", CARD), ("disabled", BG)],
               selectforeground=[("readonly", FG)],
               selectbackground=[("readonly", CARD)])
        self.root.option_add("*TCombobox*Listbox.background", CARD)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#101010")

        wrap = tk.Frame(self.root, bg=BG, padx=16, pady=14)
        wrap.pack()

        self.preview = tk.Label(wrap, bg=BG, bd=0)
        self.preview.pack(pady=(0, 4))
        self.hold_note = tk.Label(wrap, bg=BG, fg=DIM, font=("Segoe UI", 9))
        self.hold_note.pack(pady=(0, 12))

        # The note is not a constant: before Start this choice IS this run, and after
        # Start it is the next one. A label that says the wrong one of those is worse
        # than none, because it is read at exactly the moment it decides something.
        self.model_note = tk.StringVar(
            value="used when you press Start" if launcher else
            "takes effect the next time you start")
        self.model_var = self._dropdown(wrap, "Model", self._models(), self.tune["model"],
                                        self.model_note, self.pick_model)
        self.lang_var = self._textbox(wrap, "Translate into", self.tune["lang"],
                                      "any language, written as you would say it")
        self.font_var = self._dropdown(wrap, "Font", [self._name(p) for p in self.fonts],
                                       self._name(self.font_path), None, self.pick_font)

        self.swatch_vars = {}
        self._swatches(wrap, "text_colour", "Text colour", TEXT_SWATCHES)
        self._swatches(wrap, "plate_colour", "Background", PLATE_SWATCHES)

        self.vars, self.value_labels = {}, {}
        for key, title, fmt, step, why in ROWS:
            row = tk.Frame(wrap, bg=BG)
            row.pack(fill="x", pady=(0, 10))
            head = tk.Frame(row, bg=BG)
            head.pack(fill="x")
            tk.Label(head, text=title, bg=BG, fg=FG,
                     font=("Segoe UI", 10, "bold")).pack(side="left")
            lab = tk.Label(head, text="", bg=BG, fg=FG, font=("Segoe UI", 10))
            lab.pack(side="right")
            self.value_labels[key] = (lab, fmt)
            var = tk.DoubleVar(value=self.tune[key])
            self.vars[key] = var
            lo, hi = LIMITS[key]
            tk.Scale(row, from_=lo, to=hi, resolution=step, variable=var,
                     orient="horizontal", showvalue=0, bg=BG, fg=FG, troughcolor=TROUGH,
                     activebackground=ACCENT, highlightthickness=0, bd=0, sliderlength=18,
                     width=10, command=lambda _v, k=key: self.changed(k)).pack(fill="x")
            tk.Label(row, text=why, bg=BG, fg=DIM, font=("Segoe UI", 8),
                     anchor="w").pack(fill="x")

        foot = tk.Frame(wrap, bg=BG)
        foot.pack(fill="x", pady=(4, 0))
        tk.Button(foot, text="Reset", command=self.reset, bg=CARD, fg=FG, bd=0, padx=14, pady=4,
                  activebackground="#3a3a3a", activeforeground=FG).pack(side="left")
        self.foot_note = tk.Label(foot, text="", bg=BG, fg=DIM, font=("Segoe UI", 8))
        self.foot_note.pack(side="right")
        self.go = None
        if self.launcher:
            self.go = tk.Button(foot, text="Start", command=self.start, bg=ACCENT,
                                fg="#0d1a24", bd=0, padx=26, pady=5,
                                font=("Segoe UI", 10, "bold"),
                                activebackground="#a5d8ff", activeforeground="#0d1a24")
            self.go.pack(side="right", padx=(0, 12))
            self.root.bind("<Return>", lambda _e: self.start())
        # Enter is Start only until it has started; after that the selector owns Enter.
        self.status = tk.Label(wrap, text="", bg=CARD, fg=DIM, anchor="w",
                               font=("Segoe UI", 9), padx=10, pady=6)
        if self.launcher:
            self.status.pack(fill="x", pady=(12, 0))
            self.set_status("choose what you want, then press Start")
        self.idle_note()
        threading.Thread(target=self._listen, daemon=True).start()

        self.redraw()

    # ----------------------------------------------------------------- running
    def set_status(self, text):
        self.status.configure(text=text)

    def _listen(self):
        """Take status lines off stdin and show them.

        Everything worth reporting happens in the PARENT process -- loading the model is
        most of a minute of nothing, and a window that says nothing for a minute is a
        window that looks broken. The pipe already exists in the other direction for the
        Start handshake, so this costs one thread and no new mechanism.
        """
        try:
            for raw in iter(sys.stdin.buffer.readline, b""):
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("STATUS "):
                    # Tk is not thread-safe: hand the update to the loop that owns it.
                    self.root.after(0, self.set_status, line[7:])
        except Exception:
            pass

    def idle_note(self):
        self.foot_note.configure(
            text="then drag a box round the game's subtitles" if self.launcher and
            not self.started else
            "changes apply straight away  ·  Ctrl+Alt+R redraws the box")

    def start(self):
        """Say go, once. The parent process is reading this line on our stdout.

        A pipe rather than a file or a port: the panel is already a child of the thing
        waiting for it, so the channel exists and closing it says "the window was shut"
        without anybody having to invent a way to say that.
        """
        if self.started or not self.launcher:
            return
        self.started = True
        self.model_note.set("takes effect the next time you start")
        self.commit()
        if self.go is not None:
            # The same button, doing the thing that is useful NOW. Before Start there is
            # no box to move; after it, moving the box is the one action left that cannot
            # be a slider -- games put their subtitles in a different place in a cutscene
            # than in a menu, and restarting to re-aim means loading the model again.
            self.go.configure(text="Move box", command=self.move_box, bg=CARD, fg=FG,
                              activebackground="#3a3a3a", activeforeground=FG,
                              font=("Segoe UI", 9), padx=16)
        self.idle_note()
        print("RUN")
        sys.stdout.flush()

    def move_box(self):
        """Ask for the box selector again. Same event as Ctrl+Alt+R, said with a button."""
        if not self.started:
            return
        self.set_status("drag the box again, then press Enter")
        print("REDRAW")
        sys.stdout.flush()

    # ------------------------------------------------------------------ pieces
    @staticmethod
    def _name(path):
        return os.path.splitext(os.path.basename(path or ""))[0]

    @staticmethod
    def _models():
        weights, _ = list_models(home("models"))
        return weights

    def _dropdown(self, parent, title, values, current, note, on_pick):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(0, 10))
        head = tk.Frame(row, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text=title, bg=BG, fg=FG, font=("Segoe UI", 10, "bold")).pack(side="left")
        if note is not None:
            kw = {"textvariable": note} if isinstance(note, tk.StringVar) else {"text": note}
            tk.Label(head, bg=BG, fg=DIM, font=("Segoe UI", 8), **kw).pack(side="right")
        var = tk.StringVar(value=current if current in values else (values[0] if values else ""))
        box = ttk.Combobox(row, textvariable=var, values=values, state="readonly",
                           style="P.TCombobox", height=14)
        box.pack(fill="x")
        box.bind("<<ComboboxSelected>>", lambda _e: on_pick(var.get()))
        self.boxes[title] = box
        if not values:
            box.configure(state="disabled")
            tk.Label(row, text="nothing found -- drop files in the folder and reopen this window",
                     bg=BG, fg=DIM, font=("Segoe UI", 8), anchor="w").pack(fill="x")
        return var

    def _textbox(self, parent, title, current, note):
        """A box you type into, rather than a list somebody else chose for you."""
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(0, 10))
        head = tk.Frame(row, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text=title, bg=BG, fg=FG,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Label(head, text=note, bg=BG, fg=DIM,
                 font=("Segoe UI", 8)).pack(side="right")
        var = tk.StringVar(value=current)
        tk.Entry(row, textvariable=var, bg=CARD, fg=FG, insertbackground=FG,
                 relief="flat", font=("Segoe UI", 10)).pack(fill="x", ipady=4)
        # Every keystroke, not only on Enter: a language typed and never committed is a
        # setting the person believes they changed.
        var.trace_add("write", lambda *_a: self.pick_lang(var.get()))
        return var

    def _swatches(self, parent, key, title, colours):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(0, 10))
        tk.Label(row, text=title, bg=BG, fg=FG,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        strip = tk.Frame(row, bg=BG)
        strip.pack(side="right")
        var = tk.StringVar(value=self.tune[key])
        self.swatch_vars[key] = (var, [])
        for c in colours:
            b = tk.Frame(strip, bg=c, width=26, height=20, highlightthickness=2,
                         highlightbackground=BG, cursor="hand2")
            b.pack(side="left", padx=2)
            b.pack_propagate(False)
            b.bind("<Button-1>", lambda _e, k=key, col=c: self.pick_colour(k, col))
            self.swatch_vars[key][1].append((c, b))
        self._mark(key)

    def _mark(self, key):
        """Ring the swatch that is in use. Without it the panel cannot say what is selected."""
        var, buttons = self.swatch_vars[key]
        for c, b in buttons:
            b.configure(highlightbackground=ACCENT if c == var.get() else BG)

    # ------------------------------------------------------------------ state
    def read(self):
        """The controls, snapped the way the settings file will store them. -> dict"""
        d = {k: v.get() for k, v in self.vars.items()}
        d["model"] = self.model_var.get()
        d["lang"] = self.lang_var.get().strip() or TUNING["lang"]
        for k, (var, _b) in self.swatch_vars.items():
            d[k] = var.get()
        return server.clamp_tuning(d)

    def changed(self, _key=None):
        """A control moved. Redraw now, write to disk once the dragging stops.

        Dragging a slider fires this every few pixels. Writing each one would mean a hundred
        replaces of settings.json for one adjustment, and both watchers reloading their fonts as
        fast as they could read it.
        """
        self.redraw()
        if self._pending is not None:
            self.root.after_cancel(self._pending)
        self._pending = self.root.after(180, self.commit)

    def commit(self):
        self._pending = None
        self.tune = save_tuning(self.read())

    def pick_model(self, _name):
        self.changed()

    def pick_lang(self, lang):
        """A new output language changes which fonts can draw it, and the preview."""
        if lang.strip().lower() == (self.lang or "").strip().lower():
            return self.changed()
        self.lang = lang
        self.fonts = candidates(home("fonts"), render.sample_for(lang)) or []
        names = [self._name(p) for p in self.fonts]
        box = self.boxes.get("Font")
        if box is not None:
            box.configure(values=names)
        if names and self._name(self.font_path) not in names:
            # The chosen font cannot draw the new language. Keeping it silently means a
            # screenful of empty boxes and nothing saying why.
            self.font_path = save_font(self.fonts[0])
            self.font_var.set(names[0])
        self.changed()

    def pick_font(self, name):
        for p in self.fonts:
            if self._name(p) == name:
                self.font_path = save_font(p)
                break
        self.changed()

    def pick_colour(self, key, colour):
        self.swatch_vars[key][0].set(colour)
        self._mark(key)
        self.changed()

    def reset(self):
        for k, v in TUNING.items():
            if k in self.vars:
                self.vars[k].set(v)
            elif k in self.swatch_vars:
                self.swatch_vars[k][0].set(v)
                self._mark(k)
        self.redraw()
        self.commit()

    # ----------------------------------------------------------------- drawing
    def redraw(self):
        d = self.read()
        for key, (lab, fmt) in self.value_labels.items():
            lab.configure(text=fmt % d[key])
        secs = read_seconds(THAI_SAMPLE, d["read_speed"], d["min_hold"])
        self.hold_note.configure(
            text="a line this long stays up %.1f s" % secs if secs else
                 "lines clear the moment the game moves on")
        if not self.font_path:
            self.preview.configure(text="no font on this machine can draw it", fg=FG)
            return
        size = int(d["size"])
        thai = (self.lang or "").strip().lower() == "thai"
        shown = THAI_SAMPLE if thai else render.sample_for(self.lang)
        im = render.draw_line(shown, SPEAKER, render.load(self.font_path, size),
                              render.load(self.font_path, max(11, int(size * 0.55))), PREVIEW_W,
                              d["text_colour"], d["plate_colour"])
        if im is None:
            return
        flat = Image.new("RGB", im.size, BG)
        flat.paste(im, (0, 0), im)
        self._img = ImageTk.PhotoImage(flat)
        self.preview.configure(image=self._img)

    def run(self):
        self.root.mainloop()


def open_panel(launcher=False):
    Panel(launcher=launcher).run()
    return 0


# Named so a test can prove the panel offers every setting there is, rather than the three
# somebody remembered to wire up.
CONTROLS = [k for k, _t, _f, _s, _w in ROWS] + list(CHOICES)
