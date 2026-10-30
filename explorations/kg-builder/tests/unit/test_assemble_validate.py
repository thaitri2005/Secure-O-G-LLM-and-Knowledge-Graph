"""Assembly, temporal intervals, rejection reasons, and provenance invariants."""
from __future__ import annotations

import unittest
from helpers import PROJECT_ROOT
from kgbuilder.build.refine.canon import CanonDecision
from kgbuilder.core.contracts import CandidateTriple, CanonicalTriple, Entity, Evidence, dump
from kgbuilder.build.refine.resolve import Resolution
from kgbuilder.core.schema import load_schema
from kgbuilder.build.refine.validate import assemble, build_statements, confidence


class AssembleTest(unittest.TestCase):
    def test_soft_validation(self):
        entities = {name: self.entity(name) for name in ("Alice", "Acme")}
        triple = self.canonical(grounding="none")
        accepted, rejected = build_statements([triple], entities, None, {"validate": True}, "partial", "soft")
        self.assertEqual(rejected, [])
        self.assertEqual((accepted[0].status, accepted[0].reasons, accepted[0].confidence),
                         ("accepted", ["weak_evidence"], .3))
        self.assertEqual(build_statements([triple], entities, None, {"validate": True}, "partial", "strict")[0], [])
        for mode in ("strict", "soft"):
            accepted, rejected = build_statements([self.canonical(obj="Alice")], entities, None, {"validate": True}, "partial", mode)
            self.assertEqual(accepted, [])
            self.assertEqual(rejected[0].reasons, ["self_loop"])
        self.assertEqual(build_statements([triple], entities, None, {"validate": False}, "partial", "soft"),
                         build_statements([triple], entities, None, {"validate": False}, "partial", "strict"))

    def entity(self, id, name=None, kind="entity"):
        return Entity(entity_id=id, name=name or id, aliases=[], kind=kind, mention_ids=[], resolver="identity")

    def canonical(self, id="c", marker=None, time=None, grounding="exact", subject="Alice", obj="Acme"):
        text = "2021: Alice joined Acme Labs."
        e = Evidence(doc_id="d", chunk_id="d#c000", char_start=0, char_end=len(text), text=text, grounding=grounding)
        return CanonicalTriple(candidate_id=id, subject_id=subject, predicate="works_at", object_id=obj,
                               predicate_source="trigger", open_predicate="joined", temporal_marker=marker,
                               time_iso=time, evidence=e, extractor_version="v")

    def test_alice_and_provenance(self):
        values = [self.canonical("a", "start", "2021"), self.canonical("b", "end", "2024"),
                  self.canonical("c", "start", "2024", obj="Nova")]
        entities = {name: self.entity(name) for name in ["Alice", "Acme", "Nova"]}
        accepted, rejected = build_statements(values, entities, load_schema(PROJECT_ROOT / "contracts/ontology/showcase.yaml"),
                                              {"temporal": True, "validate": True}, "partial")
        self.assertEqual(rejected, [])
        self.assertEqual({(s.object_id, s.valid_from, s.valid_to, s.support_count) for s in accepted},
                         {("Acme", "2021", "2024", 2), ("Nova", "2024", None, 1)})
        for statement in accepted:
            row = dump(statement)
            for key in ("source_doc_id", "evidence_span", "valid_from", "valid_to", "extractor_version"):
                self.assertIn(key, row)
            self.assertEqual(statement.source_doc_id, statement.evidence_span.doc_id)
            self.assertEqual(statement.evidence_span, statement.evidence[0])

    def test_reasons_and_disabled_validation(self):
        entities = {"Alice": self.entity("Alice"), "Acme": self.entity("Acme"), "1964": self.entity("1964", kind="literal")}
        for triple, expected in [(self.canonical(grounding="none"), "weak_evidence"),
                                 (self.canonical(obj="Alice"), "self_loop"),
                                 (self.canonical(subject="1964"), "literal_subject")]:
            accepted, rejected = build_statements([triple], entities, None, {"validate": True}, "partial")
            self.assertEqual(accepted, [])
            self.assertIn(expected, rejected[0].reasons)
            accepted, rejected = build_statements([triple], entities, None, {"validate": False}, "partial")
            self.assertEqual(len(accepted), 1)
            self.assertEqual(rejected, [])
        self.assertEqual(confidence(["exact", "partial"], "schema"), .96)
        self.assertEqual(confidence(["exact"], "open"), .72)

    def test_assembly_inverse_and_versions(self):
        c = self.canonical()
        candidate = CandidateTriple(candidate_id="c", chunk_id="d#c000", source_doc_id="d", subject="London",
                                    predicate="is birthplace of", object="Alan Turing", extractor="kggen", extractor_version="v", evidence=c.evidence)
        resolution = Resolution([self.entity("a"), self.entity("b")], {"alan turing": "a", "london": "b"}, 2, 0)
        decision = CanonDecision("c", "Alan Turing", "born_in", "London", "inverse", "is birthplace of", "definition")
        triples = assemble([decision], {"c": candidate}, resolution, {"edc": "02aad17"})
        self.assertEqual((triples[0].subject_id, triples[0].object_id), ("a", "b"))
        self.assertEqual(triples[0].extractor_version, "v;canon=edc@02aad17")

    def test_empty_interval_validation_switch(self):
        values = [self.canonical("a", "start", "2024"), self.canonical("b", "end", "2024")]
        entities = {name: self.entity(name) for name in ["Alice", "Acme"]}
        schema = load_schema(PROJECT_ROOT / "contracts/ontology/showcase.yaml")
        accepted, rejected = build_statements(values, entities, schema,
                                              {"temporal": True, "validate": True}, "partial")
        self.assertEqual(accepted, [])
        self.assertEqual(rejected[0].reasons, ["empty_interval"])
        accepted, rejected = build_statements(values, entities, schema,
                                              {"temporal": True, "validate": False}, "partial")
        self.assertEqual(rejected, [])
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0].status, "accepted")
        self.assertIn("empty_interval", accepted[0].reasons)


if __name__ == "__main__":
    unittest.main()
