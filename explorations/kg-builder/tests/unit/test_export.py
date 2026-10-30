"""Graph export round trips, deterministic bytes, and document prediction order."""
from __future__ import annotations

import ast
import json
import unittest

import networkx as nx

from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.core.contracts import Document, Entity, GraphRecord, ValidatedStatement, dump
from kgbuilder.build.publish.export import (graph_record, strict_record, to_networkx, webnlg_prediction_lines,
                              write_contract_files, write_graph_json, write_graphml)
from kgbuilder.core.text import read_jsonl, sha256_file


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/export")
        self.record = GraphRecord.model_validate_json((PROJECT_ROOT / "tests/fixtures/graph_small.json").read_text(encoding="utf-8"))

    def test_graph_roundtrip_and_determinism(self):
        path = self.root / "graph.json"
        write_graph_json(self.record, path)
        first = sha256_file(path)
        self.assertEqual(GraphRecord.model_validate_json(path.read_text(encoding="utf-8")), self.record)
        self.assertNotRegex(path.read_text(encoding="utf-8"), r"\d{4}-\d{2}-\d{2}T")
        write_graph_json(self.record, path)
        self.assertEqual(sha256_file(path), first)
        r = self.record
        extra = Entity(entity_id="unused", name="unused", aliases=[], kind="entity", mention_ids=[], resolver="identity")
        built = graph_record(r.run_name, r.ablation, r.flags, r.documents[::-1], r.chunks[::-1],
                             [extra, *r.entities[::-1]], r.statements[::-1])
        self.assertEqual(built, r)

    def test_contracts(self):
        r = self.record
        write_contract_files(self.root, documents=r.documents[::-1], chunks=r.chunks,
                             entities=r.entities, statements=r.statements[::-1])
        self.assertEqual([ValidatedStatement.model_validate(row) for row in read_jsonl(self.root / "statements.jsonl")], r.statements)
        self.assertEqual(len(list(self.root.glob("*.jsonl"))), 8)
        self.assertEqual(read_jsonl(self.root / "mentions.jsonl"), [])
        self.assertEqual(read_jsonl(self.root / "documents.jsonl")[0]["doc_id"], "d1")

    def test_strict_record(self):
        record = self.record.model_copy(update={"statements": [s.model_copy(update={"reasons": ["weak_evidence"]})
                      if s.statement_id == "s2" else s for s in self.record.statements]})
        strict = strict_record(record)
        self.assertEqual([s.statement_id for s in strict.statements], ["s1", "s3"])
        self.assertEqual([e.entity_id for e in strict.entities], ["e1", "e2", "e4"])
        self.assertEqual(strict.documents, record.documents)
        self.assertEqual(strict.chunks, record.chunks)
        self.assertEqual(len(record.statements), 3)

    def test_graphml_attributes_and_parallel_edges(self):
        path = self.root / "graph.graphml"
        write_graphml(self.record, path)
        graph = nx.read_graphml(path, force_multigraph=True)
        self.assertEqual((graph.number_of_nodes(), graph.number_of_edges()), (4, 3))
        edge = graph["e1"]["e2"]["s1"]
        self.assertEqual((edge["valid_from"], edge["valid_to"]), ("2021", "2024"))
        self.assertEqual(edge["support_count"], 1)
        self.assertEqual(edge["evidence_span"], self.record.statements[0].evidence_span.span)
        self.assertEqual(json.loads(graph.nodes["e4"]["aliases"]), ["International Business Machines"])
        self.assertEqual(to_networkx(self.record)["e1"]["e3"]["s2"]["valid_to"], "")
        r = self.record.model_copy(update={"statements": [*self.record.statements,
            self.record.statements[0].model_copy(update={"statement_id": "s4"})]})
        write_graphml(r, path)
        self.assertEqual(nx.read_graphml(path, force_multigraph=True).number_of_edges(), 4)

    def test_predictions_order_supports_and_empty(self):
        r = self.record
        docs = [*r.documents[::-1], Document(doc_id="empty", text="No relations.")]
        lines = webnlg_prediction_lines(r, docs)
        self.assertEqual(ast.literal_eval(lines[0]), [["IBM", "operates", "Acme_Labs"]])
        self.assertEqual(ast.literal_eval(lines[-1]), [])
        s = dump(r.statements[0])
        s["evidence"].append(dump(r.statements[-1].evidence_span))
        supported = r.model_copy(update={"statements": [ValidatedStatement.model_validate(s)]})
        self.assertEqual(webnlg_prediction_lines(supported, r.documents)[0],
                         webnlg_prediction_lines(supported, r.documents)[1])
        entities = [r.entities[0].model_copy(update={"name": "Nie Haisheng"}),
                    r.entities[1].model_copy(update={"name": "Hubei"})]
        example = r.model_copy(update={"entities": entities,
            "statements": [r.statements[0].model_copy(update={"predicate": "birthPlace"})]})
        self.assertEqual(webnlg_prediction_lines(example, r.documents)[0],
                         "[['Nie_Haisheng', 'birthPlace', 'Hubei']]")


if __name__ == "__main__":
    unittest.main()
