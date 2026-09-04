# -*- coding: utf-8 -*-
"""Drag a box around the subtitles instead of typing numbers at them.

The band is the one setting nobody can guess for you: it depends on the game, the resolution and
where that game happens to draw its own subtitles in that scene. Every version of asking for it in
numbers -- `--region 840,1035,880,235`, or reading two thresholds out of `tune` -- asks the user
to do arithmetic about their own screen before anything works at all.

So: dim the screen, let them drag a rectangle over the subtitles, press Enter. The numbers are
still there underneath, and `--region` still overrides, but nobody has to meet them.

The box is remembered, because the answer only changes when the game does.

TWO THINGS THIS HAS TO GET RIGHT, and neither is obvious:

  * it must cover EVERY monitor, not the primary one. A second screen is where a lot of people put
    the game, and a selector that only dims one of them looks broken rather than limited.
  * it must hand back SCREEN coordinates, not window ones. tkinter reports the position inside its
    own window, and on a multi-monitor desktop the virtual screen can start at a negative x -- so
    a selector that forgets to add the window's own origin is correct on a single monitor and
    quietly wrong on the setup that needed it most.
"""
import tkinter as tk

DIM = 0.35              # how much of the screen is greyed out while choosing
KEY = "#101215"
LINE = "#3fa7ff"
MIN_SIDE = 24           # smaller than this is a misclick, not a selection


def norm_box(x0, y0, x1, y1):
    """A drag in any direction becomes (left, top, width, height).

    People drag right-to-left and bottom-to-top all the time, and without this those produce
    negative widths -- which do not raise, they just quietly select nothing.
    """
    return min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)


def to_screen(box, virtual):
    """Window coordinates -> screen coordinates.

    tkinter reports positions inside its own window. The selector window starts at the virtual
    screen's origin, which is (0, 0) on a single monitor and something else the moment there is a
    second one -- negative, if that monitor sits to the left. Forgetting this is correct on the
    setup that does not need it and wrong on the one that does.
    """
    l, t, w, h = box
    return l + virtual["left"], t + virtual["top"], w, h


def select(virtual, existing=None):
    """Show the selector over `virtual` (an mss-style all-monitors rect).

    Returns (left, top, width, height) in screen pixels, or None if cancelled.
    """
    ox, oy = virtual["left"], virtual["top"]
    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry("%dx%d+%d+%d" % (virtual["width"], virtual["height"], ox, oy))
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", DIM)
    except tk.TclError:
        pass
    root.configure(bg=KEY)
    root.config(cursor="crosshair")

    cv = tk.Canvas(root, bg=KEY, highlightthickness=0, cursor="crosshair")
    cv.pack(fill="both", expand=True)

    out = {"box": None}
    drag = {"x": 0, "y": 0, "rect": None, "label": None, "done": None}

    hint = cv.create_text(
        virtual["width"] // 2, 40, fill="#e8eaed", font=("Segoe UI", 15, "bold"),
        text="Drag a box around the game's subtitles     Enter = accept     Esc = cancel")

    def draw(l, t, w, h):
        if drag["rect"]:
            cv.delete(drag["rect"])
        if drag["label"]:
            cv.delete(drag["label"])
        drag["rect"] = cv.create_rectangle(l, t, l + w, t + h, outline=LINE, width=2, dash=(7, 4))
        drag["label"] = cv.create_text(
            l + w / 2, max(t - 14, 12), fill=LINE, font=("Consolas", 12, "bold"),
            text="%d x %d  at (%d, %d)" % (w, h, l + ox, t + oy))

    if existing:
        # Show where it is now, so "adjust it slightly" does not mean "find it again".
        draw(existing[0] - ox, existing[1] - oy, existing[2], existing[3])
        out["box"] = tuple(existing)

    def down(e):
        drag["x"], drag["y"] = e.x, e.y

    def move(e):
        draw(*norm_box(drag["x"], drag["y"], e.x, e.y))

    def up(e):
        l, t, w, h = norm_box(drag["x"], drag["y"], e.x, e.y)
        if w < MIN_SIDE or h < MIN_SIDE:
            return                       # a click, not a drag: keep whatever was there
        draw(l, t, w, h)
        out["box"] = to_screen((l, t, w, h), virtual)
        # The instruction has to be NEXT TO THE BOX, not in the banner at the top of the screen.
        # On a multi-monitor desktop that banner can be on a different physical screen from the
        # one being dragged on, so it is read once at the start and never seen again -- which
        # leaves someone who has just drawn a box with nothing telling them to press Enter.
        if drag["done"]:
            cv.delete(drag["done"])
        drag["done"] = cv.create_text(
            l + w / 2, t + h + 26, fill="#e8eaed", font=("Segoe UI", 14, "bold"),
            text="Press ENTER to use this box     ·     drag again to redo     ·     Esc to cancel")

    def accept(*_):
        if out["box"]:
            root.destroy()

    cv.bind("<Button-1>", down)
    cv.bind("<B1-Motion>", move)
    cv.bind("<ButtonRelease-1>", up)
    root.bind("<Return>", accept)
    root.bind("<KP_Enter>", accept)
    root.bind("<Double-Button-1>", accept)
    root.bind("<Escape>", lambda *_: (out.update(box=None), root.destroy()))
    root.focus_force()
    cv.focus_set()
    root.mainloop()
    return out["box"]
