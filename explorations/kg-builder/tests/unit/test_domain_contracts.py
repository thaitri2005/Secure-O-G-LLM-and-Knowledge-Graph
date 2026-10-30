"""Domain contract invariants, containment, hash and referential integrity."""
from __future__ import annotations

import unittest

from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.build.ingest.bsee_tables import build_tables
from kgbuilder.core.config import ConfigError
from kgbuilder.core.domain import api12, input_path, output_dir, source_id, verify_bundle
from kgbuilder.core.text import read_jsonl, sha256_file, write_json, write_jsonl
from unit.test_bsee_tables import table_fixture


class DomainContractTest(unittest.TestCase):
    def test_publication_inputs_are_readable_but_never_output_targets(self):
        source = PROJECT_ROOT / "data/benchmarks/bsee_text/v1"
        self.assertEqual(input_path(source), source)
        for target in (source, PROJECT_ROOT / "data/evaluation", PROJECT_ROOT / "tests/fixtures"):
            with self.assertRaises(ConfigError): output_dir(target, overwrite=True)
        for source in (PROJECT_ROOT / "data", PROJECT_ROOT / "runs", PROJECT_ROOT / "tests/fixtures"):
            with self.assertRaises(ConfigError): input_path(source)

    def test_keys_and_containment(self):
        self.assertEqual(api12(" 012345678900 "), "012345678900")
        for value in (12345678900, "123", "０１２３４５６７８９００"):
            with self.assertRaises(ValueError): api12(value)
        self.assertNotEqual(source_id("x", ("a:b", "c")), source_id("x", ("a", "b:c")))
        with self.assertRaises(ConfigError): output_dir(PROJECT_ROOT / "tests/fixtures")

    def test_hash_and_dangling(self):
        root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/domain_contracts")
        out = clean_dir(PROJECT_ROOT / "runs/_test/domain_contracts")
        build_tables(table_fixture(root), out)
        bundle = verify_bundle(out)
        edges = read_jsonl(out / "edges.jsonl")
        edges[0]["target"] = "bsee:borehole:999999999999"
        write_jsonl(out / "edges.jsonl", edges)
        with self.assertRaisesRegex(ConfigError, "hash"): verify_bundle(out)
        body = bundle.model_dump()
        body["files"]["edges.jsonl"] = sha256_file(out / "edges.jsonl")
        write_json(out / "graph.json", body)
        with self.assertRaisesRegex(ConfigError, "dangling"): verify_bundle(out)
