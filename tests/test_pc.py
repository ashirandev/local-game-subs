# -*- coding: utf-8 -*-
"""The PC is described in every screenshot a player might send, and the description is right.

Why (2026-10-14): two players wrote to the page with a screenshot of an error and nothing else,
and the first thing anyone helping needs is which graphics card, how much memory, and how much of
it was already in use. So the console says it before anything starts, the server's failure says
it beside the error, and the settings window carries one line of it.

GUARANTEE: on this PC the block names the card llama.cpp runs on (a separate NVIDIA card here,
next to the Intel graphics inside the CPU -- the same trap as an AMD Ryzen with built-in Radeon),
its full memory and the memory in use within 64 MB of nvidia-smi, and the driver number NVIDIA
publishes. On any PC, a reader that fails is said in words, never raised over the error.
nvidia-smi is only the reference here; the code never calls it.
"""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from gamesubs import __version__ as VERSION, pc, server  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOLERANCE_MB = 64


def nvsmi():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,driver_version",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    name, total, used, driver = out.stdout.strip().splitlines()[0].split(", ")
    return {"name": name, "total": int(total), "used": int(used), "driver": driver}


@unittest.skipUnless(sys.platform == "win32" and nvsmi(), "needs Windows with an NVIDIA card to compare against")
class OnThisPC(unittest.TestCase):

    def test_the_first_card_is_the_one_llama_cpp_uses_not_the_graphics_in_the_cpu(self):
        cards = pc.gpus()
        self.assertTrue(cards)
        self.assertEqual(cards[0]["name"], nvsmi()["name"])
        self.assertFalse(cards[0]["integrated"])
        self.assertTrue(any(c["integrated"] for c in cards[1:]),
                        "the Intel graphics inside the CPU is not reported as built in: %r" % cards)

    def test_its_full_memory_matches_nvidia_smi(self):
        card, ref = pc.gpus()[0], nvsmi()
        self.assertLessEqual(abs(card["total_mb"] - ref["total"]), TOLERANCE_MB, (card["total_mb"], ref["total"]))

    def test_memory_in_use_matches_nvidia_smi(self):
        # Bracketed: nvidia-smi just before and just after. Memory in use moves while anything else runs (a browser,
        # another test), and one reading taken after the other once failed a correct reader on a busy PC.
        misses = []
        for _ in range(5):
            before = nvsmi()["used"]
            used = pc.gpus()[0]["used_mb"]
            after = nvsmi()["used"]
            lo, hi = min(before, after) - TOLERANCE_MB, max(before, after) + TOLERANCE_MB
            if used is None or not lo <= used <= hi:
                misses.append((before, used, after))
        self.assertEqual(misses, [], "(nvidia-smi before, this reader, nvidia-smi after)")

    def test_the_driver_is_the_number_nvidia_publishes(self):
        self.assertEqual(pc.gpus()[0]["driver"], nvsmi()["driver"])

    def test_the_block_says_it_all_and_nothing_about_who(self):
        text = pc.block("llama.cpp vulkan, build 1")
        ref = nvsmi()
        for want in (ref["name"], "driver " + ref["driver"], "RAM ", "Windows ", "engine: llama.cpp vulkan"):
            self.assertIn(want, text)
        for private in (os.environ.get("COMPUTERNAME"), os.environ.get("USERNAME")):
            if private:
                self.assertNotIn(private, text)

    def test_windows_11_is_not_called_windows_10(self):
        # The registry's ProductName says "Windows 10" on every Windows 11.
        if sys.getwindowsversion().build >= 22000:
            self.assertTrue(pc.windows().startswith("Windows 11"), pc.windows())

    def test_the_settings_window_line_names_the_card_and_its_memory(self):
        line = pc.short()
        self.assertIn(nvsmi()["name"], line)
        self.assertRegex(line, r"\d+\.\d GB")


AMD_LAPTOP = [{"name": "AMD Radeon RX 7600M XT", "vendor": "AMD", "integrated": False, "total_mb": 8176,
               "used_mb": 6100, "driver": "Adrenalin 24.3.1", "driver_date": "2024-03-12"},
              {"name": "AMD Radeon(TM) Graphics", "vendor": "AMD", "integrated": True,
               "driver": "Adrenalin 24.3.1", "driver_date": "2024-03-12"}]


def readers(**kw):
    base = dict(windows=lambda: "Windows 11 24H2, build 26100.1", cpu=lambda: "AMD Ryzen 7 7840HS",
                ram=lambda: (16000, 4000), gpus=lambda: AMD_LAPTOP)
    base.update(kw)
    return base


def boom():
    raise OSError("access denied")


class AnyPC(unittest.TestCase):

    def test_an_amd_laptop_shows_the_card_its_memory_in_use_and_the_built_in_one(self):
        out = pc.lines(readers=readers())
        self.assertIn("AMD Radeon RX 7600M XT | 8.0 GB, 6.0 GB in use | driver Adrenalin 24.3.1 (2024-03-12)", out[1])
        self.assertIn("built into the processor", out[2])
        self.assertNotIn("GB", out[2], "built-in graphics has no memory of its own to show")

    def test_a_reader_that_fails_is_said_and_never_raised(self):
        out = pc.lines(readers=readers(gpus=boom, windows=boom))
        self.assertIn("graphics: Windows would not say which graphics card this is", out)
        self.assertTrue(out[0].startswith("AMD Ryzen 7 7840HS"), out[0])
        out = pc.lines(readers=readers(gpus=boom, windows=boom, cpu=boom, ram=boom))
        self.assertEqual(out[0], "Windows did not say what this PC is")

    def test_no_card_at_all_is_not_the_same_words_as_a_card_that_would_not_say(self):
        self.assertIn("graphics: Windows lists no graphics card", pc.lines(readers=readers(gpus=lambda: [])))

    def test_memory_in_use_that_cannot_be_read_is_left_out_not_shown_as_zero(self):
        card = dict(AMD_LAPTOP[0], used_mb=None)
        out = pc.lines(readers=readers(gpus=lambda: [card]))
        self.assertIn("| 8.0 GB | driver", out[1])

    def test_the_settings_window_line_survives_every_reader_failing(self):
        self.assertEqual(pc.short(readers=dict(windows=boom, ram=boom, gpus=boom)), "this PC: unknown")
        self.assertEqual(pc.short(readers=readers()),
                         "this PC: AMD Radeon RX 7600M XT 8.0 GB | driver Adrenalin 24.3.1 | RAM 15.6 GB | Windows 11 24H2")


class WhichAdapterIsWhat(unittest.TestCase):
    """Direct3D 12 decides "built in", the registry decides the size; a size line only as a last resort."""

    def adapter(self, **kw):
        a = {"name": "x", "vendor": "AMD", "vendor_id": 0x1002, "device_id": 1, "dedicated_mb": 512, "uma": None}
        a.update(kw)
        return a

    def test_an_amd_processor_that_reserves_8_gb_is_still_built_in(self):
        self.assertTrue(pc.combine(self.adapter(dedicated_mb=8192, uma=True), {})["integrated"])

    def test_a_4_gb_card_is_a_card(self):
        g = pc.combine(self.adapter(dedicated_mb=4080, uma=False), {"memory_mb": 4096})
        self.assertFalse(g["integrated"])
        self.assertEqual(g["total_mb"], 4096)

    def test_the_full_size_comes_from_the_registry_not_dxgi(self):
        # DXGI 15,995 MB, registry 16,303 MB on an RTX 5070 Ti: the registry is the number on the box.
        g = pc.combine(self.adapter(vendor="NVIDIA", dedicated_mb=15995, uma=False),
                       {"memory_mb": 16303, "driver": "32.0.16.1714"})
        self.assertEqual(g["total_mb"], 16303)
        self.assertEqual(g["driver"], "617.14")

    def test_without_direct3d_12_a_size_line_decides(self):
        self.assertTrue(pc.combine(self.adapter(dedicated_mb=128), {})["integrated"])
        self.assertFalse(pc.combine(self.adapter(dedicated_mb=6144), {})["integrated"])


class EachCardOnce(unittest.TestCase):
    """A player's screenshot (2026-10-14) listed one card twice, the second with no memory in use."""

    def card(self, name="NVIDIA GeForce RTX 5060", used=1200, integrated=False, vendor="NVIDIA"):
        return {"name": name, "vendor": vendor, "integrated": integrated, "total_mb": 8192, "used_mb": used}

    def test_the_second_entry_without_a_reading_is_left_out(self):
        self.assertEqual(pc.distinct([self.card(), self.card(used=None)]), [self.card()])

    def test_it_is_left_out_even_when_windows_lists_it_first(self):
        self.assertEqual(pc.distinct([self.card(used=None), self.card()]), [self.card()])

    def test_two_real_cards_of_one_model_both_stay(self):
        self.assertEqual(len(pc.distinct([self.card(used=900), self.card(used=300)])), 2)

    def test_a_card_windows_will_not_count_at_all_still_shows(self):
        # No reading anywhere (counters off): nothing to tell a copy from a card, so nothing is hidden.
        self.assertEqual(len(pc.distinct([self.card(used=None)])), 1)
        self.assertEqual(len(pc.distinct([self.card(used=None), self.card(used=None)])), 2)

    def test_built_in_graphics_and_other_cards_are_untouched(self):
        cards = [self.card(), self.card(name="Intel(R) UHD Graphics 770", vendor="Intel", used=None, integrated=True),
                 self.card(name="AMD Radeon RX 7600", vendor="AMD", used=None)]
        self.assertEqual(pc.distinct(cards), cards)

    def test_the_block_shows_it_once(self):
        saved = (pc.WINDOWS, pc._adapters, pc._registry, pc.counter_mb)
        two = [{"name": "NVIDIA GeForce RTX 5060", "vendor": "NVIDIA", "vendor_id": 0x10DE, "device_id": 0x2D05,
                "dedicated_mb": 7900, "luid": luid, "uma": False} for luid in ("luid_a", "luid_b")]
        pc.WINDOWS, pc._adapters, pc._registry = True, lambda: two, lambda: {}
        pc.counter_mb = lambda path: 1200 if "luid_a" in path else None
        try:
            got = pc.lines(readers={"windows": lambda: "Windows 11", "cpu": lambda: "cpu", "ram": lambda: (16384, 8192)})
        finally:
            pc.WINDOWS, pc._adapters, pc._registry, pc.counter_mb = saved
        self.assertEqual(sum("RTX 5060" in line for line in got), 1, got)


class DriverNumbers(unittest.TestCase):

    def test_nvidia_is_the_number_on_nvidias_site(self):
        self.assertEqual(pc.vendor_driver("NVIDIA", "32.0.16.1714"), "617.14")
        self.assertEqual(pc.vendor_driver("NVIDIA", "31.0.15.5222"), "552.22")

    def test_amd_is_the_adrenalin_version_when_the_driver_wrote_one(self):
        self.assertEqual(pc.vendor_driver("AMD", "31.0.24027.1012", "24.3.1"), "Adrenalin 24.3.1")
        self.assertEqual(pc.vendor_driver("AMD", "31.0.24027.1012", ""), "31.0.24027.1012")

    def test_intel_is_already_intels_number(self):
        self.assertEqual(pc.vendor_driver("Intel", "32.0.101.7088"), "32.0.101.7088")

    def test_the_registry_date_reads_year_first(self):
        self.assertEqual(pc._iso_date("9-17-2026"), "2026-09-17")
        self.assertEqual(pc._iso_date("junk"), "")


def source(name):
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "gamesubs", name),
              encoding="utf-8") as f:
        return f.read()


class ItIsWhereTheScreenshotIs(unittest.TestCase):

    def test_a_server_that_stopped_says_the_pc_beside_the_error(self):
        class P(object):
            returncode, log_path, args = 1, None, None
        saved = pc.lines
        pc.lines = lambda engine=None, readers=None: ["THE-PC-LINE"]
        try:
            msg = server._stopped(P())
        finally:
            pc.lines = saved
        self.assertIn("this PC", msg)
        self.assertIn("THE-PC-LINE", msg)

    def test_play_and_check_say_it_in_the_console(self):
        src = source("__main__.py")
        for cmd in ("def cmd_play(", "def cmd_check("):
            body = src[src.index(cmd):]
            body = body[:body.index("\ndef ", 1)]
            self.assertIn("_say_the_pc(a)", body, "%s no longer prints the PC" % cmd)
        play = src[src.index("def cmd_play("):]
        self.assertEqual(play[:play.index("\ndef ", 1)].count("_say_the_pc(a)"), 2,
                         "play must say it on both routes: with the settings window and without")

    def test_the_settings_window_carries_the_line(self):
        # The real window, not its source: the line arrives from a thread, and a thread that is
        # never started leaves "reading..." on screen for good.
        import time
        from gamesubs import panel
        saved = pc.short
        pc.short = lambda readers=None: "this PC: THE-CARD 8.0 GB"
        try:
            p = panel.Panel(launcher=True)
        except Exception as e:   # no display to open a window on
            pc.short = saved
            self.skipTest("no window: %s" % e)
        try:
            end = time.time() + 10
            while p.pc_note.cget("text") != "this PC: THE-CARD 8.0 GB" and time.time() < end:
                p.root.update()
                time.sleep(0.05)
            self.assertEqual(p.pc_note.cget("text"), "this PC: THE-CARD 8.0 GB")
            self.assertTrue(p.pc_note.winfo_ismapped(), "the line exists but is not shown")
            self.assertIn(VERSION, p.root.title(), "the window does not say which version it is")
        finally:
            pc.short = saved
            p.root.destroy()

    def test_the_block_says_which_version_this_is(self):
        # A screenshot is the only way to know whether a player has a fix yet.
        self.assertIn("local-game-subs %s on this PC" % VERSION, pc.block())

    def test_the_two_version_numbers_agree(self):
        import re
        with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as f:
            self.assertEqual(re.search(r'^version = "([^"]+)"', f.read(), re.M).group(1), VERSION)

    def test_the_engine_line_names_the_build_folder_and_its_version(self):
        exe = server.find_server(None)
        if not exe:
            self.skipTest("no llama-server in this folder")
        line = server.engine_line(exe)
        self.assertRegex(line, r"^llama\.cpp (vulkan|cuda|cpu), build \d+$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
