"""Validate EDC OIE candidate conversion without inference."""
from __future__ import annotations

import unittest
from helpers import PROJECT_ROOT
from kgbuilder import __version__
from kgbuilder.build.extract.edc_oie import build_oie_request, candidates_from_response, extractor_version
from kgbuilder.build.parse.chunking import chunk_documents
from kgbuilder.core.config import KgbError, load_config
from kgbuilder.core.contracts import Document
from kgbuilder.core.text import h, surface_key


class EdcOieTest(unittest.TestCase):
    def setUp(self):
        self.doc = Document(doc_id="d", text="Alice works at Acme Labs.")
        self.chunks = chunk_documents([self.doc], 200)

    def test_candidates_mentions_and_invalid(self):
        chunk = self.chunks[0]
        response = {"items": [{"key": chunk.chunk_id, "triples": [["Alice", "works at", "Acme Labs"],
                    ["alice", "WORKS AT", "acme labs"], ["a", "b"], ["a", 3, "b"]]}]}
        result = candidates_from_response([self.doc], self.chunks, response, "v")
        self.assertEqual((len(result.candidates), result.duplicate_candidates, result.failed_chunks), (1, 1, 0))
        c = result.candidates[0]
        self.assertEqual(c.extractor, "edc")
        self.assertEqual(c.evidence.text, self.doc.text[c.evidence.char_start:c.evidence.char_end])
        self.assertEqual(c.evidence.grounding, "exact")
        self.assertEqual([r.reasons for r in result.rejections], [["invalid_field"], ["invalid_field"]])
        for mention in result.mentions:
            self.assertEqual(mention.mention_id, "m_" + h(chunk.chunk_id, surface_key(mention.surface))[:12])
            self.assertEqual(self.doc.text[mention.char_start:mention.char_end], mention.surface)
        self.assertEqual(extractor_version("m", "abcdef0"), f"kgb/{__version__};extract=edc@abcdef0;llm=m")

    def test_missing_chunk(self):
        with self.assertRaises(KgbError) as caught:
            candidates_from_response([self.doc], self.chunks, {"items": []}, "v")
        self.assertEqual(caught.exception.code, 6)
        self.assertIn(self.chunks[0].chunk_id, str(caught.exception))

    def test_edc_surface_kept_and_grounded(self):
        doc = Document(doc_id="nie", text="Nie Haisheng was born in Zaoyang.")
        chunks = chunk_documents([doc], 200)
        response = {"items": [{"key": chunks[0].chunk_id,
                               "triples": [["Nie_Haisheng", "birthPlace", "Zaoyang"]]}]}
        result = candidates_from_response([doc], chunks, response, "v")
        self.assertEqual(result.candidates[0].subject, "Nie_Haisheng")
        self.assertEqual(result.candidates[0].evidence.grounding, "exact")

    def test_request(self):
        cfg = load_config(PROJECT_ROOT / "configs/experiments/webnlg10.yaml", mock=True)
        req = build_oie_request(self.chunks, cfg, "http://127.0.0.1:9/v1", PROJECT_ROOT / ".cache/tmp/tests/oie/net.jsonl")
        self.assertEqual(req["mode"], "oie")
        self.assertEqual(req["items"], [{"key": self.chunks[0].chunk_id, "text": self.chunks[0].text + "\n"}])


if __name__ == "__main__": unittest.main()
