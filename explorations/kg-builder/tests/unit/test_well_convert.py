"""Frozen v1 behavior and the three pre-registered v2 conversion rules."""
from __future__ import annotations

import copy
import json
import unittest

from helpers import PROJECT_ROOT
from kgbuilder.core.well_convert import TYPED_KINDS, conversion_counts, facts_from_graph_v2
from kgbuilder.core.well_facts import RELATION_SPEC, facts_from_graph
from kgbuilder.core.well_literals import load_lexicon, typed_spans
from kgbuilder.core.well_values import parse_quantity


LEXICON = load_lexicon(PROJECT_ROOT / "configs/domains/bsee/bsee_literals.yaml")


def graph(subject, relation, surface):
    return {"entities": [{"entity_id": "s", "name": subject}, {"entity_id": "o", "name": surface}],
            "chunks": [{"chunk_id": "d#c000", "char_start": 7}],
            "statements": [{"status": "accepted", "predicate": relation, "subject_id": "s", "object_id": "o",
                            "evidence": [{"doc_id": "d", "chunk_id": "d#c000", "text": surface,
                                          "char_start": 7, "char_end": 7 + len(surface)}]}]}


class WellConvertTest(unittest.TestCase):
    def test_contract_examples(self):
        examples = [
            ("well", "set_plug_at", "CIBP 15980'", "C1", "depth", ["15980"]),
            ("PB safety valve", "set_equipment_at", '2.813" X profile at 810\' MD', "C1", "depth", ["810"]),
            ("well", "spudded_on", "spudded on 6/20/2009", "C1", "date", ["2009-06-20"]),
            ("well", "has_well_status", "temporarily abandoned", "C2", "status", ["TA"]),
            ("well", "has_well_status", "TA'd", "C2", "status", ["TA"]),
            ("well", "has_well_status", "TA", "unchanged", "status", ["TA"]),
            ("well", "has_well_status", "T/A then P&A", "unchanged", "entity", None),
            ("well", "has_well_status", "ta", "unchanged", "status", ["TA"]),
            ("Hydraulic Choke", "tested_to_pressure", "250 psi low and 10,000 psi high", "C3", "pressure", ["250", "10000"]),
            ("well", "perforated_interval", "10,728'-10,734' & 10,775'-10,794' MD", "C3", "interval", [("10728", "10734"), ("10775", "10794")]),
            ("CIBP", "set_plug_at", "9,500' and 9,800'", "C3", "depth", ["9500", "9800"]),
            ("well", "reached_td", "9,500'", "unchanged", "depth", ["9500"]),
            ("well", "reached_td", "9500", "unchanged", "depth", ["9500"]),
            ("well", "perforated_interval", "9,500' to 9,520'", "unchanged", "interval", [("9500", "9520")]),
            ("well", "completed_in", "MP-3E sand", "unchanged", "entity", None),
            ("zone", "perforated_interval", "BN 7300' Sand", "unchanged", "entity", None),
            ("liner", "casing_size", '16.5 x 19" hole', "unchanged", None, None),
            ("liner", "casing_spec", "23# P-110", "unchanged", "text", ["23# P-110"]),
            ("well", "set at", "CIBP at 9,500'", "unchanged", None, None),
        ]
        for subject, relation, surface, rule, kind, values in examples:
            with self.subTest(relation=relation, surface=surface):
                raw = graph(subject, relation, surface)
                before = copy.deepcopy(raw)
                old = facts_from_graph(raw, {"d"})
                new = facts_from_graph_v2(raw, {"d"}, LEXICON)
                self.assertEqual(raw, before)
                self.assertEqual(conversion_counts(raw, {"d"}, LEXICON),
                                 {"statements": 1, **{k: int(k == rule) for k in ("unchanged", "C1", "C2", "C3")}})
                if rule == "unchanged": self.assertEqual(new, old)
                if kind: self.assertTrue(all(f.object["kind"] == kind for f in new))
                if values is not None:
                    self.assertEqual([self.value(f.object) for f in new], values)
                for f in new:
                    self.assertEqual(f.model_dump(exclude={"object", "fact_no"}), old[0].model_dump(exclude={"object", "fact_no"}))
                if kind == "date": self.assertEqual(new[0].object["precision"], "day")
                if relation == "set_equipment_at": self.assertEqual(new[0].object["reference"], "MD")

    @staticmethod
    def value(obj):
        return (obj["lower"], obj["upper"]) if obj["kind"] == "interval" else obj.get("iso", obj.get("value"))

    def test_occurrences_dedup_and_scope(self):
        raw = graph("CIBP", "set_plug_at", "9,500' and 9,800' and 9,500'")
        ev = raw["statements"][0]["evidence"][0]
        raw["statements"][0]["evidence"].append({**ev, "char_start": 8})
        raw["statements"] += [{**raw["statements"][0], "status": "rejected"},
                              {**raw["statements"][0], "evidence": [{**ev, "doc_id": "outside"}]}]
        new = facts_from_graph_v2(raw, {"d"}, LEXICON)
        self.assertEqual([f.object["value"] for f in new], ["9500", "9500", "9800", "9800"])
        self.assertEqual([f.evidence["start"] for f in new], [0, 1, 0, 1])
        self.assertEqual([f.fact_no for f in new], [1, 2, 3, 4])
        self.assertEqual(conversion_counts(raw, {"d"}, LEXICON), {"statements": 1, "unchanged": 0, "C1": 0, "C2": 0, "C3": 1})
        raw["statements"][0]["subject_id"] = "o"
        self.assertEqual(facts_from_graph_v2(raw, {"d"}, LEXICON)[0].subject["text"], raw["entities"][1]["name"])

    def test_unchanged_graph_and_mixed_counts(self):
        raw = graph("well", "reached_td", "9500")
        raw["statements"] *= 2
        self.assertEqual(facts_from_graph_v2(raw, {"d"}, LEXICON), facts_from_graph(raw, {"d"}))
        for i, (relation, surface) in enumerate((("set_plug_at", "CIBP 15980'"), ("has_well_status", "temporarily abandoned"), ("tested_to_pressure", "250 psi and 10000 psi"))):
            raw["entities"].append({"entity_id": str(i), "name": surface})
            raw["statements"].append({**raw["statements"][0], "object_id": str(i), "predicate": relation})
        self.assertEqual(conversion_counts(raw, {"d"}, LEXICON), {"statements": 5, "unchanged": 2, "C1": 1, "C2": 1, "C3": 1})

    def test_v1_dev_statement_crosscheck(self):
        path = PROJECT_ROOT / "runs/reference/bsee_text/dev_v1_guided/bsee_text_dev_v1_guided/A4/graph.json"
        if not path.is_file(): self.fail("Required published BSEE graph is missing")
        raw = json.loads(path.read_text(encoding="utf-8"))
        ids = {d["doc_id"] for d in raw["documents"]}
        excluded = 0
        for statement in raw["statements"]:
            single = {**raw, "statements": [statement]}
            old = facts_from_graph(single, ids)
            new = facts_from_graph_v2(single, ids, LEXICON)
            counts = conversion_counts(single, ids, LEXICON)
            self.assertGreaterEqual(len(new), len(old))
            if not any(counts[k] for k in ("C1", "C2", "C3")): self.assertEqual(new, old)
            if counts["C3"]:
                obj = old[0].object
                kinds = set(RELATION_SPEC[statement["predicate"]][1]) & TYPED_KINDS
                spans = typed_spans(obj["text"], kinds)
                first_valid = (obj["kind"] in TYPED_KINDS - {"date"}
                               and parse_quantity(obj["text"], obj["kind"]).status == "ok" and bool(spans)
                               and self.value(facts_from_graph(graph("well", statement["predicate"], spans[0][2]), {"d"})[0].object)
                               == self.value(obj))
                if first_valid:
                    self.assertIn(self.value(obj), [self.value(f.object) for f in new])
                else: excluded += 1
        print(json.dumps({**conversion_counts(raw, ids, LEXICON), "c3_first_literal_not_span": excluded}, sort_keys=True))
