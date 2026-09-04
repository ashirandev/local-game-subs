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

REPO = "unsloth/gemma-4-E4B-it-GGUF"
BASE = "https://huggingface.co/%s/resolve/main" % REPO
MODEL_FILE = "gemma-4-E4B-it-Q4_K_M.gguf"
MMPROJ_FILE = "mmproj-BF16.gguf"

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


def home(sub=""):
    d = os.path.join(os.path.expanduser("~"), ".local-game-subs", sub)
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


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


def hf_checksums():
    """Hugging Face's own SHA-256 for each file, from its API. {} if the call fails.

    Empty rather than fatal on failure: a checksum you cannot fetch is a reason to show the hash
    and let the user compare it, not a reason to refuse to install.
    """
    try:
        req = urllib.request.Request("https://huggingface.co/api/models/%s/tree/main" % REPO,
                                     headers={"User-Agent": "local-game-subs"})
        with urllib.request.urlopen(req, timeout=30) as r:
            tree = json.load(r)
    except Exception:
        return {}
    return {f["path"]: (f.get("lfs") or {}).get("oid") for f in tree if (f.get("lfs") or {}).get("oid")}


def fetch_model(dest_dir=None):
    """Download the model and its vision projector. Returns (model, mmproj)."""
    d = dest_dir or home("models")
    print("downloading %s into %s" % (REPO, d))
    print("(about 5.7 GB in total -- it resumes if you stop it)\n")
    sums = hf_checksums()
    if not sums:
        print("  (could not fetch checksums from Hugging Face -- the hashes below are still\n"
              "   printed, compare them against the file listing on the model page)\n")
    m = download("%s/%s" % (BASE, MODEL_FILE), os.path.join(d, MODEL_FILE), MODEL_FILE,
                 sums.get(MODEL_FILE))
    # The projector is a SEPARATE file. Without it the server starts, answers text, and fails on
    # the first image -- which is why it is downloaded here rather than left as a footnote.
    p = download("%s/%s" % (BASE, MMPROJ_FILE), os.path.join(d, MMPROJ_FILE), MMPROJ_FILE,
                 sums.get(MMPROJ_FILE))
    return m, p


def local_model(dest_dir=None):
    """The downloaded pair, or (None, None) if setup has not been run."""
    d = dest_dir or home("models")
    m, p = os.path.join(d, MODEL_FILE), os.path.join(d, MMPROJ_FILE)
    return (m, p) if os.path.isfile(m) and os.path.isfile(p) else (None, None)


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
    import json
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
