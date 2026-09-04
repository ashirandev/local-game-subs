# -*- coding: utf-8 -*-
"""This tool watches your screen. So: where can it send anything?

Nowhere, once it is installed -- and this file is here so you do not have to take that on trust.
It reads the source and fails if any module that runs while you are playing contains a URL
pointing anywhere except your own machine.

    python tests/test_no_phone_home.py

Only `server.py` may reach the internet, only to fetch llama.cpp and the model, and only from
the two hosts that publish them. Nothing in the play path may contain an external address at all.

The honest limits of a test like this: it reads string literals, so it proves there is no URL
written down. It cannot prove a URL is not assembled at runtime out of pieces. If you want the
stronger check, it takes ten seconds: run `setup` once, then disconnect from the internet
entirely and run `play`. It works, because after setup nothing outside 127.0.0.1 is involved.
"""
import os
import re
import sys
import unittest

SRC = os.path.join(__file__.rsplit("tests", 1)[0], "src", "gamesubs")

# Modules that run while you are playing. None of these may name an outside host.
RUNTIME = ["capture.py", "service.py", "overlay.py", "vision.py", "__main__.py", "__init__.py"]

# The setup module may reach exactly these, and no others.
SETUP_ALLOWED = {"huggingface.co", "api.github.com", "github.com"}

LOCAL = {"127.0.0.1", "localhost", "0.0.0.0"}
URL = re.compile(r"https?://([A-Za-z0-9._%-]+)")


def hosts(fname):
    with open(os.path.join(SRC, fname), encoding="utf-8") as f:
        src = f.read()
    return src, URL.findall(src)


class NoPhoneHome(unittest.TestCase):
    def test_the_play_path_names_no_outside_host(self):
        for f in RUNTIME:
            src, found = hosts(f)
            for h in found:
                self.assertIn(h, LOCAL,
                              "%s contains a URL pointing at %s. Everything in the play path must "
                              "stay on this machine." % (f, h))

    def test_setup_reaches_only_the_two_publishers(self):
        _, found = hosts("server.py")
        for h in found:
            self.assertIn(h, SETUP_ALLOWED | LOCAL,
                          "server.py downloads from %s, which is not one of the hosts that "
                          "publish llama.cpp and the model." % h)

    def test_the_service_binds_to_localhost_only(self):
        # A server bound to 0.0.0.0 is reachable from the rest of the network, which for a thing
        # that publishes what is on your screen is a very different tool.
        src, _ = hosts("service.py")
        self.assertIn('ThreadingHTTPServer(("127.0.0.1"', src)
        self.assertNotIn("0.0.0.0", src)

    def test_the_model_server_is_told_to_bind_to_localhost(self):
        src, _ = hosts("server.py")
        self.assertIn('"--host", "127.0.0.1"', src)

    def test_nothing_in_the_play_path_uploads(self):
        # There is no upload in this design at all: images go to a model on your own machine.
        # Named here so that adding one has to be a deliberate act that breaks a test called
        # "nothing in the play path uploads".
        for f in RUNTIME:
            src, _ = hosts(f)
            for bad in ("smtplib", "ftplib", "requests.post", "boto3", "telemetry", "analytics"):
                self.assertNotIn(bad, src, "%s mentions %s" % (f, bad))

    def test_no_module_reads_files_outside_what_it_needs(self):
        # The tool opens: images it just captured, its own source (never), the model files, and
        # the overlay's saved position. Nothing walks your disk.
        for f in RUNTIME:
            src, _ = hosts(f)
            for bad in ("os.walk", "glob.glob", "shutil.copy"):
                self.assertNotIn(bad, src, "%s uses %s" % (f, bad))

    def test_checksums_are_fetched_not_hardcoded(self):
        # A hash written into this repo would only prove the file matches what I downloaded once.
        # It says nothing about whether this repo is trustworthy, which is the actual question.
        # So the expected hashes come from the publisher's own API over HTTPS.
        src, _ = hosts("server.py")
        self.assertIn("lfs", src)
        self.assertIn("digest", src)
        self.assertNotRegex(src, r'"[0-9a-f]{64}"',
                            "a 64-hex literal looks like a hardcoded checksum")


if __name__ == "__main__":
    unittest.main(verbosity=2)
