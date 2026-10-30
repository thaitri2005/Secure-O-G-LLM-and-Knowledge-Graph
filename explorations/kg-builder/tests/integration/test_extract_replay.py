"""Run real KGGen against the recorded showcase call replay."""
from __future__ import annotations

import json
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from helpers import PROJECT_ROOT, RECORDED, clean_dir
from kgbuilder.core.config import KgbError, load_config
from kgbuilder.build.extract.kggen import run_extract
from kgbuilder.runtime.gateway import Gateway
from kgbuilder.build.ingest.corpus import load_corpus
from kgbuilder.build.parse.chunking import chunk_documents
from kgbuilder.runtime.onprem import blocked_count, guard_network, load_env


class ExtractReplayTest(unittest.TestCase):
    def test_recorded_showcase(self):
        load_env()
        tmp = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/extract_replay")
        saved = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo
        net = guard_network(tmp / "net.jsonl")
        gateway = Gateway("http://127.0.0.1:9/v1", tmp / "calls.jsonl", None, "readonly", [RECORDED["kggen_showcase"]])
        try:
            url = gateway.start()
            cfg = load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml", mock=True)
            docs = load_corpus(cfg)
            chunks = chunk_documents(docs, cfg.chunk.max_chars)
            result = run_extract(docs, chunks, cfg, url, "6259b4c")
            self.assertEqual(gateway.stats["cache_misses"], 0)
            self.assertIsNone(gateway.fatal)
            self.assertEqual(len(result.mentions), 13)
            recorded = json.loads((PROJECT_ROOT / "results/upstream/kggen/showcase/kg_merged.json").read_text(encoding="utf-8"))
            self.assertEqual({(c.subject, c.predicate, c.object) for c in result.candidates},
                             {tuple(row) for row in recorded["relations"]})
            self.assertEqual(len(result.candidates), 10)
            by_doc = {d.doc_id: d for d in docs}
            for candidate in result.candidates:
                e = candidate.evidence
                self.assertEqual(e.grounding, "exact")
                self.assertEqual(by_doc[e.doc_id].text[e.char_start:e.char_end], e.text)
            self.assertEqual(blocked_count(net), 0)
        finally:
            gateway.stop()
            socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = saved

    def test_invalid_fields_and_failed_ratio(self):
        load_env()
        tmp = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/extract_invalid")
        saved = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo
        guard_network(tmp / "net.jsonl")
        try:
            cfg = load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml", mock=True)
            docs = load_corpus(cfg)[:1]
            chunks = chunk_documents(docs, cfg.chunk.max_chars)
            graph = SimpleNamespace(entities={"IBM", "", "x" * 301},
                                    relations={("IBM", " ", "Labs"), ("IBM", "works at", "Labs"), ("ibm", "works at", "Labs")})
            with patch("kg_gen.KGGen") as mocked:
                mocked.return_value.generate.return_value = graph
                result = run_extract(docs, chunks, cfg, "http://127.0.0.1:9/v1", "6259b4c")
            self.assertEqual(len(result.mentions), 1)
            self.assertEqual(result.duplicate_candidates, 1)
            self.assertEqual(sum("invalid_mention" in r.reasons for r in result.rejections), 2)
            self.assertEqual(sum("invalid_field" in r.reasons for r in result.rejections), 1)
            with patch("kg_gen.KGGen") as mocked:
                mocked.return_value.generate.side_effect = RuntimeError("deliberate chunk failure")
                with self.assertRaises(KgbError) as caught:
                    run_extract(docs, chunks, cfg, "http://127.0.0.1:9/v1", "6259b4c")
                self.assertEqual(caught.exception.code, 6)
            self.assertEqual(blocked_count(tmp / "net.jsonl"), 0)
        finally:
            socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = saved


if __name__ == "__main__":
    unittest.main()
