"""Hermetic replay of the WINDOW_GROUNDING LIVE capture and both graph export levels."""
from __future__ import annotations

import copy
import json
import unittest

from helpers import PROJECT_ROOT, clean_dir, run_kgb
from kgbuilder.core.text import read_jsonl, sha256_file

OPTION = "A"


class WindowGroundingReplayTest(unittest.TestCase):
    def test_replay(self):
        if not (PROJECT_ROOT / "data/fixtures/llm/ablation_window_grounding.jsonl").is_file():
            self.fail("Required recorded fixture is missing")
        root = clean_dir(PROJECT_ROOT / "runs/_test/window_grounding_replay")
        cache = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/window_grounding_replay") / "no_cache.jsonl"
        live = PROJECT_ROOT / "runs/reference"

        def run(args):
            result = run_kgb([*args, "--mock", "--overwrite", "--set",
                              "llm.cache_path=.cache/tmp/tests/window_grounding_replay/no_cache.jsonl"],
                             test_id="window_grounding_replay", timeout=1800)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(cache.exists())

        def read(path):
            return json.loads(path.read_text(encoding="utf-8"))

        def qa_rows(path):
            return [{k: v for k, v in row.items()
                     if k in {"row", "em", "f1", "no_context", "seeded"} or k.startswith("recall@")}
                    for row in read(path)["rows"]]

        flags = ["--set", "qa.modes=[text, graph]"] if OPTION == "B" else []
        run(["eval", "qa", "--config", "configs/experiments/twowiki10_qa_intermediate_graphs.yaml",
             "--out", str(root / "qa_intermediate_graphs"), *flags])
        self.assertEqual(qa_rows(root / "qa_intermediate_graphs/qa.json"), qa_rows(live / "twowiki10_qa_intermediate_graphs/qa.json"))
        flags = ["--exclude", "2wiki10/A5"] if OPTION == "B" else []
        run(["ablate", "--config", "configs/experiments/ablation_window_grounding.yaml",
             "--out", str(root / "ablation"), *flags])

        def normalize(row):
            row = copy.deepcopy(row)
            row.pop("replay_wall_seconds", None)
            if row.get("llm") is not None:
                row["llm"].pop("new_seconds", None)
            return row

        self.assertEqual([normalize(r) for r in read(root / "ablation/ablation.json")["rows"]],
                         [normalize(r) for r in read(live / "ablation_window_grounding/ablation.json")["rows"]])
        self.assertEqual(qa_rows(root / "ablation/qa/qa.json"), qa_rows(live / "ablation_window_grounding/qa/qa.json"))
        for name in ("graph.json", "graph_strict.json"):
            recorded = {p.relative_to(live / "ablation_window_grounding") for p in (live / "ablation_window_grounding").rglob(name)}
            replayed = {p.relative_to(root / "ablation") for p in (root / "ablation").rglob(name)}
            self.assertEqual(replayed, recorded)
            for rel in sorted(recorded):
                self.assertEqual(sha256_file(root / "ablation" / rel), sha256_file(live / "ablation_window_grounding" / rel), str(rel))
        for log in root.rglob("llm_calls.jsonl"):
            self.assertFalse(any(r.get("miss") for r in read_jsonl(log)), str(log))
        for metrics in root.rglob("metrics.json"):
            self.assertEqual(read(metrics)["llm"]["cache_misses"], 0, str(metrics))
