"""Offline QA CLI acceptance with real MiniLM and a fake reader."""
from __future__ import annotations

import copy
import json
import unittest

import yaml

from helpers import PROJECT_ROOT, EXACT_LINKING_QA, ROBUST_LINKING_QA, clean_dir, fake_lmstudio, replay_set, run_kgb, sets
from kgbuilder.core.contracts import Chunk, Document, Entity, Evidence, GraphRecord, ValidatedStatement, dump
from kgbuilder.core.text import read_jsonl, write_json
from kgbuilder.serve.qa import prepare
from kgbuilder.core.config import load_qa, ConfigError


class QaCliTest(unittest.TestCase):
    def test_plan_robust_relevance(self):
        if not (PROJECT_ROOT / "runs/reference/ablation_sentence_grounding/2wiki10/A0/graph.json").is_file():
            self.fail("Required published test input is missing")
        for label, pins in (("robust", ROBUST_LINKING_QA), ("legacy", EXACT_LINKING_QA)):
            out = PROJECT_ROOT / "runs/_plan" / ("test_qa_" + label)
            result = run_kgb(["eval", "qa", "--config", "configs/experiments/twowiki10_qa.yaml", "--set", "llm.cache=plan",
                              *sets(pins), "--set", "qa.graphs={A0: runs/reference/ablation_sentence_grounding/2wiki10/A0}", "--set", "qa.modes=[graph]",
                              "--out", str(out), "--overwrite"], test_id="qa_plan", timeout=1800)
            self.assert_ok(result)
            row = json.loads((out / "qa.json").read_text(encoding="utf-8"))["rows"][0]
            answer = next(r for r in read_jsonl(out / "answers.jsonl") if r["qid"].startswith("0e7078b0"))
            if label == "robust":
                self.assertIn("Anne Baldwin Gust Brown", answer["seeds"])
            else:
                self.assertEqual((row["no_context"], row["seeded"]), (1, 9))
            print("WINDOW_GROUNDING QA", label, "no_context", row["no_context"], "seeded", row["seeded"], "Anne seeds", answer["seeds"])

    def setUp(self):
        self.root = clean_dir(PROJECT_ROOT / "runs/_test/qa_cli")
        self.tmp = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/qa_cli")
        source = json.loads((PROJECT_ROOT / "data/benchmarks/2wiki/2wiki_30_corpus.json").read_text(encoding="utf-8"))[:4]
        docs = [Document(doc_id=f"wiki_{r['idx']:03d}", title=r["title"], text=r["text"]) for r in source]
        by_title = {d.title: d for d in docs}
        names = ["Dangerously They Live", "Salad by the Roots", "Robert Florey", "Georges Lautner", "14 September 1900", "24 January 1926"]
        entities = [Entity(entity_id=f"e{i}", name=name, aliases=[], kind="literal" if i >= 4 else "entity", mention_ids=[], resolver="identity") for i, name in enumerate(names)]
        triples = [(0, "directed by", 2, names[0]), (1, "directed by", 3, names[1]), (2, "born on", 4, names[2]), (3, "born on", 5, names[3])]
        statements = []
        for i, (s, p, o, title) in enumerate(triples):
            doc = by_title[title]
            evidence = Evidence(doc_id=doc.doc_id, chunk_id=doc.doc_id+"#c000", char_start=0, char_end=len(doc.text), text=doc.text, grounding="partial")
            statements.append(ValidatedStatement(statement_id=f"s{i}", subject_id=f"e{s}", predicate=p, object_id=f"e{o}", predicate_source="open",
                             source_doc_id=doc.doc_id, evidence_span=evidence, evidence=[evidence], support_count=1, valid_from=None, valid_to=None,
                             extractor_version="fake", confidence=.6, status="accepted", reasons=[], candidate_ids=[f"c{i}"]))
        chunks = [Chunk(chunk_id=d.doc_id+"#c000", doc_id=d.doc_id, idx=0, char_start=0, char_end=len(d.text), text=d.text) for d in docs]
        record = GraphRecord(format="kgb.graph/1", run_name="qa_cli", ablation="A0", flags={}, documents=docs, chunks=chunks, entities=entities, statements=statements)
        for level in ("A0", "A4"):
            r = record if level == "A0" else record.model_copy(update={"ablation": "A4", "entities":entities[:4], "statements":statements[:2]})
            write_json(self.root / "g" / level / "graph.json", dump(r))
        self.raw = yaml.safe_load((PROJECT_ROOT / "configs/experiments/twowiki10_qa.yaml").read_text(encoding="utf-8"))
        self.raw["qa"]["limit"] = 1
        self.raw["qa"]["graphs"] = {level: str(self.root / "g" / level) for level in ("A0", "A4")}
        self.path = self.tmp / "qa.yaml"
        self.path.write_text(yaml.safe_dump(self.raw, sort_keys=False), encoding="utf-8")

    def run_qa(self, extra, target, config=None):
        return run_kgb(["eval", "qa", "--config", str(config or self.path), "--out", str(self.root / target), *replay_set(), *extra],
                       timeout=600, test_id="qa_cli/" + target)

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_live_scrambled_gold_and_replay(self):
        with fake_lmstudio(lambda body: "Salad By The Roots") as (base, received):
            result = self.run_qa(["--set", "llm.base_url=" + base, "--set", "llm.cache=off"], "live")
            self.assert_ok(result)
            self.assertEqual(len(received), 5)
            prompts = [body["prompt"] for _, body in received]
            questions = json.loads((PROJECT_ROOT / "data/benchmarks/2wiki/2wiki_30.json").read_text(encoding="utf-8"))[:1]
            questions[0]["answer"] = "x"
            questions[0]["evidences"] = [["x","x","x"] for _ in questions[0]["evidences"]]
            write_json(self.tmp / "scrambled.json", questions)
            scrambled = copy.deepcopy(self.raw)
            scrambled["qa"]["questions"] = str(self.tmp / "scrambled.json")
            path = self.tmp / "scrambled.yaml"
            path.write_text(yaml.safe_dump(scrambled), encoding="utf-8")
            result = self.run_qa(["--set","llm.base_url="+base,"--set","llm.cache=off"], "scrambled", path)
            self.assert_ok(result)
            self.assertEqual(len(received), 10)
            self.assertEqual(prompts, [body["prompt"] for _, body in received[5:]])
        report = json.loads((self.root / "live/qa.json").read_text(encoding="utf-8"))
        self.assertEqual(report["format"], "kgb.qa/1")
        self.assertEqual(report["n_questions"], 1)
        self.assertTrue(all(row["em"] == 1. for row in report["rows"]))
        self.assertTrue(all(row["llm"]["calls"] == 1 for row in report["rows"]))
        rows = {r["row"]: r for r in report["rows"]}
        self.assertEqual((rows["graph@A0"]["recall@5"], rows["graph@A0"]["mean_facts"]), (1., 4))
        self.assertEqual((rows["graph@A4"]["recall@5"], rows["hybrid@A4"]["recall@5"]), (.5, 1.))
        self.assertEqual(report["graphs"]["A0"]["evidence_pair_recall"], 1.)
        self.assertEqual(report["graphs"]["A4"]["evidence_pair_recall"], .5)
        self.assertEqual(len(read_jsonl(self.root / "live/answers.jsonl")), 5)
        self.assertEqual([r["stage"] for r in read_jsonl(self.root / "live/llm_calls.jsonl")], ["qa." + r["row"] for r in report["rows"]])
        for folder in ("live", "scrambled"):
            self.assertFalse(any(r.get("allowed") is False for r in read_jsonl(self.root / folder / "net.jsonl")))
        scrambled_report = json.loads((self.root / "scrambled/qa.json").read_text())
        self.assertTrue(all(row["em"] == 0. for row in scrambled_report["rows"]))
        replay = self.run_qa(["--mock", *replay_set("runs/_test/qa_cli/live/llm_calls.jsonl")], "replay")
        self.assert_ok(replay)
        replay_report = json.loads((self.root / "replay/qa.json").read_text())
        for live, replayed in zip(report["rows"], replay_report["rows"]):
            self.assertEqual(replayed["llm"]["cache_misses"], 0)
            for key in ("em", "f1", "recall@2", "recall@5", "no_context"):
                self.assertEqual(live[key], replayed[key])
        self.assertFalse((PROJECT_ROOT / ".cache/tmp/tests/qa_cli/replay/no_cache.jsonl").exists())

    def test_out_overlapping_graphs_rejected(self):
        root = clean_dir(PROJECT_ROOT / "runs/_test/qa_overlap")
        cache = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/qa_overlap") / "no_cache.jsonl"
        source = root / "src/A0"
        source.mkdir(parents=True)
        sentinel = source / "graph.json"
        sentinel.write_bytes(b"sentinel")
        for out in (root / "src", source):
            result = run_kgb(["eval", "qa", "--config", "configs/experiments/twowiki10_qa.yaml", "--mock",
                              "--set", "qa.graphs={A0: runs/_test/qa_overlap/src/A0}", *replay_set(),
                              "--out", str(out), "--overwrite"], test_id="qa_overlap", timeout=600)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("qa.graphs.A0", result.stderr)
            self.assertEqual(sentinel.read_bytes(), b"sentinel")
        self.assertFalse(cache.exists())

    def test_cli_errors_before_mutation(self):
        result = self.run_qa(["--mock","--set","llm.replay_logs=[data/fixtures/llm/showcase_kggen.jsonl]"], "miss")
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        self.assertIn("provide the recorded QA fixture", result.stderr)
        result = self.run_qa(["--mock","--set","qa.limit=2"], "missing_title")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("02b62fce087211ebbd64ac1f6bf848b6", result.stderr)
        self.assertFalse((self.root / "missing_title").exists())
        result = self.run_qa(["--mock","--set", "qa.graphs={A0: runs/_test/qa_cli/nonexistent}"], "missing_graph")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse((self.root / "missing_graph").exists())
        result = run_kgb(["eval","qa","--config",str(self.path),"--mock","--out","tests/fixtures"], timeout=600)
        self.assertEqual(result.returncode, 2, result.stderr)
        occupied = clean_dir(self.root / "occupied")
        sentinel = occupied / "sentinel.txt"; sentinel.write_text("keep")
        result = self.run_qa(["--mock"], "occupied")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(sentinel.read_text(), "keep")
        result = self.run_qa(["--mock","--overwrite","--set","qa.limit=2"], "occupied")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(sentinel.read_text(), "keep")
        # Corpus mismatch is also checked before an overwrite can remove output.
        graph_path = self.root / "g/A4/graph.json"
        graph = json.loads(graph_path.read_text())
        graph["documents"][0]["text"] += " changed"
        write_json(graph_path, graph)
        with self.assertRaisesRegex(ConfigError, "different corpora"):
            prepare(load_qa(self.path))


if __name__ == "__main__": unittest.main()

