# -*- coding: utf-8 -*-
"""setup.bat gets past "is Python here?" whatever kind of program `python` turns out to be.

WHY. A player on an RTX 5070 laptop double-clicked setup.bat and the window closed at once, with
not one word in it (his video, 14 Oct 2026). Every way out of setup.bat ends at `pause`, so a
silent close means cmd stopped reading the file before the first echo -- and the first thing it
runs is `python --version`.

When `python` is a batch file, which is what pyenv-win puts on PATH, cmd hands the rest of the run
to it and never comes back: running a .bat from a .bat without `call` is a jump, not a call.
Measured here with setup.bat's own bytes and a python.bat shaped like pyenv's: no output, exit 0,
no .venv. With `call` the same run creates .venv and goes on to the packages. `call` changes
nothing when python is a real .exe.

The line endings were measured too, because the repo stores .bat files with LF and cmd is known
to lose labels in LF files: every `goto` in setup.bat, play.bat and tune.bat found its label.

These run cmd.exe, so they need Windows. The fake python never makes a real environment: it puts
where.exe where the private Python would be, which fails the package step in well under a second.
That keeps the file fast enough to run under every mutant.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETUP = os.path.join(ROOT, "setup.bat")
SYSTEM = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")

# A python.bat shaped like pyenv-win's shim. For `-m venv <dir>` it makes <dir>\Scripts\python.exe
# out of where.exe, so setup.bat carries on to the package step and fails there, fast.
SHIM = "\r\n".join([
    "@echo off",
    'if /i "%~1"=="-m" if /i "%~2"=="venv" (',
    '  mkdir "%~3\\Scripts" 2>nul',
    '  copy /y "%SystemRoot%\\System32\\where.exe" "%~3\\Scripts\\python.exe" >nul',
    ")",
    "exit /b 0",
    ""])


@unittest.skipUnless(os.name == "nt", "setup.bat runs under cmd.exe")
class SetupBat(unittest.TestCase):

    def run_setup(self, with_shim, shim_name="python.bat"):
        d = tempfile.mkdtemp(prefix="gamesubs_setup_")
        self.addCleanup(shutil.rmtree, d, True)
        game, shim = os.path.join(d, "game"), os.path.join(d, "shim")
        os.makedirs(game)
        os.makedirs(shim)
        # the bytes a player gets: .gitattributes says eol=lf, so the zip GitHub serves has LF endings
        # whatever this checkout has
        with open(SETUP, "rb") as src, open(os.path.join(game, "setup.bat"), "wb") as dst:
            dst.write(src.read().replace(b"\r\n", b"\n"))
        with open(os.path.join(shim, shim_name), "w", newline="") as f:
            f.write(SHIM)
        path = os.pathsep.join(([shim] if with_shim else []) + [SYSTEM, os.path.dirname(SYSTEM)])
        env = dict(os.environ, PATH=path, PIP_NO_INDEX="1")
        env.pop("PYTHONPATH", None)
        # the full path, as a double-click passes it: a bare name depends on whether cmd may look in
        # the current folder (NoDefaultCurrentDirectoryInExePath), which is not what is under test
        p = subprocess.run(["cmd", "/c", os.path.join(game, "setup.bat")], cwd=game, env=env,
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
        return p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace"), game

    def test_a_python_that_is_a_batch_file_hands_the_run_back(self):
        out, game = self.run_setup(with_shim=True)
        self.assertTrue(out.strip(), "setup.bat ended without printing anything: the window just closes")
        self.assertIn("Creating a private Python", out)
        self.assertTrue(os.path.isfile(os.path.join(game, ".venv", "Scripts", "python.exe")))
        # the line after `python -m venv`: proves the venv step came back too, not only the check
        self.assertIn("Installing the five packages", out)

    def test_python_installed_without_path_is_found_through_py(self):
        # a player, 15 Oct 2026: Python installed, `python` not found, and the installer he ran had no
        # "Add Python to PATH" box to tick. Python's launcher `py` is on PATH in that case.
        out, game = self.run_setup(with_shim=True, shim_name="py.bat")
        self.assertNotIn("Python is not installed", out)
        self.assertIn("Creating a private Python", out)
        self.assertTrue(os.path.isfile(os.path.join(game, ".venv", "Scripts", "python.exe")))
        self.assertIn("Installing the five packages", out)

    def test_no_python_at_all_still_says_so_and_waits(self):
        out, game = self.run_setup(with_shim=False)
        self.assertIn("Python is not installed", out)
        self.assertIn("Press any key", out)
        self.assertFalse(os.path.exists(os.path.join(game, ".venv")))


if __name__ == "__main__":
    unittest.main()
