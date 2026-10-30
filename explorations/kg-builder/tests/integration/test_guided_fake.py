"""Exercise guided builds and EDC schema short-circuits through a fake gateway upstream."""
from __future__ import annotations

import json
import unittest

import yaml

from helpers import PROJECT_ROOT, METRIC_KEYS, clean_dir, fake_lmstudio, run_kgb
from kgbuilder.core.text import cj, read_jsonl, write_jsonl
from kgbuilder.runtime.onprem import blocked_count


class GuidedFakeTest(unittest.TestCase):
    def setUp(self):
        self.root = clean_dir(PROJECT_ROOT / "runs/_test/guided_fake" / self._testMethodName)
        self.corpus = self.root / "corpus.jsonl"
        write_jsonl(self.corpus, [{"doc_id": "invented", "text": "Bridge plug set at 4,210 ft MD. Drilled to 5,480 ft."}])
        self.config = self.root / "config.yaml"
        self.config.write_text(yaml.safe_dump({
            "run": {"name": "guided_fake"}, "corpus": {"path": str(self.corpus)},
            "extract": {"backend": "guided", "guided_prompt": "configs/prompts/bsee_guided.txt"},
            "canon": {"schema_path": "contracts/ontology/bsee.yaml"}}), encoding="utf-8")

    def build(self, replies, level="A0", expected=0):
        out = self.root / "build"
        with fake_lmstudio(replies) as (url, received):
            result = run_kgb(["build", "--config", str(self.config), "--ablation", level,
                              "--set", "llm.base_url=" + url, "--set", "llm.cache='off'",
                              "--set", "llm.replay_logs=[]", "--out", str(out)],
                             test_id="guided_fake/" + self._testMethodName)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertFalse((out / "net_edc_oie.jsonl").exists())
        self.assertEqual(blocked_count(out / "net.jsonl"), 0)
        return out, received

    def test_a0_fenced_array_rejections_and_gateway_request(self):
        valid = {"subject": "Bridge plug", "relation": "set_plug_at", "object": "4,210 ft MD"}
        items = [valid, valid, {"subject": "well", "relation": "drilled_to", "object": "5,480 ft"},
                 {**valid, "relation": "drilled_by"}, {**valid, "object": "8,000 ft"}, {"subject": 1}]
        out, received = self.build(["```json\n" + cj(items) + "\n```"])
        self.assertEqual(len(received), 1)
        path, body = received[0]
        self.assertEqual(path, "/v1/completions")
        self.assertEqual((body["max_tokens"], body["temperature"], body["model"]), (2048, 0, "qwen3.6-35b-a3b"))
        calls = read_jsonl(out / "llm_calls.jsonl")
        self.assertEqual([m["role"] for m in calls[0]["messages"]], ["system", "user"])
        self.assertEqual(calls[0]["stage"], "extract")
        candidates = read_jsonl(out / "candidates.jsonl")
        self.assertEqual(len(candidates), 2)
        self.assertTrue(all(c["extractor"] == "guided" for c in candidates))
        self.assertTrue(any(c["evidence"]["grounding"] == "exact" for c in candidates))
        metrics = json.loads((out / "metrics.json").read_text())
        self.assertEqual(set(metrics), METRIC_KEYS)
        self.assertEqual((metrics["duplicate_candidates"], metrics["failed_chunks"]), (1, 0))
        self.assertEqual(sorted(r["reasons"][0] for r in read_jsonl(out / "rejected.jsonl")),
                         ["guided_invalid_item", "guided_not_in_text", "guided_out_of_schema"])

    def test_a4_schema_short_circuit_and_candidate_id_order(self):
        items = [{"subject": "Bridge plug", "relation": "set_plug_at", "object": "4,210 ft MD"},
                 {"subject": "well", "relation": "drilled_to", "object": "5,480 ft"}]
        out, received = self.build([cj(items), "set_plug_at: A plug is set at a depth.\ndrilled_to: A well is drilled to a depth."], "A4")
        self.assertEqual(len(received), 2)
        calls = read_jsonl(out / "llm_calls.jsonl")
        self.assertEqual([r["stage"] for r in calls], ["extract", "canon"])
        self.assertEqual([r["asked_max_tokens"] for r in calls], [2048, 512])
        candidates = sorted(read_jsonl(out / "candidates.jsonl"), key=lambda c: c["candidate_id"])
        request = json.loads((out / "edc/request.json").read_text())
        response = json.loads((out / "edc/response.json").read_text())
        triples = [[c["subject"], c["predicate"], c["object"]] for c in candidates]
        self.assertEqual(request["items"][0]["triples"], triples)
        self.assertFalse(request["enrich_schema"])
        self.assertEqual(response["items"][0]["results"], [{"canonical": t, "candidates": {}} for t in triples])
        self.assertEqual(len(read_jsonl(out / "statements.jsonl")), 2)
        self.assertEqual(blocked_count(out / "net_edc.jsonl"), 0)

    def test_recall_modes_request_counts(self):
        text = "Drilled to 100 ft successfully. Tested valve at 900 psi successfully. Set plug at 300 ft safely."
        write_jsonl(self.corpus, [{"doc_id": "invented", "text": text}])
        base = yaml.safe_load(self.config.read_text())
        for mode, recall, count in (("chunk", False, 1), ("windows2", False, 2), ("groups4", False, 4), ("chunk", True, 2)):
            body = {**base, "extract": {**base["extract"], "guided_mode": mode}}
            if mode == "groups4": body["extract"]["guided_prompt"] = "configs/prompts/bsee_guided_groups.txt"
            if recall: body["extract"]["guided_recall_prompt"] = "configs/prompts/bsee_guided_recall.txt"
            self.config.write_text(yaml.safe_dump(body), encoding="utf-8")
            clean_dir(self.root / "build")
            (self.root / "build").rmdir()
            out, received = self.build(["[]"] * count)
            self.assertEqual(len(received), count)
            self.assertEqual(json.loads((out / "metrics.json").read_text())["failed_chunks"], 0)
            self.assertNotIn("literals", json.loads((out / "metrics.json").read_text())["stage_seconds"])
            self.assertFalse((out / "literals.jsonl").exists())

    def test_recall_literals_stage_and_a0_guard(self):
        write_jsonl(self.corpus, [{"doc_id": "invented", "text": 'Cut 9-5/8" casing at 1,200 ft BML.'}])
        body = yaml.safe_load(self.config.read_text())
        body["literals"] = {"derive_attributes": True, "lexicon": "configs/domains/bsee/bsee_literals.yaml"}
        self.config.write_text(yaml.safe_dump(body), encoding="utf-8")
        reply = cj([{"subject": '9-5/8" casing', "relation": "cut_at", "object": "1,200 ft BML"}])
        for level in ("A0", "A4"):
            clean_dir(self.root / "build")
            (self.root / "build").rmdir()
            out, received = self.build([reply, "cut_at: A tubular is cut at a depth."], level)
            metrics = json.loads((out / "metrics.json").read_text())
            self.assertEqual(set(metrics), METRIC_KEYS)
            self.assertEqual("literals" in metrics["stage_seconds"], level == "A4")
            self.assertEqual((out / "literals.jsonl").exists(), level == "A4")
            self.assertEqual(len(received), 2 if level == "A4" else 1)
            if level == "A4":
                candidates = read_jsonl(out / "candidates.jsonl")
                self.assertEqual([c["extractor"] for c in candidates], ["guided", "derived"])
                self.assertEqual(len(read_jsonl(out / "statements.jsonl")), 2)
                request = json.loads((out / "edc/request.json").read_text())
                self.assertEqual(len(request["items"][0]["triples"]), 1)

    def test_unparsed_chunk_exits_six(self):
        out, received = self.build(["This is not an array."], expected=6)
        self.assertEqual(len(received), 1)
        manifest = json.loads((out / "manifest.json").read_text())
        self.assertEqual(manifest["exit_code"], 6)
        self.assertIn("guided extraction failed for 1/1 chunks", (out / "run.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
