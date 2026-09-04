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


class Flags(unittest.TestCase):
    def test_the_batch_size_is_derived_from_the_image_ceiling(self):
        # One image must fit a single ubatch. If someone raises the ceiling and leaves the batch
        # behind, the encode silently caps and quality drops with no error -- so the batch is
        # computed, and this test fails if anyone turns it back into a literal.
        self.assertGreaterEqual(server.IMG_UB, server.IMG_CEIL)
        i = server.FLAGS.index("-ub")
        self.assertEqual(int(server.FLAGS[i + 1]), server.IMG_UB)
        self.assertEqual(int(server.FLAGS[server.FLAGS.index("-b") + 1]), server.IMG_UB)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
