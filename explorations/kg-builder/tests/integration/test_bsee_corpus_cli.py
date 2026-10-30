"""Synthetic CLI corpus generation and containment without model imports."""
from __future__ import annotations

import json
import unittest

import yaml

from helpers import PROJECT_ROOT, clean_dir, run_kgb
from unit.test_bsee_corpus import corpus_fixture


class BseeCorpusCliTest(unittest.TestCase):
    def test_v2_cli_verification_and_containment(self):
        from unit.test_bsee_corpus import corpus_v2_fixture
        from kgbuilder.core.text import read_jsonl, write_jsonl
        from unit.test_well_gold import TEST_CONFIG
        root, cfg, _ = corpus_v2_fixture("recall_corpus_cli")
        path = root / "config.yaml"
        path.write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
        args = ["domain", "corpus-v2", "--config", str(path)]
        result = run_kgb([*args, "--out", str(root / "out")])
        self.assertEqual(result.returncode, 0, result.stderr)
        stats = json.loads(result.stdout)
        def integers(value):
            return all(integers(v) for v in value.values()) if isinstance(value, dict) else type(value) is int
        self.assertTrue(integers(stats))
        self.assertEqual(stats["n_gold"], 7)
        result = run_kgb([*args, "--out", str(root / "repeat")])
        self.assertEqual(result.returncode, 0, result.stderr)
        for p in (root / "out").iterdir(): self.assertEqual(p.read_bytes(), (root / "repeat" / p.name).read_bytes())
        for output in (root / "out", cfg.source_corpus, PROJECT_ROOT / "configs/recall_bad"):
            result = run_kgb([*args, "--out", str(output)])
            self.assertEqual(result.returncode, 2)
        source = cfg.source_corpus / "corpus.jsonl"
        original = source.read_bytes(); source.write_bytes(original + b"\n")
        result = run_kgb([*args, "--out", str(root / "bad_hash")])
        self.assertEqual(result.returncode, 2)
        self.assertIn("corpus hash differs from freeze", result.stderr)
        self.assertFalse((root / "bad_hash").exists())
        source.write_bytes(original)
        sources = read_jsonl(cfg.source_corpus / "doc_sources.jsonl")
        sources[-1]["text_sha256"] = "bad"
        write_jsonl(cfg.source_corpus / "doc_sources.jsonl", sources)
        result = run_kgb([*args, "--out", str(root / "bad_source")])
        self.assertEqual(result.returncode, 2)
        self.assertIn("eligible/source mismatch", result.stderr)
        gold_root = PROJECT_ROOT / yaml.safe_load(TEST_CONFIG.read_text())["root"]
        seal = gold_root / "seals/annotator_b.json"
        seal.write_bytes(seal.read_bytes() + b"\n")
        result = run_kgb([*args, "--out", str(root / "bad_seal")])
        self.assertEqual(result.returncode, 2)
        self.assertFalse((root / "bad_seal").exists())

    def test_dev_split_guards_and_repeat(self):
        from unit.test_well_gold import gold_fixture, TEST_CONFIG
        from kgbuilder.core.text import sha256_file
        cfg = gold_fixture(complete=True)
        root = clean_dir(PROJECT_ROOT / "runs/_test/guided_subset_cli")
        corpus = cfg["root"] / "corpus"
        args = ["domain", "split-corpus", "--corpus", str(corpus), "--gold-config", str(TEST_CONFIG), "--part", "dev"]
        result = run_kgb([*args, "--out", str(root / "out")])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["n"], 1)
        result = run_kgb([*args, "--out", str(root / "repeat")])
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("dev.jsonl", "manifest.json"):
            self.assertEqual(sha256_file(root / "out" / name), sha256_file(root / "repeat" / name))
        self.assertEqual(run_kgb([*args, "--out", str(root / "out")]).returncode, 2)
        result = run_kgb([*args[:-1], "test", "--out", str(root / "test")])
        self.assertEqual(result.returncode, 2)
        path = corpus / "corpus.jsonl"
        path.write_bytes(path.read_bytes() + b"\n")
        result = run_kgb([*args, "--out", str(root / "bad")])
        self.assertEqual(result.returncode, 2)
        self.assertIn("corpus hash differs from freeze", result.stderr)
        self.assertFalse((root / "bad").exists())

    def test_cli(self):
        root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/bsee_corpus_cli")
        tables = clean_dir(PROJECT_ROOT / "runs/_test/bsee_corpus_cli_tables")
        cfg = corpus_fixture(root, tables)
        path = root / "corpus.yaml"
        path.write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
        out = clean_dir(PROJECT_ROOT / "runs/_test/bsee_corpus_cli")
        args = ["domain", "corpus", "--config", str(path), "--out", str(out)]
        result = run_kgb(args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["llm_calls"], 0)
        self.assertEqual(run_kgb(args).returncode, 2)
