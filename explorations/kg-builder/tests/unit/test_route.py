"""Schema coverage routing with fixed unit-vector embeddings."""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
from kgbuilder.build.extract.route import coverage, relation_text, route_documents
from kgbuilder.core.contracts import Document
from kgbuilder.core.schema import Relation, SchemaSpec


class RouteTest(unittest.TestCase):
    def setUp(self):
        self.doc = Document(doc_id="d", text="First sentence. Second sentence.")
        self.schema = SchemaSpec({"aRelation": Relation("aRelation", "A relation.")}, "csv", Path("unused"))
        self.cfg = SimpleNamespace(extract=SimpleNamespace(backend="auto", route_tau=.5))

    def test_relation_text(self):
        for name, expected in [("birthPlace", "birth place"), ("works_at", "works at"),
                               ("elevationAboveTheSeaLevel", "elevation above the sea level")]:
            self.assertEqual(relation_text(name), expected)

    def test_coverage_boundary(self):
        def encode(xs):
            return np.array([[1., 0.]] if xs == ["a relation"] else [[1., 0.], [0., 1.]])
        self.assertEqual(coverage(self.doc, np.array([[1., 0.]]), encode), .5)
        route = route_documents([self.doc], self.schema, self.cfg, encode)[0]
        self.assertEqual((route.backend, route.score, route.reason), ("edc", .5, "coverage>=tau"))
        self.cfg.extract.route_tau = .5001
        route = route_documents([self.doc], self.schema, self.cfg, encode)[0]
        self.assertEqual((route.backend, route.reason), ("kggen", "coverage<tau"))

    def test_no_schema_and_fixed_backends_never_encode(self):
        encode = Mock(side_effect=AssertionError("unexpected encoder call"))
        route = route_documents([self.doc], None, self.cfg, encode)[0]
        self.assertEqual((route.backend, route.score, route.reason), ("kggen", None, "no_schema"))
        for backend in ("kggen", "edc"):
            self.cfg.extract.backend = backend
            route = route_documents([self.doc], self.schema, self.cfg, encode)[0]
            self.assertEqual((route.backend, route.score, route.reason), (backend, None, "backend=" + backend))
        encode.assert_not_called()


if __name__ == "__main__": unittest.main()
