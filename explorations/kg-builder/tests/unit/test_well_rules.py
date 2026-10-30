"""Three synthetic examples per frozen relation plus negative and modality cases."""
from __future__ import annotations

import json
import unittest
from collections import Counter

from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.core.text import cj, write_jsonl
from kgbuilder.core.well_facts import load_annotations
from kgbuilder.core.well_values import in_name
from kgbuilder.evaluation.well_rules import RULE_RELATIONS, RULES_VERSION, annotate, governing_cue


# Synthetic sentences and exact expectations for the corrected annotation rules.
AMENDMENT_CASES = [
    ("Tested tubing to 1000 psi and bled down to 200 psi.", [("tested_to_pressure", "1000", "psi", None)]),
    ("Bled down to 200 psi, then tested casing to 1500 psi.", [("tested_to_pressure", "1500", "psi", None)]),
    ("Tested BOP to 250 psi and 5000 psi.", [("tested_to_pressure", "250", "psi", None), ("tested_to_pressure", "5000", "psi", None)]),
    ("Pressured up to 5000 psi on control line.", []),
    ("TD at 6000 ft MD in Amber 6100 ft Sand.", [("reached_td", "6000", "ft", "MD")]),
    ("Reached TD at 6000 ft MD and 5600 ft TVD.", [("reached_td", "6000", "ft", "MD"), ("reached_td", "5600", "ft", "TVD")]),
    ("Reached TD at 6000 ft MD and set plug at 5800 ft.", [("reached_td", "6000", "ft", "MD"), ("set_plug_at", "5800", "ft", "unknown")]),
    ("Drilled to 4000 ft and perforated 3900-3950 ft.", [("drilled_to", "4000", "ft", "unknown"), ("perforated_interval", ("3900", "3950"), "ft", "unknown")]),
    ("FIT at 600 ft MD held 12 ppg; raised mud weight to 10.5 ppg.", [("fit_lot_emw", "12", "ppg", None), ("has_mud_weight", "10.5", "ppg", None)]),
    ("Perforated 7100-7120 ft in the Amber 7200 ft Sand.", [("perforated_interval", ("7100", "7120"), "ft", "unknown")]),
    ("TD at 600ft MD.", [("reached_td", "600", "ft", "MD")]),
    ("Drilling 8-1/2 in. hole at 4000 ft.", []),
    ("Drilled 8-1/2 in. hole at 4000 ft.", []),
    ("Drilled 8-1/2 in. hole to 4000 ft.", [("drilled_to", "4000", "ft", "unknown")]),
    ("Fired 3 shots at 7100 ft.", []),
    ("Fired gun at 7100 ft.", [("perforated_interval", "7100", "ft", "unknown")]),
    ("Testing casing to 1000 psi.", []),
    ("Perforated 3900-3950 ft; drilling resumed at 4000 ft.", [("perforated_interval", ("3900", "3950"), "ft", "unknown")]),
    ("Drilled to 4000 ft, TD at 4500 ft.", [("drilled_to", "4000", "ft", "unknown"), ("reached_td", "4500", "ft", "unknown")]),
    ("Reached section TD at 4000 ft.", [("drilled_to", "4000", "ft", "unknown")]),
    ("Reached section TD at 4000 ft; TD at 6000 ft.", [("drilled_to", "4000", "ft", "unknown")]),
    ("Tagged plug in Amber 6100 ft Sand at 6200 ft.", []),
    ("Set packer in Amber 6100 ft Sand at 6200 ft.", []),
    ("Set cement plug in Amber 6100 ft Sand at 6200 ft.", []),
    ("Cut casing in Amber 6100 ft Sand at 6200 ft.", []),
    ("Set packer at 6000 ft in Amber 6100 ft Sand.", [("set_equipment_at", "6000", "ft", "unknown")]),
]


class WellRulesTest(unittest.TestCase):
    def test_amendment_governing_cues_and_names(self):
        cue_relations = {"reached_td", "drilled_to", "perforated_interval", "fit_lot_emw", "tested_to_pressure"}
        noun_relations = {"tagged_at", "set_equipment_at", "set_plug_at", "cut_at"}
        root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/well_rules_v2")
        for text, expected in AMENDMENT_CASES:
            with self.subTest(text=text):
                facts = annotate("synthetic", "synthetic#c000", text)
                relations = cue_relations | {row[0] for row in expected}
                if "Amber 6100 ft Sand at 6200 ft" in text: relations |= noun_relations
                actual = [(f.relation, (f.object["lower"], f.object["upper"]) if f.object["kind"] == "interval" else f.object["value"],
                           f.object["unit"], f.object.get("reference")) for f in facts if f.relation in relations]
                self.assertCountEqual(actual, expected)
                for f in facts:
                    if f.object["kind"] in {"depth", "interval"}:
                        self.assertFalse(in_name(text, f.object["start"], f.object["end"]))
                        if "Amber 6100 ft Sand at 6200 ft" in text: self.assertNotEqual(f.object.get("value"), "6200")
                if text.startswith("Tested tubing"):
                    self.assertEqual(facts[0].qualifiers, {"test_kind": "tubing", "result": "failed"})
                rows = [{"record": "chunk", "format": "kgb.well_annotation/1", "annotator": RULES_VERSION,
                         "chunk_id": "synthetic#c000", "status": "annotated" if facts else "no_facts", "n_facts": len(facts), "note": ""},
                        *[f.model_dump() for f in facts]]
                write_jsonl(root / "case.jsonl", rows)
                self.assertEqual(len(load_annotations(root / "case.jsonl", {"synthetic#c000": text})), len(facts))
                self.assertEqual(cj([f.model_dump() for f in facts]), cj([f.model_dump() for f in annotate("synthetic", "synthetic#c000", text)]))

    def test_v2_is_subset_of_frozen_v1(self):
        captured = json.loads((PROJECT_ROOT / "tests/fixtures/bsee/rules_v1_outputs.json").read_text())
        cases = json.loads((PROJECT_ROOT / "tests/fixtures/bsee/rules_cases.json").read_text())
        self.assertEqual({r["text"] for r in captured["cases"]}, {text for text, _ in AMENDMENT_CASES} | {r["text"] for r in cases})
        def stable(row): return cj({k: v for k, v in row.items() if k not in {"annotator", "fact_no"}})
        for case in captured["cases"]:
            with self.subTest(text=case["text"]):
                before = Counter(stable(f) for f in case["facts"])
                after = Counter(stable(f.model_dump()) for f in annotate("synthetic", "synthetic#c000", case["text"]))
                self.assertFalse(after - before, (case["text"], before, after))

    def test_cue_boundaries(self):
        for text in ("Stage 2 cemented at 5000 ft.", "Accepted 3000 psi.", "Transferred 200 bbl mud.", "Offset well at 4000 ft."):
            self.assertIsNone(governing_cue(text, len(text)))
        self.assertEqual(governing_cue("Reached section TD at 4000 ft.", 22), ("drill", 18))

    def test_synthetic_cases(self):
        cases = json.loads((PROJECT_ROOT / "tests/fixtures/bsee/rules_cases.json").read_text())
        counts = Counter(row["relation"] for row in cases)
        self.assertEqual(set(counts), set(RULE_RELATIONS))
        self.assertTrue(all(n >= 3 for n in counts.values()))
        root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/well_rules")
        for i, case in enumerate(cases):
            with self.subTest(i=i, relation=case["relation"]):
                facts = annotate("synthetic", "synthetic#c000", case["text"])
                self.assertIn(case["relation"], {f.relation for f in facts})
                self.assertEqual(facts, annotate("synthetic", "synthetic#c000", case["text"]))
                rows = [{"record": "chunk", "format": "kgb.well_annotation/1", "annotator": RULES_VERSION, "chunk_id": "synthetic#c000", "status": "annotated", "n_facts": len(facts), "note": ""}]
                for fact in facts:
                    row = fact.model_dump(exclude_none=True); row["time"] = None; rows.append(row)
                write_jsonl(root / "case.jsonl", rows)
                self.assertEqual(len(load_annotations(root / "case.jsonl", {"synthetic#c000": case["text"]})), len(facts))

    def test_negatives_and_modality(self):
        for text in ("BN 7300' Sand", "Pressured up to 5000 psi on control line.", "Bled off 2000 psi from annulus."):
            self.assertEqual(annotate("d", "d#c000", text), [])
        for prefix, expected in [("", ("positive", "done")), ("Attempt to ", ("positive", "attempted")),
                                 ("Unable to ", ("negative", "done")), ("Attempt with no success to ", ("negative", "attempted"))]:
            rows = annotate("d", "d#c000", prefix + "test tubing to 1000 psi.")
            test = next(r for r in rows if r.relation == "tested_to_pressure")
            self.assertEqual((test.polarity, test.modality), expected)
        rows = annotate("d", "d#c000", "Drill to section TD of 11398 ft MD.")
        self.assertNotIn("reached_td", {r.relation for r in rows})
        rows = annotate("d", "d#c000", "Set DX plug in x-nipple @ 1484' MD.")
        self.assertEqual([r.relation for r in rows], ["set_plug_at"])
