# -*- coding: utf-8 -*-
"""play finishes a setup that stopped half way, instead of saying what is missing and closing.

WHY. A player on 1.0.4 (2026-11-18): setup stopped between the model and its projector, so play
said "found gemma-4-E2B-it-Q4_K_M.gguf but no projector to go with it" and closed. Setup again;
this time the newest llama.cpp release was still uploading its files, so there was no
llama-server, and play said so and closed. Both times the fix was "run setup again", which is
something a program can do for you.

WHAT MUST STAY TRUE. Play fetches only what setup itself fetches, and only what is missing. On a
PC where setup finished it fetches nothing, so the promise in tests/test_no_phone_home.py holds:
after setup, play reaches nothing outside this PC.

    python tests/test_play_finishes_a_setup_that_stopped.py
"""
import io
import os
import shutil
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from gamesubs import __main__ as m                              # noqa: E402
from gamesubs import server                                     # noqa: E402

MAIN = io.open(os.path.join(ROOT, "src", "gamesubs", "__main__.py"), encoding="utf-8").read()
PLAY = MAIN[MAIN.index("def cmd_play("):MAIN.index("def cmd_fonts(")]


def args(**kw):
    return types.SimpleNamespace(**dict({"base_url": "", "llama_server": None}, **kw))


class Finish(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="gamesubs_finish_")
        self.calls = []
        self.was = (server.find_server, server.fetch_llama, server.fetch_model)
        self.server_here = True
        server.find_server = lambda explicit=None: "llama-server.exe" if self.server_here else None
        server.fetch_llama = lambda backend="vulkan", dest_dir=None: self.calls.append(("llama", backend))
        server.fetch_model = lambda dest_dir=None, which=None: self.calls.append(("model", which, dest_dir))
        self.e2b = server.CATALOG["e2b"]

    def tearDown(self):
        server.find_server, server.fetch_llama, server.fetch_model = self.was
        shutil.rmtree(self.d, ignore_errors=True)

    def put(self, name):
        io.open(os.path.join(self.d, name), "wb").write(b"x")

    def finish(self, **kw):
        return m._finish_setup(args(**kw), models_dir=self.d, say=lambda t: None)

    def test_the_players_case_a_catalog_model_without_its_projector_gets_it(self):
        self.put(self.e2b["weights"])
        self.assertEqual(self.finish(), [self.e2b["save_as"]])
        self.assertEqual(self.calls, [("model", "e2b", self.d)])

    def test_no_llama_server_gets_llama_cpp(self):
        self.server_here = False
        self.put(self.e2b["weights"])
        self.put(self.e2b["save_as"])
        self.assertEqual(self.finish(), ["llama.cpp"])
        self.assertEqual(self.calls, [("llama", "vulkan")])

    def test_a_finished_setup_fetches_nothing(self):
        self.put(self.e2b["weights"])
        self.put(self.e2b["save_as"])
        self.assertEqual(self.finish(), [])
        self.assertEqual(self.calls, [])

    def test_a_model_the_player_dropped_in_is_not_ours_to_download_around(self):
        self.put("some-other-vision-model.gguf")
        self.assertEqual(self.finish(), [])
        self.assertEqual(self.calls, [])

    def test_a_llama_server_the_player_named_is_not_downloaded_around(self):
        self.server_here = False
        self.assertEqual(self.finish(llama_server=r"C:\tools\llama-server.exe"), [])
        self.assertEqual(self.calls, [])

    def test_a_model_served_elsewhere_needs_nothing_here(self):
        self.server_here = False
        self.put(self.e2b["weights"])
        self.assertEqual(self.finish(base_url="http://127.0.0.1:9000/v1"), [])
        self.assertEqual(self.calls, [])


class PlayCallsIt(unittest.TestCase):
    """Both ways into play finish the setup BEFORE they look for the model or start llama-server."""

    def test_the_window_path(self):
        path = PLAY[PLAY.index("        else:"):PLAY.index("base = a.base_url or")]
        self.assertIn("_finish_setup(a,", path)
        self.assertLess(path.index("_finish_setup(a,"), path.index("server.resolve_model("))

    def test_the_console_path(self):
        path = PLAY[PLAY.index("if a.no_panel:"):PLAY.index("        else:")]
        self.assertIn("_finish_setup(a)", path)
        self.assertLess(path.index("_finish_setup(a)"), path.index("_choose_model(a)"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
