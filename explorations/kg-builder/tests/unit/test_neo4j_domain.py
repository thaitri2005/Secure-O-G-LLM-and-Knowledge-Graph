"""CSV completeness and guarded idempotent attachment with a fake driver only."""
from __future__ import annotations

import csv
import json
import unittest

from helpers import PROJECT_ROOT
from kgbuilder.adapters.neo4j_domain import DomainStore
from kgbuilder.build.publish.domain_export import export_bulk
from kgbuilder.build.refine.well_link import link_text
from kgbuilder.core.config import ConfigError, KgbError
from kgbuilder.core.text import iter_jsonl, sha256_file
from unit.test_well_link import link_fixture


class Result(list):
    def consume(self): return None


class FakeDriver:
    def __init__(self, tables, manifest):
        self.hash = sha256_file(tables / "graph.json")
        self.nodes = {r["id"]: json.dumps(r["sources"], sort_keys=True, separators=(",", ":"), ensure_ascii=False) for r in iter_jsonl(tables / "nodes.jsonl")}
        self.manifest, self.writes, self.ids = manifest, [], set()
    def session(self, **kwargs): return self
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def close(self): pass
    def run(self, query, **params):
        if "KgbDomainMeta" in query: return Result([{"hash": self.hash}])
        if "UNWIND labels" in query or "type(r)" in query:
            kind = "nodes" if "UNWIND labels" in query else "relationships"
            return Result([{"kind": r["type"], "count": r["rows"]} for r in self.manifest["files"].values() if r["kind"] == kind])
        if "sources_json" in query: return Result([{"id": i, "sources": self.nodes[i]} for i in params["ids"] if i in self.nodes])
        if "RETURN n.id AS id" in query: return Result([{"id": i} for i in params["ids"] if i in self.nodes])
        self.writes.append((query, params))
        self.ids.update(r["id"] for r in params["rows"])
        return Result()


class Neo4jDomainTest(unittest.TestCase):
    def test_bulk_attach_and_guards(self):
        root, run, tables, sources = link_fixture("bsee_domain_store")
        manifest = export_bulk(tables, root / "bulk")
        ids, endpoints = set(), []
        for name, entry in manifest["files"].items():
            with (root / "bulk" / name).open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), entry["rows"])
            if entry["kind"] == "nodes": ids.update(r["id:ID"] for r in rows)
            else: endpoints.extend(value for r in rows for value in (r[":START_ID"], r[":END_ID"]))
        self.assertTrue(set(endpoints) <= ids)
        self.assertEqual(len(ids), manifest["nodes"])
        link_text(run, tables, sources, {"version": "links/v1", "well_aliases": ["the well"]}, root / "links")
        fake = FakeDriver(tables, manifest)
        store = DomainStore({"uri": "bolt://127.0.0.1:7688", "batch_size": 2}, "synthetic", lambda *a, **k: fake)
        first = store.attach(run / "graph.json", root / "links")
        count = len(fake.ids)
        self.assertEqual(store.attach(run / "graph.json", root / "links"), first)
        self.assertEqual(len(fake.ids), count)
        from kgbuilder.core.text import cj
        fake.nodes = {r["id"]: cj(r["sources"]) for r in iter_jsonl(tables / "nodes.jsonl")}
        self.assertGreater(store.audit(tables, root / "bulk")["provenance_verified"], 0)
        fake.writes.clear(); fake.hash = "0" * 64
        with self.assertRaises(KgbError) as error: store.attach(run / "graph.json", root / "links")
        self.assertEqual(error.exception.code, 7)
        self.assertEqual(fake.writes, [])
        (run / "graph.json").write_bytes((run / "graph.json").read_bytes() + b" ")
        def forbidden(*args, **kwargs): self.fail("driver opened before input hash check")
        store = DomainStore({"uri": "bolt://127.0.0.1:7688"}, "synthetic", forbidden)
        with self.assertRaises(ConfigError): store.attach(run / "graph.json", root / "links")
