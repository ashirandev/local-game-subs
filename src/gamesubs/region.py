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
  * NOTHING MAY BE DRAWN AT A POINT JUST BECAUSE IT IS INSIDE THE VIRTUAL RECTANGLE. The
    virtual screen is the bounding box of every monitor, and a bounding box of monitors that are
    not the same size or not aligned CONTAINS HOLES -- coordinates that are inside it and on no
    physical display at all. Measured on a real 3-monitor desktop (2560x1440 + 1920x1080 offset
    358px down + a portrait 1080x1920), the virtual rectangle is 5560x1920 and both of this
    selector's instructions landed in a hole: the banner at (2780, 40) and, for a subtitle box at
    the bottom of the main screen, "press ENTER" at (1269, 1465). A person saw a box, no
    instructions anywhere, and no way to find out what to press.
  * it must hand back SCREEN coordinates, not window ones. tkinter reports the position inside its
    own window, and on a multi-monitor desktop the virtual screen can start at a negative x -- so
    a selector that forgets to add the window's own origin is correct on a single monitor and
    quietly wrong on the setup that needed it most.
"""
import tkinter as tk

DIM = 0.35              # how much of the screen is greyed out while choosing
KEY = "#101215"
GUIDE = "#5c6a76"      # the centre line, off
HIT = "#7cffb2"        # ...and lit, when the box agrees with it
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


def monitor_for(x, y, monitors):
    """The monitor a point is actually on. -> monitor dict, or None if it is in a hole."""
    for m in monitors or []:
        if (m["left"] <= x < m["left"] + m["width"]
                and m["top"] <= y < m["top"] + m["height"]):
            return m
    return None


def banner_spots(monitors, y=44):
    """Where the "drag a box" line goes: once per MONITOR. -> [(x, y), ...] in screen pixels.

    Not once in the middle of the virtual screen. The middle of the virtual screen is a point that
    may be on no display at all -- measured at (2780, 40) on a real desktop -- and even when it
    lands on one, it lands on whichever monitor happens to sit in the middle, which is not the one
    the game is on. One per monitor costs three lines of text and cannot miss.
    """
    return [(m["left"] + m["width"] // 2, m["top"] + y) for m in monitors or []]


def hint_spot(box, monitors, gap=30, height=38):
    """Where to put the instruction for a box. -> (x, y) in SCREEN pixels, centre of the text.

    Below the box normally, above it when the box sits at the bottom of its monitor, and inside it
    when the box covers the monitor top to bottom.

    Game subtitles are at the BOTTOM of the screen -- that is what the box is drawn around, every
    single time -- so "below the box" is off the monitor in the ordinary case, not the exotic one.
    """
    l, t, w, h = box
    x = l + w / 2.0
    m = monitor_for(x, t + h / 2.0, monitors)
    if m is None:
        return x, t + h + gap
    half = height / 2.0
    top, bottom = m["top"], m["top"] + m["height"]
    if t + h + gap + half <= bottom:
        return x, t + h + gap
    if t - gap - half >= top:
        return x, t - gap
    return x, min(bottom - half, max(top + half, t + h - half - 6))


# Where a game puts its subtitles, as fractions of the monitor. Not guessed -- measured twice.
#
#   the box a person dragged by hand on 2560x1440 : centre 0.488, spans 0.756 - 0.849
#   RE4R's own cutscene line, from a screenshot    : centre 0.501, spans ~0.745 - 0.775
#
# The first draft of this was 0.75 - 0.86 and the real line starts at 0.745, which clips it
# by a hair -- and a clipped line is the failure nobody can see, because the model reads the
# half it was given and translates that half perfectly. So the default is deliberately
# taller than either measurement on both sides.
#
# Tall also because a box drawn round a ONE-line subtitle is short by exactly one line the
# moment the game shows two, which RE4R does in its first cutscene. Wide because a narrow
# box clips a long sentence the same way. Neither error is visible; being too big only
# costs a little reading of empty picture.
DEFAULT_W = 0.62
DEFAULT_H = 0.16
DEFAULT_BOTTOM = 0.88


def default_box(mon):
    """A first guess at the subtitle strip: centred, low, on THIS monitor. -> tuple

    There was no first guess at all until now. The selector opened on an empty screen and
    the first thing a new user had to do was invent a rectangle -- for a tool whose entire
    job they had not seen work yet. With a box already drawn, Enter is the whole step, and
    a drag is still there for the game that puts its subtitles somewhere else.

    Centred horizontally because that is where subtitles are, on every game that has them.
    The old fallback was the bottom 28%% of the screen at FULL width, which is neither
    centred nor a subtitle strip: it takes in the whole HUD, and everything it takes in is
    something the model can read out and translate.
    """
    w = int(mon["width"] * DEFAULT_W)
    h = int(mon["height"] * DEFAULT_H)
    left = int(mon["left"]) + (int(mon["width"]) - w) // 2
    top = int(mon["top"]) + int(mon["height"] * DEFAULT_BOTTOM) - h
    return (left, top, w, h)


SNAP = 14              # pixels: how close counts as "they meant the centre"


def inside(box, x, y):
    """Is this point within the box? Screen pixels, both. -> bool"""
    if not box:
        return False
    l, t, w, h = box
    return l <= x <= l + w and t <= y <= t + h


def centred_on(box, monitors, tol=SNAP):
    """The monitor this box is (almost) horizontally centred on, or None. -> dict|None"""
    if not box:
        return None
    mid = box[0] + box[2] / 2.0
    for m in monitors or []:
        if abs(mid - (m["left"] + m["width"] / 2.0)) <= tol:
            return m
    return None


def snap_x(box, monitors, tol=SNAP):
    """Pull the box onto a monitor's centre line when it is already nearly there. -> tuple

    Without this, "centred" is a thing you can want and cannot have: a hand lands within a few
    pixels and stays there, and no amount of care with a mouse fixes it. With it, near enough IS
    centred, and the guide line turning solid is what says so.
    """
    m = centred_on(box, monitors, tol)
    if not m:
        return tuple(box)
    l, t, w, h = box
    return (int(m["left"] + (m["width"] - w) // 2), t, w, h)


def keep_on_screen(box, virtual):
    """Clamp a moved box inside the whole desktop. -> tuple

    Not inside one monitor: the box may legitimately be dragged onto a different screen, and a
    clamp that assumed one would fight the person doing it.
    """
    l, t, w, h = box
    l = max(virtual["left"], min(l, virtual["left"] + virtual["width"] - w))
    t = max(virtual["top"], min(t, virtual["top"] + virtual["height"] - h))
    return (int(l), int(t), int(w), int(h))


def select(virtual, existing=None, monitors=None):
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
    drag = {"x": 0, "y": 0, "rect": None, "label": None, "done": None, "btn": None,
            "mode": None, "off": (0, 0), "guides": [], "mark": []}
    mons = list(monitors or [virtual])

    # One banner per monitor, rather than one in the middle of the virtual screen. The middle of
    # the virtual screen is not a place -- see the module docstring -- and even when it is on a
    # display it is on whichever display happens to be in the middle, which is not the one the
    # game is on.
    for bx, by in banner_spots(mons):
        cv.create_text(
            bx - ox, by - oy, fill="#e8eaed", font=("Segoe UI", 15, "bold"),
            text="Drag a box round the subtitles, then drag it about to aim it"
                 "     Enter = accept     Esc = cancel")

    # The centre line of every monitor, always on. It is the thing the box is being lined up
    # against, and a guide you have to summon is a guide nobody uses.
    for m in mons:
        gx = m["left"] + m["width"] // 2 - ox
        drag["guides"].append(cv.create_line(gx, m["top"] - oy, gx, m["top"] + m["height"] - oy,
                                             fill=GUIDE, width=1, dash=(3, 6)))

    def mark_centre(l, t, w, h):
        """A cross at the middle of the box, and the guide lit when the two agree."""
        for item in drag["mark"]:
            cv.delete(item)
        drag["mark"] = []
        cx, cy = l + w // 2, t + h // 2
        on = centred_on(to_screen((l, t, w, h), virtual), mons)
        col = HIT if on else LINE
        drag["mark"] = [cv.create_line(cx - 11, cy, cx + 11, cy, fill=col, width=2),
                        cv.create_line(cx, cy - 11, cx, cy + 11, fill=col, width=2)]
        for i, m in enumerate(mons):
            cv.itemconfigure(drag["guides"][i],
                             fill=HIT if (on is m) else GUIDE,
                             width=2 if (on is m) else 1,
                             dash=() if (on is m) else (3, 6))

    def draw(l, t, w, h):
        if drag["rect"]:
            cv.delete(drag["rect"])
        if drag["label"]:
            cv.delete(drag["label"])
        drag["rect"] = cv.create_rectangle(l, t, l + w, t + h, outline=LINE, width=2, dash=(7, 4))
        on = centred_on(to_screen((l, t, w, h), virtual), mons)
        drag["label"] = cv.create_text(
            l + w / 2, max(t - 14, 12), fill=HIT if on else LINE,
            font=("Consolas", 12, "bold"),
            text="%d x %d  at (%d, %d)%s" % (w, h, l + ox, t + oy,
                                             "   centred" if on else ""))
        mark_centre(l, t, w, h)

    def place(box):
        """Show and remember a box given in SCREEN pixels."""
        box = keep_on_screen(box, virtual)
        out["box"] = box
        draw(box[0] - ox, box[1] - oy, box[2], box[3])
        show_accept(box[0] - ox, box[1] - oy, box[2], box[3])

    def down(e):
        drag["x"], drag["y"] = e.x, e.y
        box = out["box"]
        # Inside the box means move it; anywhere else means draw a new one. The size is right
        # after the first drag and it is the POSITION that wants adjusting, over and over.
        if inside(box, e.x + ox, e.y + oy):
            drag["mode"] = "move"
            drag["off"] = (e.x + ox - box[0], e.y + oy - box[1])
        else:
            drag["mode"] = "draw"

    def move(e):
        if drag["mode"] == "move":
            box = out["box"]
            moved = keep_on_screen((e.x + ox - drag["off"][0], e.y + oy - drag["off"][1],
                                    box[2], box[3]), virtual)
            moved = snap_x(moved, mons)
            out["box"] = moved
            draw(moved[0] - ox, moved[1] - oy, moved[2], moved[3])
        else:
            draw(*norm_box(drag["x"], drag["y"], e.x, e.y))

    def up(e):
        if drag["mode"] == "move":
            place(out["box"])
            return
        l, t, w, h = norm_box(drag["x"], drag["y"], e.x, e.y)
        if w < MIN_SIDE or h < MIN_SIDE:
            if out["box"]:                       # a click inside nothing: leave what is there
                place(out["box"])
            return
        place(snap_x(to_screen((l, t, w, h), virtual), mons))

    def nudge(dx, dy):
        """Arrow keys, for the last few pixels a mouse will not give you."""
        if not out["box"]:
            return
        l, t, w, h = out["box"]
        place((l + dx, t + dy, w, h))

    def centre_it(*_):
        """One key that does the thing the guide is there to help with."""
        if not out["box"]:
            return
        l, t, w, h = out["box"]
        m = centred_on(out["box"], mons, tol=10 ** 6) or mons[0]
        place((int(m["left"] + (m["width"] - w) // 2), t, w, h))

    def show_accept(l, t, w, h):
        """The one control that has to be findable, drawn where it can actually be seen.

        It is a BUTTON, not a line of text, because the keyboard is the input that can be taken
        away: this window is borderless and always-on-top over a running game, and a game that
        keeps the keyboard leaves a person with a box on screen, no way to confirm it, and their
        keystrokes going into the game behind. The mouse is already proven to work at this exact
        moment -- they just dragged the box with it.
        """
        for k in ("done", "btn"):
            if drag[k]:
                cv.delete(drag[k])
                drag[k] = None
        sx, sy = hint_spot(to_screen((l, t, w, h), virtual), mons)
        x, y = sx - ox, sy - oy
        drag["done"] = cv.create_text(
            x, y, fill="#06121c", font=("Segoe UI", 14, "bold"),
            text="   Press ENTER to use this box      or click here   ·   "
                 "drag inside to move   ·   C = centre   ·   arrows nudge   ·   Esc = cancel   ")
        bx = cv.bbox(drag["done"])
        drag["btn"] = cv.create_rectangle(bx[0] - 10, bx[1] - 10, bx[2] + 10, bx[3] + 10,
                                          fill=LINE, outline="#e8eaed", width=2)
        cv.tag_lower(drag["btn"], drag["done"])
        for item in (drag["btn"], drag["done"]):
            cv.tag_bind(item, "<ButtonRelease-1>", accept)

    def accept(*_):
        if out["box"]:
            root.destroy()

    if existing:
        # Show where it is now, so "adjust it slightly" does not mean "find it again" -- with the
        # button already on it, because an unchanged box is a box you accept without dragging.
        place(tuple(existing))

    cv.bind("<Button-1>", down)
    cv.bind("<B1-Motion>", move)
    cv.bind("<ButtonRelease-1>", up)
    root.bind("<Return>", accept)
    root.bind("<KP_Enter>", accept)
    root.bind("<Double-Button-1>", accept)
    for key, d in (("Left", (-1, 0)), ("Right", (1, 0)),
                   ("Up", (0, -1)), ("Down", (0, 1))):
        root.bind("<%s>" % key, lambda _e, d=d: nudge(*d))
        root.bind("<Shift-%s>" % key, lambda _e, d=d: nudge(d[0] * 10, d[1] * 10))
    root.bind("<c>", centre_it)
    root.bind("<C>", centre_it)
    root.bind("<Escape>", lambda *_: (out.update(box=None), root.destroy()))
    root.focus_force()
    cv.focus_set()
    root.mainloop()
    return out["box"]
