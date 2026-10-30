"""Synthetic evaluator CLI checks, with gold guards added by the evaluation contract."""
from __future__ import annotations

import unittest
import copy
import json
import yaml

from helpers import PROJECT_ROOT, run_kgb
from unit.test_well_eval import eval_fixture
from unit.test_well_gold import TEST_CONFIG, gold_fixture
from kgbuilder.core.text import read_jsonl, sha256_file, write_json, write_jsonl
from kgbuilder.core.well_facts import score
from unit.test_well_facts import fact


class WellEvalCliTest(unittest.TestCase):
    def test_v2_verified_gold(self):
        from unit.test_well_gold import TEST_CONFIG_V2
        from unit.test_well_attribution import synthetic_run
        from helpers import clean_dir
        cfg = gold_fixture(complete=True, config=TEST_CONFIG_V2)
        root = clean_dir(PROJECT_ROOT / "runs/_test/recall_eval_cli")
        corpus = cfg["root"] / "corpus"
        split = json.loads((cfg["root"] / "split.json").read_text())
        docs = [d for d in read_jsonl(corpus / "corpus.jsonl") if d["doc_id"] in split["dev"]]
        run = synthetic_run(root, docs, [], level="A0")
        result = run_kgb(["eval", "wells", "--config", "configs/experiments/bsee_eval.yaml", "--run", str(run),
                          "--corpus", str(corpus), "--gold", str(cfg["root"]), "--gold-config", str(TEST_CONFIG_V2),
                          "--split", "dev", "--out", str(root / "out")])
        self.assertEqual(result.returncode, 0, result.stderr)
        scores = json.loads((root / "out/scores.json").read_text())
        self.assertEqual(scores["converter"]["version"], "v2")
        self.assertIn("ai_gold_converter_v1", scores["exports"]["full"])

    def test_gold_guards_and_success(self):
        root, run, tables, corpus = eval_fixture("bsee_eval_gold_cli")
        cfg = gold_fixture(complete=True)
        docs = read_jsonl(cfg["root"] / "corpus/corpus.jsonl")
        original = json.loads((run / "graph.json").read_text())
        graph = {**original, "documents": [], "chunks": [], "entities": [], "statements": []}
        for i, doc in enumerate(docs):
            identity = doc["doc_id"]
            graph["documents"].append({**doc, "title": None, "published_at": None, "source_uri": None})
            graph["chunks"].append({"chunk_id": identity + "#c000", "doc_id": identity, "idx": 0, "char_start": 0, "char_end": len(doc["text"]), "text": doc["text"]})
            graph["entities"] += [{"entity_id": f"{side}{i}", "name": surface, "aliases": [], "kind": "entity", "mention_ids": [], "resolver": "synthetic"}
                                  for side, surface in (("s", "The well"), ("o", str((i + 1) * 1000) + " ft MD"))]
            statement = copy.deepcopy(original["statements"][0])
            ev = {"doc_id": identity, "chunk_id": identity + "#c000", "char_start": 0, "char_end": len(doc["text"]), "text": doc["text"], "grounding": "exact"}
            statement.update(statement_id=f"statement{i}", subject_id=f"s{i}", object_id=f"o{i}", source_doc_id=identity, evidence_span=ev, evidence=[ev])
            graph["statements"].append(statement)
        write_json(run / "graph.json", graph)
        write_jsonl(run / "documents.jsonl", docs)
        (corpus / "corpus.jsonl").write_bytes((cfg["root"] / "corpus/corpus.jsonl").read_bytes())
        base = ["eval", "wells", "--config", "configs/experiments/bsee_eval.yaml", "--run", str(run), "--corpus", str(corpus), "--out", str(root / "gold_eval")]
        result = run_kgb([*base, "--gold", str(cfg["root"]), "--gold-config", str(TEST_CONFIG)])
        self.assertEqual(result.returncode, 0, result.stderr)
        scores = json.loads((root / "gold_eval/scores.json").read_text())
        self.assertEqual(scores["dev_excluded"], 1)
        self.assertEqual(scores["exports"]["full"]["ai_gold"]["L3"]["f1"], 1)
        self.assertEqual(scores["policy_file_sha256"], sha256_file(PROJECT_ROOT / "configs/experiments/bsee_eval.yaml"))
        self.assertEqual(scores["references"]["ai_gold"]["adjudicated.jsonl"], sha256_file(cfg["root"] / "adjudicated.jsonl"))
        result = run_kgb([*base, "--split", "dev", "--overwrite"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires --gold", result.stderr)
        result = run_kgb([*base, "--split", "dev", "--gold", str(cfg["root"]), "--gold-config", str(TEST_CONFIG), "--out", str(root / "mixed")])
        self.assertEqual(result.returncode, 2)
        self.assertIn("run scope outside dev split", result.stderr)
        dev_ids = set(json.loads((cfg["root"] / "split.json").read_text())["dev"])
        dev_graph = copy.deepcopy(graph)
        dev_graph["documents"] = [d for d in graph["documents"] if d["doc_id"] in dev_ids]
        dev_graph["chunks"] = [c for c in graph["chunks"] if c["doc_id"] in dev_ids]
        dev_graph["statements"] = [s for s in graph["statements"] if s["source_doc_id"] in dev_ids]
        dev_run = root / "dev_run"; dev_run.mkdir()
        write_json(dev_run / "graph.json", dev_graph)
        write_jsonl(dev_run / "documents.jsonl", dev_graph["documents"])
        result = run_kgb([*base, "--run", str(dev_run), "--out", str(root / "dev_eval"), "--split", "dev",
                          "--gold", str(cfg["root"]), "--gold-config", str(TEST_CONFIG)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["gold_split"], "dev")
        self.assertEqual(run_kgb([*base, "--gold", str(root), "--gold-config", str(TEST_CONFIG)]).returncode, 2)
        labels = ["domain", "labels", "--config", "configs/experiments/bsee_eval.yaml", "--tables", str(tables), "--corpus", str(corpus), "--out", str(root / "labels")]
        self.assertEqual(run_kgb(labels).returncode, 2)
        result = run_kgb([*labels, "--gold-config", str(TEST_CONFIG)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self._policy_and_pairing_regressions(root, base, labels, cfg, scores)
        path = cfg["root"] / "seals/annotator_b.json"
        path.write_bytes(path.read_bytes() + b" ")
        self.assertEqual(run_kgb([*base, "--gold", str(cfg["root"]), "--gold-config", str(TEST_CONFIG), "--overwrite"]).returncode, 2)
        self.assertEqual(run_kgb([*labels, "--gold-config", str(TEST_CONFIG), "--overwrite"]).returncode, 2)

    def _policy_and_pairing_regressions(self, root, base, labels, cfg, scores):
        frozen = PROJECT_ROOT / "configs/experiments/bsee_eval.yaml"
        alternate = root / "alternate_eval.yaml"
        alternate.write_bytes(frozen.read_bytes())
        def command(template, config, output):
            args = list(template)
            args[args.index("--config") + 1] = str(config)
            args[args.index("--out") + 1] = str(output)
            return args
        gold_args = ["--gold", str(cfg["root"]), "--gold-config", str(TEST_CONFIG)]
        paired = command(base, alternate, root / "paired")
        result = run_kgb([*paired, *gold_args, "--baseline", str(root / "gold_eval")])
        self.assertEqual(result.returncode, 0, result.stderr)
        paired_scores = json.loads((root / "paired/scores.json").read_text())
        self.assertEqual(paired_scores["exports"]["full"]["ai_gold"]["paired"]["L1"]["difference"], 0)
        result = run_kgb([*command(labels, alternate, root / "identical_labels"), "--gold-config", str(TEST_CONFIG)])
        self.assertEqual(result.returncode, 0, result.stderr)
        policy = yaml.safe_load(frozen.read_text())
        changed = copy.deepcopy(policy); changed["tolerance"]["depth_ft"] = 2
        # Invented F10 example: the alternate policy alone turns an FP into a TP.
        self.assertEqual(score([fact("1000")], [fact("1002")], policy)["L1"]["tp"], 0)
        self.assertEqual(score([fact("1000")], [fact("1002")], changed)["L1"]["tp"], 1)
        alternate.write_text(yaml.safe_dump(changed), encoding="utf-8")
        for option, reference in (("--labels", root / "labels"), ("--rules", root), ("--baseline", root / "gold_eval")):
            output = root / ("missing_gold_config_" + option[2:])
            result = run_kgb([*command(base, frozen, output), option, str(reference)])
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("requires --gold-config", result.stderr)
            self.assertFalse(output.exists())
        output = root / "policy_without_gold"
        result = run_kgb([*command(base, alternate, output), "--gold-config", str(TEST_CONFIG)])
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("policy hash differs from freeze", result.stderr)
        self.assertFalse(output.exists())
        result = run_kgb([*command(base, frozen, root / "verified_without_gold"), "--gold-config", str(TEST_CONFIG)])
        self.assertEqual(result.returncode, 0, result.stderr)
        for template, extra, name in ((base, gold_args, "bad_eval_policy"),
                                       (labels, ["--gold-config", str(TEST_CONFIG)], "bad_labels_policy")):
            output = root / name
            result = run_kgb([*command(template, alternate, output), *extra])
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("policy hash differs from freeze", result.stderr)
            self.assertFalse(output.exists())
        # Pairing rejects absent provenance as well as changed policy/reference identities.
        for field in ("policy_sha256", "references", "corpus_sha256"):
            broken = copy.deepcopy(scores)
            broken[field] = "different"
            write_json(root / "gold_eval/scores.json", broken)
            result = run_kgb([*command(base, frozen, root / ("bad_" + field)), *gold_args, "--baseline", str(root / "gold_eval")])
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("baseline", result.stderr)
            self.assertFalse((root / ("bad_" + field) / "scores.json").exists())
        legacy = copy.deepcopy(scores); del legacy["references"]
        write_json(root / "gold_eval/scores.json", legacy)
        result = run_kgb([*command(base, frozen, root / "legacy"), *gold_args, "--baseline", str(root / "gold_eval")])
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("baseline reference identity mismatch", result.stderr)
        write_json(root / "gold_eval/scores.json", scores)

    def test_cli(self):
        root, run, tables, corpus = eval_fixture("bsee_eval_cli")
        result = run_kgb(["eval", "wells", "--config", "configs/experiments/bsee_eval.yaml", "--run", str(run),
                          "--corpus", str(corpus), "--out", str(root / "evaluation")])
        self.assertEqual(result.returncode, 0, result.stderr)
        result = run_kgb(["eval", "wells", "--config", "configs/experiments/bsee_eval.yaml", "--run", str(run),
                          "--corpus", str(corpus), "--gold", str(root), "--out", str(root / "bad")])
        self.assertEqual(result.returncode, 2)
