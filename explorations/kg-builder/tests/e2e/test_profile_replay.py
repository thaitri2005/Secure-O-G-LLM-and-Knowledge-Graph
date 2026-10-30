"""Export a fake server run and replay it without a server or private cache."""
from __future__ import annotations

import json
import unittest
from helpers import PROJECT_ROOT, RECORDED, clean_dir, fake_vllm, run_kgb
from kgbuilder.core.text import read_jsonl, sha256_file
from kgbuilder.runtime.gateway import render


class ProfileReplayTest(unittest.TestCase):
    def test_server_fixture_export_and_offline_replay(self):
        fixture_root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/vllm")
        env = {"KGB_VLLM_API_KEY": "test-key"}
        for name in ("vllm_nofixture", "vllm_live", "vllm_replay", "lmstudio_a0"):
            clean_dir(PROJECT_ROOT / ".cache/tmp/tests" / name)
            clean_dir(PROJECT_ROOT / "runs/_test" / name)
        def build(name, extra):
            return run_kgb(["build", "--config", "configs/experiments/showcase.yaml", "--ablation", "A0", "--out", "runs/_test/" + name, *extra], test_id=name, env_extra=env)
        result = build("vllm_nofixture", ["--mock", "--set", "llm.profile=vllm"])
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        self.assertIn("LLM replay miss for profile vllm", result.stderr)
        rows = read_jsonl(RECORDED["kggen_showcase"])
        contents = {render(row["messages"]): row["content"] for row in rows}
        with fake_vllm(lambda body: contents[body["prompt"]], model="qwen3.6-35b-a3b") as (upstream, received):
            result = build("vllm_live", ["--set", "llm.profile=vllm", "--set", "llm.model=qwen3.6-35b-a3b", "--set", "llm.base_url=" + upstream])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(any(path == "/v1/completions" for path, _, _ in received))
        fixture = fixture_root / "fixture.jsonl"
        result = run_kgb(["fixtures", "--from", "runs/_test/vllm_live", "--to", str(fixture), "--overwrite"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        recorded = read_jsonl(fixture)
        self.assertTrue(recorded)
        self.assertTrue(all(row["profile"] == "vllm" for row in recorded))
        self.assertFalse((PROJECT_ROOT / ".cache/tmp/tests/vllm_replay/no_cache.jsonl").exists())
        result = build("vllm_replay", ["--mock", "--set", "llm.profile=vllm", "--set", "llm.model=qwen3.6-35b-a3b", "--set", f"llm.replay_logs=[{fixture.as_posix()}]"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        metrics = json.loads((PROJECT_ROOT / "runs/_test/vllm_replay/metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(metrics["llm"]["cache_misses"], 0)
        self.assertFalse((PROJECT_ROOT / ".cache/tmp/tests/vllm_replay/no_cache.jsonl").exists())
        result = build("lmstudio_a0", ["--mock"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sha256_file(PROJECT_ROOT / "runs/_test/vllm_replay/graph.json"), sha256_file(PROJECT_ROOT / "runs/_test/lmstudio_a0/graph.json"))


if __name__ == "__main__": unittest.main()
