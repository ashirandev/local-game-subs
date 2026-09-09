# -*- coding: utf-8 -*-
"""No function may import a name the module already imports.

WHAT HAPPENED. `server` was imported inside eight different functions of `__main__.py`, one of
them `_loop`. When a module-level `from . import server` was added, those eight local imports
turned `server` into a LOCAL name for the whole of each function -- and Python decides that at
compile time, for the entire body, not from the import line onwards. So `_loop` raised

    UnboundLocalError: cannot access local variable 'server' where it is not associated with
    a value

at its FIRST use of `server`, forty lines above the import that caused it. It shipped, and it
shipped past 287 green tests and 67 killed mutants, because not one of them runs `_loop` -- it
loops on the screen forever and there was no way to call it that stops.

WHY THIS TEST AND NOT A BETTER ONE. A test that really ran `_loop` would be better evidence and
is the right thing to want, but the honest version of it opens a region selector on somebody's
screen. This one costs nothing, needs no display, and closes the whole class rather than the one
instance: any name imported at module level and again inside a function is the bug, whether or
not that function has been run yet.

A local import is still fine for something the module does NOT import -- that is how the heavy
optional dependencies stay optional here.
"""
import ast
import io
import os
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "gamesubs")


def module_level_names(tree):
    out = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                out.add(a.asname or a.name.split(".")[0])
    return out


def shadowed(tree):
    """[(function, name, line)] for every local import of a module-level name."""
    top = module_level_names(tree)
    bad = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    name = a.asname or a.name.split(".")[0]
                    if name in top:
                        bad.append((fn.name, name, node.lineno))
    return bad


class NoFunctionShadowsAModuleImport(unittest.TestCase):

    def test_every_module_in_the_package(self):
        for f in sorted(os.listdir(SRC)):
            if not f.endswith(".py"):
                continue
            tree = ast.parse(io.open(os.path.join(SRC, f), encoding="utf-8").read())
            bad = shadowed(tree)
            self.assertEqual(bad, [], "%s: %s" % (f, "; ".join(
                "%s() re-imports %s at line %d" % b for b in bad)))

    def test_the_check_can_still_see_the_thing_it_looks_for(self):
        """The sweep-tool lesson, applied here: a checker that has stopped working reports a
        clean tree in exactly the same words as a clean tree."""
        tree = ast.parse("import os\n\n\ndef f():\n    import os\n    return os\n")
        self.assertEqual(shadowed(tree), [("f", "os", 5)])

    def test_and_leaves_an_honest_local_import_alone(self):
        """Optional heavy dependencies are imported inside the function that needs them, on
        purpose. Only a name the module ALREADY has is a shadow."""
        tree = ast.parse("import os\n\n\ndef f():\n    import numpy\n    return numpy, os\n")
        self.assertEqual(shadowed(tree), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
