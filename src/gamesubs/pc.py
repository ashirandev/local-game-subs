# -*- coding: utf-8 -*-
"""What this PC is, in a few lines that a screenshot carries.

Why (2026-10-14): two players wrote to the page with a screenshot of an error and nothing else.
The first thing anyone helping needs is the graphics card, how much memory it has, and how much of
that something else was already using -- and asking for it costs a day of messages each way. So
`play` prints it before anything starts, every error from the model server repeats it beside the
error, and the settings window carries one line of it. Whatever a player screenshots, the answer
to "which card?" is already in the picture.

Read from Windows itself, never from a vendor tool: nvidia-smi exists only with NVIDIA's driver,
and the players most likely to need help are the ones on AMD and Intel. DXGI lists every adapter,
the display driver's registry key holds the full memory size and the driver version, and the
WDDM performance counters say how much graphics memory is in use, for every brand alike.

Shown, never sent. Nothing here leaves the PC, and there is no computer name or user name in it.
Every reader answers None rather than raise: a crash while describing the PC would replace the
error the player needed to see.
"""
import ctypes
import os
import platform
import re
import sys

from . import __version__

WINDOWS = sys.platform == "win32"

GPU_VENDORS = {0x10DE: "NVIDIA", 0x1002: "AMD", 0x8086: "Intel"}
MICROSOFT_VENDOR = 0x1414               # the software renderer every Windows lists; not a card
INTEGRATED_MB = 2048                    # only when Direct3D 12 cannot say (see _shares_system_memory)
DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE = 2
PDH_MORE_DATA = 0x800007D2
PDH_FMT_LARGE = 0x400


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return None


def gb(mb):
    return "%.1f GB" % (mb / 1024.0)


# ---------------------------------------------------------------- Windows, processor, memory

def windows():
    """'Windows 11 24H2, build 26100.6584'.

    The name comes from the build number, not the registry's ProductName: that still says
    "Windows 10" on every Windows 11, because Microsoft never changed it.
    """
    if not WINDOWS:
        return platform.platform()
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as k:
        def get(name):
            try:
                return winreg.QueryValueEx(k, name)[0]
            except OSError:
                return None
        build = int(get("CurrentBuild") or sys.getwindowsversion().build)
        ubr, release = get("UBR"), get("DisplayVersion") or get("ReleaseId")
    name = "Windows 11" if build >= 22000 else "Windows 10" if build >= 10240 else "Windows"
    return "%s%s, build %d%s" % (name, " " + release if release else "", build,
                                 ".%d" % ubr if isinstance(ubr, int) else "")


def cpu():
    """The processor's own name, as Windows keeps it. -> str or None."""
    if not WINDOWS:
        return platform.processor() or None
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
        return " ".join(str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).split()) or None


def ram_mb():
    """-> (total MB, available MB) of the PC's memory."""
    class MS(ctypes.Structure):
        _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                    ("avail", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong),
                    ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
    m = MS()
    m.l = ctypes.sizeof(MS)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return None
    return m.total // 2 ** 20, m.avail // 2 ** 20


# ---------------------------------------------------------------- graphics, any brand

class _Luid(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_int32)]


class _AdapterDesc1(ctypes.Structure):
    _fields_ = [("name", ctypes.c_wchar * 128), ("vendor", ctypes.c_uint32), ("device", ctypes.c_uint32),
                ("subsys", ctypes.c_uint32), ("revision", ctypes.c_uint32), ("dedicated", ctypes.c_size_t),
                ("dedicated_system", ctypes.c_size_t), ("shared", ctypes.c_size_t), ("luid", _Luid),
                ("flags", ctypes.c_uint32)]


class _PdhItem(ctypes.Structure):
    _fields_ = [("name", ctypes.c_wchar_p), ("status", ctypes.c_uint32), ("value", ctypes.c_longlong)]


def _com(obj, index, *argtypes):
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtable[index])


def _shares_system_memory(adapter):
    """Direct3D 12's own answer to "is this graphics built into the processor" (UMA).
    -> True / False, or None when Direct3D 12 cannot say.

    A memory-size line cannot tell: an AMD processor's built-in graphics can reserve 8 GB of RAM
    as its own, and a 4 GB RX 6500 XT reports just under 4,096 MB.
    """
    try:
        d3d12 = ctypes.windll.d3d12
    except OSError:
        return None
    iid = (ctypes.c_ubyte * 16)(*bytes.fromhex("f1199818b61d574bbe541821339b85f7"))
    device = ctypes.c_void_p()
    create = d3d12.D3D12CreateDevice
    create.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    create.restype = ctypes.c_long
    if create(adapter, 0xB000, ctypes.addressof(iid), ctypes.byref(device)) != 0 or not device:
        return None
    try:
        arch = (ctypes.c_uint32 * 4)()
        hr = _com(device, 13, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)(
            device, 1, ctypes.addressof(arch), ctypes.sizeof(arch))
        return bool(arch[2]) if hr == 0 else None
    finally:
        _com(device, 2)(device)


def _adapters():
    """Every hardware adapter DXGI lists, the card Windows would pick for speed first."""
    factory, ranked = ctypes.c_void_p(), True
    dxgi = ctypes.windll.dxgi
    iid6 = (ctypes.c_ubyte * 16)(*bytes.fromhex("4f69b6c109ffa944b03c77900a0a1d17"))
    if dxgi.CreateDXGIFactory1(iid6, ctypes.byref(factory)) != 0:
        ranked, factory = False, ctypes.c_void_p()
        iid1 = (ctypes.c_ubyte * 16)(*bytes.fromhex("78ae0a776ff2ba4da829253c83d1b387"))
        if dxgi.CreateDXGIFactory1(iid1, ctypes.byref(factory)) != 0:
            return []
    adapter_iid = (ctypes.c_ubyte * 16)(*bytes.fromhex("618f03293938264691fd086879011a05"))
    out = []
    try:
        for i in range(16):
            adapter = ctypes.c_void_p()
            if ranked:
                hr = _com(factory, 29, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                          ctypes.POINTER(ctypes.c_void_p))(
                    factory, i, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE, ctypes.addressof(adapter_iid),
                    ctypes.byref(adapter))
            else:
                hr = _com(factory, 12, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p))(
                    factory, i, ctypes.byref(adapter))
            if hr != 0:
                break
            d = _AdapterDesc1()
            try:
                ok = _com(adapter, 10, ctypes.POINTER(_AdapterDesc1))(adapter, ctypes.byref(d)) == 0
                if ok and not d.flags & 2 and d.vendor != MICROSOFT_VENDOR:
                    out.append({"name": d.name.strip(), "vendor_id": d.vendor, "device_id": d.device,
                                "vendor": GPU_VENDORS.get(d.vendor, "0x%04X" % d.vendor),
                                "dedicated_mb": d.dedicated // 2 ** 20,
                                "luid": "luid_0x%08x_0x%08x" % (d.luid.high & 0xFFFFFFFF, d.luid.low),
                                "uma": _safe(_shares_system_memory, adapter)})
            finally:
                _com(adapter, 2)(adapter)
    finally:
        _com(factory, 2)(factory)
    return out


def _registry():
    """(vendor id, device id) -> {memory_mb, driver, driver_date} from the display drivers' keys.

    DXGI's dedicated memory leaves out what the driver reserves: 15,995 MB against 16,303 MB on an
    RTX 5070 Ti. HardwareInformation.qwMemorySize holds the full size, the number on the box.
    """
    import winreg
    out = {}
    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
        for i in range(winreg.QueryInfoKey(k)[0]):
            sub = winreg.EnumKey(k, i)
            if not sub.isdigit():
                continue
            values = {}
            try:
                with winreg.OpenKey(k, sub) as s:
                    for name in ("MatchingDeviceId", "HardwareInformation.qwMemorySize", "DriverVersion",
                                 "DriverDate", "RadeonSoftwareVersion"):
                        try:
                            values[name] = winreg.QueryValueEx(s, name)[0]
                        except OSError:
                            pass
            except OSError:
                continue
            ids = re.search(r"ven_([0-9a-f]{4})&dev_([0-9a-f]{4})", str(values.get("MatchingDeviceId", "")).lower())
            if not ids:
                continue
            mem = values.get("HardwareInformation.qwMemorySize")
            if isinstance(mem, bytes):
                mem = int.from_bytes(mem[:8], "little")
            out[(int(ids.group(1), 16), int(ids.group(2), 16))] = {
                "memory_mb": mem // 2 ** 20 if isinstance(mem, int) and mem > 0 else None,
                "driver": str(values.get("DriverVersion") or ""),
                "radeon": str(values.get("RadeonSoftwareVersion") or ""),
                "driver_date": _iso_date(values.get("DriverDate"))}
    return out


def _iso_date(text):
    """The registry keeps the driver's date as M-D-YYYY; a screenshot reads better as YYYY-MM-DD."""
    m = re.match(r"^\s*(\d{1,2})-(\d{1,2})-(\d{4})\s*$", str(text or ""))
    return "%s-%02d-%02d" % (m.group(3), int(m.group(1)), int(m.group(2))) if m else ""


def vendor_driver(vendor, windows_version, radeon=""):
    """The driver number the vendor's own site and app show, which is what a player can compare.

    Windows keeps every driver as four numbers, and only Intel's match what Intel publishes.
    NVIDIA's is the last digit of the third number and all of the fourth: 32.0.16.1714 is the
    617.14 that nvidia-smi and NVIDIA's download page say (checked on this PC). AMD's Adrenalin
    version is not in those four numbers at all; its driver writes it to a value of its own.
    """
    v = str(windows_version or "")
    if vendor == "NVIDIA":
        parts = v.split(".")
        if len(parts) == 4 and parts[2].isdigit() and parts[3].isdigit():
            n = parts[2][-1] + parts[3].zfill(4)
            return "%s.%s" % (n[:-2].lstrip("0") or "0", n[-2:])
    if vendor == "AMD" and radeon:
        return "Adrenalin %s" % radeon
    return v


def counter_mb(path):
    """One WDDM performance counter, summed over every instance its wildcard matches, in MB."""
    pdh = ctypes.windll.pdh
    query, counter = ctypes.c_void_p(), ctypes.c_void_p()
    if pdh.PdhOpenQueryW(None, None, ctypes.byref(query)) != 0:
        return None
    try:
        if pdh.PdhAddEnglishCounterW(query, ctypes.c_wchar_p(path), None, ctypes.byref(counter)) != 0:
            return None
        if pdh.PdhCollectQueryData(query) != 0:
            return None
        size, count = ctypes.c_uint32(0), ctypes.c_uint32(0)
        r = pdh.PdhGetFormattedCounterArrayW(counter, PDH_FMT_LARGE, ctypes.byref(size), ctypes.byref(count), None)
        if r & 0xFFFFFFFF != PDH_MORE_DATA:
            return 0 if r == 0 else None
        buf = ctypes.create_string_buffer(size.value)
        if pdh.PdhGetFormattedCounterArrayW(counter, PDH_FMT_LARGE, ctypes.byref(size), ctypes.byref(count), buf) != 0:
            return None
        items = ctypes.cast(buf, ctypes.POINTER(_PdhItem * count.value)).contents
        return int(sum(it.value for it in items if it.status in (0, 1)) // 2 ** 20)
    finally:
        pdh.PdhCloseQuery(query)


def gpus():
    """Every graphics adapter, the one Windows picks for speed first. -> list of dicts.

    Each has name, vendor, integrated, driver, driver_date; a separate card also total_mb (the
    full size) and used_mb (in use by every program right now, None when Windows will not say).
    Built-in graphics has no memory of its own to count: it lives in the PC's RAM.
    """
    if not WINDOWS:
        return []
    reg = _safe(_registry) or {}
    out = []
    for a in _adapters():
        g = combine(a, reg.get((a["vendor_id"], a["device_id"])) or {})
        if not g["integrated"]:
            g["used_mb"] = _safe(counter_mb, "\\GPU Adapter Memory(%s_phys_*)\\Dedicated Usage" % a["luid"])
        out.append(g)
    return out


def combine(adapter, reg):
    """One adapter as DXGI lists it, plus its registry key -> what the block shows.

    "integrated" is Direct3D 12's answer when it gives one; only when it cannot does a size line
    decide. The total is the registry's full size, DXGI's smaller one only when that is missing.
    """
    integrated = adapter["uma"] if adapter["uma"] is not None else adapter["dedicated_mb"] < INTEGRATED_MB
    g = {"name": adapter["name"], "vendor": adapter["vendor"], "integrated": integrated,
         "driver": vendor_driver(adapter["vendor"], reg.get("driver"), reg.get("radeon")),
         "driver_date": reg.get("driver_date", "")}
    if not integrated:
        g["total_mb"] = reg.get("memory_mb") or adapter["dedicated_mb"]
    return g


# ---------------------------------------------------------------- the block a screenshot carries

def lines(engine=None, readers=None):
    """The PC in three or four lines. `engine` is a line about llama.cpp when the caller knows it.

    `readers` replaces the four readers (tests only): a dict with windows / cpu / ram / gpus.
    """
    r = dict(windows=windows, cpu=cpu, ram=ram_mb, gpus=gpus)
    r.update(readers or {})
    ram = _safe(r["ram"])
    first = [x for x in (_safe(r["windows"]), _safe(r["cpu"]),
                         ram and "RAM %s, %s free" % (gb(ram[0]), gb(ram[1]))) if x]
    out = [" | ".join(first) or "Windows did not say what this PC is"]
    cards = _safe(r["gpus"])
    if not cards:
        out.append("graphics: %s" % ("Windows lists no graphics card" if cards == [] else
                                     "Windows would not say which graphics card this is"))
    for i, g in enumerate(cards or []):
        bits = [g["name"]]
        if g["integrated"]:
            bits.append("built into the processor")
        else:
            used = g.get("used_mb")
            bits.append(gb(g["total_mb"]) + (", %s in use" % gb(used) if used is not None else ""))
        if g.get("driver"):
            bits.append("driver %s%s" % (g["driver"], " (%s)" % g["driver_date"] if g.get("driver_date") else ""))
        out.append(("graphics: " if i == 0 else "          ") + " | ".join(bits))
    if engine:
        out.append("engine: " + engine)
    return out


def block(engine=None, indent="  "):
    """The lines under a heading that says what they are for and that they stay on this PC.

    The version is in the heading because a screenshot is also the only way to know whether a
    player has a fix yet. A screenshot with no block at all is 1.0.1 or older.
    """
    return "\n".join([indent + "local-game-subs %s on this PC (shown for a screenshot when you ask for help -- "
                               "nothing is sent anywhere):" % __version__]
                     + [indent + "  " + l for l in lines(engine)])


def short(readers=None):
    """One line for the settings window: the card, its memory, the RAM, Windows."""
    r = dict(windows=windows, ram=ram_mb, gpus=gpus)
    r.update(readers or {})
    cards = _safe(r["gpus"]) or []
    ram = _safe(r["ram"])
    win = _safe(r["windows"])
    bits = []
    if cards:
        g = cards[0]
        bits.append(g["name"] + ("" if g["integrated"] else " " + gb(g["total_mb"])))
        if g.get("driver"):
            bits.append("driver " + g["driver"])
    if ram:
        bits.append("RAM " + gb(ram[0]))
    if win:
        bits.append(win.split(",")[0])
    return "this PC: " + (" | ".join(bits) or "unknown")


if __name__ == "__main__":
    print(block())
