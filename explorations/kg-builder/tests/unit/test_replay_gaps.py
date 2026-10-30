"""Read-only completion gate agrees with fixture export and replay indexing."""
from __future__ import annotations

import json
import unittest

from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.build import pipeline
from kgbuilder.core.text import write_jsonl
from kgbuilder.runtime import gateway


class ReplayGapsTest(unittest.TestCase):
    def setUp(self):
        self.root = clean_dir(PROJECT_ROOT / "runs/_test/replay_gaps" / self._testMethodName)

    def row(self, name, content):
        messages = [{"role": "user", "content": name}]
        params = {"model": "qwen3.6-35b-a3b", "temperature": 0, "max_tokens": 8, "stop": gateway.STOP}
        return {"messages": messages, "params": params, "content": content, "stage": "judge",
                "key": gateway.cache_key({**params, "prompt": gateway.render(messages)}),
                "cache_hit": False}

    def test_export_and_replay_agree(self):
        r1, r2, r3, r4 = [self.row(name, answer) for name, answer in
                          [("k1", "Yes"), ("k2", None), ("k3", "No"), ("k4", None)]]
        a, b = self.root / "a/llm_calls.jsonl", self.root / "b/llm_calls.jsonl"
        write_jsonl(a, [r1, r2, r3])
        write_jsonl(b, [r4, {**r4, "content": "Yes"}, {**r1, "cache_hit": True}])
        self.assertEqual(gateway.replay_gaps([a, b]), {
            "rows": 6, "skipped": 0, "failed_rows": 2,
            "unreplayable": [{"key": r2["key"][:12], "stage": "judge"}]})
        fixture = self.root / "fx.jsonl"
        self.assertEqual(pipeline.export_fixtures(self.root, fixture, False), 3)
        index, skipped = gateway.load_replay([fixture])
        self.assertEqual(set(index), {r1["key"], r3["key"], r4["key"]})
        self.assertNotIn(r2["key"], index)
        self.assertEqual(skipped, 0)

    def test_null_rows_misses_and_invalid_lines(self):
        rows = [self.row("null-a", None), self.row("null-b", None)]
        miss = {**self.row("miss", None), "miss": True}
        path = self.root / "llm_calls.jsonl"
        write_jsonl(path, [*rows, miss])
        gaps = gateway.replay_gaps([path, self.root / "missing.jsonl"])
        self.assertEqual(gaps["failed_rows"], 2)
        self.assertEqual(gaps["unreplayable"], [
            {"key": row["key"][:12], "stage": "judge"} for row in sorted(rows, key=lambda row: row["key"])])
        # Malformed JSON cannot supply a key; valid non-object JSON is harmless.
        path.write_text(path.read_text(encoding="utf-8") + "bad json\nnull\n", encoding="utf-8")
        gaps = gateway.replay_gaps([path])
        self.assertEqual((gaps["rows"], gaps["skipped"], gaps["failed_rows"]), (4, 1, 2))
        self.assertNotIn(miss["key"][:12], [row["key"] for row in gaps["unreplayable"]])

