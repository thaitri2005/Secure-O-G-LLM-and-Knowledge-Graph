"""Round-trip and invariant tests for graph contracts."""
from __future__ import annotations
import json
import unittest
from pydantic import ValidationError
from kgbuilder.core.contracts import *


class ContractTest(unittest.TestCase):
    def test_guided_candidate_roundtrip(self):
        candidate = CandidateTriple(candidate_id="c_guided", chunk_id="d#c000", source_doc_id="d",
                                    subject="well", predicate="drilled_to", object="100 ft",
                                    extractor="guided", extractor_version="v", evidence=self.evidence())
        self.assertEqual(CandidateTriple.model_validate(dump(candidate)), candidate)
        with self.assertRaises(ValidationError):
            CandidateTriple.model_validate({**dump(candidate), "extractor": "unknown"})

    def test_derived_candidate_roundtrip(self):
        candidate = CandidateTriple(candidate_id="d_size", chunk_id="d#c000", source_doc_id="d",
            subject='7" liner', predicate="casing_size", object='7"', extractor="derived",
            extractor_version="v;derive=bsee_literals_v1", evidence=self.evidence())
        self.assertEqual(CandidateTriple.model_validate(dump(candidate)), candidate)

    def evidence(self):
        return Evidence(doc_id="d", chunk_id="d#c000", char_start=0, char_end=4, text="Text", grounding="exact")
    def test_roundtrip(self):
        e = self.evidence(); self.assertEqual(Evidence.model_validate(dump(e)), e)
        s = ValidatedStatement(statement_id="s", subject_id="a", predicate="p", object_id="b", predicate_source="schema", source_doc_id="d", evidence_span=e, evidence=[e], support_count=1, valid_from=None, valid_to=None, extractor_version="v", confidence=.9, status="accepted", reasons=[], candidate_ids=["c"])
        self.assertEqual(ValidatedStatement.model_validate(dump(s)), s)
        g = GraphRecord(format="kgb.graph/1", run_name="r", ablation="A0", flags={}, documents=[], chunks=[], entities=[], statements=[s])
        self.assertEqual(GraphRecord.model_validate_json(json.dumps(dump(g))), g)
    def test_invalid_span_and_extra(self):
        e = dump(self.evidence()); e["span"] = "d:0-5"
        with self.assertRaises(ValidationError): Evidence.model_validate(e)
        e = dump(self.evidence()); e["unknown"] = 1
        with self.assertRaises(ValidationError): Evidence.model_validate(e)
    def test_statement_invariants(self):
        e = self.evidence()
        with self.assertRaises(ValidationError):
            ValidatedStatement(statement_id="s", subject_id="a", predicate="p", object_id="b", predicate_source="schema", source_doc_id="x", evidence_span=e, evidence=[e], support_count=2, valid_from="2024", valid_to="2021", extractor_version="v", confidence=.9, status="accepted", reasons=[], candidate_ids=["c"])

    def test_each_statement_invariant(self):
        e = self.evidence()
        data = dict(statement_id="s", subject_id="a", predicate="p", object_id="b", predicate_source="schema",
                    source_doc_id="d", evidence_span=e, evidence=[e], support_count=1,
                    valid_from=None, valid_to=None, extractor_version="v", confidence=.9,
                    status="accepted", reasons=[], candidate_ids=["c"])
        for changes in [dict(source_doc_id="wrong"), dict(support_count=2), dict(support_count=0),
                        dict(evidence=[]), dict(confidence=1.1), dict(valid_from="yesterday"),
                        dict(valid_from="2024", valid_to="2021")]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                ValidatedStatement(**{**data, **changes})
        rejected = ValidatedStatement(**{**data, "valid_from": "2024", "valid_to": "2021",
                                        "reasons": ["empty_interval"], "status": "rejected"})
        self.assertEqual(rejected.status, "rejected")
        for field in ("source_doc_id", "evidence_span", "valid_from", "valid_to", "extractor_version"):
            incomplete = dict(data)
            del incomplete[field]
            with self.subTest(field=field), self.assertRaises(ValidationError):
                ValidatedStatement(**incomplete)
        self.assertIsNone(dump(ValidatedStatement(**data))["valid_to"])

    def test_document_constraints_and_freezing(self):
        d = Document(doc_id="d", text="  one\r\ntwo  ")
        self.assertEqual(d.text, "one\ntwo")
        self.assertIsNone(dump(d)["published_at"])
        for values in [dict(doc_id="bad id", text="ok"), dict(doc_id="d", text=" "),
                       dict(doc_id="d", text="a", extra="no"), dict(doc_id="d", text="a", published_at="now")]:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                Document(**values)
        with self.assertRaises(ValidationError):
            d.text = "changed"
        with self.assertRaises(ValidationError):
            Evidence(doc_id="d", chunk_id="d#c000", char_start=4, char_end=3, text="x", grounding="exact")


if __name__ == "__main__": unittest.main()
