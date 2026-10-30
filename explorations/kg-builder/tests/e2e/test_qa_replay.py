"""Replay the recorded graph QA build and reader with no personal cache."""
from __future__ import annotations

import json
import unittest

import yaml

from helpers import PROJECT_ROOT, SENTENCE_GROUNDING, EXACT_LINKING_QA, sets, TWOWIKI_QA_FIXTURE, clean_dir, run_kgb
from kgbuilder.core.text import sha256_file

CORPUS_LIMIT = 24
QA_LIMIT = 10


class QaReplayTest(unittest.TestCase):
    def test_qa_replay(self):
        if not TWOWIKI_QA_FIXTURE.is_file():
            self.fail("Required recorded fixture is missing")
        live_root = PROJECT_ROOT / "runs/reference/twowiki10_sentence_grounding"
        manifest = live_root / "2wiki10/A0/manifest.json"
        if manifest.exists():
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["config"]["corpus"]["limit"], CORPUS_LIMIT)
        live_qa_path = live_root / "qa/qa.json"
        live_qa = json.loads(live_qa_path.read_text(encoding="utf-8")) if live_qa_path.exists() else None
        if live_qa is not None:
            self.assertEqual(live_qa["config"]["limit"], QA_LIMIT)
        out = clean_dir(PROJECT_ROOT / "runs/_test/qa_replay")
        tmp = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/qa_replay")
        result = run_kgb(["run", "--config", "configs/experiments/twowiki10_demo.yaml", "--mock", *sets(SENTENCE_GROUNDING), "--set", f"corpus.limit={CORPUS_LIMIT}",
                          "--out", str(out), "--overwrite"], timeout=1800, test_id="qa_replay")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for level in ("A0", "A1", "A4"):
            run = out / "2wiki10" / level
            metrics = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["llm"]["cache_misses"], 0)
            live = live_root / "2wiki10" / level / "graph.json"
            if live.exists():
                self.assertEqual(sha256_file(run / "graph.json"), sha256_file(live))
        raw = yaml.safe_load((PROJECT_ROOT / "configs/experiments/twowiki10_qa.yaml").read_text(encoding="utf-8"))
        raw["qa"]["graphs"] = {level: str(out / "2wiki10" / level) for level in ("A0", "A1", "A4")}
        source = tmp / "qa.yaml"
        source.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        result = run_kgb(["eval", "qa", "--config", str(source), "--mock", *sets(EXACT_LINKING_QA), "--set", f"qa.limit={QA_LIMIT}",
                          "--out", str(out / "qa"), "--overwrite"], timeout=1800, test_id="qa_replay")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads((out / "qa/qa.json").read_text(encoding="utf-8"))
        self.assertEqual((len(report["rows"]), report["n_questions"]), (7, QA_LIMIT))
        for row in report["rows"]:
            self.assertEqual(row["llm"]["cache_misses"], 0)
            if live_qa is not None:
                live_row = next(r for r in live_qa["rows"] if r["row"] == row["row"])
                for key in ["em", "f1", "no_context", *[k for k in row if k.startswith("recall@")]]:
                    self.assertEqual(row[key], live_row[key], (row["row"], key))
        self.assertFalse((tmp / "no_cache.jsonl").exists())


if __name__ == "__main__": unittest.main()
