"""Deterministic routing with cached MiniLM and no external network."""
from __future__ import annotations

import socket
import unittest
from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.build.extract.route import route_documents
from kgbuilder.build.ingest.corpus import load_corpus
from kgbuilder.core.config import load_config
from kgbuilder.core.schema import load_schema
from kgbuilder.runtime.onprem import blocked_count, guard_network, load_env


class MiniLMRouteTest(unittest.TestCase):
    def test_webnlg_coverage(self):
        load_env()
        root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/route")
        saved = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo
        net = guard_network(root / "net.jsonl")
        try:
            cfg = load_config(PROJECT_ROOT / "configs/experiments/webnlg10.yaml", sets=["extract.backend=auto"], mock=True)
            docs = load_corpus(cfg); schema = load_schema(cfg.canon.schema_path)
            first = route_documents(docs, schema, cfg)
            self.assertEqual(first, route_documents(docs, schema, cfg))
            self.assertEqual(len(first), 10)
            for route in first:
                self.assertIsInstance(route.score, float)
                self.assertTrue(-1 <= route.score <= 1)
                self.assertEqual(route.backend == "edc", route.score >= .33)
                print(f"{route.doc_id} {route.backend} {route.score:.4f}")
            self.assertEqual(blocked_count(net), 0)
        finally:
            socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = saved


if __name__ == "__main__": unittest.main()
