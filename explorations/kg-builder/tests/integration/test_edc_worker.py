"""Exercise isolated EDC against recorded SD/SC calls and its original scorer."""
from __future__ import annotations

import ast
import json
import os
import socket
import subprocess
import unittest

from helpers import PROJECT_ROOT, PY_EDC, RECORDED, clean_dir
from kgbuilder.build.refine.canon import finalize, run_worker
from kgbuilder.core.config import load_config
from kgbuilder.core.contracts import CandidateTriple, Evidence
from kgbuilder.build.refine.edc_worker import drop_undefined, map_results
from kgbuilder.runtime.gateway import Gateway
from kgbuilder.runtime.onprem import blocked_count, guard_network, load_env
from kgbuilder.core.schema import load_schema


class EdcWorkerTest(unittest.TestCase):
    def setUp(self):
        load_env()
        self.tmp = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/edc_worker" / self._testMethodName)
        self.env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src"), "PYTHONHASHSEED": "0",
                    "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}

    def test_map_results_and_drop_undefined(self):
        items = [{"key": "c", "triples": [["a", "missing", "b"], ["a", "known", "b"]]}]
        sd = [{"known": "Known relation definition."}]
        kept, dropped = drop_undefined(items, sd)
        self.assertEqual(kept, [[["a", "known", "b"]]])
        self.assertEqual(dropped, [{0}])
        mapped = map_results(items, sd, [[["a", "canonical", "b"]]], [[{"canonical": 0.5}]], dropped)
        self.assertEqual(mapped[0]["results"][0], {"canonical": None, "candidates": {}, "reason": "edc_undefined"})
        self.assertEqual(mapped[0]["results"][1]["canonical"], ["a", "canonical", "b"])
        self.assertIsInstance(mapped[0]["results"][1]["candidates"]["canonical"], float)
        target = map_results(items, sd, [[None, ["a", "known", "b"]]], [[{}, {}]], [set()])
        self.assertIsNone(target[0]["results"][0]["canonical"])
        self.assertNotIn("reason", target[0]["results"][0])

    def test_selftest(self):
        net = self.tmp / "net_edc.jsonl"
        result = subprocess.run([str(PY_EDC), "-m", "kgbuilder.build.refine.edc_worker", "--selftest", "--net-log", str(net)],
                                cwd=PROJECT_ROOT, env=self.env, capture_output=True, text=True, encoding="utf-8", timeout=300)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True, "schema_relations": 159})
        self.assertEqual(blocked_count(net), 0)

    def test_replay_recorded_edc(self):
        saved = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo
        guard_network(self.tmp / "net_core.jsonl")
        gateway = Gateway("http://127.0.0.1:9/v1", self.tmp / "calls.jsonl", None, "readonly", [RECORDED["edc_webnlg10"]])
        try:
            url = gateway.start()
            recorded = json.loads((PROJECT_ROOT / "results/upstream/edc/webnlg_10/iter0/result_at_each_stage.json").read_text(encoding="utf-8"))
            root = PROJECT_ROOT / "third_party/edc"
            request = {"version": 1, "model": "qwen3.6-35b-a3b", "base_url": url, "api_key": "lm-studio",
                       "schema_csv": str(root / "schemas/webnlg_schema.csv"), "enrich_schema": False,
                       "few_shot_dir": str(root / "few_shot_examples/webnlg"),
                       "templates_dir": str(root / "prompt_templates"), "embedder": "sentence-transformers/all-MiniLM-L6-v2",
                       "net_log": str(self.tmp / "net_edc.jsonl"),
                       "items": [{"key": f"webnlg_{item['index']:04d}", "text": item["input_text"], "triples": item["oie"]} for item in recorded]}
            response = run_worker(request, self.tmp / "edc", load_config(PROJECT_ROOT / "configs/experiments/webnlg10.yaml", mock=True), gateway)
            self.assertEqual(gateway.stats["cache_misses"], 0)
            self.assertIsNone(gateway.fatal)
            for original, result in zip(recorded, response["items"]):
                self.assertEqual([r["canonical"] for r in result["results"]], original["schema_canonicalizaiton"])
                self.assertEqual([set(d) for d in ast.literal_eval(original["canonicalization_candidates"])],
                                 [set(r["candidates"]) for r in result["results"]])
            self.assertEqual(blocked_count(self.tmp / "net_edc.jsonl"), 0)
            self.assertEqual(blocked_count(self.tmp / "net_core.jsonl"), 0)
        finally:
            gateway.stop()
            socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = saved

    def test_replay_recorded_oie(self):
        from kgbuilder.build.extract.edc_oie import build_oie_request
        from kgbuilder.build.ingest.corpus import load_corpus
        from kgbuilder.build.parse.chunking import chunk_documents
        cfg = load_config(PROJECT_ROOT / "configs/experiments/webnlg10.yaml", mock=True)
        chunks = chunk_documents(load_corpus(cfg), cfg.chunk.max_chars)
        gateway = Gateway("http://127.0.0.1:9/v1", self.tmp / "calls.jsonl", None, "readonly", [RECORDED["edc_webnlg10"]])
        try:
            request = build_oie_request(chunks, cfg, gateway.start(), self.tmp / "net_edc_oie.jsonl")
            response = run_worker(request, self.tmp / "edc_oie", cfg, gateway)
            recorded = json.loads((PROJECT_ROOT / "results/upstream/edc/webnlg_10/iter0/result_at_each_stage.json").read_text(encoding="utf-8"))
            self.assertEqual(gateway.stats["cache_misses"], 0)
            self.assertEqual(len(response["items"]), 10)
            for original, result in zip(recorded, response["items"]):
                self.assertEqual(result["triples"], original["oie"])
            self.assertEqual(blocked_count(self.tmp / "net_edc_oie.jsonl"), 0)
        finally:
            gateway.stop()

    def test_evaluate_mode(self):
        root = PROJECT_ROOT / "results/upstream/edc/webnlg_10"
        net = self.tmp / "net_eval.jsonl"
        result = subprocess.run([str(PY_EDC), "-m", "kgbuilder.build.refine.edc_worker", "--evaluate", str(root / "iter0/canon_kg.txt"),
                                 str(root / "reference.txt"), "--net-log", str(net)], cwd=self.tmp, env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=1800)
        (self.tmp / "eval.txt").write_text(result.stdout, encoding="utf-8")
        (self.tmp / "evaluator.log").write_text(result.stderr, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Total scores", result.stdout)
        self.assertEqual(blocked_count(net), 0)

    def candidate(self, predicate="is birthplace of", trigger=None):
        e = Evidence(doc_id="d", chunk_id="d#c000", char_start=0, char_end=4, text="text", grounding="exact")
        return CandidateTriple(candidate_id="c", chunk_id="d#c000", source_doc_id="d", subject="London",
                               predicate=predicate, object="Alan Turing", extractor="kggen", extractor_version="v",
                               evidence=e, trigger_relation=trigger)

    def response(self, value, reason=None):
        result = {"canonical": value, "candidates": {}}
        if reason: result["reason"] = reason
        return {"items": [{"key": "d#c000", "definitions": {}, "results": [result]}]}

    def test_finalize(self):
        c = self.candidate()
        schema = load_schema(PROJECT_ROOT / "contracts/ontology/showcase.yaml")
        decisions, rejected = finalize([c], self.response(["wrong", "birthplace_of", "wrong"]), schema, False, {"canon": True})
        d = decisions[0]
        self.assertEqual((d.subject, d.predicate, d.object, d.predicate_source), ("Alan Turing", "born_in", "London", "inverse"))
        decisions, rejected = finalize([c], self.response(None), schema, False, {"canon": True})
        self.assertEqual(rejected[0].reasons, ["edc_unmapped"])
        decisions, rejected = finalize([c], self.response(None, "edc_undefined"), schema, False, {"canon": True})
        self.assertEqual(rejected[0].reasons, ["edc_undefined"])
        decisions, _ = finalize([c], None, schema, False, {"canon": False})
        self.assertEqual(decisions[0].predicate_source, "open")
        decisions, _ = finalize([self.candidate("joined", "works_at")], None, schema, False, {"canon": False, "temporal": True})
        self.assertEqual((decisions[0].predicate, decisions[0].predicate_source), ("works_at", "trigger"))


if __name__ == "__main__":
    unittest.main()
