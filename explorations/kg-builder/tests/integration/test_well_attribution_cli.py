"""Verified synthetic gold, DEV output, test_subset-only TEST and CLI privacy guards."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from helpers import PROJECT_ROOT, clean_dir, run_kgb
from kgbuilder.core.text import read_jsonl, sha256_file, write_json, write_jsonl
from unit.test_well_attribution import synthetic_run
from unit.test_well_gold import TEST_CONFIG, gold_fixture
from kgbuilder.evaluation import well_gold


class WellAttributionCliTest(unittest.TestCase):
    def test_recall_v2_dev_labels_and_test_privacy(self):
        from unit.test_well_gold import TEST_CONFIG_V2
        for split_name in ("dev", "test"):
            cfg = gold_fixture(complete=True, config=TEST_CONFIG_V2)
            root = clean_dir(PROJECT_ROOT / "runs/_test/recall_attribute_cli")
            corpus = cfg["root"] / "corpus"
            split = json.loads((cfg["root"] / "split.json").read_text())
            docs = [d for d in read_jsonl(corpus / "corpus.jsonl") if d["doc_id"] in split["dev" if split_name == "dev" else "test_subset"]]
            run = synthetic_run(root, docs, [], level="A4")
            result = run_kgb(["eval", "attribution", "--config", "configs/experiments/bsee_eval.yaml", "--run", str(run),
                "--corpus", str(corpus), "--gold-config", str(TEST_CONFIG_V2), "--split", split_name, "--out", str(root / "out")])
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads((root / "out/attribution.json").read_text())
            self.assertEqual("recall_diagnostics" in output, split_name == "dev")
            self.assertEqual("recall_triggers" in output, split_name == "dev")
            self.assertEqual((root / "out/per_fact.jsonl").exists(), split_name == "dev")
            if split_name == "dev":
                rows = read_jsonl(root / "out/per_fact.jsonl")
                self.assertTrue(rows)
                for row in rows:
                    self.assertTrue(row["relation_absent"] and row["sentence_silent"] and row["chunk_abstained"])
            else:
                for path in (root / "out").iterdir():
                    for doc in docs:
                        self.assertNotIn(doc["doc_id"], path.read_text())
                        self.assertNotIn(doc["text"], path.read_text())

    def test_v2_lexicon_hash_and_v1_compatibility(self):
        from unit.test_well_gold import TEST_CONFIG_V2
        for config in (TEST_CONFIG, TEST_CONFIG_V2):
            cfg = gold_fixture(complete=True, config=config)
            root = clean_dir(PROJECT_ROOT / "runs/_test/recall_attribute_lexicon")
            corpus = cfg["root"] / "corpus"
            split = json.loads((cfg["root"] / "split.json").read_text())
            docs = [d for d in read_jsonl(corpus / "corpus.jsonl") if d["doc_id"] in split["dev"]]
            run = synthetic_run(root, docs, [], level="A0")
            args = ["eval", "attribution", "--config", "configs/experiments/bsee_eval.yaml", "--run", str(run),
                    "--corpus", str(corpus), "--gold-config", str(config), "--split", "dev"]
            lexicon = root / "lexicon.yaml"
            lexicon.write_bytes((PROJECT_ROOT / "configs/domains/bsee/bsee_literals.yaml").read_bytes())
            result = run_kgb([*args, "--lexicon", str(lexicon), "--out", str(root / "copy")])
            self.assertEqual(result.returncode, 0, result.stderr)
            lexicon.write_bytes(lexicon.read_bytes() + b"\n")
            result = run_kgb([*args, "--lexicon", str(lexicon), "--out", str(root / "changed")])
            self.assertEqual(result.returncode, 2 if config == TEST_CONFIG_V2 else 0, result.stderr)
            if config == TEST_CONFIG_V2:
                self.assertIn("converter lexicon hash differs from freeze", result.stderr)
            else:
                from unit.test_well_attribution import LEXICON
                from kgbuilder.core.config import load_well_eval
                from kgbuilder.core.well_literals import load_lexicon
                from kgbuilder.evaluation.well_attribution import attribute
                attribute(run, corpus, cfg["root"], load_well_eval(PROJECT_ROOT / "configs/experiments/bsee_eval.yaml").model_dump(),
                          load_lexicon(lexicon), "dev", "full", root / "direct")
                for p in (root / "changed").iterdir():
                    self.assertEqual(p.read_bytes(), (root / "direct" / p.name).read_bytes())

    def test_test_subset_test_output_is_aggregate_only(self):
        cfg = gold_fixture(complete=True)
        root = clean_dir(PROJECT_ROOT / "runs/_test/guided_attribute_pilot_cli")
        corpus = cfg["root"] / "corpus"
        split = json.loads((cfg["root"] / "split.json").read_text())
        docs = [d for d in read_jsonl(corpus / "corpus.jsonl") if d["doc_id"] in split["test_subset"]]
        self.assertTrue(docs)
        run = synthetic_run(root, docs, [], level="A0")
        result = run_kgb(["eval", "attribution", "--config", "configs/experiments/bsee_eval.yaml", "--run", str(run),
                          "--corpus", str(corpus), "--gold-config", str(TEST_CONFIG), "--split", "test", "--out", str(root / "out")])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("per_chunk", json.loads(result.stdout))
        self.assertFalse((root / "out/per_fact.jsonl").exists())
        texts = [result.stdout, *[p.read_text() for p in (root / "out").iterdir()]]
        for text in texts:
            for doc in docs:
                self.assertNotIn(doc["doc_id"], text)
                self.assertNotIn(doc["text"], text)

    def test_verified_dev_and_cli_guards(self):
        cfg = gold_fixture(complete=True)
        root = clean_dir(PROJECT_ROOT / "runs/_test/guided_attribute_cli")
        corpus = cfg["root"] / "corpus"
        split = json.loads((cfg["root"] / "split.json").read_text())
        docs = [d for d in read_jsonl(corpus / "corpus.jsonl") if d["doc_id"] in split["dev"]]
        run = synthetic_run(root, docs, [], level="A0")
        args = ["eval", "attribution", "--config", "configs/experiments/bsee_eval.yaml", "--run", str(run), "--corpus", str(corpus),
                "--gold-config", str(TEST_CONFIG), "--split", "dev", "--out", str(root / "out")]
        result = run_kgb(args)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["llm_calls"], 0)
        self.assertNotIn("per_chunk", output)
        self.assertEqual(output["stages"]["extract_missed"], 1)
        self.assertEqual(output["inputs"]["policy"], sha256_file(PROJECT_ROOT / "configs/experiments/bsee_eval.yaml"))
        self.assertEqual(output["inputs"]["lexicon"], sha256_file(PROJECT_ROOT / "configs/domains/bsee/bsee_literals.yaml"))
        self.assertTrue((root / "out/per_fact.jsonl").is_file())
        self.assertEqual(run_kgb(args).returncode, 2)
        result = run_kgb([*args, "--split", "test", "--out", str(root / "not_pilot")])
        self.assertEqual(result.returncode, 2)
        self.assertIn("run scope outside test_subset", result.stderr)
        (run / "graph_strict.json").unlink()
        result = run_kgb([*args, "--export", "strict", "--out", str(root / "missing_strict")])
        self.assertEqual(result.returncode, 2)
        self.assertIn("missing requested graph export", result.stderr)
        lexicon = root / "bad_lexicon.yaml"; lexicon.write_text("version: 1\n", encoding="utf-8")
        result = run_kgb([*args, "--lexicon", str(lexicon), "--out", str(root / "bad_lexicon")])
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid literal lexicon", result.stderr)
        policy = root / "alternate_policy.yaml"
        policy.write_bytes((PROJECT_ROOT / "configs/experiments/bsee_eval.yaml").read_bytes() + b"\n")
        result = run_kgb([*args, "--config", str(policy), "--out", str(root / "bad_policy")])
        self.assertEqual(result.returncode, 2)
        self.assertIn("policy hash differs from freeze", result.stderr)
        changed = [{**d, "text": d["text"] + " Changed."} for d in docs]
        write_jsonl(run / "documents.jsonl", changed)
        result = run_kgb([*args, "--out", str(root / "bad_scope")])
        self.assertEqual(result.returncode, 2)
        self.assertIn("scope/hash mismatch", result.stderr)

    def test_outside_subset_document_refused(self):
        prepare = well_gold.prepare
        def reserve_test(cfg, corpus):
            selection = json.loads((corpus / "selection.json").read_text())
            selection["test_subset"] = []
            write_json(corpus / "selection.json", selection)
            return prepare(cfg, corpus)
        with patch.object(well_gold, "prepare", side_effect=reserve_test):
            cfg = gold_fixture(complete=True)
        root = clean_dir(PROJECT_ROOT / "runs/_test/guided_attribute_reserved_cli")
        corpus = cfg["root"] / "corpus"
        split = json.loads((cfg["root"] / "split.json").read_text())
        docs = [d for d in read_jsonl(corpus / "corpus.jsonl") if d["doc_id"] in split["test"]]
        # Reserve the synthetic TEST documents before preparing and sealing gold.
        self.assertEqual(split["test_subset"], [])
        run = synthetic_run(root, docs, [], level="A0")
        result = run_kgb(["eval", "attribution", "--config", "configs/experiments/bsee_eval.yaml", "--run", str(run),
                          "--corpus", str(corpus), "--gold-config", str(TEST_CONFIG), "--split", "test", "--out", str(root / "out")])
        self.assertEqual(result.returncode, 2)
        self.assertIn("run scope outside test_subset", result.stderr)
        self.assertFalse((root / "out/attribution.json").exists())
