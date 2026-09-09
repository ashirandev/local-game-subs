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
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from . import service

# The models this tool knows how to fetch. A link in a readme is not the same thing: every
# gemma-4 projector is published as `mmproj-BF16.gguf`, so downloading a second model BY HAND
# either overwrites the first one's projector or lands a second file with the same name and
# nothing to say which model it belongs to. `save_as` is the whole reason this is a table and
# not a URL in a text file.
CATALOG = {
    "e4b": {"repo": "unsloth/gemma-4-E4B-it-GGUF",
            "weights": "gemma-4-E4B-it-Q4_K_M.gguf",
            "mmproj": "mmproj-BF16.gguf", "save_as": "mmproj-BF16.gguf",
            "gb": 5.9,
            "note": "the default. Steadier on names it has to spell."},
    "e2b": {"repo": "unsloth/gemma-4-E2B-it-GGUF",
            "weights": "gemma-4-E2B-it-Q4_K_M.gguf",
            "mmproj": "mmproj-BF16.gguf", "save_as": "mmproj-E2B-BF16.gguf",
            "gb": 4.1,
            "note": "smaller and faster: 0.66 s a line against 1.07 s, and 1.6 GB"
                    " more of the card left to the game. Measured on 21 frames each."},
}
DEFAULT_MODEL = "e4b"
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

FLAGS = ["-c", "8192", "-np", "1", "-ngl", "99", "-fa", "on",
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
TUNING = dict(CHOICES, size=DEFAULT_SIZE, min_hold=service.MIN_HOLD,
              read_speed=service.READ_SPEED)

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
    key = (which or DEFAULT_MODEL).lower()
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


def match_projector(weight, projectors, weights=None):
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
    """
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
    proj = match_projector(weight, projectors, weights)
    if not proj:
        raise SystemExit(
            "found %s but no projector to go with it.\n"
            "A vision model is two files: the weights and an mmproj-*.gguf. Without the second\n"
            "one the server starts, answers text, and fails on every picture." % weight)
    return os.path.join(d, weight), os.path.join(d, proj)


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
            raise SystemExit("the model server exited (code %s) before it was ready. Run it by "
                             "hand to see why." % proc.returncode)
        try:
            vc.ask("Reply with the single word: ok", image=png, max_tokens=16)
            return True
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, str(e).split("\n")[0][:100])
        time.sleep(2)
    raise SystemExit("the server never answered a question about an image.\n  last error: %s\n"
                     "  The usual cause is a missing or mismatched --mmproj: a server without one "
                     "starts fine, answers text, and fails only on pictures." % last)



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
    cmd = [exe, "-m", model, "--mmproj", mmproj, "--port", str(port),
           "--host", "127.0.0.1"] + FLAGS + list(extra or [])
    print("starting: %s\n  model: %s" % (os.path.basename(exe), os.path.basename(model)))
    out = subprocess.DEVNULL if quiet else None
    return subprocess.Popen(cmd, stdout=out, stderr=out)
