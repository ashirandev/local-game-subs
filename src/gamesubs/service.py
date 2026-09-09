# -*- coding: utf-8 -*-
"""The pipeline: watch the band, read it when it changes, publish the line on localhost.

    capture -> change gate -> one vision call -> GET /current

The overlay is a separate process that polls `/current`. Splitting them is not architecture for
its own sake: the reader and the writer have completely different failure modes, and when the
subtitle stops appearing you want to know which half stopped. With two processes you just open
`/current` in a browser and the answer is right there.

LATEST-ONLY, NEVER A QUEUE. A vision call takes seconds; a subtitle is worthless late. If a new
line appears while one is being read, the waiting frame is DROPPED, not queued. A queue here
drifts further behind the game with every line, and it presents as the model getting slower --
which sends you looking in exactly the wrong place.

THE HOLD TIMER LIVES HERE, NOT IN THE OVERLAY. Whoever owns the text owns how long it stays up.
Two components each running their own dwell timer on the same line are two clocks that will
disagree, and the disagreement looks like flicker.
"""
import collections
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LF_CHAR = chr(10)

SCHEMA = {
    "type": "object",
    "properties": {"speaker": {"type": "string"},
                   "en": {"type": "string"},
                   "th": {"type": "string"}},
    "required": ["speaker", "en", "th"],
}

# WHATEVER IS IN THE BOX GETS TRANSLATED, and there is no rule here trying to be clever
# about which text "counts". There was one: it told the model to return nothing for a menu,
# an inventory or a HUD. Both models ignored it -- measured 3/3 each on an inventory screen,
# and caught live on a Windows panel that opened over the box -- so it was an instruction
# that changed nothing except to make the prompt longer.
#
# Classifying it properly was tried too: an extra `kind` field, measured on eleven frames.
# It never once mislabelled a real subtitle (24/24) and it did catch a game's own inventory
# screen -- but it called a Windows panel `dialogue`, because a paragraph of prose in a box
# is what narration looks like. It bought part of a case at the cost of a field, and the
# person aiming the box had already answered the question by aiming it.
#
# So: the box is the whole of the decision. Point it at the subtitles and that is what gets
# read. A menu inside the box is a menu somebody chose to include.
PROMPT = (
    "This image is a strip from a video game screen. Somebody has drawn this box around the"
    " part they want translated.\n"
    "{pronouns}"
    "1. Copy the text you can read in it EXACTLY into `en`.\n"
    "2. Translate that into natural spoken {lang} and put it in `th`. Translate the meaning,"
    " not word by word. Keep it short, the way a subtitle is short.\n"
    "3. If a character name is shown above or beside the line, put it in `speaker` -- and "
    "NOT in `en` or `th`. The name is not part of what the character said, and writing it "
    "again at the start of the translation shows it twice. Otherwise leave `speaker` "
    "empty.\n"
    "4. If there is NO readable text at all, return all three fields empty. An empty answer "
    "is a correct answer here, and it will happen often.\n"
    "Never invent a line. Never describe the picture. Only what is written on it."
)


# A note appended for languages where choosing a pronoun means claiming something about the
# speaker that a strip of screen does not show.
#
# Thai pronouns carry gender, age, rank and how close two people are. "I" alone can be
# ผม ฉัน หนู กู ข้า อั๊ว -- and picking one is a statement about who is talking, made by a model
# that can see a rectangle of pixels. Wrong is not a stylistic slip in Thai: it is rude, or
# absurd, or it turns a stranger into an intimate.
#
# 🔑 THIS IS A PROMPT RULE AND SO IT IS A RATE. The deterministic half that exists
# everywhere else in this file cannot exist here: Thai does not put spaces between words,
# and every candidate pronoun is a substring of ordinary words -- ผม is also "hair",
# แก sits inside แกง and แก้, นาย inside นายก and นายจ้าง. A replacement pass would
# quietly corrupt real words to fix a wording preference, which is a bad trade.
NEUTRAL_PRONOUNS = {
    "thai": ("0. PRONOUNS FIRST, before anything else. For the person speaking, always "
             "write ฉัน -- never ผม, หนู, กู, ข้า or อั๊ว. For the person being spoken to, "
             "always write คุณ -- never นาย, เธอ, แก, มึง, ท่าน or ลื้อ. A strip of screen "
             "does not show who is talking, whether they are a man or a woman, how old "
             "they are, or how well the two of them know each other, and every other Thai "
             "pronoun claims all of that. He, she, it and they are different: those are "
             "plain in the English, so translate them normally.\n"),
}


def prompt_for(lang):
    """The prompt, plus the pronoun rule for languages that need one. -> str"""
    return PROMPT.format(lang=lang,
                        pronouns=NEUTRAL_PRONOUNS.get((lang or "").strip().lower(), ""))


MEMO_MAX = 128          # sentences remembered; a game scene has nowhere near this many


def normalise(line):
    """One key for the same sentence however it came back from the model. -> str

    Whitespace collapsed, trailing punctuation dropped, case folded. Measured on a real
    run: the same menu caption arrived as both "Change game settings" and "Change game
    settings." within seconds, which is one sentence and must not be two answers.
    """
    return " ".join((line or "").split()).strip().rstrip(" .!?…").casefold()


def _bare(text):
    """A name reduced to what two spellings of it have in common. -> str"""
    return "".join(c for c in (text or "").lower() if c.isalnum())


def _is(segment, speaker):
    """Is this segment the speaker's name, rather than a word that happens to be short? -> bool"""
    s, n = _bare(segment), _bare(speaker)
    return bool(n) and s == n


def _label_kind(en, speaker):
    """Where the name label sits in the ENGLISH line, if it is there at all. -> str|None

    English is the copy of what is on the screen, in the script it was written in, so it is the
    only one of the two fields where the name can be RECOGNISED rather than guessed at. Thai comes
    back transliterated -- Leon becomes ลีออน or เลออน depending on the day -- and no comparison
    against "Leon" will ever match it.

    Three placements, because games do not agree: `NAME: line`, the name on its own line above,
    and the name on its own line below.
    """
    head, sep, rest = (en or "").partition(":")
    if sep and rest.strip() and _is(head, speaker):
        return "colon"
    parts = [p for p in (en or "").split(LF_CHAR)]
    if len(parts) > 1:
        if _is(parts[0], speaker) and LF_CHAR.join(parts[1:]).strip():
            return "first"
        if _is(parts[-1], speaker) and LF_CHAR.join(parts[:-1]).strip():
            return "last"
    return None


def _cut(text, kind):
    """Remove the label at `kind` from a line, in whatever script it is written in. -> str"""
    if not text:
        return text
    if kind == "colon":
        head, sep, rest = text.partition(":")
        return rest.strip() if sep and rest.strip() and len(head) <= 24 else text
    parts = text.split(LF_CHAR)
    if len(parts) < 2:
        return text
    keep = parts[1:] if kind == "first" else parts[:-1]
    return LF_CHAR.join(keep).strip() or text


def _lead_colon(text):
    """True if this line opens with a short run of text and a colon. -> bool"""
    head, sep, rest = (text or "").partition(":")
    return bool(sep and rest.strip() and 0 < len(head.strip()) <= 24 and LF_CHAR not in head)


def _looks_like_a_name(head):
    """Could this run of text before a colon be a character name? -> bool

    Latin letters, capitalised, at most three words. Deliberately narrow: this is used
    where the model has NOT reported a speaker, so nothing else vouches for it. Thai text
    before a colon fails it, which is the point -- ฟังนะ: เราต้องไป is a sentence.
    """
    s = (head or "").strip()
    if not s or len(s) > 24 or len(s.split()) > 3:
        return False
    return s[0].isupper() and all(c.isalpha() or c in " .'-" for c in s)


def split_speaker(en, th, speaker):
    """Take the name label out of the line, or out of neither. -> (speaker, en, th)

    The model is told to put the name in `speaker`, and mostly does -- 71 of 83 lines in one
    real session. Then it writes it at the start of the line as well, because that is how it
    appears on screen, and the result is the name twice: once as a label and once
    transliterated into Thai.

    🔑 DECIDED FROM ENGLISH, APPLIED TO BOTH. Cutting whatever sits in the label position
    is not the same question. A character saying someone else's name is ordinary -- Ada says
    "Leon, behind you" -- and when a subtitle wraps, that name is alone on the first line and
    looks exactly like a label. Three of four such frames were being eaten. English still
    holds the original spelling, so it is the only field where the name can be RECOGNISED.

    🔑 AND WHEN THE MODEL REPORTS NO SPEAKER AT ALL, a `Name:` at the very start is
    PROMOTED rather than deleted. Caught live twice in 83 lines, both during a scene where
    the radio breaks up: `Hunnigan: -- chopper-` with `speaker` empty, so every guard here
    correctly stayed out of it and the name went to screen transliterated. Moving it into
    the label loses nothing even when the guess is wrong -- the words are still on screen,
    in the original spelling, which is more than deleting them would leave.

    NOTHING IS EVER REMOVED FROM THE MIDDLE. There is no search for the name inside the
    text: a name in the middle of a line is someone being spoken to, which is speech.
    """
    if not (en or th):
        return speaker, en, th
    if not speaker:
        head, sep, rest = (en or "").partition(":")
        if sep and rest.strip() and _looks_like_a_name(head):
            return head.strip(), rest.strip(), _cut(th, "colon")
        return speaker, en, th
    kind = _label_kind(en, speaker)
    if kind:
        return speaker, _cut(en, kind), _cut(th, kind)
    if _lead_colon(th) and ":" not in (en or ""):
        return speaker, en, _cut(th, "colon")
    return speaker, en, th


MIN_HOLD = 1.2                 # seconds -- the shortest a line may be on screen
HOLD_CAP = 6.0                 # and the longest this floor will ever ask for
READ_SPEED = 15.0              # characters a player reads per second while also playing
EYE_S = 0.4                    # finding the plate before reading a word of it


def read_seconds(text, speed=READ_SPEED, lo=MIN_HOLD, hi=HOLD_CAP, eye=EYE_S):
    """How long this line has to stay up before anyone could have read it. -> float

    COUNT CHARACTERS, NOT WORDS. Thai does not put spaces between words, so the obvious
    reading -- split on whitespace -- returns 1 for most translations this tool produces.
    Measured on a real run: "เปลี่ยนการตั้งค่าเกม" is 20 characters and six Thai words, and
    exactly one space-separated group. A floor built on word count would give that line the
    same time as a single "OK".

    Everything above the count is a reading rate, which is how broadcast subtitles have always
    been timed. `speed` is deliberately slower than a reading-only rate: the person is playing
    a game, and the subtitle is not the thing they are looking at.

    Returns 0.0 for an empty line -- nothing to read means nothing to wait for, which is what
    keeps "no translation, go dark" true.
    """
    n = len("".join((text or "").split()))
    if not n or speed <= 0 or lo <= 0:
        return 0.0
    return max(lo, min(hi, eye + n / float(speed)))


class Current:
    """What `/current` says right now. One lock: the HTTP threads read it while the worker writes.

    A FLOOR ON HOW BRIEFLY A LINE MAY APPEAR. The model answers in about a second, and by then
    the game has often moved on -- so the loop clears the line almost as soon as it arrives and
    the translation is on screen for a tenth of a second. Present, correct, and unreadable.

    The floor DEFERS a clear, it never refuses one: the clear still happens, at the moment the
    line has been up long enough to read. And it never delays a REPLACEMENT -- a new translation
    goes up at once, because holding the old one back would mean deliberately showing Thai that
    belongs to a sentence no longer on screen, which is the exact failure this repo already has
    a comment about in the play loop.

    `now` is injectable so the tests can measure a floor without spending it.
    """

    EMPTY = {"speaker": "", "source": "", "text": ""}

    def __init__(self, speed=READ_SPEED, min_hold=MIN_HOLD):
        self._lk = threading.Lock()
        self._d = dict(self.EMPTY)
        self.at = 0.0
        self.speed, self.min_hold = speed, min_hold
        self._until = 0.0          # no clearing before this moment
        self._owed = False         # a clear that arrived early and is still owed

    def hold_for(self, text):
        """Seconds this text is entitled to. -> float"""
        return read_seconds(text, self.speed, self.min_hold)

    def set(self, speaker="", source="", text="", now=None):
        """Publish a line, or clear one. True if the change landed now. -> bool"""
        now = time.time() if now is None else now
        with self._lk:
            if not text:
                if self._d["text"] and now < self._until:
                    self._owed = True
                    return False
                self._d = dict(self.EMPTY)
                self._owed = False
                return True
            self._d = {"speaker": speaker, "source": source, "text": text}
            self.at = now
            self._until = now + self.hold_for(text)
            self._owed = False
            return True

    def get(self, now=None):
        """The line to show. Pays off a deferred clear once its floor has run out."""
        now = time.time() if now is None else now
        with self._lk:
            if self._owed and now >= self._until:
                self._d = dict(self.EMPTY)
                self._owed = False
            return dict(self._d)

    def expire(self, ttl, now=None):
        """Clear a line that has been up too long. True if this call cleared one.

        The floor wins over this: a minimum and a maximum that disagree is a minimum.
        """
        now = time.time() if now is None else now
        with self._lk:
            if self._d["text"] and now - self.at > ttl and now >= self._until:
                self._d = dict(self.EMPTY)
                self._owed = False
                return True
        return False


class Worker(threading.Thread):
    """Reads the newest frame and nothing else. See LATEST-ONLY at the top of this file."""

    def __init__(self, client, current, lang="Thai", on_line=None):
        super().__init__(daemon=True)
        self.client, self.cur, self.lang = client, current, lang
        self.on_line = on_line or (lambda **kw: None)
        self.job = None
        self.ev = threading.Event()
        self.lk = threading.Lock()
        self.n = self.blank = self.err = self.repeats = 0
        # en -> (speaker, th). Ordered so the oldest sentence is the one dropped.
        self.said = collections.OrderedDict()

    def submit(self, jpg):
        """Hand over a frame. Returns True if this REPLACED one that was still waiting."""
        with self.lk:
            dropped = self.job is not None
            self.job = jpg
        self.ev.set()
        return dropped

    def run(self):
        while True:
            self.ev.wait()
            self.ev.clear()
            with self.lk:
                jpg, self.job = self.job, None
            if jpg is None:
                continue
            t0 = time.time()
            try:
                d = self.client.ask(prompt_for(self.lang), image=jpg, schema=SCHEMA)
            except Exception as e:
                self.err += 1
                # Keep going. One unreadable frame is ordinary; a dead loop is not.
                self.on_line(error="%s: %s" % (type(e).__name__, str(e).split("\n")[0][:120]))
                continue
            dt = time.time() - t0
            spk = (d.get("speaker") or "").strip()
            # One decision for both fields. Deciding them separately is how the Thai came
            # to be cut on a frame whose English said the name was never a label.
            spk, en, th = split_speaker((d.get("en") or "").strip(),
                                        (d.get("th") or "").strip(), spk)
            # A failed read often comes back as the speaker's name in the translation field. It is
            # a name, not a line, and showing it looks like a hallucination to whoever is watching.
            if th and spk and th.strip().lower() == spk.strip().lower():
                th = ""
            self.n += 1
            # THE SAME SENTENCE KEEPS THE SAME WORDING. A vision model is sampling, so a
            # line read twice comes back translated twice -- close, not identical -- and
            # the words on screen change while the English behind them has not moved.
            # Measured on one run: "Play through the main story and experience the
            # nightmare" was read 88 times and produced TWO Thai renderings; "View bonus
            # content" was read twice and produced two. Nothing was wrong with either
            # wording, and watching them swap is still the tool looking broken.
            #
            # First answer wins, for as long as it is remembered. Not the best answer --
            # there is no way to tell which is best, and "sometimes better" bought with
            # "always moving" is a bad trade for something being read at a glance.
            key = normalise(en)
            repeat = False
            if key:
                first = self.said.get(key)
                if first:
                    spk, th = first
                    repeat = True
                    self.said.move_to_end(key)
                else:
                    self.said[key] = (spk, th)
                    if len(self.said) > MEMO_MAX:
                        self.said.popitem(last=False)
            if not th:
                self.blank += 1
                self.cur.set()
                self.on_line(secs=dt, blank=True)
                continue
            self.cur.set(spk, en, th)
            self.repeats += repeat
            self.on_line(secs=dt, speaker=spk, source=en, text=th, repeat=repeat,
                         tokens=(self.client.last_usage or {}).get("total_tokens"))


def serve_http(current, port, band_norm=None, band_rect=None):
    """Publish `/current` (and a little else) on localhost. Returns the server; call .shutdown().

    `band_rect` is the watched box in ABSOLUTE screen pixels, alongside the fractions in
    `band_norm`. The overlay needs the absolute one: fractions are of a single monitor and say
    nothing about where that monitor starts, so on a second screen they place the window a whole
    screen width away -- a bug this repo already has a killed mutant for, in the box selector.
    """

    class H(BaseHTTPRequestHandler):
        def _send(self, body, ctype="application/json; charset=utf-8"):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            # The overlay polls several times a second. A cached /current freezes the subtitle on
            # screen while the log keeps scrolling, which reads as "the overlay broke".
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            p = self.path.split("?")[0]
            if p == "/current":
                self._send(json.dumps(current.get(), ensure_ascii=False).encode("utf-8"))
            elif p == "/band":
                self._send(json.dumps({"band": band_norm,
                                       "rect": band_rect}).encode("utf-8"))
            elif p == "/snap":
                self._send(SNAP["jpg"], "image/jpeg")
            elif p == "/health":
                self._send(json.dumps({"ok": True, "showing": bool(current.get()["text"]),
                                       "band": band_norm}).encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *a):
            pass          # the overlay polls ~7x/s; one log line each would drown the console

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


SNAP = {"jpg": b""}       # the last band handed to the model, served at /snap to check the region
