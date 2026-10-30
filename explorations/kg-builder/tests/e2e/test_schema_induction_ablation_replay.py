"""Hermetic replay of the grouped schema induction/judge validation/ablation LIVE capture, gated on its fixture."""
from __future__ import annotations

import copy
import json
import unittest

from helpers import PROJECT_ROOT, SENTENCE_GROUNDING, sets, clean_dir, run_kgb
from kgbuilder.core.text import read_jsonl, sha256_file
from kgbuilder.core.config import AblationInduce
from kgbuilder.evaluation import ablation

OPTION = "A"
INDUCE_2WIKI = ["--set", "induce.max_entities=20"] if OPTION == "B" else []
TWOWIKI_MANIFEST = PROJECT_ROOT / "runs/reference/twowiki10_sentence_grounding/2wiki10/A0/manifest.json"
TWOWIKI_SUBSET = (["--set", "corpus.limit=14"] if TWOWIKI_MANIFEST.is_file()
          and json.loads(TWOWIKI_MANIFEST.read_text(encoding="utf-8"))["config"]["corpus"]["limit"] == 14 else [])
HAS_2WIKI = (PROJECT_ROOT / "data/fixtures/llm/twowiki10_kggen_qa.jsonl").is_file()


class SchemaInductionAblationReplayTest(unittest.TestCase):
    def test_replay(self):
        if not (PROJECT_ROOT / "data/fixtures/llm/schema_induction_ablation_sentence.jsonl").is_file():
            self.fail("Required recorded fixture is missing")
        root = clean_dir(PROJECT_ROOT / "runs/_test/schema_ablation_replay")
        cache = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/schema_ablation_replay") / "no_cache.jsonl"
        def run(args):
            result = run_kgb([*args, *sets(SENTENCE_GROUNDING), "--mock", "--set", "llm.cache_path=.cache/tmp/tests/schema_ablation_replay/no_cache.jsonl"],
                             test_id="schema_ablation_replay", timeout=1800)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(cache.exists())
        for name, config in [("showcase_noschema", "configs/experiments/showcase_noschema.yaml"), ("2wiki10", "configs/experiments/twowiki10.yaml")]:
            live_induce = PROJECT_ROOT / "runs/reference/schema_induction" / name / "induce"
            self.assertTrue(HAS_2WIKI)
            self.assertTrue(live_induce.is_dir(), str(live_induce))
            source = "runs/reference/schema_induction/showcase_noschema/A4" if name == "showcase_noschema" else json.loads((live_induce / "summary.json").read_text())["source_run"]
            flags = INDUCE_2WIKI if name == "2wiki10" else []
            out = root / "schema" / name / "induce"
            run(["induce", "--config", config, "--run", source, "--out", str(out), "--overwrite", *flags])
            self.assertEqual((out / "schema_induced.yaml").read_bytes(), (live_induce / "schema_induced.yaml").read_bytes())
            live_pass2 = PROJECT_ROOT / "runs/reference/schema_induction" / (name + "_pass2") / "A4"
            self.assertTrue(live_pass2.is_dir(), str(live_pass2))
            flags = [*TWOWIKI_SUBSET, "--set", "extract.backend=kggen"] if name == "2wiki10" else []
            out = root / "schema" / (name + "_pass2") / "A4"
            run(["build", "--config", config, "--ablation", "A4", *flags,
                 "--set", "canon.schema_path=" + (live_induce / "schema_induced.yaml").relative_to(PROJECT_ROOT).as_posix(),
                 "--out", str(out), "--overwrite"])
            self.assertEqual(sha256_file(out / "graph.json"), sha256_file(live_pass2 / "graph.json"))
        excluded = ["--exclude", "2wiki10/A5"] if OPTION == "B" and HAS_2WIKI else []
        run(["ablate", "--config", "configs/experiments/ablation_sentence_grounding.yaml", *excluded, "--out", str(root / "ablation"), "--overwrite"])
        table = json.loads((root / "ablation/ablation.json").read_text())
        self.assertTrue(all(row["status"] in {"ok", "skipped"} for row in table["rows"]))
        live_path = PROJECT_ROOT / "runs/reference/ablation_sentence_grounding/ablation.json"
        self.assertTrue(live_path.is_file(), str(live_path))
        if live_path.is_file():
            live = json.loads(live_path.read_text())
            def normalize(row):
                row = copy.deepcopy(row)
                row.pop("replay_wall_seconds", None)
                if row.get("llm") is not None:
                    row["llm"].pop("new_seconds", None)
                return row
            for replayed, recorded in zip(table["rows"], live["rows"]):
                self.assertEqual(normalize({k: replayed[k] for k in recorded}), normalize(recorded))
                if replayed["status"] == "ok":
                    self.assertEqual(replayed["flagged"], 0)
                    self.assertEqual(replayed["flagged_by_reason"], {})
                self.assertIsNone(replayed["webnlg_strict"])
            self.assertEqual(len(table["rows"]), len(live["rows"]))
            def qa_rows(value):
                return [{k: v for k, v in row.items() if "seconds" not in k} for row in value["rows"]] if value else None
            if HAS_2WIKI:
                self.assertIsNotNone(table["qa"])
                self.assertIsNotNone(live["qa"])
                self.assertEqual(qa_rows(table["qa"]), qa_rows(live["qa"]))
            else:
                self.assertIsNone(table["qa"])
                self.assertIsNone(live["qa"])
            self.assertEqual(table["induce"], live["induce"])
            for live_block in live["induce"]:
                if live_block["status"] != "ok":
                    continue
                label = live_block["label"]
                pass2 = root / "schema" / (label + "_pass2") / "A4"
                live_pass2 = PROJECT_ROOT / "runs/reference/schema_induction" / (label + "_pass2") / "A4"
                replayed = ablation.induce_block(AblationInduce(
                    label=label, induce_dir=root / "schema" / label / "induce",
                    pass2_run=pass2 if live_pass2.is_dir() else None))
                self.assertEqual({k: v for k, v in replayed.items() if k != "pass2_fresh_calls"},
                                 {k: v for k, v in live_block.items() if k != "pass2_fresh_calls"})
                if live_pass2.is_dir():
                    self.assertEqual(replayed["pass2_fresh_calls"], 0)
                else:
                    self.assertIsNone(replayed["pass2_fresh_calls"])
        for log in root.rglob("llm_calls.jsonl"):
            self.assertFalse(any(r.get("miss") for r in read_jsonl(log)), str(log))
        for metrics in root.rglob("metrics.json"):
            self.assertEqual(json.loads(metrics.read_text())["llm"]["cache_misses"], 0, str(metrics))
