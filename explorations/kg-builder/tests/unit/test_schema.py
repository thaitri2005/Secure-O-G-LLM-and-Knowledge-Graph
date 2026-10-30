"""YAML and original EDC CSV schema validation and emission tests."""
from __future__ import annotations

import csv
import unittest
import yaml
from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.core.config import KgbError
from kgbuilder.core.schema import load_schema, write_edc_csv


class SchemaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/schema" / self._testMethodName)

    def test_showcase_and_edc_csv(self):
        showcase = load_schema(PROJECT_ROOT / "contracts/ontology/showcase.yaml")
        self.assertEqual(len(showcase.relations), 7)
        self.assertEqual(showcase.trigger_index()["joined"], ("works_at", "start"))
        self.assertEqual(showcase.temporal_relations(), {"works_at"})
        edc = load_schema(PROJECT_ROOT / "third_party/edc/schemas/webnlg_schema.csv")
        self.assertEqual(len(edc.relations), 159)
        self.assertEqual(edc.temporal_relations(), set())

    def test_csv_roundtrip_and_upstream_loop(self):
        showcase = load_schema(PROJECT_ROOT / "contracts/ontology/showcase.yaml")
        path = self.tmp / "schema.csv"
        write_edc_csv(showcase, path)
        read = load_schema(path)
        self.assertEqual({x.name: x.definition for x in read.relations.values()},
                         {x.name: x.definition for x in showcase.relations.values()})
        count = 0
        with open(path, "r") as fh:
            for row in csv.reader(fh):
                relation, relation_definition = row
                self.assertTrue(relation and relation_definition)
                count += 1
        self.assertEqual(count, 7)
        self.assertNotIn(b"\r\r\n", path.read_bytes())

    def test_invalid_yaml(self):
        cases = [
            {"bad name": {"definition": "A sufficiently long definition."}},
            {"valid": {"definition": "A sufficiently long definition.", "inverse_of": "missing"}},
            {"a": {"definition": "A sufficiently long definition.", "inverse_of": "b"},
             "b": {"definition": "A sufficiently long definition.", "inverse_of": "a"}},
            {"a": {"definition": "A sufficiently long definition.", "temporal": {"start": ["joined"]}},
             "b": {"definition": "A sufficiently long definition.", "temporal": {"start": ["was joined"]}}},
        ]
        path = self.tmp / "invalid.yaml"
        for case in cases:
            path.write_text(yaml.safe_dump({"version": 1, "relations": case}), encoding="utf-8")
            with self.subTest(case=case), self.assertRaises(KgbError) as caught:
                load_schema(path)
            self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
