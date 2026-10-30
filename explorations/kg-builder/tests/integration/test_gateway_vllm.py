"""Authenticated fake-vLLM modes, profile isolation, replay and preflight."""
from __future__ import annotations

import json
import os
import socket
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from helpers import PROJECT_ROOT, RECORDED, clean_dir, fake_vllm
from kgbuilder.build.pipeline import preflight
from kgbuilder.core.config import KgbError, load_config
from kgbuilder.runtime.gateway import Gateway, cache_key, render, request_key, row_key
from kgbuilder.runtime.onprem import blocked_count, guard_network, load_env


class VllmGatewayTest(unittest.TestCase):
    def setUp(self):
        load_env()
        self.root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/gateway_vllm" / self._testMethodName)
        self.gateways = []
        self.saved = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo
        self.net = guard_network(self.root / "net.jsonl")
        self.env = patch.dict(os.environ, {"KGB_VLLM_API_KEY": "test-key"})
        self.env.start()
        self.body = {"model": "qwen3.6-35b-a3b-fp8", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 1, "temperature": 0}

    def tearDown(self):
        for gateway in self.gateways: gateway.stop()
        self.env.stop()
        socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = self.saved
        self.assertEqual(blocked_count(self.net), 0)

    def gateway(self, upstream="http://127.0.0.1:9/v1", mode="off", replay=(), profile="vllm", request_mode="completions_chatml"):
        number = len(self.gateways)
        gateway = Gateway(upstream, self.root / f"calls{number}.jsonl", self.root / f"cache{number}.jsonl", mode,
                          replay, profile=profile, request_mode=request_mode, api_key_env="KGB_VLLM_API_KEY")
        self.gateways.append(gateway)
        return gateway, gateway.start()

    def chat(self, url, body=None):
        req = urllib.request.Request(url + "/chat/completions", data=json.dumps(body or self.body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as response: return json.load(response)

    def test_raw_chatml_and_auth(self):
        with fake_vllm(["answer"]) as (upstream, received):
            gateway, url = self.gateway(upstream)
            self.assertEqual(self.chat(url)["choices"][0]["message"]["content"], "answer")
            path, req, authorization = received[0]
            self.assertEqual((path, authorization), ("/v1/completions", "Bearer test-key"))
            self.assertEqual(req["prompt"], render(self.body["messages"]))
            row = json.loads(gateway.log_path.read_text(encoding="utf-8"))
            self.assertEqual(row["profile"], "vllm")
            self.assertEqual(row["key"], cache_key(req, "vllm"))
            self.assertNotEqual(row["key"], request_key(req))
            self.assertNotIn("test-key", gateway.log_path.read_text(encoding="utf-8"))
            with urllib.request.urlopen(url + "/models", timeout=10) as response:
                self.assertEqual(json.load(response)["data"][0]["id"], self.body["model"])
            self.assertEqual(received[-1][2], "Bearer test-key")

    def test_chat_nothink_and_null_content(self):
        with fake_vllm(["answer", None]) as (upstream, received):
            gateway, url = self.gateway(upstream, request_mode="chat_nothink")
            self.assertEqual(self.chat(url)["choices"][0]["message"]["content"], "answer")
            path, req, authorization = received[0]
            self.assertEqual(path, "/v1/chat/completions")
            self.assertEqual(req["messages"], self.body["messages"])
            self.assertEqual(req["chat_template_kwargs"], {"enable_thinking": False})
            self.assertNotIn("prompt", req)
            self.assertEqual(self.chat(url)["choices"][0]["message"]["content"], "")
            row = json.loads(gateway.log_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row_key(row), row["key"])

    def test_profile_isolation_and_replay_both_modes(self):
        for request_mode in ("completions_chatml", "chat_nothink"):
            with self.subTest(mode=request_mode):
                with fake_vllm(["recorded"]) as (upstream, received):
                    live, url = self.gateway(upstream, "readwrite", request_mode=request_mode)
                    self.assertEqual(self.chat(url)["choices"][0]["message"]["content"], "recorded")
                replay_path = live.log_path
                laptop, url = self.gateway(mode="readonly", replay=[replay_path], profile="lmstudio", request_mode=request_mode)
                with self.assertRaises(urllib.error.HTTPError) as caught: self.chat(url)
                self.assertEqual(caught.exception.code, 503)
                server, url = self.gateway(mode="readonly", replay=[replay_path], request_mode=request_mode)
                self.assertEqual(self.chat(url)["choices"][0]["message"]["content"], "recorded")
                self.assertEqual(server.stats["cache_hits"], 1)
        row = json.loads(RECORDED["kggen_showcase"].read_text(encoding="utf-8").splitlines()[0])
        gateway, url = self.gateway(mode="readonly", replay=[RECORDED["kggen_showcase"]])
        body = {"model": row["params"]["model"], "messages": row["messages"], "max_tokens": row["asked_max_tokens"], "temperature": row["params"]["temperature"]}
        with self.assertRaises(urllib.error.HTTPError) as caught: self.chat(url, body)
        self.assertEqual(caught.exception.code, 503)

    def test_wrong_key_is_401_not_fatal(self):
        with fake_vllm(["unused"]) as (upstream, received):
            gateway, url = self.gateway(upstream)
            with patch.dict(os.environ, {"KGB_VLLM_API_KEY": "wrong-test-key"}):
                with self.assertRaises(urllib.error.HTTPError) as caught: self.chat(url)
            self.assertEqual(caught.exception.code, 401)
            self.assertIsNone(gateway.fatal)

    def test_preflight_readiness_and_probe(self):
        def config(url):
            return load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml", sets=["llm.profile=vllm", "llm.base_url=" + url])
        with fake_vllm(["OK"]) as (upstream, received):
            cfg = config(upstream)
            self.assertFalse(any("context" in x for x in preflight(cfg)))
            self.assertIn("Probe: OK", preflight(cfg, probe=True))
            self.assertTrue(all("/api/v0" not in path for path, _, _ in received))
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(KgbError, "KGB_VLLM_API_KEY") as caught: preflight(cfg)
                self.assertEqual(caught.exception.code, 3)
            with patch.dict(os.environ, {"KGB_VLLM_API_KEY": "wrong-test-key"}):
                with self.assertRaisesRegex(KgbError, "API key") as caught: preflight(cfg)
                self.assertEqual(caught.exception.code, 3)
        for settings, text in [({"model": "other"}, "served-model-name"), ({"max_model_len": 4096}, "context")]:
            with fake_vllm([], **settings) as (upstream, received):
                with self.assertRaisesRegex(KgbError, text) as caught: preflight(config(upstream))
                self.assertEqual(caught.exception.code, 3)
        with fake_vllm([], max_model_len=None) as (upstream, received):
            self.assertTrue(any("WARNING" in x and "max_model_len" in x for x in preflight(config(upstream))))
        with self.assertRaisesRegex(KgbError, "tunnel") as caught: preflight(config("http://127.0.0.1:9/v1"))
        self.assertEqual(caught.exception.code, 3)


if __name__ == "__main__": unittest.main()
