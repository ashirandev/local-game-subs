# -*- coding: utf-8 -*-
"""The subtitle window counts the screen in the same pixels as the box it is placed on.

Why (2026-10-14): a player on a laptop with an RTX 5070 saw the translation "in a corner, as if it
went off the screen", while the console showed every line read and translated. The box is drawn
and read in real pixels (mss switches its own process to them), and the subtitle window is
another process that never asked: at 125-150% display scaling Windows multiplied every position
it was given, so the plate opened 1.25-1.5 times further right and down than the box.

Every PC this was tested on runs at 100%, where both kinds of pixel are the same and nothing can
look wrong. So the test does not look at the screen: it starts the real overlay process and asks
Windows, from outside, which kind of pixel that process counts in.

GUARANTEE: the overlay process and the selector both run per-monitor DPI aware (2), the mode mss
puts the capture in, on any display scaling.
"""
import ctypes
import os
import subprocess
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PER_MONITOR = 2


def awareness(pid):
    """Windows' own answer for another process: 0 unaware, 1 system, 2 per-monitor. None if it will not say."""
    k32, shcore = ctypes.windll.kernel32, ctypes.windll.shcore
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        v = ctypes.c_int(-1)
        return v.value if shcore.GetProcessDpiAwareness(ctypes.c_void_p(h), ctypes.byref(v)) == 0 else None
    finally:
        k32.CloseHandle(h)


class _Entry(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("usage", ctypes.c_uint32), ("pid", ctypes.c_uint32),
                ("heap", ctypes.c_size_t), ("module", ctypes.c_uint32), ("threads", ctypes.c_uint32),
                ("parent", ctypes.c_uint32), ("prio", ctypes.c_long), ("flags", ctypes.c_uint32),
                ("exe", ctypes.c_char * 260)]


def interpreter(pid):
    """The process that really runs Python. A venv's Scripts\\python.exe is a launcher that starts the base
    interpreter as its CHILD, so the pid Popen returns never runs a line of ours -- asking it reads 0 whatever the
    code does (measured: a direct SetProcessDpiAwareness(2) returned S_OK and the launcher still read 0)."""
    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    snap = k32.CreateToolhelp32Snapshot(2, 0)
    kids, e = [], _Entry()
    e.size = ctypes.sizeof(_Entry)
    try:
        ok = k32.Process32First(ctypes.c_void_p(snap), ctypes.byref(e))
        while ok:
            if e.parent == pid and e.exe.lower().startswith(b"python"):
                kids.append(e.pid)
            ok = k32.Process32Next(ctypes.c_void_p(snap), ctypes.byref(e))
    finally:
        k32.CloseHandle(ctypes.c_void_p(snap))
    return interpreter(kids[0]) if kids else pid


def env():
    return dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"), PYTHONIOENCODING="utf-8")


@unittest.skipUnless(sys.platform == "win32", "display scaling is a Windows matter here")
class RealPixels(unittest.TestCase):

    def test_the_subtitle_window_counts_real_pixels(self):
        # Port 9 has nothing on it: the window opens, finds no box and no line, and waits.
        p = subprocess.Popen([sys.executable, "-B", "-X", "utf8", "-m", "gamesubs", "overlay", "--port", "9"],
                             cwd=ROOT, env=env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            got, end = None, time.time() + 20
            while time.time() < end and p.poll() is None:
                got = awareness(interpreter(p.pid))
                if got == PER_MONITOR:
                    break
                time.sleep(0.25)
            self.assertIsNone(p.poll(), "the overlay exited: %s" % p.stdout.read().decode("utf-8", "replace")[-400:]
                              if p.poll() is not None else "")
            self.assertEqual(got, PER_MONITOR, "the subtitle window counts scaled pixels: on a laptop at 150% "
                                               "it opens 1.5 times further right and down than the box")
        finally:
            p.kill()
            p.wait(10)

    def test_the_selector_counts_real_pixels_without_waiting_for_mss(self):
        code = ("import ctypes, os; from gamesubs import region; region.real_pixels(); "
                "v = ctypes.c_int(-1); ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(v)); print(v.value)")
        out = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, env=env(), capture_output=True, text=True,
                             timeout=60)
        self.assertEqual(out.stdout.strip(), str(PER_MONITOR), out.stderr[-400:])
        with open(os.path.join(ROOT, "src", "gamesubs", "region.py"), encoding="utf-8") as f:
            src = f.read()
        body = src[src.index("def select("):]
        self.assertLess(body.index("real_pixels()"), body.index("tk.Tk()"),
                        "the selector opens its window before it asks for real pixels")


if __name__ == "__main__":
    unittest.main(verbosity=2)
