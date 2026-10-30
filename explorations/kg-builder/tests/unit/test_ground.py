"""Evidence selection on the recorded showcase text."""
from __future__ import annotations
import unittest
from helpers import PROJECT_ROOT
from kgbuilder.core.config import load_config
from kgbuilder.build.ingest.corpus import load_corpus
from kgbuilder.build.parse.chunking import chunk_documents
from kgbuilder.build.parse.ground import ground, ground_rule
from kgbuilder.core.contracts import Document, Chunk


class GroundTest(unittest.TestCase):
    def setUp(self):
        self.docs = {d.doc_id: d for d in load_corpus(load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml"))}
        self.chunks = {c.doc_id: c for c in chunk_documents(list(self.docs.values()), 2000)}

    def evidence(self, doc_id, s, p, o):
        doc = self.docs[doc_id]
        e = ground(doc, self.chunks[doc_id], s, p, o)
        self.assertEqual(e, ground_rule(doc, self.chunks[doc_id], s, p, o)[0])
        self.assertEqual(doc.text[e.char_start:e.char_end], e.text)
        return e

    def test_turing_distinct_supports(self):
        a = self.evidence("demo_turing", "Alan Turing", "was born in", "London")
        b = self.evidence("demo_turing", "London", "is birthplace of", "Alan Turing")
        self.assertEqual(a.text, "Alan Turing was born in London.")
        self.assertEqual(b.text, "London was the birthplace of Alan Turing.")
        self.assertEqual((a.grounding, b.grounding), ("exact", "exact"))
        self.assertNotEqual(a.span, b.span)

    def test_alice(self):
        joined = self.evidence("demo_alice", "Alice", "joined", "Acme Labs")
        left = self.evidence("demo_alice", "Alice", "left", "Acme Labs")
        self.assertEqual(joined.text, "2021: Alice joined Acme Labs.")
        self.assertEqual(left.text, "2024: Alice left Acme Labs and joined Nova AI.")

    def test_ungroundable(self):
        e = self.evidence("demo_turing", "Unseen", "invented", "Nothing")
        self.assertEqual(e.grounding, "none")
        self.assertEqual(e.text, self.chunks["demo_turing"].text)

    def test_edc_showcase_unchanged(self):
        for did, s, p, o in [("demo_turing", "Alan Turing", "was born in", "London"),
                              ("demo_turing", "London", "is birthplace of", "Alan Turing"),
                              ("demo_alice", "Alice", "joined", "Acme Labs"),
                              ("demo_alice", "Alice", "left", "Acme Labs"),
                              ("demo_turing", "Unseen", "invented", "Nothing")]:
            with self.subTest(did=did, p=p):
                self.assertEqual(self.evidence(did, s, p, o),
                                 ground(self.docs[did], self.chunks[did], s, p, o, edc_style=True))

    def test_edc_webnlg(self):
        docs = load_corpus(load_config(PROJECT_ROOT / "configs/experiments/webnlg10.yaml"))
        by_doc = {d.doc_id: d for d in docs}
        chunks = {c.doc_id: c for c in chunk_documents(docs, 20000)}
        cases = [("webnlg_0000", "Nie_Haisheng", "birthPlace", "Zaoyang", "exact", "partial"),
                 ("webnlg_0004", "ALCO_RS-3", "powerType", "Diesel-electric_transmission", "partial", "none"),
                 ("webnlg_0007", "Acharya_Institute_of_Technology", "address",
                  '"Soldevanahalli,_Acharya_Dr._Sarvapalli_Radhakrishnan_Road,_Hessarghatta_Main_Road,_Bangalore_-_560090,_India"', "partial", "none"),
                 ("webnlg_0008", "Alan_B._Miller_Hall", "completionDate", '"1 June 2009"', "none", "none")]
        for did, s, p, o, expected, old in cases:
            for edc_style, grounding in [(True, expected), (False, old)]:
                with self.subTest(did=did, edc_style=edc_style):
                    doc, chunk = by_doc[did], chunks[did]
                    ev = ground(doc, chunk, s, p, o, edc_style=edc_style)
                    self.assertEqual(ev, ground_rule(doc, chunk, s, p, o, edc_style=edc_style)[0])
                    self.assertEqual(ev.grounding, grounding)
                    self.assertEqual(doc.text[ev.char_start:ev.char_end], ev.text)
                    if did == "webnlg_0004":
                        self.assertEqual((ev.char_start, ev.char_end, ev.text),
                                         (chunk.char_start, chunk.char_end, chunk.text))

    def test_window_rules(self):
        cases = [
            ("Alan B. Miller Hall, owned by the College of William and Mary, was designed by Robert A.M. Stern and completed on June 1, 2009.",
             ("Alan_B._Miller_Hall", "completionDate", '"1_June_2009"'), "exact", None),
            ("Wis\u0142awa Szymborska was a poet. She resided in Krak\u00f3w.",
             ("Wis\u0142awa Szymborska", "resided in", "Krak\u00f3w"), "window", None),
            ("Robert Florey was a director. He was born in Paris. He worked at Paramount.",
             ("Robert Florey", "worked for", "Paramount"), "coref", "He was born in Paris. He worked at Paramount."),
            ("The airport is in Madrid. It is 610 metres above sea level.",
             ("The airport", "elevationAboveTheSeaLevel", "610.0"), "window", None)]
        for value, triple, expected, span_text in cases:
            doc = Document(doc_id="d", text=value)
            chunk = Chunk(chunk_id="d#c000", doc_id="d", idx=0, char_start=0, char_end=len(value), text=value)
            for edc_style in (False, True):
                evidence, rule = ground_rule(doc, chunk, *triple, edc_style=edc_style, mode="window")
                self.assertEqual(rule, expected)
                self.assertEqual(evidence.grounding, "exact" if expected == "exact" else "partial")
                self.assertEqual(evidence.text, span_text or value)
                self.assertEqual(evidence.text, doc.text[evidence.char_start:evidence.char_end])
            if triple[1] == "completionDate":
                self.assertEqual(ground(doc, chunk, *triple, edc_style=True).grounding, "none")
            if triple[1] == "resided in":
                self.assertEqual(ground(doc, chunk, *triple).grounding, "partial")


if __name__ == "__main__": unittest.main()
