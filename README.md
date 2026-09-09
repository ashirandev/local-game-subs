# local-game-subs

**🇹🇭 อ่านภาษาไทย → [README.th.md](README.th.md)**

Read a game's subtitles off your own screen with a small local vision model, and show them
translated in an overlay. One machine. Nothing is uploaded, nothing is stored.

```
  screen ──► band ──► change gate ──► vision model ──► /current ──► overlay
   12 fps      ▲                            ▲
        the bottom-middle          runs only when the TEXT changed,
         of your monitor            not when the picture changed
```

It works with any game that draws subtitles, because it reads pixels rather than hooking into
anything. There is no injection, no memory reading, no modding — the game does not know it exists.

![the translated line over the game](docs/3-the-result.png)

*The plate is the size of the sentence and sits on the box you aimed. When nobody is speaking
there is nothing on screen at all.*

Everything you set is in one window, and it stays open while you play — every control on it
reaches the subtitle straight away, because a subtitle setting is not something anyone can
judge without watching one.

![the settings window](docs/6-the-dashboard.png)

![the translation above the game's own line](docs/8-over-a-real-game.png)

*Resident Evil 4, with **Show in OBS and recordings** ticked: the translation sits above
the box, the game's own line stays inside it. Photographed off the monitor, because that
is what it takes — see below.*

> 📷 **Why there is no screenshot of it over a real game:** the overlay hides itself from
> screen capture on purpose. It sits in the strip being watched, so a recording of it would
> be read as a new subtitle and translated again. Print Screen, OBS and Steam's screenshot
> key all see the game without it; a phone camera sees it fine. Recording or streaming? Tick
> **Show in OBS and recordings** in the settings window — it stops the hiding *and* moves
> the plate above the box, because doing only the first makes the tool read its own output.

**👉 If you just want to use it: [GUIDE.md](GUIDE.md)** — download to subtitles in five minutes,
with pictures, no command line. The rest of this page is how it works and how it was measured.

---

## What you need

| | |
|---|---|
| **GPU** | ~6 GB of free VRAM. Measured use with the model, its vision projector and an 8k context: **4.85 GB** |
| **Disk** | about 6.5 GB, all of it inside the program's own folder |
| **OS** | Windows for the click-through overlay. The capture and translation halves are cross-platform |
| **Python** | 3.8 or newer |

**What the hardware actually buys you** — same five test images, same model, same answers, only
the llama.cpp build changed. Measured on this machine with `gamesubs check`:

| build | seconds per line | read verbatim | download |
|---|---|---|---|
| **CUDA** (RTX 5070 Ti) | **0.6** | 4/4 | 515 MB |
| **Vulkan** (same card) | **0.7** | 4/4 | 34 MB |
| **CPU only** (28 cores) | **3.0** | 4/4 | 18 MB |

E2B against E4B, same machine, 21 reads each over seven scenes — two-line cutscene subtitles, a speaker label, a menu, proper nouns, pale text, a line touching the edge, HUD digits:

| | seconds a line | GPU | reads the same words |
|---|---|---|---|
| **gemma-4 E2B** Q4_K_M | **0.66** | 8.3 GB | yes, in 6 of 7 |
| gemma-4 E4B Q4_K_M | 1.07 | 9.9 GB | yes |

E2B is a third faster in every one of the seven and leaves 1.6 GB more of the card to the game. The difference it loses on is spelling: it wrote *Racoon City* for *Raccoon City*. Both translated an inventory screen instead of returning nothing, so that one is the prompt, not the model.

All three read every line correctly; only the speed moves. `setup` installs the **Vulkan** build:
a tenth of a second slower than CUDA, fifteen times smaller, works on AMD and Intel too, and never
has to match a CUDA runtime version to your driver. `--backend cuda` if you want that tenth back.

CPU-only works and is honestly marginal: at 3 s the translation lands just as the line is leaving
the screen. Fine for a slow story game, frustrating in anything brisk.

### That table was wrong the first time, and the way it was wrong is the interesting part

The first run of it said CUDA 0.6, **Vulkan 3.6**, **CPU 18.2** — and on that basis `setup` shipped
CUDA by default, downloading 515 MB where 34 would do. The numbers were real. The comparison was
not: every arm was measured with the model's *reasoning* left switched on, and for a one-line
subtitle the thinking is most of the work. Turn it off and CUDA barely moves while Vulkan goes
3.6 → 0.7 and the CPU goes 18.2 → 3.0.

Two things worth taking from it. **A variable that affects every arm can still change the ranking
between them**, so "same conditions" is not enough — the conditions have to be *right*. And the
mistake was invisible: nothing errored, every answer was correct in every arm, and the wrong
conclusion was a confident one backed by real measurements.

It was caught only because a user following this README would have gotten 2.6 s where the README
claimed 0.6, and that gap had to be explained rather than shrugged at.

---

## Downloads

Everything is free. `gamesubs setup` fetches the model for you, but if you would rather click:

| what | where | size |
|---|---|---|
| **Python** | [python.org/downloads](https://www.python.org/downloads/) — tick *Add Python to PATH* | ~30 MB |
| **llama.cpp** | `setup` fetches this for you. By hand: [github.com/ggml-org/llama.cpp/releases](https://github.com/ggml-org/llama.cpp/releases) — take the newest **b-numbered** release, not the one GitHub labels *Latest* (that tag carries no binaries), and pick `bin-win-cuda-*` **plus** its matching `cudart-*` runtime zip, or `bin-win-vulkan-*` on its own | 34–515 MB |
| **The model** | [gemma-4-E4B-it-Q4_K_M.gguf](https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_K_M.gguf) | 4.7 GB |
| **Vision projector** | [mmproj-BF16.gguf](https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/mmproj-BF16.gguf) | 945 MB |
| (both, same page) | [unsloth/gemma-4-E4B-it-GGUF](https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF) | |
| **A smaller, faster model** | [unsloth/gemma-4-E2B-it-GGUF](https://huggingface.co/unsloth/gemma-4-E2B-it-GGUF) — take `gemma-4-E2B-it-Q4_K_M.gguf` **and that page’s own `mmproj-BF16.gguf`**, then rename the projector to `mmproj-E2B-BF16.gguf` before saving it beside the other one | 4.1 GB |

`gamesubs models` prints this table with the links, says which you already have, and `gamesubs setup --model-name e2b` downloads a pair and names it correctly.

⚠️ **Both models publish their projector as `mmproj-BF16.gguf`.** Keep two models and download the second one by hand, and it lands on top of the first model’s projector — same name, within a few MB of the same size — and that model then reads every frame as blank with nothing on screen to say why. `setup --model-name` renames it for you, which is why it exists.

🛑 **You need BOTH files.** The projector is what lets the model see. Without it the server
starts normally, answers questions about text, and then fails on every single frame — which looks
like this tool is broken rather than like a file is missing.

Put both in `%USERPROFILE%\.local-game-subs\models` (or wherever, and pass `--llama-server` and
your own `--base-url`). Any other vision model works too; this one is the default because it is
small enough to leave the GPU to the game.

---

## "Is this a virus?"

Fair question. It watches your screen, it has `.bat` files, and it downloads a program and runs
it. You should want an answer, and it should be one you can check rather than one you have to
believe.

**What it does with your screen:** every 1/12th of a second it copies one strip near the bottom
of your monitor, and *only* when the text in that strip changes does it send that strip to a
language model **running on your own PC**. The reply is drawn in the overlay. Nothing is uploaded,
nothing is saved. (`tune` writes `band.png` so you can check the crop; that file stays on your
disk and is overwritten each tick.)

**The check that settles it, and it takes ten seconds:** run `setup` once, then **turn off your
internet** and run `play`. It works exactly the same. A screen-reader that keeps working with the
network unplugged is not sending your screen anywhere.

Then, in increasing order of effort:

| | |
|---|---|
| **There is no program of mine to trust** | It is about 2,000 lines of Python. No compiled binary is shipped from this repo — you can read every line, and GitHub shows you every change |
| **It cannot spread into your system** | Its Python packages go into a `.venv` inside the folder, never into your system Python. Nothing touches your registry, your PATH, or your home folder. Delete the folder and every trace is gone |
| **The one binary is not mine either** | `llama-server` comes from [llama.cpp](https://github.com/ggml-org/llama.cpp)'s official release page, a project with tens of thousands of users. Run it through [VirusTotal](https://www.virustotal.com/) if you like |
| **Every download is checksummed** | Against a SHA-256 published **by the same host that serves the file** — Hugging Face's API for the model, GitHub's release metadata for llama.cpp. A file that does not match is deleted, not warned about. No hash is hardcoded in this repo, because a hash I typed in would only prove the file matches what *I* downloaded |
| **The no-phone-home test** | `python tests/test_no_phone_home.py` reads the source and fails if any module in the play path contains a URL pointing anywhere but your own machine, or if the local service binds to anything other than `127.0.0.1` |

**Windows will still warn you**, and it is right to: nothing here is code-signed, because a
certificate costs a few hundred dollars a year and this is free. You will see SmartScreen on the
`.bat` files and possibly on `llama-server.exe`. That warning means "unsigned", not "malicious" —
but it also means *don't take my word for it*, so the checks above are the point.

**The honest limit of the test:** it reads string literals, so it proves no URL is written down.
It cannot prove one is not assembled at runtime from pieces. That is why the first check on this
page is the one to actually do — pull the network and watch it keep working.

---

## Everything lives in one folder

Unzip it wherever you like. `setup.bat` puts everything it needs *beside itself*:

```
local-game-subs   setup.bat  play.bat        <- what you double-click
   .venv\                     <- a private Python, so your system Python is untouched
   models\                    <- the model and its vision projector
   llama.cpp\                 <- the program that runs the model
   src\  tests```

Nothing is written to your home folder, your registry, or your system Python. **Uninstalling is
deleting the folder**, and that really is all of it — no 6 GB left behind in a hidden directory
after the tool that put it there is gone.

Move the folder anywhere and it keeps working. Want the big files somewhere else — a second
drive, or shared between two copies? Set `GAMESUBS_HOME` to that path.

---

## Using a different model

`models\` is a drop box. Put any vision GGUF in it **together with its `mmproj-*.gguf`
projector**, and it appears in a dropdown the next time you start:

```
Which model should read your screen?
  [ gemma-4-E4B-it-Q4_K_M.gguf   (4.6 GB)          v ]
    projector: mmproj-BF16.gguf
```

With one model in the folder there is no dialog — it just starts. Pick from the command line
instead with `--model-file <name>`, or skip the dialog entirely with `--no-pick`.

A vision model is always **two files**. Get them from the same place, and note that a model with
no projector beside it is offered but cannot be started: without one the server loads happily,
answers questions about text, and then fails on every single frame.

---

## Quick start

**No git, no pip, no command line:** press *Code -> Download ZIP* at the top of this page,
unzip it, and double-click **`setup.bat`**. It builds a private Python inside the folder, installs
the five packages it needs into that, downloads llama.cpp and the model, and runs the check.
Then double-click **`play.bat`**. Step by step, with pictures: **[GUIDE.md](GUIDE.md)**.

If you would rather use the command line:

```bash
pip install git+https://github.com/ashirandev/local-game-subs.git
```

**1. Get everything** — llama.cpp for your GPU plus the model, about 6 GB, resumable, and every
step skips itself if it is already done:

```bash
python -m gamesubs setup
```

**2. Prove it works, before you touch a game:**

```bash
python -m gamesubs check
```

It renders subtitles, sends them to your model, and prints what came back plus your seconds per
line. A minute here turns "nothing appears in my game" into an error message you can actually
read.

**3. Play:**

```bash
python -m gamesubs play
```

That opens **one window with everything on it** — model, font, text colour, background, size,
and how long a line stays up — and nothing happens until you press **Start**. Then you aim a
box at the game's subtitles while the model loads behind it, and a strip along the bottom of
the window says which stage it is on.

![the dashboard](docs/6-the-dashboard.png)

Leave the window open while you play: every control on it reaches the subtitle straight away.
A subtitle setting is not something anyone can judge without watching one.

**One box.** The rectangle you drag is what gets read, how wide a line may get, and where the
translation appears — one thing to aim, in the place you drew it. The plate itself is the size
of the **sentence**, centred in that box: a fixed slab with the words floating inside it makes
the text look unstable every time the line changes length. The box is grown by `--pad` (14 px)
at the edges, because a drag that ends one pixel inside the sentence hands the model a clipped
word which it then translates perfectly, as the wrong word.

The box opens already drawn, centred and low, where games put their subtitles — measured
against both a box a person aimed by hand and RE4R's own cutscene line. Drag outside it to
redraw, drag **inside** it to move it without resizing, arrow keys to nudge, `C` to centre.
The dashed line down the middle of each screen is where the centre is, and it turns green
when the box agrees with it.

⚠️ **Draw the box tall enough for a TWO-line subtitle.** A box drawn around a one-line one is
short by exactly one line the moment a game shows two, and the model is then handed half a
sentence, translates that half perfectly, and nothing looks broken. The console warns you when the
text reaches the edge of your box.

There is nothing else to place. The subtitle appears on your box by itself, clicks go straight
through to the game, and when nobody is speaking there is nothing on screen at all.
`Ctrl+Alt+Q` quits.

**A settings window opens with it** — model, font, text colour, background, text size, and how
long a line stays up. Leave it open while you play: every change reaches the subtitle straight
away, because a subtitle setting is not something anyone can judge without watching one.

The hotkeys are global because they have to be: a locked window cannot be clicked, so an unlock
button *on the window* would make the first lock permanent.

**If subtitles are missed, or the same line is read over and over,** tune the two thresholds for
your game:

```bash
python -m gamesubs tune
```

The band defaults to the **bottom quarter of the monitor, middle 70% of its width**, checked
**12 times a second** — games centre their subtitles, so the outer edges are HUD and scenery, and
cropping them makes the image the model reads about a third smaller. `--wfrac 1.0` takes the full
width back; `--region L,T,W,H` sets it exactly.

Play for a minute and watch two columns. `ink` is how many subtitle-coloured pixels are in the
band — look at it with a line up and with none, and put `--min-ink` between the two. `chg` is how
much changed — look at it while a line sits there and when a new line appears, and put `--change`
between those. It also writes `band.png`, the exact crop being read; open it and check your
subtitles are inside it. Then:

```bash
python -m gamesubs play --min-ink 900 --change 40
```

---

## How it captures your screen

Through **[mss](https://github.com/BoboTiG/python-mss)**, which on Windows is a thin wrapper over
GDI's `BitBlt` + `CreateDIBSection` — the same call the Print Screen key uses. No driver, no
injection, no hook into the game. The game cannot tell it is happening, and there is nothing to
be flagged by anti-cheat, because nothing touches the game at all.

It copies **only the band**, not the whole screen. Measured on a 1792x360 strip of a 1440p
monitor:

| | median | worst of 60 |
|---|---|---|
| copy the band out of the screen | 14.0 ms | 16.8 ms |
| decide whether the text changed | 2.7 ms | 7.0 ms |
| **total per tick** | **16.7 ms** | |

At 12 ticks a second there are 83 ms to spend, so this uses about **20%** of one core's time and
nothing else. The model only runs when the gate says the text changed, which on real dialogue is
a few times a minute rather than twelve times a second.

### The one thing that can stop it working

GDI capture **cannot see a game running in true fullscreen (exclusive) mode** — it comes back
black, or as your desktop. This is a property of the capture API, not a bug here, and it takes ten
seconds to check: while `play` is running, open **http://127.0.0.1:8914/snap** in a browser. That
is the exact image being sent to the model.

- black or frozen → set the game to **Borderless Windowed**, which is what most games default to
  now and costs nothing in performance
- your desktop instead of the game → same fix
- the game, but the subtitles are outside the box → `--region` or `--wfrac`, see `tune`

Why not something faster? DXGI Desktop Duplication (`dxcam`) and Windows Graphics Capture both
handle exclusive fullscreen and are quicker. They are also extra dependencies with their own
failure modes, and at 20% of one core there is nothing here worth optimising: the model takes 0.6
seconds, the capture takes 0.014. Making the cheap half faster would not move the total.

---

## The part worth reading: when to spend a model call

A vision call takes about a second. Firing one per frame is not slow, it is broken. So the only
real design question is *when has the text changed*, and the obvious answer is wrong.

**Do not diff the frames.** A subtitle sits on top of live gameplay, so a pixel diff fires on
every explosion, every camera pan and every blade of moving grass — and almost none of those
frames contain a new word.

**Diff the text.** Mask the band down to subtitle-coloured pixels first, then compare masks.
Gameplay disappears from the comparison because it was never in it.

The mask is `red AND green both bright` — white text and yellow text, and between them close to
every game's subtitles. A red HUD marker fails it (green too low). A blue objective marker fails
it (red too low). Foliage, smoke and skin all fail it.

An earlier version keyed on *yellow*, because the game in front of me at the time had yellow
subtitles. That constant did not survive the second game. The lesson outlived it: gate on what the
thing you want is made of, and pick the loosest property that still excludes everything else.

### The bug that shipped in this file, and what caught it

Masks are compared after being shrunk, so antialiasing wobble on a *static* line is not read as a
new line. Shrinking is an average, and **text is thin**: a 40 px letter stroke averaged into a
10 px cell lands well under half brightness. Threshold at the obvious midpoint and most of the
glyph disappears — every sentence collapses toward the same faint smear.

With the first defaults, `>127` and a change threshold of 90, four completely different subtitles
moved 47, 35 and 30 cells — all under 90, so all three read as *the same line*. The first subtitle
was translated and the tool then went quiet. That looks like the model dying, and it sends you to
look at the model.

Measured on the four rendered subtitles the test suite still uses. `jitter` is the same line
shifted one pixel; `worst pair` is the smallest difference between **any** two of the four,
because the gate compares consecutive lines and any two lines can be consecutive:

| threshold | jitter | worst pair | separation | |
|---|---|---|---|---|
| `>127` (the midpoint) | 6 | 17 | **×2.8** | two lines read as one |
| `>90` | 11 | 50 | ×4.5 | |
| `>60` | 10 | 58 | ×5.8 | |
| `>25` | 9 | 78 | **×8.7** | shipped |

The default `--change 30` sits in that gap with room on both sides: under half the smallest real
signal, over three times the noise.

**Two things about this are worth more than the fix.** The tests were green throughout, because
they compared **filled rectangles** — a block of solid colour survives being shrunk and real
glyphs do not. And when the suite was rewritten to render actual sentences, it was *still* green,
because it compared one pair of lines: the pair it happened to pick differed by 47 while the worst
pair differed by 17. An average, or a lucky sample, hides exactly the case that breaks.

The suite now renders real text and asserts on the **worst** pair, so any future change to the
mask, the downscale or the threshold has to survive the two most similar lines rather than a
convenient one.

---

## Other things in here that were learned the hard way

**An empty answer is an error, not a fallback.** A reasoning model can spend its whole token
budget thinking and return `content: ""` with the thinking in `reasoning_content`. Reading that
field "so something comes back" scores the model's monologue instead of its answer, and the run
looks healthy while measuring nothing. `vision.py` raises instead.

**The overlay has to be invisible to screen capture.** It is always-on-top and it belongs at the
bottom centre — which is exactly the strip being watched. So the translated line lands in the next
frame, gets read as a new subtitle, and gets translated again. The first end-to-end run did this
with its own placeholder: *"drag me, then Ctrl+Alt+L"* came back as Thai, and then the Thai came
back. `WDA_EXCLUDEFROMCAPTURE` keeps the window on your monitor and out of every capture,
including this tool's own. `--in-capture` turns that off for OBS, and then the overlay has to live
outside the band.

**Switch the model's reasoning off, twice.** Once as a server flag, once per request — either
can override the other. With it on, the model writes out its thinking before answering, and for a
one-line subtitle that thinking is most of the work: **2.5 s per line against 0.6 s**, same model,
same card. Nothing errors and every answer stays correct, so nothing points at it. The tool is
simply four times too slow to keep up with dialogue.

**Latest-only, never a queue.** If a new line appears while one is being read, the waiting frame
is *dropped*. A subtitle delivered after the character stopped talking is worse than none, and a
queue drifts further behind with every line — which presents as the model getting slower, sending
you to look in exactly the wrong place.

**Sniff the image format, don't assume it.** This was hardcoded to `image/jpeg` once, which is
fine right up until someone tests whether PNG reads better. A mislabelled payload does not
reliably fail; it fails silently.

**One clock per line.** The hold timer lives in the service, not in the overlay. Two components
each running their own dwell timer on the same line are two clocks that will disagree, and the
disagreement looks like flicker.

**Fonts fail silently.** A font without glyphs for your language substitutes rather than refusing,
and the result looks fine in a screenshot and wrong to a reader. The overlay measures a sample
string in the candidate font and in a font known to lack the script — equal widths mean both are
drawing the same fallback.

**`re.findall(r"\{.*\}")` finds one match, not many.** `.*` is greedy, so it returns a single span
from the first brace to the last. Sorting those "candidates" by length then does nothing, and
`{} and then {"th": "..."}` becomes one unparseable blob. Braces have to be counted, outside
string literals, or a `}` inside the translated line ends the object early.

---

## What is measured, and what is not

Measured with `gamesubs check`, on gemma-4 E4B Q4_K_M, RTX 5070 Ti 16 GB:

- **0.6 s per line** on the CUDA build, **0.7 s** on Vulkan, **3.0 s** on the CPU
- **4 of 4** rendered subtitles read verbatim and translated into natural Thai, on **all three**
- **1 of 1** frame with no dialogue correctly returned empty, rather than inventing a line
- **4.85 GB** of VRAM, model + projector + 8k context
- the gate, on those four lines: **9** for a static line, **78** for the two most similar lines,
  against a threshold of **30** — noise and signal on opposite sides with room to spare

Every one of those numbers comes out of `gamesubs check`, so you can produce your own rather than
take mine.

**Not measured: how well any model reads subtitles over real gameplay.** Rendered bands are much
easier than text sitting on top of moving scenery — different contrast, compression, motion blur
and background. Everything above establishes that the path works end to end. It is not evidence
about accuracy in a real game, and I would not quote it as such. If you run it on a game, the
numbers you get are the numbers that count.

`tune` and `check` exist for exactly this reason: every number here was measured on my screen and
my card, and yours are different. The tool's job is to hand you your own.

---

## Tests

```bash
python tests/test_capture.py     # the mask, the downscale, the gate, rendered-text fixtures
python tests/test_vision.py      # the model client, against a real HTTP server
python tests/test_service.py     # the job slot, the hold timer, what /current publishes
python tests/test_server.py      # download, resume, checksums, asset picking
python tests/test_overlay.py     # the window, and why it must be invisible to capture
python tests/test_no_phone_home.py  # nothing in the play path can reach the internet
```

123 tests, no network, no GPU, about a second.

```bash
python mutants.py
```

A green suite proves the tests ran, not that they would go red if the code were wrong. `mutants.py`
makes 32 plausible edits — several of them things this code used to say — and checks each one
turns a test red. **32/32 killed.** The first two on the list are the threshold bug above, which
survived two earlier versions of the suite.

Writing that runner turned up a bug of its own worth passing on: a mutant the **same length** as
the code it replaces can leave a stale `.pyc` behind, because Python judges bytecode fresh from
the source's size and its mtime in whole seconds. Mutate, test and restore inside one second and
the suite then fails on correct code. It does not look like a caching problem — it looks like a
flaky test.

---

## Endpoints

While `run` is going, `http://127.0.0.1:8914` serves:

| | |
|---|---|
| `/current` | the line right now, as `{"speaker", "source", "text"}` |
| `/snap` | the last band handed to the model — open this if the region looks wrong |
| `/health` | whether a line is up, and the band being watched |
| `/band` | the watched region as fractions of the monitor |

Two processes rather than one, on purpose: when subtitles stop appearing you want to know which
half stopped, and with a service you just open `/current` and the answer is there.

---

## Contact

**Something broken, a question, or an idea** — open an issue. That is the fastest route and
the answer is then there for whoever hits the same thing next.

**Work enquiries** — ashiran.awork@gmail.com

---

## Licence

MIT.
