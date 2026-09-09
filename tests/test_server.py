# -*- coding: utf-8 -*-
"""Tests for the setup path -- the part a new user hits first, and the only part that touches
the network.

Run against a real local HTTP server rather than a mocked urllib, because the things that go
wrong here are wire behaviour: a partial file, a server that ignores a Range header, a server
that does not say how big the file is. A mock would only confirm the mock.
"""
import io
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, __file__.rsplit("tests", 1)[0] + "src")
from gamesubs import server

BODY = b"".join(bytes([i % 256]) for i in range(50000))
CFG = {"ranges": True, "length": True}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        rng = self.headers.get("Range")
        start = 0
        if rng and CFG["ranges"]:
            start = int(rng.split("=")[1].split("-")[0])
            if start >= len(BODY):
                self.send_response(416)
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", "bytes %d-%d/%d"
                             % (start, len(BODY) - 1, len(BODY)))
        else:
            self.send_response(200)
        if CFG["length"]:
            self.send_header("Content-Length", str(len(BODY) - start))
        self.end_headers()
        self.wfile.write(BODY[start:])

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


class Download(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 8935), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = "http://127.0.0.1:8935/file.bin"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        CFG["ranges"], CFG["length"] = True, True
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, "file.bin")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_a_fresh_download_is_byte_exact(self):
        server.download(self.url, self.p, "file.bin")
        self.assertEqual(io.open(self.p, "rb").read(), BODY)

    def test_a_partial_file_resumes_rather_than_restarting(self):
        io.open(self.p, "wb").write(BODY[:20000])
        server.download(self.url, self.p, "file.bin")
        self.assertEqual(io.open(self.p, "rb").read(), BODY)

    def test_a_complete_file_is_left_alone(self):
        io.open(self.p, "wb").write(BODY)
        before = os.path.getmtime(self.p)
        server.download(self.url, self.p, "file.bin")       # server answers 416
        self.assertEqual(io.open(self.p, "rb").read(), BODY)
        self.assertEqual(os.path.getmtime(self.p), before)

    def test_a_server_that_ignores_range_restarts_instead_of_corrupting(self):
        # The dangerous case: we ask to resume, the server sends the WHOLE file with 200, and
        # appending it to what we already had would produce a plausible-looking corrupt file.
        CFG["ranges"] = False
        io.open(self.p, "wb").write(BODY[:20000])
        server.download(self.url, self.p, "file.bin")
        self.assertEqual(io.open(self.p, "rb").read(), BODY)

    def test_a_matching_checksum_passes(self):
        import hashlib
        server.download(self.url, self.p, "file.bin", hashlib.sha256(BODY).hexdigest())
        self.assertTrue(os.path.isfile(self.p))

    def test_a_wrong_checksum_deletes_the_file_and_refuses(self):
        # Deleted, not warned about: a corrupt 5 GB model left on disk gets used, and then fails
        # later as something that looks like a model problem rather than a download problem.
        with self.assertRaises(SystemExit) as e:
            server.download(self.url, self.p, "file.bin", "00" * 32)
        self.assertFalse(os.path.isfile(self.p))
        self.assertIn("checksum", str(e.exception))

    def test_an_already_complete_file_is_still_checksummed(self):
        # The resume path must not become a way to keep a corrupt file: if the bytes are already
        # there, they still have to be the right bytes.
        io.open(self.p, "wb").write(BODY)
        with self.assertRaises(SystemExit):
            server.download(self.url, self.p, "file.bin", "00" * 32)

    def test_no_checksum_available_still_downloads_and_prints_one(self):
        # A hash we could not fetch is a reason to show the user the hash, not a reason to refuse
        # to install.
        server.download(self.url, self.p, "file.bin", None)
        self.assertEqual(io.open(self.p, "rb").read(), BODY)

    def test_sha256_of_matches_hashlib(self):
        import hashlib
        io.open(self.p, "wb").write(BODY)
        self.assertEqual(server.sha256_of(self.p), hashlib.sha256(BODY).hexdigest())

    def test_no_content_length_is_refused_not_guessed(self):
        # Without a size there is no way to tell a finished download from a truncated one, and
        # guessing produces a corrupt model that fails much later with an unrelated error.
        CFG["length"] = False
        with self.assertRaises(SystemExit):
            server.download(self.url, self.p, "file.bin")


class Locate(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_an_explicit_path_that_exists_is_used(self):
        p = os.path.join(self.d, server.EXE)
        io.open(p, "wb").write(b"x")
        self.assertEqual(server.find_server(p), p)

    def test_an_explicit_path_that_does_not_exist_is_not_invented(self):
        self.assertIsNone(server.find_server(os.path.join(self.d, "nope.exe")))

    def test_local_model_reports_nothing_before_setup(self):
        self.assertEqual(server.local_model(self.d), (None, None))

    def test_local_model_needs_the_projector_too(self):
        # Half a setup is the failure this guards: with only the weights the server starts,
        # answers text, and fails on every frame.
        io.open(os.path.join(self.d, server.MODEL_FILE), "wb").write(b"x")
        self.assertEqual(server.local_model(self.d), (None, None))
        io.open(os.path.join(self.d, server.MMPROJ_FILE), "wb").write(b"x")
        self.assertNotEqual(server.local_model(self.d), (None, None))

    def test_start_refuses_clearly_when_llama_server_is_missing(self):
        with self.assertRaises(SystemExit) as e:
            server.start(exe=os.path.join(self.d, "nope.exe"))
        self.assertIn("llama-server", str(e.exception))


ASSETS = sorted([
    "cudart-llama-bin-win-cuda-12.4-x64.zip",
    "cudart-llama-bin-win-cuda-13.3-x64.zip",
    "llama-b10796-bin-macos-arm64.tar.gz",
    "llama-b10796-bin-ubuntu-vulkan-x64.tar.gz",
    "llama-b10796-bin-win-cpu-x64.zip",
    "llama-b10796-bin-win-cuda-12.4-x64.zip",
    "llama-b10796-bin-win-cuda-13.3-x64.zip",
    "llama-b10796-bin-win-vulkan-x64.zip",
    "llama-b10796-xcframework.zip",
])


class PickAssets(unittest.TestCase):
    """Real asset names from a real release. The first version of this picked the wrong file."""

    def test_cuda_takes_the_binary_not_the_runtime(self):
        # `bin-win-cuda-13.3-x64` is a substring of BOTH the build and the 373 MB runtime package,
        # and the runtime sorts first. Picking it downloads a third of a gigabyte and yields no
        # llama-server at all.
        got = server.pick_assets(ASSETS, "cuda")
        self.assertEqual(got[0], "llama-b10796-bin-win-cuda-13.3-x64.zip")

    def test_cuda_also_takes_the_runtime(self):
        # The CUDA build has no CUDA runtime DLLs in it, and without them llama-server fails to
        # start without explaining itself.
        self.assertIn("cudart-llama-bin-win-cuda-13.3-x64.zip", server.pick_assets(ASSETS, "cuda"))

    def test_vulkan_is_one_file_and_it_is_the_windows_one(self):
        self.assertEqual(server.pick_assets(ASSETS, "vulkan"),
                         ["llama-b10796-bin-win-vulkan-x64.zip"])

    def test_cpu_picks_the_cpu_build(self):
        self.assertEqual(server.pick_assets(ASSETS, "cpu"), ["llama-b10796-bin-win-cpu-x64.zip"])

    def test_no_backend_ever_picks_a_non_windows_build(self):
        for b in server.BACKENDS:
            for n in server.pick_assets(ASSETS, b):
                self.assertIn("win", n, "%s picked %s" % (b, n))

    def test_a_release_without_the_wanted_build_returns_nothing(self):
        # Empty, so the caller can print the real asset list and a link rather than downloading
        # something that cannot work.
        self.assertEqual(server.pick_assets(["llama-b1-bin-macos-arm64.tar.gz"], "cuda"), [])

    def test_a_runtime_only_release_is_not_treated_as_a_build(self):
        self.assertEqual(server.pick_assets(["cudart-llama-bin-win-cuda-13.3-x64.zip"], "cuda"), [])


class OneFolder(unittest.TestCase):
    """Everything the tool installs lives beside the scripts, so uninstalling is deleting it."""

    def test_the_app_folder_is_the_repo_not_your_home_directory(self):
        d = server.app_dir()
        self.assertNotIn(".local-game-subs", d)
        self.assertTrue(os.path.isfile(os.path.join(d, "setup.bat"))
                        or os.path.isfile(os.path.join(d, "pyproject.toml")))

    def test_downloads_land_inside_it(self):
        for sub in ("models", "llama.cpp"):
            self.assertEqual(os.path.dirname(server.home(sub)), server.app_dir())

    def test_an_env_var_can_move_the_whole_lot(self):
        old = os.environ.get("GAMESUBS_HOME")
        os.environ["GAMESUBS_HOME"] = self.d = tempfile.mkdtemp()
        try:
            self.assertEqual(server.app_dir(), self.d)
        finally:
            if old is None:
                del os.environ["GAMESUBS_HOME"]
            else:
                os.environ["GAMESUBS_HOME"] = old
            shutil.rmtree(self.d, ignore_errors=True)


class ChooseModel(unittest.TestCase):
    """The models folder is a drop box: any vision GGUF plus its projector should just work."""

    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def touch(self, *names):
        for n in names:
            io.open(os.path.join(self.d, n), "wb").write(b"x")

    def test_projectors_are_not_offered_as_models(self):
        self.touch("gemma-4-E4B-it-Q4_K_M.gguf", "mmproj-BF16.gguf")
        weights, proj = server.list_models(self.d)
        self.assertEqual(weights, ["gemma-4-E4B-it-Q4_K_M.gguf"])
        self.assertEqual(proj, ["mmproj-BF16.gguf"])

    def test_non_gguf_files_are_ignored(self):
        self.touch("model.gguf", "mmproj.gguf", "readme.txt", "notes.md")
        self.assertEqual(server.list_models(self.d)[0], ["model.gguf"])

    def test_a_single_pair_needs_no_choosing(self):
        self.touch("gemma-4-E4B-it-Q4_K_M.gguf", "mmproj-BF16.gguf")
        m, p = server.resolve_model(None, self.d)
        self.assertTrue(m.endswith("gemma-4-E4B-it-Q4_K_M.gguf"))
        self.assertTrue(p.endswith("mmproj-BF16.gguf"))

    def test_the_right_projector_is_paired_with_each_model(self):
        # The failure this prevents is quiet: a mismatched projector starts fine, answers text,
        # and reads pictures out of nothing -- which looks like a bad model, not a bad pairing.
        self.touch("gemma-4-E4B-it-Q4_K_M.gguf", "mmproj-gemma-4-E4B-it-BF16.gguf",
                   "Qwen3-VL-8B-Q4_K_M.gguf", "mmproj-Qwen3-VL-8B-F16.gguf")
        self.assertIn("gemma", os.path.basename(
            server.resolve_model("gemma-4-E4B-it-Q4_K_M.gguf", self.d)[1]).lower())
        self.assertIn("qwen", os.path.basename(
            server.resolve_model("Qwen3-VL-8B-Q4_K_M.gguf", self.d)[1]).lower())

    def test_one_projector_serves_whichever_model_is_picked(self):
        self.touch("a-Q4_K_M.gguf", "b-Q4_K_M.gguf", "mmproj-BF16.gguf")
        self.assertTrue(server.resolve_model("b-Q4_K_M.gguf", self.d)[1].endswith("mmproj-BF16.gguf"))

    def test_several_models_and_no_choice_refuses_rather_than_guessing(self):
        self.touch("a-Q4_K_M.gguf", "b-Q4_K_M.gguf", "mmproj-BF16.gguf")
        with self.assertRaises(SystemExit) as e:
            server.resolve_model(None, self.d)
        self.assertIn("more than one", str(e.exception))

    def test_a_model_with_no_projector_is_refused_with_the_reason(self):
        self.touch("lonely-Q4_K_M.gguf")
        with self.assertRaises(SystemExit) as e:
            server.resolve_model(None, self.d)
        self.assertIn("two files", str(e.exception))

    def test_an_empty_folder_says_where_to_put_things(self):
        with self.assertRaises(SystemExit) as e:
            server.resolve_model(None, self.d)
        self.assertIn("setup", str(e.exception))
        self.assertIn(self.d, str(e.exception))

    def test_an_unknown_name_lists_what_is_there(self):
        self.touch("a-Q4_K_M.gguf", "mmproj-BF16.gguf")
        with self.assertRaises(SystemExit) as e:
            server.resolve_model("typo.gguf", self.d)
        self.assertIn("a-Q4_K_M.gguf", str(e.exception))


class Flags(unittest.TestCase):
    def test_the_batch_size_is_derived_from_the_image_ceiling(self):
        # One image must fit a single ubatch. If someone raises the ceiling and leaves the batch
        # behind, the encode silently caps and quality drops with no error -- so the batch is
        # computed, and this test fails if anyone turns it back into a literal.
        self.assertGreaterEqual(server.IMG_UB, server.IMG_CEIL)
        i = server.FLAGS.index("-ub")
        self.assertEqual(int(server.FLAGS[i + 1]), server.IMG_UB)
        self.assertEqual(int(server.FLAGS[server.FLAGS.index("-b") + 1]), server.IMG_UB)

    def test_reasoning_is_switched_off_on_the_server(self):
        # Worth 4x. With reasoning on, the model writes out its thinking before answering, and for
        # a one-line subtitle that thinking is most of the work: 2.5 s per line against 0.6 s,
        # same model, same card. It never errors and the answers stay right, so nothing points at
        # it -- the tool is just four times too slow to keep up with dialogue.
        i = server.FLAGS.index("--reasoning")
        self.assertEqual(server.FLAGS[i + 1], "off")

    def test_the_image_floor_is_not_pinned_to_the_ceiling(self):
        # Pinning the floor up forces small images to the maximum, which roughly doubled a read
        # on a path with a deadline -- that does not make it slow, it makes it blank.
        self.assertLess(server.IMG_FLOOR, server.IMG_CEIL)

    def test_the_projector_is_always_passed(self):
        d = tempfile.mkdtemp()
        try:
            exe = os.path.join(d, server.EXE)
            io.open(exe, "wb").write(b"x")
            captured = {}

            class FakePopen(object):
                def __init__(self, cmd, **kw):
                    captured["cmd"] = cmd

                def terminate(self):
                    pass

            import subprocess as sp
            real = sp.Popen
            sp.Popen = FakePopen
            try:
                server.start(model="m.gguf", mmproj="p.gguf", exe=exe)
            finally:
                sp.Popen = real
            self.assertIn("--mmproj", captured["cmd"])
            self.assertEqual(captured["cmd"][captured["cmd"].index("--mmproj") + 1], "p.gguf")
        finally:
            shutil.rmtree(d, ignore_errors=True)


class ASecondModelDoesNotBreakTheFirst(unittest.TestCase):
    """The folder tells people to drop models in. Doing it used to unpair the one that
    worked, because upstream ships every gemma-4 projector as `mmproj-BF16.gguf` -- a name
    with no fragment of the model in it. Rename the new one so the pair is clear, and the
    OLD model now matches nothing: `resolve_model` refuses to start, and the reason it
    gives is about a missing projector that is sitting right there."""

    E4B = "gemma-4-E4B-it-Q4_K_M.gguf"
    E2B = "gemma-4-E2B-it-Q4_K_M.gguf"
    PROJ = ["mmproj-BF16.gguf", "mmproj-E2B-BF16.gguf"]

    def test_the_named_pair_still_wins(self):
        self.assertEqual(server.match_projector(self.E2B, self.PROJ, [self.E2B, self.E4B]),
                         "mmproj-E2B-BF16.gguf")

    def test_and_the_nameless_one_is_left_for_the_model_nothing_else_claims(self):
        self.assertEqual(server.match_projector(self.E4B, self.PROJ, [self.E2B, self.E4B]),
                         "mmproj-BF16.gguf")

    def test_two_nameless_projectors_are_still_a_refusal(self):
        """Elimination needs something to eliminate. Two files that say nothing about which
        model they belong to is a genuine ambiguity, and guessing it wrong produces a server
        that answers text and reads pictures out of nothing."""
        self.assertIsNone(server.match_projector(
            self.E4B, ["mmproj-BF16.gguf", "mmproj-1.gguf"], [self.E2B, self.E4B]))

    def test_one_projector_needs_no_reasoning_at_all(self):
        self.assertEqual(server.match_projector(self.E4B, ["mmproj-BF16.gguf"],
                                                [self.E2B, self.E4B]), "mmproj-BF16.gguf")

    def test_a_real_folder_with_both_models_in_it_resolves_both(self):
        """The seam. `match_projector` can be perfect and still never be told about the
        other models -- `resolve_model` is the only caller, and it is the one that has the
        folder listing. Mutation found this by removing the third argument at the call site
        while every test of the function itself stayed green."""
        d = tempfile.mkdtemp()
        try:
            for n in (self.E4B, self.E2B) + tuple(self.PROJ):
                with open(os.path.join(d, n), "wb") as f:
                    f.write(b"x")
            self.assertEqual(os.path.basename(server.resolve_model(self.E4B, d)[1]),
                             "mmproj-BF16.gguf")
            self.assertEqual(os.path.basename(server.resolve_model(self.E2B, d)[1]),
                             "mmproj-E2B-BF16.gguf")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_it_behaves_as_before_when_nobody_passes_the_folder(self):
        """The third argument is optional, and the old two-argument call still means what it
        meant: no claim, no answer."""
        self.assertIsNone(server.match_projector(self.E4B, self.PROJ))


class TheModelCatalog(unittest.TestCase):
    """Downloading a second model by hand is a trap, so the tool does it.

    Every gemma-4 projector upstream is called `mmproj-BF16.gguf`. Follow a link, save both
    files, and the new projector lands on top of the working one -- same name, within a few
    megabytes of the same size, and the model it belonged to now reads every frame as blank.
    A URL in a readme cannot prevent that; a table with a `save_as` in it can."""

    def test_every_entry_is_complete(self):
        for key, e in server.CATALOG.items():
            for field in ("repo", "weights", "mmproj", "save_as", "gb", "note"):
                self.assertIn(field, e, "%s is missing %s" % (key, field))

    def test_no_two_models_write_their_projector_to_the_same_name(self):
        """The whole point. This is the test that stops a third entry being added the
        obvious way and quietly breaking the two that work."""
        names = [e["save_as"] for e in server.CATALOG.values()]
        self.assertEqual(len(names), len(set(names)), names)

    def test_a_saved_projector_still_names_its_own_model(self):
        """`save_as` has to carry a fragment `match_projector` can pair on, or renaming it
        has bought nothing. The default keeps the bare upstream name on purpose -- it is the
        one that wins by elimination."""
        for key, e in server.CATALOG.items():
            if key == server.DEFAULT_MODEL:
                continue
            self.assertTrue(set(server._tokens(e["weights"])) & set(server._tokens(e["save_as"])),
                            "%s: %s says nothing about %s" % (key, e["save_as"], e["weights"]))

    def test_the_default_is_what_the_module_constants_say(self):
        """Those constants are read by `local_model`, by the tests, and by anything that
        predates the catalog. Two answers to "which model is the default" is one too many."""
        e = server.CATALOG[server.DEFAULT_MODEL]
        self.assertEqual((server.REPO, server.MODEL_FILE, server.MMPROJ_FILE),
                         (e["repo"], e["weights"], e["save_as"]))

    def test_the_projector_lands_under_the_name_the_table_chose(self):
        """Without the network: what matters is the destination path, and a label in a
        progress line looks exactly like it in the source. Mutation caught that -- the first
        version of this mutant changed the printed name and nothing could tell."""
        seen = []
        real = server.download
        server.download = lambda url, dest, label, sha=None: seen.append(dest) or dest
        try:
            server.fetch_model(r"C:\tmp\models", "e2b")
        finally:
            server.download = real
        self.assertTrue(seen[-1].endswith("mmproj-E2B-BF16.gguf"), seen)

    def test_asking_for_a_model_that_is_not_there_says_what_is(self):
        with self.assertRaises(SystemExit) as cm:
            server.fetch_model(tempfile.gettempdir(), "e9b")
        self.assertIn("e2b", str(cm.exception))


class TheCatalogIsReachableFromTheCommandLine(unittest.TestCase):
    """A table nobody can see is a worse readme than a readme. The seam again: the catalog
    can be perfect and still have no command that prints it or downloads from it."""

    @staticmethod
    def source():
        return io.open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "src", "gamesubs", "__main__.py"),
            encoding="utf-8").read()

    def test_setup_can_be_pointed_at_any_of_them(self):
        body = self.source()
        self.assertIn('"--model-name"', body)
        self.assertIn("fetch_model(a.dir", body)
        self.assertIn("model_name", body[body.index("def cmd_setup("):])

    def test_there_is_a_command_that_prints_the_links(self):
        body = self.source()
        i = body.index("def cmd_models(")
        block = body[i:body.index("def cmd_setup(")]
        self.assertIn("server.HF", block, "it lists models without saying where they are")
        self.assertIn("setup --model-name", block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
