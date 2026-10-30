"""Closed ontology definitions are exact copies of the normative task table."""
from __future__ import annotations

import json
import unittest

from helpers import PROJECT_ROOT
from kgbuilder.core.schema import load_schema
from kgbuilder.core.well_values import RELATIONS


class BseeSchemaTest(unittest.TestCase):
    def test_schema(self):
        schema = load_schema(PROJECT_ROOT / "contracts/ontology/bsee.yaml")
        definitions = json.loads((PROJECT_ROOT / "tests/fixtures/bsee/ontology_definitions.json").read_text())
        self.assertEqual(tuple(schema.relations), RELATIONS)
        self.assertEqual(len(RELATIONS), 21)
        self.assertEqual({k: v.definition for k, v in schema.relations.items()}, definitions)
        for relation in schema.relations.values():
            self.assertTrue(10 <= len(relation.definition) <= 500)
            self.assertNotIn("`", relation.definition)
            self.assertNotIn("**", relation.definition)
            self.assertIsNone(relation.inverse_of)
        self.assertEqual(schema.temporal_relations(), set())
