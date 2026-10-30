"""Preserve EDC OIE positions and historical KGGen canonicalization requests."""
from __future__ import annotations

import unittest
from helpers import PROJECT_ROOT
from kgbuilder.build.refine.canon import build_request, finalize, request_order
from kgbuilder.core.config import edc_dirs, load_config
from kgbuilder.core.contracts import CandidateTriple, Chunk, Evidence


class CanonOrderTest(unittest.TestCase):
    def candidate(self, cid, chunk="d#c000", backend="edc", trigger=None):
        return CandidateTriple(candidate_id=cid, chunk_id=chunk, source_doc_id="d", subject="Alice",
            predicate=cid, object="Acme", extractor=backend, extractor_version="v", trigger_relation=trigger,
            evidence=Evidence(doc_id="d", chunk_id=chunk, char_start=0, char_end=5, text="Alice", grounding="partial"))

    def test_derived_request_key_equality(self):
        from kgbuilder.evaluation.well_attribution import request_key
        from kgbuilder.core.contracts import dump
        candidates = [self.candidate(cid, backend=backend) for cid, backend in
                      (("z", "guided"), ("b", "derived"), ("a", "kggen"), ("edc", "edc"))]
        self.assertEqual([c.candidate_id for c in request_order(candidates)],
                         [c["candidate_id"] for c in sorted([dump(c) for c in candidates], key=request_key)])

    def test_order_and_positional_finalize(self):
        edc = [self.candidate(cid) for cid in ("z", "a", "m")]
        kg = [self.candidate(cid, "d#c001", "kggen") for cid in ("z2", "a2")]
        self.assertEqual([c.candidate_id for c in request_order(edc + kg + [self.candidate("trigger", trigger="works_at")])], ["z", "a", "m", "a2", "z2"])
        response = {"items": [{"key": "d#c000", "definitions": {}, "results": [
            {"canonical": ["Alice", p, "Acme"]} for p in ("one", "two", "three")]}]}
        decisions, rejected = finalize(edc, response, None, False, {"canon": True})
        self.assertEqual([d.predicate for d in decisions], ["one", "two", "three"])
        self.assertEqual(rejected, [])

    def test_text_convention_and_historical_request(self):
        cfg = load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml", mock=True)
        chunks = {f"d#c00{i}": Chunk(chunk_id=f"d#c00{i}", doc_id="d", idx=i, char_start=0, char_end=5, text="Alice") for i in (0, 1)}
        net = PROJECT_ROOT / ".cache/tmp/tests/canon_order/net.jsonl"
        backend_mix = [self.candidate("a"), self.candidate("b", "d#c001", "kggen")]
        req = build_request(backend_mix, chunks, None, True, cfg, "http://127.0.0.1:9/v1", net)
        self.assertEqual([i["text"] for i in req["items"]], ["Alice\n", "Alice"])
        candidates = [self.candidate(cid, chunk, "kggen") for cid, chunk in (("z", "d#c000"), ("a", "d#c001"), ("b", "d#c000"), ("m", "d#c001"))]
        groups = {}
        for c in sorted(candidates, key=lambda c: c.candidate_id):
            groups.setdefault(c.chunk_id, []).append([c.subject, c.predicate, c.object])
        few, templates = edc_dirs(cfg)
        historical = {"version": 1, "model": cfg.llm.model, "base_url": "http://127.0.0.1:9/v1", "api_key": "lm-studio",
            "schema_csv": None, "enrich_schema": True, "few_shot_dir": str(few), "templates_dir": str(templates),
            "embedder": cfg.canon.embedder, "net_log": str(net.resolve()),
            "items": [{"key": key, "text": chunks[key].text, "triples": t} for key, t in sorted(groups.items())]}
        self.assertEqual(build_request(candidates, chunks, None, True, cfg, "http://127.0.0.1:9/v1", net), historical)

    def test_guided_candidate_id_sort_and_positional_mapping(self):
        candidates = [self.candidate(cid, backend="guided") for cid in ("z", "a", "m")]
        cfg = load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml", mock=True)
        chunk = Chunk(chunk_id="d#c000", doc_id="d", idx=0, char_start=0, char_end=5, text="Alice")
        request = build_request(candidates, {chunk.chunk_id: chunk}, None, False, cfg,
                                "http://127.0.0.1:9/v1", PROJECT_ROOT / ".cache/tmp/tests/canon_order/net.jsonl")
        self.assertEqual(request["items"][0]["text"], "Alice")
        self.assertEqual(request["items"][0]["triples"], [["Alice", cid, "Acme"] for cid in ("a", "m", "z")])
        response = {"items": [{"key": chunk.chunk_id, "definitions": {}, "results": [
            {"canonical": triple, "candidates": {}} for triple in request["items"][0]["triples"]]}]}
        decisions, rejections = finalize(candidates, response, None, False, {"canon": True})
        self.assertEqual([(d.candidate_id, d.predicate) for d in decisions], [(cid, cid) for cid in ("z", "a", "m")])
        self.assertEqual(rejections, [])


if __name__ == "__main__": unittest.main()
