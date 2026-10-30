"""Verify the loopback gateway against recorded responses and fake servers."""
from __future__ import annotations

import json
import os
import subprocess
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from helpers import PROJECT_ROOT, PY_EDC, RECORDED, clean_dir, fake_lmstudio
from kgbuilder.runtime.gateway import Gateway, MIN_TOKENS, STOP, load_replay, render, request_key, row_key, summarize, planned_calls, replay_gaps


class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/gateway" / self._testMethodName)
        self.gateways = []

    def tearDown(self):
        for gateway in self.gateways:
            gateway.stop()

    def gateway(self, url="http://127.0.0.1:9/v1", mode="readonly", logs=()):
        gateway = Gateway(url, self.tmp / "calls.jsonl", self.tmp / "cache.jsonl", mode, list(logs))
        self.gateways.append(gateway)
        return gateway, gateway.start()

    def chat(self, base, body=None):
        body = body or {"model": "qwen3.6-35b-a3b", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 1, "temperature": 0}
        req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.load(response)

    def test_render_and_floor(self):
        with fake_lmstudio(["A"]) as (upstream, received):
            gateway, base = self.gateway(upstream, "off")
            gateway.set_stage("verify")
            self.assertEqual(self.chat(base)["choices"][0]["message"]["content"], "A")
            path, sent = received[0]
            self.assertEqual(path, "/v1/completions")
            self.assertEqual(sent["max_tokens"], MIN_TOKENS)
            self.assertEqual(sent["stop"], STOP)
            self.assertTrue(sent["prompt"].endswith("<think>\n\n</think>\n\n"))
            row = json.loads((self.tmp / "calls.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(row["stage"], "verify")
            self.assertFalse(row["cache_hit"])

    def test_readwrite_then_hit(self):
        with fake_lmstudio(["answer"]) as (upstream, received):
            gateway, base = self.gateway(upstream, "readwrite")
            self.chat(base)
            self.chat(base)
            self.assertEqual(len(received), 1)
            rows = [json.loads(x) for x in (self.tmp / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["cache_hit"] for r in rows], [False, True])
            cache = [json.loads(x) for x in (self.tmp / "cache.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(cache), 1)
            self.assertEqual(row_key(cache[0]), rows[0]["key"])
            self.assertEqual(gateway.stats["cache_hits"], 1)

    def test_recorded_replay(self):
        for path in RECORDED.values():
            for line in path.read_text(encoding="utf-8").splitlines():
                self.assertIsNotNone(row_key(json.loads(line)))
        row = json.loads(RECORDED["kggen_showcase"].read_text(encoding="utf-8").splitlines()[0])
        gateway, base = self.gateway(logs=[RECORDED["kggen_showcase"]])
        body = {"model": row["params"]["model"], "messages": row["messages"],
                "max_tokens": row["asked_max_tokens"], "temperature": row["params"]["temperature"]}
        self.assertEqual(self.chat(base, body)["choices"][0]["message"]["content"], row["content"])
        self.assertEqual(gateway.stats["cache_misses"], 0)
        self.assertIsNone(gateway.fatal)

    def test_all_laptop_keys_unchanged(self):
        logs = sorted((PROJECT_ROOT / "data/fixtures/llm").glob("*.jsonl"))
        self.assertEqual(len(logs), 7 + sum((PROJECT_ROOT / "data/fixtures/llm" / name).is_file() for name in
                                          ("bsee_text_test_subset_v1_base.jsonl", "bsee_text_dev_v1_base.jsonl",
                                           "bsee_text_dev_v1_guided.jsonl", "bsee_text_test_subset_v1_guided.jsonl",
                                           "bsee_text_dev_v2_guided.jsonl", "bsee_text_dev_v2_guided_windows.jsonl",
                                           "bsee_text_dev_v2_guided_groups.jsonl", "bsee_text_dev_v2_guided_recall.jsonl",
                                           "bsee_text_test_v2_guided.jsonl", "bsee_text_test_v2_guided_recall.jsonl")))
        for path in logs:
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                self.assertEqual(row_key(row), request_key({**row["params"], "prompt": render(row["messages"])}), str(path))

    def test_readonly_miss(self):
        gateway, base = self.gateway()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.chat(base)
        self.assertEqual(caught.exception.code, 503)
        self.assertTrue(gateway.fatal.startswith("cache_miss:"))
        row = json.loads((self.tmp / "calls.jsonl").read_text(encoding="utf-8"))
        self.assertTrue(row["miss"])
        self.assertIsNone(row["content"])

    def test_plan_leaf_and_forward(self):
        from kgbuilder.build.pipeline import export_fixtures
        from kgbuilder.core.text import read_jsonl
        gets = []
        def metadata(path):
            gets.append(path)
            return {}
        with fake_lmstudio(["must not be used"], metadata=metadata) as (upstream, received):
            gateway, base = self.gateway(upstream, "plan")
            with patch.object(gateway, "_request", side_effect=AssertionError("plan reached upstream")):
                for stage in ("judge", "qa.text", "induce.concepts"):
                    gateway.set_stage(stage)
                    reply = self.chat(base)
                    self.assertEqual(reply["choices"][0]["message"]["content"], "")
                    self.assertEqual(reply["choices"][0]["finish_reason"], "plan")
                for req in (base + "/models", urllib.request.Request(base + "/completions", data=b"{}")):
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(req, timeout=10)
                    self.assertEqual(caught.exception.code, 503)
            self.assertIsNone(gateway.fatal)
            self.assertEqual((received, gets), ([], []))
        rows = read_jsonl(self.tmp / "calls.jsonl")
        self.assertTrue(all(r["miss"] and r["planned"] and r["content"] is None for r in rows))
        self.assertFalse((self.tmp / "cache.jsonl").exists())
        self.assertEqual(planned_calls([self.tmp / "calls.jsonl"]), {"rows": 3, "planned_rows": 3, "planned_keys": 1,
                         "by_stage": {"judge": 1, "qa.text": 1, "induce.concepts": 1}, "replayed": 0})
        self.assertEqual(replay_gaps([self.tmp / "calls.jsonl"])["unreplayable"], [])
        self.assertEqual(load_replay([self.tmp / "calls.jsonl"])[0], {})
        (self.tmp / "calls.jsonl").rename(self.tmp / "llm_calls.jsonl")
        self.assertEqual(export_fixtures(self.tmp, self.tmp / "fixture.jsonl", False), 0)

    def test_plan_nonleaf_and_hit(self):
        row = json.loads(RECORDED["kggen_showcase"].read_text(encoding="utf-8").splitlines()[0])
        with fake_lmstudio(["must not be used"]) as (upstream, received):
            gateway, base = self.gateway(upstream, "plan", [RECORDED["kggen_showcase"]])
            gateway.set_stage("extract")
            body = {"model": row["params"]["model"], "messages": row["messages"],
                    "max_tokens": row["asked_max_tokens"], "temperature": row["params"]["temperature"]}
            self.assertEqual(self.chat(base, body)["choices"][0]["message"]["content"], row["content"])
            gateway.set_stage("canon")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.chat(base)
            self.assertEqual(caught.exception.code, 503)
            self.assertTrue(gateway.fatal.startswith("cache_miss:"))
            self.assertEqual(received, [])

    def test_three_failures_and_4xx(self):
        gateway, base = self.gateway(mode="off")
        for status in (400, 400, 400):
            with patch.object(gateway._opener, "open", side_effect=urllib.error.HTTPError("http://127.0.0.1", status, "bad", {}, None)):
                with self.assertRaises(urllib.error.HTTPError):
                    self.chat(base)
        self.assertIsNone(gateway.fatal)
        for _ in range(3):
            with patch.object(gateway._opener, "open", side_effect=urllib.error.HTTPError("http://127.0.0.1", 500, "bad", {}, None)):
                with self.assertRaises(urllib.error.HTTPError):
                    self.chat(base)
        self.assertTrue(gateway.fatal.startswith("upstream_failed:"))

    def test_nonloopback_rejected(self):
        with self.assertRaises(ValueError):
            Gateway("http://192.168.1.5/v1", self.tmp / "no.jsonl", None, "off")

    def test_forward_models_and_env_authorization(self):
        with fake_lmstudio(["answer"]) as (upstream, received):
            gateway, base = self.gateway(upstream, "off")
            with urllib.request.urlopen(base + "/models", timeout=10) as response:
                self.assertEqual(json.load(response)["data"][0]["id"], "qwen3.6-35b-a3b")
            real_open = gateway._opener.open
            seen = []
            def inspect(req, **kwargs):
                seen.append(req.get_header("Authorization"))
                return real_open(req, **kwargs)
            with patch.dict(os.environ, {"LMSTUDIO_API_KEY": "temporary-unit-test-value"}):
                with patch.object(gateway._opener, "open", side_effect=inspect):
                    self.chat(base)
            self.assertEqual(seen, ["Bearer temporary-unit-test-value"])

    def test_python39_import(self):
        result = subprocess.run([str(PY_EDC), "-c", "import sys; sys.path.insert(0, 'src'); import kgbuilder.runtime.gateway, kgbuilder.runtime.onprem, kgbuilder.core.project"],
                                cwd=PROJECT_ROOT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_summarize_misses(self):
        rows = [{"usage": {"prompt_tokens": 10, "completion_tokens": 2}, "seconds": 1.5, "cache_hit": True, "finish_reason": "stop"},
                {"usage": {"prompt_tokens": 20, "completion_tokens": 3}, "seconds": 2.5, "cache_hit": False, "finish_reason": "length"},
                {"usage": {}, "seconds": 0, "miss": True, "content": None}]
        path = self.tmp / "summary.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        result = summarize(path)
        self.assertEqual((result["llm_calls"], result["cache_hits"], result["cache_misses"]), (3, 1, 1))
        self.assertEqual((result["prompt_tokens"], result["completion_tokens"], result["llm_seconds"]), (30, 5, 4.0))

    def test_replay_invalid_and_first_wins(self):
        path = self.tmp / "rows.jsonl"
        row = {"params": {"model": "m"}, "messages": [], "content": "first"}
        path.write_text(json.dumps(row) + "\n" + json.dumps({**row, "content": "second"}) + "\nnull\nbad\n", encoding="utf-8")
        index, skipped = load_replay([path])
        self.assertEqual(skipped, 2)
        self.assertEqual(index[row_key(row)]["content"], "first")
        self.assertEqual(request_key({"a": 1, "b": 2}), request_key({"b": 2, "a": 1}))


if __name__ == "__main__":
    unittest.main()
