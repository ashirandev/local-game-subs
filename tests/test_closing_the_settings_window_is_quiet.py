# -*- coding: utf-8 -*-
"""Closing the settings window ends its process quietly, while the translator is still talking to it.

WHY. A player on 1.0.4 (2026-11-18) closed the settings window and the console filled with
"Fatal Python error: _enter_buffered_busy: could not acquire lock for <_io.BufferedReader
name='<stdin>'> at interpreter shutdown" and a thread dump, in the middle of the subtitles. The
translation went on; the player could not know that, and asked what they had broken. The window
waits for status lines from the translator on a daemon thread. Waiting in sys.stdin.buffer holds
that buffer's lock, and at exit Python cannot take it: 10 of 10 closes on 3.11, 3.13 and 3.14.

WHAT MUST STAY TRUE. The status lines still arrive, and the process ends with exit code 0 and
nothing on stderr while the translator still holds the pipe open -- which it always does, because
the window is closed first.

    python tests/test_closing_the_settings_window_is_quiet.py
"""
import io
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")

# The window's process in miniature: the reader the panel uses, on the thread the panel puts it on,
# then the end of the program while the parent still holds our stdin open.
CHILD = r'''
import sys, threading, time
sys.path.insert(0, sys.argv[1])
from gamesubs import panel
got = []
threading.Thread(target=panel.read_status, args=(got.append,), daemon=True).start()
end = time.time() + 20
while not got and time.time() < end:
    time.sleep(0.02)
print(got[0] if got else "(nothing arrived)", flush=True)
'''


class ClosingIsQuiet(unittest.TestCase):

    def close_once(self):
        p = subprocess.Popen([sys.executable, "-B", "-X", "utf8", "-c", CHILD, SRC],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            p.stdin.write("STATUS loading the model\n".encode("utf-8"))
            p.stdin.flush()
            said = p.stdout.readline().decode("utf-8", "replace").strip()
            err = p.stderr.read().decode("utf-8", "replace")
            p.wait(timeout=60)
        finally:
            p.stdin.close()
        return said, p.returncode, err

    def test_the_status_line_arrives_and_the_window_closes_without_a_crash(self):
        for _ in range(3):
            said, code, err = self.close_once()
            self.assertEqual(said, "loading the model")
            self.assertNotIn("Fatal Python error", err)
            self.assertEqual(code, 0, err[:300])

    def test_the_window_reads_its_status_through_that_reader(self):
        text = io.open(os.path.join(SRC, "gamesubs", "panel.py"), encoding="utf-8").read()
        listen = text[text.index("    def _listen("):text.index("    def _read_pc(")]
        self.assertIn("read_status(", listen)
        self.assertNotIn("sys.stdin.buffer.readline", text.replace("in sys.stdin.buffer.readline", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
