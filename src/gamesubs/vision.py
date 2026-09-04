# -*- coding: utf-8 -*-
"""A small OpenAI-compatible vision client. Standard library only.

Points at anything that speaks `/v1/chat/completions` with image content: llama.cpp's
`llama-server`, LM Studio, Ollama, vLLM, or a hosted endpoint if you want one. Nothing here is
specific to a vendor or a model.

Four things in this file are not obvious, and each one cost a real debugging session:

1. AN EMPTY ANSWER IS AN ERROR, NOT A FALLBACK. A reasoning model can spend its whole token
   budget thinking and return `content: ""` with the thinking in `reasoning_content`. Reading
   that field "so something comes back" scores the model's monologue instead of its answer, and
   the run looks healthy while measuring nothing. This raises instead.

2. SNIFF THE IMAGE FORMAT, DO NOT ASSUME IT. This was hardcoded to `image/jpeg`, which is fine
   until someone tests whether PNG reads better -- they would have been sending PNG bytes under a
   JPEG label. A mislabelled payload does not reliably fail; it fails silently, which is worse.

3. IMAGE FIRST, THEN THE INSTRUCTION. The vision tower attends over the whole image; the trailing
   text is what the model is answering about.

4. THE TIMEOUT MUST KNOW THERE IS AN IMAGE IN THERE. Sizing a timeout from `len(prompt)` hands
   the slowest kind of call the shortest deadline, and it shows up as an occasional timeout
   rather than as an error, which is a much longer bug to find.
"""
import base64
import json
import urllib.error
import urllib.request

MIMES = ((b"\x89PNG\r\n\x1a\n", "image/png"),
         (b"\xff\xd8\xff", "image/jpeg"),
         (b"GIF87a", "image/gif"),
         (b"GIF89a", "image/gif"))


def sniff(raw):
    """Real format from the magic bytes, or a refusal. Never a guess."""
    for magic, mime in MIMES:
        if raw[:len(magic)] == magic:
            return mime
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("unrecognised image format (first bytes %r). Convert it rather than letting "
                     "the server guess." % raw[:8])


def objects(txt):
    """Every brace-balanced substring of `txt`, outermost first at each starting brace.

    The obvious version of this is `re.findall(r"\\{.*\\}", txt, re.S)`, and it is wrong in a way
    that hides: `.*` is greedy, so it returns ONE span running from the first `{` to the last `}`
    in the whole reply. Sorting those "candidates" by length then does nothing, and a reply like
    `{} and then {"th": "..."}` yields a single unparseable blob. Braces have to be counted, and
    counted outside string literals, or a `}` inside the translated text ends the object early.
    """
    out = []
    for i, ch in enumerate(txt):
        if ch != "{":
            continue
        depth, in_str, esc = 0, False, False
        for j in range(i, len(txt)):
            c = txt[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    out.append(txt[i:j + 1])
                    break
    return out


class EmptyAnswer(RuntimeError):
    """The model returned no content. See note 1 at the top of this file."""


class VisionClient:
    """One call, one answer.

    >>> vc = VisionClient("http://127.0.0.1:8080/v1", "gemma")
    >>> vc.ask("What does this say?", open("band.jpg", "rb").read())
    """

    def __init__(self, base_url, model, api_key=None, timeout=None):
        self.base = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.last_usage = {}
        self.last_finish = None
        self.schema_honoured = None      # None until the first schema call; then True/False

    def ask(self, prompt, image=None, schema=None, max_tokens=512, temperature=0.2):
        """Returns text, or a parsed dict when `schema` is given."""
        content = prompt
        if image is not None:
            raw = image if isinstance(image, bytes) else open(image, "rb").read()
            content = [{"type": "image_url",
                        "image_url": {"url": "data:%s;base64,%s"
                                             % (sniff(raw), base64.b64encode(raw).decode())}},
                       {"type": "text", "text": prompt}]

        body = {"model": self.model,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": max_tokens,
                "temperature": temperature,
                # Reasoning off, per request as well as on the server. For a one-line subtitle
                # the model's thinking is most of the work: 2.5 s per line with it against 0.6 s
                # without, on the same model and card. It never errors and the answers stay
                # correct, so nothing points at it -- the tool is just four times too slow to
                # keep up with dialogue. `/no_think` is a Qwen token and is literal text to
                # other models; this is the portable way to ask.
                "chat_template_kwargs": {"enable_thinking": False}}
        if schema is not None:
            # Ask for constrained output. Servers that support it become far more reliable to
            # parse; servers that do not will ignore this key, which is why the fallback below
            # exists rather than an assumption either way.
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "answer", "strict": True,
                                                       "schema": schema}}

        # An image is worth far more prefill than its prompt suggests. The constant is deliberately
        # generous: being slow to give up costs one late answer, giving up early costs the answer.
        timeout = self.timeout or (30 + (90 if image is not None else 0) + max_tokens / 8.0)
        req = urllib.request.Request(
            self.base + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     **({"Authorization": "Bearer " + self.api_key} if self.api_key else {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # str(HTTPError) is 'HTTP Error 400: Bad Request' and says nothing. The body says
            # what the server actually objected to.
            raise RuntimeError("%s -- %s" % (e, e.read().decode("utf-8", "replace")[:400]))

        self.last_usage = data.get("usage") or {}
        self.last_finish = (data.get("choices") or [{}])[0].get("finish_reason")
        msg = data["choices"][0]["message"]
        txt = (msg.get("content") or "").strip()
        if not txt:
            raise EmptyAnswer(
                "the model returned no content%s. Serve with reasoning disabled, or raise "
                "max_tokens. Do NOT read reasoning_content instead -- that scores the monologue, "
                "not the answer." % (" (only reasoning_content)" if msg.get("reasoning_content")
                                     else ""))
        if schema is None:
            return txt
        return self._parse(txt)

    def _parse(self, txt):
        try:
            out = json.loads(txt)
            if self.schema_honoured is None:
                self.schema_honoured = True
            return out
        except ValueError:
            pass
        # The server ignored response_format, or wrapped the object in prose. Take the longest
        # BALANCED object, so a stray `{}` earlier in the prose does not win.
        self.schema_honoured = False
        for cand in sorted(objects(txt), key=len, reverse=True):
            try:
                return json.loads(cand)
            except ValueError:
                continue
        raise ValueError("a schema was requested but the reply is not JSON: %r" % txt[:200])
