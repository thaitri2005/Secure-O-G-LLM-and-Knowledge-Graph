"""Synthetic occurrence links preserve report scope and disclose ambiguity."""
from __future__ import annotations

import json
import shutil
import unittest

from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.build.ingest.bsee_tables import build_tables
from kgbuilder.build.refine.well_link import link_text
from kgbuilder.core.config import ConfigError
from kgbuilder.core.text import cj, read_jsonl, sha256_file, sha256_text, write_json
from unit.test_bsee_tables import table_fixture


def link_fixture(name):
    root = clean_dir(PROJECT_ROOT / "runs/_test" / name)
    raw = clean_dir(PROJECT_ROOT / ".cache/tmp/tests" / name)
    tables = root / "tables"; tables.mkdir()
    build_tables(table_fixture(raw), tables)
    run = root / "text"; run.mkdir()
    shutil.copyfile(PROJECT_ROOT / "tests/fixtures/bsee/text_graph.json", run / "graph.json")
    sources = root / "doc_sources.jsonl"
    shutil.copyfile(PROJECT_ROOT / "tests/fixtures/bsee/doc_sources.jsonl", sources)
    graph = json.loads((run / "graph.json").read_text())
    write_json(run / "manifest.json", {"exit_code": 0, "corpus_hash": sha256_text(cj(sorted(
        (d["doc_id"], sha256_text(d["text"])) for d in graph["documents"])))})
    return root, run, tables, sources


class WellLinkTest(unittest.TestCase):
    def test_scope_and_ambiguity(self):
        root, run, tables, sources = link_fixture("bsee_link_unit")
        policy = {"version": "links/v1", "well_aliases": ["well", "the well"]}
        original = sha256_file(run / "graph.json")
        stats = link_text(run, tables, sources, policy, root / "links")
        self.assertEqual(stats, {"matched": 5, "ambiguous": 1, "unresolved": 0, "llm_calls": 0})
        links = read_jsonl(root / "links/links.jsonl")
        occurrences = {r["source"]: r for r in links if r["type"] == "EXTRACTED_FROM"}
        self.assertEqual(occurrences["s0"]["target"], "bsee:borehole:012345678900")
        self.assertEqual(occurrences["s1"]["target"], "bsee:borehole:012345679100")
        self.assertEqual(occurrences["s2"]["target"], "bsee:borehole:012345679100")
        self.assertFalse(any(r["type"] == "value_alignment" for r in links))
        self.assertEqual(sha256_file(run / "graph.json"), original)
        link_text(run, tables, sources, policy, root / "repeat")
        for name in ("graph.json", "links.jsonl", "unresolved.jsonl"):
            self.assertEqual((root / "links" / name).read_bytes(), (root / "repeat" / name).read_bytes())
        rows = read_jsonl(sources); rows[0]["text_sha256"] = "0" * 64
        sources.write_text("\n".join(cj(row) for row in rows), encoding="utf-8")
        with self.assertRaisesRegex(ConfigError, "hash"):
            link_text(run, tables, sources, policy, root / "bad")
        self.assertFalse((root / "bad").exists())

    def test_dangling_evidence(self):
        root, run, tables, sources = link_fixture("bsee_link_evidence")
        graph = json.loads((run / "graph.json").read_text())
        for ev in [graph["statements"][0]["evidence_span"], graph["statements"][0]["evidence"][0]]:
            ev["chunk_id"] = "missing"
        write_json(run / "graph.json", graph)
        with self.assertRaisesRegex(ConfigError, "EXTRACTED_FROM"):
            link_text(run, tables, sources, {"version": "links/v1", "well_aliases": []}, root / "bad")
