"""Casing derivation preserves provenance, deduplicates, and never calls EDC."""
from __future__ import annotations

import unittest

from helpers import PROJECT_ROOT
from kgbuilder.build.refine.canon import CanonDecision
from kgbuilder.build.refine.literals import derive
from kgbuilder.core.contracts import CandidateTriple, Evidence
from kgbuilder.core.schema import load_schema
from kgbuilder.core.text import h, surface_key
from kgbuilder.core.well_literals import load_lexicon


class LiteralsTest(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema(PROJECT_ROOT / "contracts/ontology/bsee.yaml")
        self.lexicon = load_lexicon(PROJECT_ROOT / "configs/domains/bsee/bsee_literals.yaml")

    def candidate(self, cid="c", subject='9-5/8" casing', obj="1,200' BML", extractor="guided"):
        return CandidateTriple(candidate_id=cid, chunk_id="d#c000", source_doc_id="d",
            subject=subject, predicate="cut_at", object=obj, extractor=extractor, extractor_version="v",
            evidence=Evidence(doc_id="d", chunk_id="d#c000", char_start=0, char_end=10,
                              text="Cut casing", grounding="partial"))

    def test_derivation_id_decision_and_provenance(self):
        c = self.candidate()
        original = CanonDecision("c", c.subject, c.predicate, c.object, "schema", "cut_at", None)
        candidates, decisions, rows = derive([c], [original], self.schema, self.lexicon)
        self.assertEqual(len(candidates), 2)
        d = candidates[-1]
        expected_id = "d_" + h(c.chunk_id, "derived", surface_key(c.subject), "casing_size", surface_key('9-5/8"'))[:16]
        self.assertEqual(d.candidate_id, expected_id)
        self.assertEqual((d.subject, d.predicate, d.object, d.extractor), (c.subject, "casing_size", '9-5/8"', "derived"))
        self.assertEqual(d.evidence, c.evidence)
        self.assertEqual(d.extractor_version, "v;derive=bsee_literals_v1")
        self.assertEqual(decisions[-1], CanonDecision(expected_id, c.subject, "casing_size", '9-5/8"', "schema", "casing_size", None))
        self.assertEqual(rows, [{"candidate_id": expected_id, "rule": "derived", "source_candidate_id": "c", "after": '9-5/8"'}])
        self.assertEqual(derive(candidates, decisions, self.schema, self.lexicon), (candidates, decisions, []))

    def test_skips_and_deduplicates(self):
        for surface in ('16.5 x 19" hole', '16.5 x 19" casing', "tubing", '7" and 9" casing', '7" casingwork'):
            c = self.candidate(subject=surface)
            self.assertEqual(derive([c], [], self.schema, self.lexicon), ([c], [], []))
        c = self.candidate()
        candidates, decisions, rows = derive([self.candidate("z"), c], [], self.schema, self.lexicon)
        self.assertEqual((len(candidates), len(decisions), len(rows)), (3, 1, 1))
        self.assertEqual(rows[0]["source_candidate_id"], "c")
        existing = CanonDecision("existing", c.subject, "casing_size", '9-5/8"', "schema", "casing_size", None)
        self.assertEqual(derive([c], [existing], self.schema, self.lexicon), ([c], [existing], []))

    def test_rejected_and_object_surface(self):
        c = self.candidate(subject='13-3/8" casing', extractor="kggen")
        candidates, decisions, rows = derive([c], [], self.schema, self.lexicon)
        self.assertEqual(decisions[0].object, '13-3/8"')
        self.assertEqual(rows[0]["source_candidate_id"], "c")
        c = self.candidate(subject="well", obj='7" LINER')
        self.assertEqual(derive([c], [], self.schema, self.lexicon)[1][0].object, '7"')
