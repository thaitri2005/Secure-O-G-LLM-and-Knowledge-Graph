"""Deterministic temporal event assembly and trigger acceptance tests."""
from __future__ import annotations

import unittest
from helpers import PROJECT_ROOT
from kgbuilder.core.contracts import CandidateTriple, CanonicalTriple, Evidence, Document, Chunk
from kgbuilder.build.parse.ground import ground
from kgbuilder.core.schema import load_schema
from kgbuilder.build.refine.temporal import intervals, tag


class TemporalTest(unittest.TestCase):
    def test_window_preserves_exact_trigger_date(self):
        value = "Alice was hired by Acme Labs in 2021. In 2024 she left Acme Labs."
        doc = Document(doc_id="d", text=value)
        chunk = Chunk(chunk_id="d#c000", doc_id="d", idx=0, char_start=0, char_end=len(value), text=value)
        schema = load_schema(PROJECT_ROOT / "contracts/ontology/showcase.yaml")
        times = []
        for mode in ("sentence", "window"):
            ev = ground(doc, chunk, "Alice", "was hired by", "Acme Labs", mode=mode)
            self.assertEqual(ev.grounding, "exact")
            candidate = CandidateTriple(candidate_id="c", chunk_id=chunk.chunk_id, source_doc_id="d", subject="Alice",
                                        predicate="was hired by", object="Acme Labs", extractor="kggen", extractor_version="v", evidence=ev)
            times.append(tag([candidate], schema)[0].time_iso)
        self.assertEqual(times, ["2021", "2021"])

    def canonical(self, id, time, marker):
        e = Evidence(doc_id="d", chunk_id="d#c000", char_start=0, char_end=4, text="text", grounding="exact")
        return CanonicalTriple(candidate_id=id, subject_id="Alice", predicate="works_at", object_id="Acme",
                               predicate_source="trigger", open_predicate="joined", evidence=e,
                               extractor_version="v", temporal_marker=marker, time_iso=time)

    def test_alice_intervals(self):
        output = intervals([self.canonical("a", "2021", "start"), self.canonical("b", "2024", "end")])
        self.assertEqual([(x.valid_from, x.valid_to, len(x.members)) for x in output], [("2021", "2024", 2)])
        nova = intervals([self.canonical("c", "2024", "start")])
        self.assertEqual((nova[0].valid_from, nova[0].valid_to), ("2024", None))

    def test_end_only_and_repeat_end(self):
        output = intervals([self.canonical("a", "2021", "end"), self.canonical("b", "2024", "end")])
        self.assertEqual((output[0].valid_from, output[0].valid_to), (None, "2021"))
        self.assertEqual(len(output[0].members), 2)

    def test_duplicate_starts_and_empty(self):
        output = intervals([self.canonical("b", "2022", "start"), self.canonical("a", "2021", "start"),
                            self.canonical("c", "2024", "end")])
        self.assertEqual((output[0].valid_from, output[0].valid_to, len(output[0].members)), ("2021", "2024", 3))
        empty = intervals([self.canonical("a", "2024", "start"), self.canonical("b", "2024", "end")])
        self.assertEqual(empty[0].reasons, ["empty_interval"])

    def test_timeless_latest(self):
        values = [self.canonical("a", "2020", "start"), self.canonical("b", "2021", "end"),
                  self.canonical("c", "2024", "start"), self.canonical("d", None, None)]
        output = intervals(values)
        self.assertEqual([c.candidate_id for c in output[-1].members], ["c", "d"])
        timeless = intervals([values[-1]])
        self.assertEqual((timeless[0].valid_from, timeless[0].valid_to), (None, None))
        self.assertEqual(intervals([]), [])

    def test_tag_normalization_and_no_schema(self):
        text = "2021: Alice was hired by Acme Labs."
        e = Evidence(doc_id="d", chunk_id="d#c000", char_start=0, char_end=len(text), text=text, grounding="exact")
        c = CandidateTriple(candidate_id="c", chunk_id="d#c000", source_doc_id="d", subject="Alice",
                            predicate="was hired by", object="Acme Labs", extractor="kggen", extractor_version="v", evidence=e)
        tagged = tag([c], load_schema(PROJECT_ROOT / "contracts/ontology/showcase.yaml"))[0]
        self.assertEqual((tagged.trigger_relation, tagged.temporal_marker, tagged.time_iso), ("works_at", "start", "2021"))
        self.assertIsNone(c.time_iso)
        self.assertEqual(tag([c], None), [c])


if __name__ == "__main__":
    unittest.main()
