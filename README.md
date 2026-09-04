# local-game-subs

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

---

## Requirements

- Python 3.8+, Windows for the click-through overlay (the rest is cross-platform)
- `pip install mss numpy Pillow`
- **A vision-capable model** served on an OpenAI-compatible endpoint — [llama.cpp](https://github.com/ggml-org/llama.cpp)'s
  `llama-server`, LM Studio, Ollama, vLLM. A small one is the point: this was built and measured on
  a **4B model, 5.0 GB of weights plus a 0.9 GB vision projector**, which leaves the GPU usable for
  the game.

A text-only model cannot do this. If your server refuses the first image, it has no projector
loaded.

---

## Quick start

```bash
pip install git+https://github.com/ashirandev/local-game-subs.git
```

**1. Point it at your subtitles and find your numbers.** No model is loaded, nothing is published:

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
subtitles are inside it.

**2. Run it:**

```bash
python -m gamesubs run --base-url http://127.0.0.1:8080/v1 --model gemma --lang Thai \
                       --min-ink 900 --change 40
```

**3. Show it, in a second terminal:**

```bash
python -m gamesubs overlay
```

Drag the window where you want the line, then `Ctrl+Alt+L` to lock it — locked, it is
click-through and the game gets every click. `Ctrl+Alt+Q` quits and saves the position.

The hotkeys are global because they have to be: a locked window cannot be clicked, so an unlock
button *on the window* would make the first lock permanent.

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

Measured, on a 4B vision model on a 16 GB card:

- **~0.6–0.7 s per line**, image to translated text, with the schema honoured by the server
- **4 of 4** rendered subtitles read verbatim and translated into natural Thai
- **1 of 1** frame with no dialogue correctly returned empty, rather than inventing a line
- the gate, on those four lines: **9** for a static line, **78** for the two most similar lines,
  against a threshold of **30** — noise and signal on opposite sides with room to spare

**Not measured: how well any model reads subtitles over real gameplay.** Rendered bands are much
easier than text sitting on top of moving scenery — different contrast, compression, motion blur
and background. Everything above establishes that the path works end to end. It is not evidence
about accuracy in a real game, and I would not quote it as such. If you run it on a game, the
numbers you get are the numbers that count.

`tune` exists for exactly this reason: every threshold here was measured on my screen, and yours
is a different screen.

---

## Tests

```bash
python tests/test_capture.py     # the mask, the downscale, the gate, rendered-text fixtures
python tests/test_vision.py      # the model client, against a real HTTP server
python tests/test_service.py     # the job slot, the hold timer, what /current publishes
```

67 tests, no network, no GPU, about a second.

```bash
python mutants.py
```

A green suite proves the tests ran, not that they would go red if the code were wrong. `mutants.py`
makes 16 plausible edits — several of them things this code used to say — and checks each one
turns a test red. **16/16 killed.** The first two on the list are the threshold bug above, which
survived two earlier versions of the suite.

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

## Licence

MIT.
