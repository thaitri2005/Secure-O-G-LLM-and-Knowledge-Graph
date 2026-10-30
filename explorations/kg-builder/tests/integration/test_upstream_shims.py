"""Offline tests for the on-prem shims in scripts/upstream (no LM Studio needed).

A fake LM Studio /v1/completions on 127.0.0.1 replays a recorded reply from
tests/fixtures/upstream/mock_llm_samples.jsonl.
"""

import json
import socket
import sys
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "upstream"))

import _nothink  # noqa: E402
import _onprem  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "upstream" / "mock_llm_samples.jsonl"


def fixture(name: str) -> dict:
    for line in FIXTURES.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["fixture"] == name:
            return row
    raise KeyError(name)


class FakeLMStudio(BaseHTTPRequestHandler):
    received = []
    reply_text = ""

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeLMStudio.received.append((self.path, body))
        out = json.dumps({"choices": [{"text": FakeLMStudio.reply_text, "finish_reason": "stop"}],
                          "usage": {"prompt_tokens": 10, "completion_tokens": 2}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


class NoThinkProxyTest(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeLMStudio)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.log = ROOT / ".cache" / "tmp" / "test_nothink_calls.jsonl"
        self.log.unlink(missing_ok=True)
        FakeLMStudio.received = []

    def tearDown(self):
        self.server.shutdown()
        self.log.unlink(missing_ok=True)

    def chat(self, base: str, messages: list, max_tokens: int) -> dict:
        body = {"model": "qwen3.6-35b-a3b", "messages": messages, "max_tokens": max_tokens, "temperature": 0}
        req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=10).read())

    def test_edc_verify_call_gets_letter_and_think_is_disabled(self):
        sample = fixture("edc_canonicalization_verify")
        FakeLMStudio.reply_text = sample["content"]
        base = _nothink.start(f"http://127.0.0.1:{self.server.server_address[1]}/v1", self.log)

        reply = self.chat(base, sample["messages"], max_tokens=1)

        self.assertEqual(reply["choices"][0]["message"]["content"], "A")
        path, sent = FakeLMStudio.received[0]
        self.assertEqual(path, "/v1/completions")
        self.assertTrue(sent["prompt"].endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n"))
        self.assertEqual(sent["max_tokens"], _nothink.MIN_TOKENS)
        self.assertIn("<|im_end|>", sent["stop"])
        self.assertEqual(_nothink.summarize(self.log)["llm_calls"], 1)

    def test_render_keeps_roles_in_order(self):
        prompt = _nothink.render([{"role": "system", "content": "S"},
                                  {"role": "user", "content": [{"type": "text", "text": "U"}]}])
        self.assertTrue(prompt.startswith("<|im_start|>system\nS<|im_end|>\n<|im_start|>user\nU<|im_end|>\n"))


class NetworkGuardTest(unittest.TestCase):
    def setUp(self):
        self.saved = (socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo)

    def tearDown(self):
        socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = self.saved
        (_onprem.PROJECT_ROOT / "runs" / "upstream" / "logs" / "net_unittest.jsonl").unlink(missing_ok=True)

    def test_blocks_non_loopback_and_logs_it(self):
        log = _onprem.guard_network("net_unittest")
        with socket.socket() as s, self.assertRaises(ConnectionRefusedError):
            s.connect(("93.184.216.34", 80))
        with self.assertRaises(ConnectionRefusedError):
            socket.getaddrinfo("example.com", 443)
        rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(rows and not any(r["allowed"] for r in rows))


if __name__ == "__main__":
    unittest.main()
