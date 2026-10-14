# -*- coding: utf-8 -*-
"""Find, download and start a local vision model, so nobody has to get the flags right by hand.

Getting a vision model serving correctly is the step where people give up, and the reason is that
**the wrong flags do not produce an error**. A server started without a projector loads cleanly,
answers a text question, reports `multimodal: true` on some builds, and then returns HTTP 500 on
the first image. So `wait_until_it_can_see()` below sends an actual picture before this module
admits the server is ready. That check is the whole point of the file.

The numbers in FLAGS are not guesses either:

    --image-max-tokens 1120   the vision position-embedding table size for this model family.
                              At 560 it misreads real text -- and reports nothing while doing it.
    --image-min-tokens 280    the floor, left open rather than pinned to the ceiling: forcing a
                              small image up to the maximum roughly doubled a subtitle read, and
                              on a path with a deadline that does not make it slow, it makes it
                              BLANK.
    -b / -ub 1152             one image must land in a single ubatch, because the vision tower is
                              non-causal. Above -ub the encode silently caps near 512, which is
                              worse than the low setting and reports nothing. So the batch size is
                              COMPUTED from the ceiling, never written beside it -- otherwise
                              raising one and forgetting the other is a silent quality drop.
"""
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request

from . import pc, service

# The models this tool knows how to fetch. A link in a readme is not the same thing: every
# gemma-4 projector is published as `mmproj-BF16.gguf`, so downloading a second model BY HAND
# either overwrites the first one's projector or lands a second file with the same name and
# nothing to say which model it belongs to. `save_as` is the whole reason this is a table and
# not a URL in a text file.
CATALOG = {
    "e4b": {"repo": "unsloth/gemma-4-E4B-it-GGUF",
            "weights": "gemma-4-E4B-it-Q4_K_M.gguf",
            "mmproj": "mmproj-BF16.gguf", "save_as": "mmproj-BF16.gguf",
            "gb": 5.9, "width": 2560,
            "note": "steadier on names it has to spell; a third slower, and 1.6 GB more of the card."},
    "e2b": {"repo": "unsloth/gemma-4-E2B-it-GGUF",
            "weights": "gemma-4-E2B-it-Q4_K_M.gguf",
            "mmproj": "mmproj-BF16.gguf", "save_as": "mmproj-E2B-BF16.gguf",
            "gb": 4.1, "width": 1536,
            "note": "the default. 0.66 s a line against 1.07 s, and 1.6 GB"
                    " more of the card left to the game. Measured on 21 frames each."},
}
# E2B since 1.0.2 (2026-10-14). It reads the same words as E4B in 6 of 7 scenes, a third faster,
# and the card is shared with a game: 3.0 GB in use against 4.6 GB (Vulkan, 8k, measured that
# day). The first two reports from players were both a server that stopped at start, and the one
# reproduced here was a card out of memory. E4B's edge is spelling names: worth choosing, not a default.
DEFAULT_MODEL = "e2b"
HF = "https://huggingface.co/%s/resolve/main"

# What `setup` fetches with no arguments. Kept as plain names because the rest of the module
# and its tests have used them since before there was a catalog.
REPO = CATALOG[DEFAULT_MODEL]["repo"]
BASE = HF % REPO
MODEL_FILE = CATALOG[DEFAULT_MODEL]["weights"]
MMPROJ_FILE = CATALOG[DEFAULT_MODEL]["save_as"]

IMG_CEIL = 1120
IMG_FLOOR = 280
IMG_UB = IMG_CEIL + 32          # derived, never a literal -- see the note above

# No -ngl. With "-ngl 99" llama.cpp is told to put every layer on the card and refuses to fit:
# on a card with too little free memory it says "failed to fit params to free device memory:
# n_gpu_layers already set by user to 99, abort" and exits with code 1 -- which is all a player
# saw (2026-10-14, a report to the page). Left out, llama.cpp fits the model to the free memory
# itself. Measured the same day on an RTX 5070 Ti, Vulkan, this model at 8k: 4577 MB used with
# and without it, so a card with room keeps every layer and the same speed; a request that died
# with it (-c 1048576) started without it.
FLAGS = ["-c", "8192", "-np", "1", "-fa", "on",
         "-b", str(IMG_UB), "-ub", str(IMG_UB),
         "--image-min-tokens", str(IMG_FLOOR), "--image-max-tokens", str(IMG_CEIL),
         # Leaving this out cost 4x. With reasoning on, the model writes out its thinking before
         # it answers, and for a one-line subtitle that thinking is most of the work: measured
         # 2.5 s per line with it, 0.6 s without, same model, same card, same everything else.
         # It never errors and the answers stay correct, so nothing points at it -- the tool is
         # simply four times too slow to keep up with dialogue. Set on the server here AND per
         # request in vision.py, because either one alone can be overridden by the other.
         "--reasoning", "off"]

WINDOWS = sys.platform == "win32"
EXE = "llama-server.exe" if WINDOWS else "llama-server"


def app_dir():
    """The one folder this tool keeps everything in.

    Everything it downloads -- the model, its projector, llama.cpp -- lands beside the scripts you
    double-click, so uninstalling is deleting the folder. Nothing is written to your home
    directory, your registry, or anywhere else, and nothing is left behind.

    That matters more than it sounds: 5.7 GB parked in a hidden folder under your home directory,
    after you have deleted the tool that put it there, is the kind of thing you find two years
    later while hunting for disk space.

    Falls back to `~/.local-game-subs` only when the package is installed somewhere unwritable,
    which is what a `pip install` into system site-packages looks like. `GAMESUBS_HOME` overrides
    both.
    """
    env = os.getenv("GAMESUBS_HOME")
    if env:
        return env
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    marker = any(os.path.isfile(os.path.join(root, f))
                 for f in ("setup.bat", "pyproject.toml", "README.md"))
    if marker and os.access(root, os.W_OK):
        return root
    return os.path.join(os.path.expanduser("~"), ".local-game-subs")


def home(sub=""):
    d = os.path.join(app_dir(), sub)
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


SETTINGS = "settings.json"

# Everything the control panel owns. ONE COPY OF EACH: the two that also belong to the
# translator are imported from it rather than typed again, because a default that exists twice
# disagrees with itself the first time somebody changes one of them, and nothing goes red.
DEFAULT_SIZE = 28
LIMITS = {"size": (14, 64), "min_hold": (0.0, 5.0), "read_speed": (6.0, 40.0)}
# Free text rather than a slider. "" means "decide for me", which is what every one of these
# meant before there was a panel, and still has to mean when settings.json does not exist.
# The font is NOT here. It has had its own key since before there was a panel, and a
# second copy of it would be two answers to one question -- the loser being whichever
# process happens to read the other one. The panel writes it through save_font().
CHOICES = {"model": "", "lang": "Thai",
           "text_colour": "#ffffff", "plate_colour": "#000000"}
# On/off, stored as JSON booleans. NOT called FLAGS: that name is taken by the
# llama-server argv list a few lines down, and taking it turned every test that reads
# those flags into an AttributeError on a dict.
#
# `record` is two changes at once and they only make sense together: stop hiding from
# screen capture, and move the plate off the watched box. Either alone is a broken
# recording -- invisible, or a feedback loop.
SWITCHES = {"record": False}
TUNING = dict(CHOICES, size=DEFAULT_SIZE, min_hold=service.MIN_HOLD,
              read_speed=service.READ_SPEED, **SWITCHES)

# What the panel offers. Any #rrggbb is accepted from the file -- these are just the swatches.
TEXT_SWATCHES = ["#ffffff", "#ffe27a", "#a8e6a1", "#9fd8ff", "#ffb0b0"]
PLATE_SWATCHES = ["#000000", "#141414", "#101828", "#1a1010", "#0d1a0d"]


def is_colour(v):
    """True for a #rrggbb string and nothing else. -> bool"""
    return (isinstance(v, str) and len(v) == 7 and v[0] == "#"
            and all(c in "0123456789abcdefABCDEF" for c in v[1:]))


def clamp_tuning(d):
    """Keep only the known keys, in the right type, inside their range. -> dict

    settings.json is a file a person can open and type in, and every value in it is read by a
    DIFFERENT process from the one that wrote it -- so a bad value does not fail where anyone
    would connect it to what they just did. A hand-typed 0 in `read_speed` is a division by zero
    in the translator. Everything that reads this file comes through here.
    """
    d = d or {}
    out = dict(TUNING)
    for k, lo_hi in LIMITS.items():
        v = d.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        out[k] = type(TUNING[k])(max(lo_hi[0], min(lo_hi[1], v)))
    for k in SWITCHES:
        if isinstance(d.get(k), bool):
            out[k] = d[k]
    for k in CHOICES:
        v = d.get(k)
        if not isinstance(v, str) or len(v) > 400:
            continue
        if k.endswith("_colour") and not is_colour(v):
            continue
        out[k] = v
    return out


def load_tuning():
    return clamp_tuning(load_settings().get("tuning"))


def save_tuning(d):
    s = load_settings()
    s["tuning"] = clamp_tuning(d)
    save_settings(s)
    return s["tuning"]


def settings_stamp():
    """Changes whenever settings.json does. (0, 0) when there is no file yet.

    Size as well as time: two writes inside the same filesystem timestamp tick are ordinary when
    a slider is being dragged, and on Windows that tick can be milliseconds wide.
    """
    try:
        st = os.stat(os.path.join(app_dir(), SETTINGS))
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return (0, 0)


def load_settings():
    """Whatever was saved last time, or {} -- a missing or broken file is not worth an error."""
    try:
        with open(os.path.join(app_dir(), SETTINGS), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_settings(d):
    """Write via a temp file and replace, so an interruption cannot leave a half-written file.

    A truncated settings.json is worse than none: the tool would start ignoring a box the user
    chose, with nothing on screen to say why.

    AND THE TIMESTAMP IS FORCED FORWARD. Two other processes decide whether to re-read this
    file by comparing (mtime, size), and the panel writes it whenever a control settles --
    which can be twice inside one filesystem timestamp tick. Same tick and same length is a
    write nobody sees: the subtitle keeps the old colour until something else happens to
    change the file, and there is nothing on screen or in a log to say why. Found by a test
    that saved twice in a row.
    """
    p = os.path.join(app_dir(), SETTINGS)
    try:
        before = os.stat(p).st_mtime_ns
    except OSError:
        before = 0
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, p)
    try:
        st = os.stat(p)
        if st.st_mtime_ns <= before:
            os.utime(p, ns=(st.st_atime_ns, before + 1000000))
    except OSError:
        pass


def load_font():
    """The font chosen last time, or None."""
    f = load_settings().get("font")
    return f if isinstance(f, str) and f else None


def save_font(path):
    d = load_settings()
    d["font"] = path
    save_settings(d)
    return path


def load_region():
    """The saved capture box as (left, top, width, height), or None."""
    r = load_settings().get("region")
    if isinstance(r, list) and len(r) == 4 and all(isinstance(v, int) for v in r) \
            and r[2] > 0 and r[3] > 0:
        return tuple(r)
    return None


def save_region(box):
    d = load_settings()
    d["region"] = [int(v) for v in box]
    save_settings(d)
    return d["region"]


def find_server(explicit=None):
    """Locate llama-server. Returns a path or None."""
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    on_path = shutil.which(EXE)
    if on_path:
        return on_path
    for d in (home("llama.cpp"), os.path.join(os.path.expanduser("~"), "llama.cpp"),
              r"C:\llama.cpp" if WINDOWS else "/usr/local/bin"):
        if not os.path.isdir(d):
            continue
        for base, _, files in os.walk(d):
            if EXE in files:
                return os.path.join(base, EXE)
    return None


def backend_of(exe):
    """Which build an existing llama-server came from, read from the folder it was unpacked into.

    Worth knowing, and not otherwise knowable: a Vulkan build and a CUDA build are the same
    filename and the same version string, and on this machine they differ by SIX TIMES in speed.
    An already-installed server is skipped by setup, so without this a slow build stays in place
    silently and the tool just feels sluggish for no visible reason.
    """
    parts = os.path.normpath(exe).lower().split(os.sep)
    for b in BACKENDS:
        if b in parts:
            return b
    return None


def _human(n):
    return "%.1f GB" % (n / 1073741824.0) if n >= 1073741824 else "%.0f MB" % (n / 1048576.0)


def sha256_of(path, chunk=1 << 22):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def verify(path, expected, label):
    """Check a downloaded file against a hash the PUBLISHER gave us, and delete it if it differs.

    The hash never comes from this repository. Hugging Face reports it as `lfs.oid` and GitHub as
    the release asset's `digest`, both over HTTPS from the same host that serves the file. A
    checksum I typed into this file would only prove the file matches what I downloaded once --
    it would tell you nothing about whether I am trustworthy, which is the actual question.

    Deleting on mismatch rather than warning: a corrupt 5 GB model that stays on disk gets used,
    and it fails later as something that looks like a model problem.
    """
    got = sha256_of(path)
    if expected and got != expected.lower():
        os.remove(path)
        raise SystemExit(
            "%s did not match the checksum the publisher lists, so it was deleted.\n"
            "  expected %s\n  got      %s\n"
            "  Usually this means the download was interrupted in a way that could not be\n"
            "  resumed, or that a file of the same name from somewhere else was already in that\n"
            "  folder -- a different build of the same model has a different hash. Run setup\n"
            "  again to fetch a clean copy." % (label, expected, got))
    print("    sha256 %s%s" % (got, "  (matches the publisher)" if expected else ""))
    return got


def download(url, dest, label, sha256=None):
    """Resumable download with a progress line. Refuses to guess at a missing size."""
    have = os.path.getsize(dest) if os.path.isfile(dest) else 0
    req = urllib.request.Request(url, headers={"User-Agent": "local-game-subs"})
    if have:
        req.add_header("Range", "bytes=%d-" % have)
    try:
        r = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code == 416 and have:
            print("  %s already complete (%s)" % (label, _human(have)))
            verify(dest, sha256, label)
            return dest
        raise
    total = r.headers.get("Content-Length")
    if total is None:
        r.close()
        raise SystemExit("the server did not report a size for %s -- refusing to guess whether a "
                         "partial file is complete." % label)
    # Decide whether the range was honoured BEFORE using `have` for anything else. A 206 means
    # Content-Length is what REMAINS, so the real total is that plus what is on disk. A plain 200
    # means the server ignored the request and is sending the whole file, so what is on disk must
    # be discarded -- appending to it would produce a file of plausible size and wrong contents,
    # which then fails much later as an unrelated model error.
    if have and getattr(r, "status", 200) != 206:
        have = 0
    total = int(total) + have
    mode = "ab" if have else "wb"
    print("  %s -> %s%s" % (label, _human(total), "  (resuming)" if have else ""))
    got, t0, last = have, time.time(), 0.0
    with open(dest, mode) as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if time.time() - last > 0.5:
                last = time.time()
                mb = got / 1048576.0 / max(time.time() - t0, 0.001)
                sys.stdout.write("\r    %5.1f%%  %s / %s   %.1f MB/s   "
                                 % (100.0 * got / total, _human(got), _human(total), mb))
                sys.stdout.flush()
    r.close()
    print("\r    done: %s%s" % (_human(got), " " * 30))
    if got != total:
        raise SystemExit("%s ended at %s, expected %s -- run setup again to resume."
                         % (label, _human(got), _human(total)))
    verify(dest, sha256, label)
    return dest


def hf_checksums(repo=None):
    """Hugging Face's own SHA-256 for each file, from its API. {} if the call fails.

    Empty rather than fatal on failure: a checksum you cannot fetch is a reason to show the hash
    and let the user compare it, not a reason to refuse to install.
    """
    try:
        req = urllib.request.Request("https://huggingface.co/api/models/%s/tree/main"
                                     % (repo or REPO),
                                     headers={"User-Agent": "local-game-subs"})
        with urllib.request.urlopen(req, timeout=30) as r:
            tree = json.load(r)
    except Exception:
        return {}
    return {f["path"]: (f.get("lfs") or {}).get("oid") for f in tree if (f.get("lfs") or {}).get("oid")}


def fetch_model(dest_dir=None, which=None):
    """Download a catalog model and its vision projector. Returns (model, mmproj).

    The projector is saved under the catalog's `save_as`, not under the name it has
    upstream. Every gemma-4 projector is called `mmproj-BF16.gguf` there, so a second model
    fetched under its own name would overwrite the first model's projector -- silently,
    with a file of almost exactly the same size.
    """
    d = dest_dir or home("models")
    key = (which or setup_default(d)).lower()
    if key not in CATALOG:
        raise SystemExit("no model called %r. Known: %s"
                         % (which, ", ".join(sorted(CATALOG))))
    e = CATALOG[key]
    print("downloading %s into %s" % (e["repo"], d))
    print("(about %.1f GB in total -- it resumes if you stop it)" % e["gb"])
    print("  %s" % (HF % e["repo"]))
    sums = hf_checksums(e["repo"])
    if not sums:
        print("  (could not fetch checksums from Hugging Face -- the hashes below are"
              " still printed, compare them against the model page)")
    print("")
    base = HF % e["repo"]
    m = download("%s/%s" % (base, e["weights"]), os.path.join(d, e["weights"]),
                 e["weights"], sums.get(e["weights"]))
    # The projector is a SEPARATE file. Without it the server starts, answers text, and fails
    # on the first image -- which is why it is downloaded here rather than left as a footnote.
    p = download("%s/%s" % (base, e["mmproj"]), os.path.join(d, e["save_as"]),
                 e["save_as"], sums.get(e["mmproj"]))
    return m, p


def setup_default(dest_dir=None):
    """Which model `setup` with no name means: the catalog model already in the folder, else the default.

    Since the default moved to E2B, a player who has E4B and is told "run setup again: it checks
    every file and downloads what is broken" would otherwise get a second model of 4 GB, and the
    broken one left as it was. Setup repairs what you have; it does not swap it.
    """
    d = dest_dir or home("models")
    have = [k for k, e in CATALOG.items() if os.path.isfile(os.path.join(d, e["weights"]))]
    return DEFAULT_MODEL if (DEFAULT_MODEL in have or not have) else sorted(have)[0]


def local_model(dest_dir=None):
    """The downloaded pair, or (None, None) if setup has not been run."""
    d = dest_dir or home("models")
    m, p = os.path.join(d, MODEL_FILE), os.path.join(d, MMPROJ_FILE)
    return (m, p) if os.path.isfile(m) and os.path.isfile(p) else (None, None)


def _tokens(name):
    out, cur = [], ""
    for ch in os.path.basename(name).lower():
        if ch.isalnum():
            cur += ch
        elif cur:
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return [t for t in out if t not in ("gguf", "it", "bf16", "f16", "f32")]


# GGUF value types that are one fixed-size number, by their type id in the header.
_GGUF_FIXED = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?",
               10: "<Q", 11: "<q", 12: "<d"}
_GGUF_INTS = (0, 1, 2, 3, 4, 5, 10, 11)


def _gguf_str(f):
    n = struct.unpack("<Q", f.read(8))[0]
    return f.read(n).decode("utf-8")


def _gguf_skip(f, kind):
    if kind in _GGUF_FIXED:
        f.seek(struct.calcsize(_GGUF_FIXED[kind]), 1)
    elif kind == 8:
        f.seek(struct.unpack("<Q", f.read(8))[0], 1)
    elif kind == 9:
        sub, n = struct.unpack("<IQ", f.read(12))
        if sub in _GGUF_FIXED:
            f.seek(n * struct.calcsize(_GGUF_FIXED[sub]), 1)
        else:
            for _ in range(n):
                _gguf_skip(f, sub)
    else:
        raise ValueError("unknown GGUF value type %d" % kind)


def gguf_width(path):
    """The width a model file talks in, read from its own header. -> int, or None

    A text model's is `<architecture>.embedding_length`. A vision projector's is
    `clip.vision.projection_dim` -- the width of what it hands the text model. The two must be
    equal, and llama-server checks: a pair that differs exits with code 1 before it opens a port.
    Measured on the files `setup` fetches -- E2B 1536 and its projector 1536, E4B 2560 and its
    projector 2560 -- and on a user's folder, 2026-09-27, where an E2B dropped in by hand had been
    paired with the E4B projector because the names could not tell them apart.

    NAMES CANNOT. `gemma` and `4` are in both models' names and in any projector named after
    either, so name matching hands E2B the E4B projector whenever E2B's own is missing. The
    header is the file saying what it is.

    None means "could not tell" -- not a GGUF, the old version-1 layout, or a family that does
    not write the key -- and every caller treats that as no evidence either way, never as a
    mismatch. Only the header is read: the loop stops at the key, which the files seen so far all
    put ahead of the tokenizer's quarter-million strings.
    """
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"GGUF":
                return None
            version, _tensors, count = struct.unpack("<IQQ", f.read(20))
            if version < 2:
                return None
            arch = None
            for _ in range(count):
                key = _gguf_str(f)
                kind = struct.unpack("<I", f.read(4))[0]
                if key == "general.architecture" and kind == 8:
                    arch = _gguf_str(f)
                    continue
                if kind in _GGUF_INTS and (key == "clip.vision.projection_dim"
                                           or (arch and key == arch + ".embedding_length")):
                    fmt = _GGUF_FIXED[kind]
                    return int(struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0])
                _gguf_skip(f, kind)
    except (OSError, ValueError, struct.error, UnicodeDecodeError):
        return None
    return None


def _fits(weight_path, projector_path):
    """False only when BOTH headers answered and the answers differ."""
    a, b = gguf_width(weight_path), gguf_width(projector_path)
    return a is None or b is None or a == b


def match_projector(weight, projectors, weights=None, folder=None):
    """Pick the projector that belongs to a given model file.

    A vision model is two files, and they must be from the same model. Pairing them wrongly
    is not a loud failure: the server starts, answers text, and then reads pictures out of
    nothing -- which looks like a bad model rather than a bad pairing.

    Matched on shared name fragments rather than on order, because a folder people drop files
    into has no order.

    THEN THE PART THAT NAME MATCHING CANNOT DO. Upstream ships every gemma-4 projector under
    the same filename -- `mmproj-BF16.gguf` -- so it carries no fragment of the model it
    belongs to. Add a second model and rename ITS projector to tell them apart, and the
    original one now matches nothing and comes back None: following the folder's own
    instructions breaks the model that was working. So when a name says nothing, fall back
    to elimination -- a projector no OTHER model has a claim on is the one left for this
    model. `weights` is the rest of the folder; without it this behaves as it always did.

    There is deliberately no `len(projectors) == 1` shortcut. It reads like the obvious
    fast path and it is wrong: one projector whose name belongs to a DIFFERENT model in
    the folder should be refused, not handed over. Elimination says that; the shortcut
    says "there is only one, take it" and produces a server that answers text and reads
    pictures out of nothing.

    `folder` is where the files are, and with it the headers get a veto: a projector whose
    width differs from the model's is dropped before any name is compared, because no name can
    make that pair start (see `gguf_width`). It is a veto and nothing more -- two files of the
    same width are not proven to belong together, so the rules above still choose among the
    projectors that are left.
    """
    if folder:
        projectors = [p for p in projectors
                      if _fits(os.path.join(folder, weight), os.path.join(folder, p))]
    if not projectors:
        return None
    want = set(_tokens(weight))
    best = max(projectors, key=lambda p: (len(want & set(_tokens(p))), -len(p)))
    if want & set(_tokens(best)):
        return best
    claimed = set()
    for other in weights or []:
        theirs = set(_tokens(other))
        for pr in projectors:
            if theirs & set(_tokens(pr)):
                claimed.add(pr)
    left = [pr for pr in projectors if pr not in claimed]
    return left[0] if len(left) == 1 else None


def list_models(dest_dir=None):
    """(weights, projectors) found in the models folder. Anything a user dropped in counts."""
    d = dest_dir or home("models")
    try:
        files = sorted(f for f in os.listdir(d) if f.lower().endswith(".gguf"))
    except OSError:
        return [], []
    proj = [f for f in files if "mmproj" in f.lower()]
    return [f for f in files if f not in proj], proj


def resolve_model(choice=None, dest_dir=None):
    """(model_path, projector_path) for `choice`, or for the only candidate. Raises if unclear."""
    d = dest_dir or home("models")
    weights, projectors = list_models(d)
    if not weights:
        raise SystemExit(
            "no model files found in\n  %s\n"
            "Run `python -m gamesubs setup` to download one, or drop any vision GGUF in that\n"
            "folder together with its mmproj-*.gguf projector." % d)
    if choice:
        hit = [w for w in weights if w == choice or os.path.basename(choice) == w]
        if not hit:
            raise SystemExit("no model called %r in %s. Found: %s"
                             % (choice, d, ", ".join(weights)))
        weight = hit[0]
    elif len(weights) == 1:
        weight = weights[0]
    else:
        raise SystemExit("more than one model in %s -- pick one with --model-file:\n  %s"
                         % (d, "\n  ".join(weights)))
    proj = match_projector(weight, projectors, weights, d)
    if not proj:
        raise SystemExit(_no_projector(weight, projectors, d))
    return os.path.join(d, weight), os.path.join(d, proj)


def pairs(dest_dir=None):
    """Every model in the folder with the projector it would start with.
    -> [(weight, projector or None, why there is none or "")]

    The picker's list. It asks the same question `resolve_model` asks, through the same
    function, so the window can never offer a pair that the start then refuses -- or start a
    pair the header already said cannot work -- and it gives the same reason in the same words.
    """
    d = dest_dir or home("models")
    weights, projectors = list_models(d)
    out = []
    for w in weights:
        p = match_projector(w, projectors, weights, d)
        out.append((w, p, "" if p else _no_projector(w, projectors, d)))
    return out


def _no_projector(weight, projectors, d):
    """Why there is no projector for `weight`, in words that say what to do next."""
    want = gguf_width(os.path.join(d, weight))
    wrong = [(p, gguf_width(os.path.join(d, p))) for p in projectors]
    wrong = [(p, w) for p, w in wrong if want and w and w != want]
    if not wrong:
        return ("found %s but no projector to go with it.\n"
                "A vision model is two files: the weights and an mmproj-*.gguf. Without the second\n"
                "one the server starts, answers text, and fails on every picture." % weight)
    lines = ["%s has no projector that fits it." % weight,
             "Its header says it is %d wide, and a projector has to match:" % want]
    lines += ["  %s is %d wide -- it belongs to a different model" % (p, w) for p, w in wrong]
    same = [k for k, e in CATALOG.items() if e.get("width") == want]
    if same:
        lines.append("This looks like %s. Get the pair that goes together with:\n"
                     "  python -m gamesubs setup --model-name %s" % (same[0].upper(), same[0]))
    else:
        lines.append("Download the mmproj-*.gguf published beside this model and put it in\n  %s" % d)
    return "\n".join(lines)


def _probe_png():
    """A small real PNG. A flat image is a plausible thing for a broken encoder to accept."""
    from PIL import Image
    import io as _io
    im = Image.new("RGB", (64, 64))
    px = im.load()
    for y in range(64):
        for x in range(64):
            px[x, y] = (x * 4, y * 4, 128)
    b = _io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def wait_until_it_can_see(base_url, model="local", timeout=300, proc=None):
    """Block until the server answers a question ABOUT A PICTURE.

    Not until the port opens, and not until it answers text. Both of those go green on a server
    with no projector loaded, which then fails on every real frame. This is the difference between
    "it started" and "it works", and it is worth the one small image it costs.
    """
    from .vision import VisionClient
    vc = VisionClient(base_url, model, timeout=30)
    end = time.time() + timeout
    png, last = _probe_png(), "no attempt yet"
    while time.time() < end:
        if proc is not None and proc.poll() is not None:
            raise SystemExit(_stopped(proc))
        try:
            vc.ask("Reply with the single word: ok", image=png, max_tokens=16)
            return True
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, str(e).split("\n")[0][:100])
        time.sleep(2)
    raise SystemExit("the server never answered a question about an image.\n  last error: %s\n"
                     "  The usual cause is a missing or mismatched --mmproj: a server without one "
                     "starts fine, answers text, and fails only on pictures.\n%s"
                     % (last, pc.block(engine_line(getattr(proc, "args", [None])[0]))))



LLAMA_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=12"

# Backend -> the substring identifying its Windows asset, and the separate CUDA runtime zip when
# that backend needs one. Vulkan is the default: 34 MB against 515 MB, no runtime to match to a
# driver, and it works on NVIDIA, AMD and Intel alike. What that costs in speed is in the README.
BACKENDS = {
    "vulkan": ("bin-win-vulkan-x64", None),
    "cuda": ("bin-win-cuda-13.3-x64", "cudart-llama-bin-win-cuda-13.3-x64"),
    "cpu": ("bin-win-cpu-x64", None),
}


def _latest_build():
    """The newest release that actually carries binaries.

    Deliberately NOT /releases/latest. That endpoint answers with a tag holding a single asset
    and no llama-server anywhere in it; the builds live in the b-numbered releases. Asking the
    obvious endpoint hands a new user a download that cannot possibly work.
    """
    req = urllib.request.Request(LLAMA_API, headers={"User-Agent": "local-game-subs"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rels = json.load(r)
    for rel in rels:
        if rel.get("tag_name", "").startswith("b") and \
                any(a["name"].startswith("llama-") for a in rel["assets"]):
            return rel
    raise SystemExit("no llama.cpp build release found. Download one by hand from "
                     "https://github.com/ggml-org/llama.cpp/releases")


def pick_assets(names, backend):
    """Which files to download for `backend`, binary first. Empty when nothing matches.

    Separated out and tested because it got this wrong on the first run, in a way that would have
    downloaded 373 MB and produced no llama-server at all: asking for the CUDA build by the
    substring `bin-win-cuda-13.3-x64` ALSO matches `cudart-llama-bin-win-cuda-13.3-x64.zip`, the
    runtime package. Two files, one substring, and the wrong one sorts first.

    So the binary is identified by BOTH the platform substring and the `llama-` prefix, and the
    runtime by its own full prefix.
    """
    want, runtime = BACKENDS[backend]
    out = [n for n in names if want in n and n.startswith("llama-")]
    if out and runtime:
        # The CUDA build ships WITHOUT the CUDA runtime DLLs, and missing them llama-server does
        # not explain itself: a DLL error box, or on some systems nothing at all.
        out += [n for n in names if n.startswith(runtime)]
    return out


def fetch_llama(backend="vulkan", dest_dir=None):
    """Download and unzip llama.cpp's Windows build. Returns the path to llama-server.exe."""
    import zipfile
    if not WINDOWS:
        raise SystemExit("automatic download is Windows-only. Install or build llama.cpp for your "
                         "platform, then pass --llama-server /path/to/llama-server")
    if backend not in BACKENDS:
        raise SystemExit("unknown backend %r. Pick one of: %s"
                         % (backend, ", ".join(sorted(BACKENDS))))
    rel = _latest_build()
    # One folder per backend. Same filename, same version string, six times the speed between
    # them -- so which build this is has to be readable from somewhere, and the path is the one
    # place that survives unzipping.
    d = dest_dir or os.path.join(home("llama.cpp"), backend)
    if not os.path.isdir(d):
        os.makedirs(d)
    names = {a["name"]: a["browser_download_url"] for a in rel["assets"]}
    todo = pick_assets(sorted(names), backend)
    if not todo:
        raise SystemExit("release %s has no asset for the %s backend. It has:%s  %s%sDownload one "
                         "by hand from %s"
                         % (rel["tag_name"], backend, os.linesep,
                            (os.linesep + "  ").join(sorted(names)), os.linesep, rel["html_url"]))
    print("llama.cpp %s, %s build" % (rel["tag_name"], backend))
    # GitHub reports each asset's own sha256 in the release metadata, so the binary is checked
    # against the same host that published it.
    digests = {a["name"]: (a.get("digest") or "").replace("sha256:", "") for a in rel["assets"]}
    for n in todo:
        z = os.path.join(d, n)
        download(names[n], z, n, digests.get(n) or None)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(d)
        os.remove(z)
    for base, _, files in os.walk(d):
        if EXE in files:
            return os.path.join(base, EXE)
    raise SystemExit("unzipped %s but found no %s inside it." % (todo[0], EXE))


def has_nvidia():
    """True when nvidia-smi answers -- the only question that decides cuda vs vulkan."""
    return gpu_used_mb() is not None


def gpu_used_mb():
    """Total GPU memory in use right now, in MB, or None when nvidia-smi is not available.

    Reported rather than computed: the file sizes tell you what the weights take and say nothing
    about the KV cache, the vision tower's working set, or whatever else is on the card. People
    sizing a machine need the number that actually shows up.
    """
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, timeout=10)
    except Exception:
        return None
    try:
        return sum(int(x) for x in out.decode().split())
    except ValueError:
        return None


def start(model=None, mmproj=None, exe=None, port=8080, extra=None, quiet=True):
    """Start llama-server with the flags this model actually needs. Returns the Popen."""
    exe = find_server(exe)
    if not exe:
        raise SystemExit(
            "llama-server was not found.\n"
            "  Get a build from https://github.com/ggml-org/llama.cpp/releases (pick the one for\n"
            "  your GPU), unzip it, and either put it on your PATH or drop it in:\n"
            "    %s\n"
            "  Or point at it directly:  --llama-server C:\\path\\to\\%s" % (home("llama.cpp"), EXE))
    if not model:
        model, mmproj = local_model()
        if not model:
            raise SystemExit("no model found. Run:  python -m gamesubs setup")
    if mmproj and not _fits(model, mmproj):
        # Both routes here -- the picker and `resolve_model` -- already asked the header. This is
        # for the route that gets added later and does not: the last place a mismatch can be said
        # in words, because after it the only report is llama-server exiting with code 1 behind a
        # hidden window.
        raise SystemExit("%s (%s wide) and %s (%s wide) are not a pair -- the projector belongs "
                         "to a different model." % (os.path.basename(model), gguf_width(model),
                                                    os.path.basename(mmproj), gguf_width(mmproj)))
    # A free port, not 8080 because it is the default: a player's 1.0.2 screenshot (2026-10-14)
    # said "couldn't bind HTTP server socket ... port: 8080" and code 1 -- something else on that
    # PC held it. The caller reads proc.port for the address.
    asked, port = port, free_port(port)
    cmd = [exe, "-m", model, "--mmproj", mmproj, "--port", str(port),
           "--host", "127.0.0.1"] + FLAGS + list(extra or [])
    print("starting: %s\n  model: %s" % (os.path.basename(exe), os.path.basename(model)))
    if port != asked:
        print("  port %d is in use by another program, so the model uses %d" % (asked, port))
    if not quiet:
        proc = subprocess.Popen(cmd)
    else:
        # Never DEVNULL. The server says why it stopped, and throwing that away left a player with
        # "exited (code 1). Run it by hand to see why" -- which nobody does. Kept in the folder,
        # one file, overwritten each start, never sent anywhere.
        log = open(server_log(), "w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
        log.close()                 # the server holds its own handle; ours is not needed
        proc.log_path = log.name
    proc.port = port
    return proc


PORT_SCAN = 50


def free_port(preferred):
    """`preferred` if nothing on this PC is listening there, else the next free one above it.

    Asked by binding, not by connecting: Windows reserves whole port ranges for Hyper-V and WSL
    where nothing answers a connection and nothing else may listen either.
    """
    import socket
    for p in range(preferred, preferred + PORT_SCAN):
        s = socket.socket()
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s.bind(("127.0.0.1", p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    return preferred                # all taken: the server will say so, and why_it_stopped reads it


def server_log():
    return os.path.join(home("logs"), "llama-server.log")


# What the server's own words mean, for a player. (words to look for, why, what to try). The first
# row is a measured message (2026-10-14, Vulkan, a card out of memory); the rest are llama.cpp's
# wording for the other ways a start fails. Lower case, matched anywhere in the log.
WHY = [
    (("erroroutofdevicememory", "failed to allocate", "out of memory", "failed to fit params"),
     "the graphics card ran out of memory for this model.",
     "Close other programs that use the card (a game that is already running counts). On E4B,\n"
     "  the smaller E2B in the settings window needs 1.6 GB less."),
    (("no vulkan devices", "vulkan: no devices", "failed to initialize vulkan", "vk::createinstance",
      "no usable gpu"),
     "no graphics card that the engine can use was found.",
     "Update the graphics driver from NVIDIA, AMD or Intel and try again."),
    # Measured: a player's 1.0.2 screenshot, 2026-10-14, code 1. start() now picks a free port, so
    # this is left for a port taken in the instant between that check and the server's own bind.
    (("couldn't bind http server socket", "could not bind http server socket"),
     "another program on this PC took the port the engine was about to use.",
     "Start it again: it looks for a free port each time."),
    (("unknown model architecture",),
     "this llama.cpp is too old for the model.",
     "Run setup again to get a newer llama.cpp."),
    # Not a bare "flash_attn": some builds print "flash_attn = auto" on every healthy start.
    (("flash attention is not supported", "flash_attn is not supported", "flash attention not supported"),
     "the graphics card cannot run the engine's fast attention.",
     "Update the graphics driver. If that does not help, send the file below."),
    (("failed to load model", "gguf_init", "invalid magic"),
     "the model file could not be read; it may be incomplete.",
     "Run setup again: it checks every file and downloads what is broken."),
]
# Windows exit codes that carry a meaning of their own, for when the log says nothing we know.
CODES = {
    0xC0000409: ("the engine crashed inside the graphics driver or its own code.",
                 "Update the graphics driver. If it still crashes, send the file below."),
    0xC000001D: ("this processor lacks an instruction the engine was built for.",
                 "Run setup with --backend cpu, or send the file below."),
    0xC0000135: ("a Windows file the engine needs is missing.",
                 "Install the Microsoft Visual C++ Redistributable (x64), then try again."),
    0xC0000005: ("the engine crashed (it read memory it should not).",
                 "Update the graphics driver. If it still crashes, send the file below."),
}


def why_it_stopped(code, text):
    """(why, what to try) for a server that exited before it was ready, from its own words first
    and its exit code second. Never empty: an unknown failure still says where its words are."""
    low = (text or "").lower()
    for words, why, act in WHY:
        if any(w in low for w in words):
            return why, act
    hit = CODES.get((code or 0) & 0xFFFFFFFF)
    if hit:
        return hit
    return ("the engine stopped and did not say why in words this program knows.",
            "Send the file below when you ask for help.")


def _stopped(proc):
    code = proc.returncode
    path = getattr(proc, "log_path", None)
    text = ""
    if path:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            pass
    why, act = why_it_stopped(code, text)
    shown = "%s (0x%08X)" % (code, code & 0xFFFFFFFF) if code and code > 255 else str(code)
    msg = ["the model server stopped before it was ready (code %s)." % shown,
           "  why: %s" % why, "  what to try: %s" % act]
    tail = [l for l in text.splitlines() if l.strip()][-8:]
    if tail:
        msg += ["  the server's last words:"] + ["    " + l[:150] for l in tail]
    if path:
        msg.append("  all of them: %s" % path)
    # Beside the error, not only at the top of the console: by the time it stops, the start of the
    # window has scrolled away, and this screenshot is the one a player sends.
    args = getattr(proc, "args", None)
    msg.append(pc.block(engine_line(args[0] if args else None)))
    return "\n".join(msg)


def engine_line(exe):
    """'llama.cpp vulkan, build 10796': which build from its folder, which version from the server.

    Asked with --version (0.9 s), because the server's log does not say: build 10796 starts
    straight in with its settings (measured 2026-10-14), and "is this llama.cpp too old for the
    model" is a question a screenshot should answer.
    """
    if not exe:
        return None
    build = None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        build = re.search(r"\bbuild (\d+)", (out.stdout + out.stderr).decode("utf-8", "replace"))
    except Exception:
        pass
    return "llama.cpp %s%s" % (backend_of(exe) or os.path.dirname(exe),
                               ", build %s" % build.group(1) if build else "")
