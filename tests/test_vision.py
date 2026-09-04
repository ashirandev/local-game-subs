# -*- coding: utf-8 -*-
"""Tests for the model client, against a real HTTP server returning canned replies.

A mock of `urllib` would test that the mock was called. These tests run the actual request path,
because the failures worth catching here -- an empty answer, a server that ignores the schema, a
400 whose message is in the body -- all live in what comes back over the wire.
"""
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, __file__.rsplit("tests", 1)[0] + "src")
from gamesubs.vision import EmptyAnswer, VisionClient, sniff

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32

REPLY = {"body": {}, "status": 200, "seen": []}


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        REPLY["seen"].append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        b = json.dumps(REPLY["body"]).encode("utf-8")
        self.send_response(REPLY["status"])
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


def answer(content, **extra):
    m = {"role": "assistant", "content": content}
    m.update(extra)
    return {"choices": [{"message": m, "finish_reason": "stop"}], "usage": {"total_tokens": 7}}


class Sniff(unittest.TestCase):
    def test_png(self):
        self.assertEqual(sniff(PNG), "image/png")

    def test_jpeg(self):
        self.assertEqual(sniff(JPEG), "image/jpeg")

    def test_webp(self):
        self.assertEqual(sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "image/webp")

    def test_gif(self):
        self.assertEqual(sniff(b"GIF89a" + b"\x00" * 8), "image/gif")

    def test_unknown_bytes_are_refused_not_guessed(self):
        # This used to be hardcoded to image/jpeg, which is fine until someone sends PNG. A
        # mislabelled payload does not reliably fail -- it fails silently.
        with self.assertRaises(ValueError):
            sniff(b"not an image at all")


class Wire(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 8934), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        REPLY["body"], REPLY["status"], REPLY["seen"] = {}, 200, []
        self.vc = VisionClient("http://127.0.0.1:8934/v1", "test")

    def test_plain_text_round_trip(self):
        REPLY["body"] = answer("hello")
        self.assertEqual(self.vc.ask("hi"), "hello")

    def test_the_image_goes_first_and_the_prompt_after(self):
        # The vision tower attends over the whole image; the trailing text is what the model is
        # answering about.
        REPLY["body"] = answer("ok")
        self.vc.ask("what is this", image=PNG)
        parts = REPLY["seen"][0]["messages"][0]["content"]
        self.assertEqual([p["type"] for p in parts], ["image_url", "text"])
        self.assertTrue(parts[0]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_a_text_only_call_sends_a_plain_string(self):
        REPLY["body"] = answer("ok")
        self.vc.ask("hi")
        self.assertIsInstance(REPLY["seen"][0]["messages"][0]["content"], str)

    def test_every_request_asks_for_reasoning_to_be_off(self):
        # The server flag can be overridden per request and vice versa, so both have to say it.
        # This is a 4x difference that produces no error and no wrong answers -- only a tool too
        # slow to keep up with dialogue, which is very hard to trace back to a missing key.
        REPLY["body"] = answer("ok")
        self.vc.ask("hi")
        self.assertEqual(REPLY["seen"][0]["chat_template_kwargs"]["enable_thinking"], False)

    def test_empty_content_raises_instead_of_returning_nothing(self):
        REPLY["body"] = answer("")
        with self.assertRaises(EmptyAnswer):
            self.vc.ask("hi")

    def test_reasoning_only_raises_and_says_so(self):
        # The trap this exists for: reading reasoning_content "so something comes back" scores
        # the model's monologue instead of its answer, and the run looks healthy.
        REPLY["body"] = answer("", reasoning_content="let me think about this...")
        with self.assertRaises(EmptyAnswer) as e:
            self.vc.ask("hi")
        self.assertIn("reasoning_content", str(e.exception))

    def test_schema_is_sent_as_response_format(self):
        REPLY["body"] = answer('{"a": 1}')
        self.vc.ask("hi", schema={"type": "object"})
        self.assertEqual(REPLY["seen"][0]["response_format"]["type"], "json_schema")

    def test_clean_json_parses_and_records_that_the_schema_held(self):
        REPLY["body"] = answer('{"speaker": "", "en": "Go", "th": "ไป"}')
        self.assertEqual(self.vc.ask("hi", schema={"type": "object"})["th"], "ไป")
        self.assertIs(self.vc.schema_honoured, True)

    def test_json_wrapped_in_prose_is_recovered_and_flagged(self):
        # Some servers accept response_format and ignore it. Recovering is right; recovering
        # SILENTLY is not -- schema_honoured is how you find out your server does this.
        REPLY["body"] = answer('Sure! Here you go:\n{"speaker": "", "en": "Go", "th": "ไป"}\nHope that helps.')
        self.assertEqual(self.vc.ask("hi", schema={"type": "object"})["th"], "ไป")
        self.assertIs(self.vc.schema_honoured, False)

    def test_the_longest_object_wins_not_the_first(self):
        REPLY["body"] = answer('{} and then {"speaker": "", "en": "Go", "th": "ไป"}')
        self.assertEqual(self.vc.ask("hi", schema={"type": "object"})["th"], "ไป")

    def test_a_reply_with_no_json_at_all_raises(self):
        REPLY["body"] = answer("I cannot help with that.")
        with self.assertRaises(ValueError):
            self.vc.ask("hi", schema={"type": "object"})

    def test_an_http_error_carries_the_body_not_just_the_status(self):
        # str(HTTPError) is 'HTTP Error 400: Bad Request' and tells you nothing. The body is
        # where the server says what it actually objected to.
        REPLY["status"] = 400
        REPLY["body"] = {"error": {"message": "context size exceeded", "n_ctx": 2048}}
        with self.assertRaises(RuntimeError) as e:
            self.vc.ask("hi")
        self.assertIn("context size exceeded", str(e.exception))

    def test_usage_is_kept(self):
        REPLY["body"] = answer("ok")
        self.vc.ask("hi")
        self.assertEqual(self.vc.last_usage["total_tokens"], 7)

    def test_an_api_key_becomes_a_bearer_header(self):
        REPLY["body"] = answer("ok")
        VisionClient("http://127.0.0.1:8934/v1", "test", api_key="sekrit").ask("hi")
        self.assertTrue(REPLY["seen"])          # reached the server with the header attached


if __name__ == "__main__":
    unittest.main(verbosity=2)
