"""Strict annotation shapes, span occurrence resolution and partitioned matching."""
from __future__ import annotations

import copy
import json
import unittest

from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.core.config import ConfigError
from kgbuilder.core.text import write_jsonl
from kgbuilder.core.well_facts import AnnotationFacts, RELATION_SPEC, WellFact, annotation_message, bootstrap_ci, facts_from_graph, iaa_score, load_annotations, match, paired_bootstrap, resolve_fact, score, sign_test, value_equal
from kgbuilder.core.well_values import RELATIONS


def fact(value="1000", relation="reached_td", **changes):
    row = {"record": "fact", "format": "kgb.well_annotation/1", "annotator": "synthetic", "chunk_id": "d#c000", "fact_no": 1,
           "relation": relation, "subject": {"implicit": "report_well", "type": "Borehole"},
           "object": {"kind": "depth", "text": value + " ft MD", "occ": 0, "value": value, "unit": "ft", "reference": "MD", "datum": "unknown"},
           "qualifiers": {}, "polarity": "positive", "modality": "done", "time": None, "uncertainty": "certain",
           "evidence": {"text": "The well reached " + value + " ft MD.", "occ": 0}, "note": ""}
    row.update(changes)
    return WellFact.model_validate(row)


def graph_fact(relation, surface):
    graph = {"entities": [{"entity_id": "s", "name": "the well"}, {"entity_id": "o", "name": surface}],
             "chunks": [{"chunk_id": "d#c000", "char_start": 0}],
             "statements": [{"status": "accepted", "predicate": relation, "subject_id": "s", "object_id": "o",
                             "evidence": [{"doc_id": "d", "chunk_id": "d#c000", "text": surface, "char_start": 0, "char_end": len(surface)}]}]}
    return facts_from_graph(graph, {"d"})[0]


class WellFactsTest(unittest.TestCase):
    def test_time_does_not_affect_scores(self):
        dates = [None, {"text": "3/14/2011", "occ": 0, "iso": "2011-03-14", "precision": "day"},
                 {"text": "4/15/2012", "occ": 0, "iso": "2012-04-15", "precision": "day"}]
        gold = [fact(str(value), fact_no=i + 1) for i, value in enumerate((100, 101, 100, 200))]
        pred = [fact(str(value), fact_no=i + 1) for i, value in enumerate((101, 102, 100, 200))]
        gold += [fact("300", fact_no=5, modality="planned"), fact("400", fact_no=6, uncertainty="uncertain"),
                 fact("500", fact_no=7, relation="other", other_label="synthetic_depth")]
        pred += [fact(str(value), fact_no=i + 5) for i, value in enumerate((300, 400, 500))]
        for scoring in (lambda g, p: score(g, p, {}), lambda g, p: score(g, p, {}, symmetric=True),
                        lambda g, p: iaa_score(g, p, {})):
            baseline = scoring(gold, pred)
            for side, facts in enumerate((gold, pred)):
                for index in range(len(facts)):
                    for time in dates:
                        changed = list(facts)
                        changed[index] = changed[index].model_copy(update={"time": time})
                        self.assertEqual(scoring(changed, pred) if side == 0 else scoring(gold, changed), baseline)

    def test_compact_depth_conversion(self):
        for relation in ("hasDepth", "reached_td"):
            obj = graph_fact(relation, "600ft MD").object
            self.assertEqual((obj["kind"], obj["value"], obj["unit"], obj["reference"]), ("depth", "600", "ft", "MD"))
            self.assertTrue(value_equal(obj, fact("601").object, {}))

    def test_at_depth_reference_at_l3(self):
        obj = {"kind": "density", "text": "12 ppg", "occ": 0, "value": "12", "unit": "ppg"}
        depth = {"text": "600 ft MD", "occ": 0, "value": "600", "unit": "ft", "reference": "MD", "datum": "unknown"}
        a = fact(relation="fit_lot_emw", object=obj, qualifiers={"at_depth": depth})
        for reference in ("TVD", "unknown", "MD", None):
            b = a.model_copy(update={"qualifiers": {} if reference is None else {"at_depth": {**depth, "reference": reference}}})
            self.assertEqual(match([a], [b], {}, "L3"), [] if reference == "TVD" else [(0, 0)])
            self.assertEqual(match([a], [b], {}, "L2"), [(0, 0)])

    def test_symmetric_iaa_and_directional_score(self):
        def pressure(value, **changes):
            return fact(relation="tested_to_pressure", object={"kind": "pressure", "text": value + " psi", "occ": 0,
                                                               "value": value, "unit": "psi"}, **changes)
        a = pressure("1000")
        for value, expected in (("990", 1), ("989", 0)):
            b = pressure(value)
            for left, right in ((a, b), (b, a)):
                self.assertEqual(iaa_score([left], [right], {})["L1"]["f1"], expected)
        self.assertEqual(score([a], [pressure("990")], {})["L1"]["tp"], 1)
        self.assertEqual(score([pressure("990")], [a], {})["L1"]["tp"], 0)
        a, b = [pressure("1000", subject={"text": name, "occ": 0, "type": "Tubular"})
                for name in ("upper production tubing", "tubing long lower string")]
        self.assertEqual(iaa_score([a], [b], {})["L3"]["f1"], 1)
        self.assertEqual(iaa_score([b], [a], {})["L3"]["f1"], 1)
        left = [pressure(value, fact_no=i + 1, evidence={"text": "Synthetic test.", "occ": 0, "start": 0, "end": 15})
                for i, value in enumerate(("1000", "990", "1000", "2000", "1980", "3000", "4000"))]
        right = [pressure(value, fact_no=i + 1, evidence={"text": "Synthetic test.", "occ": 0, "start": 0, "end": 15})
                 for i, value in enumerate(("990", "1000", "1010", "1980", "2000", "3000"))]
        ab, ba = iaa_score(left, right, {}), iaa_score(right, left, {})
        for level in ("L1", "L2", "L3"):
            self.assertEqual(ab[level]["tp"], ba[level]["tp"])
            self.assertEqual(ab[level]["f1"], ba[level]["f1"])
            self.assertEqual(ab[level]["precision"], ba[level]["recall"])

    def _issues(self, row, chunk_changes=None, raw=None):
        root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/well_facts_diagnostics")
        path = root / "synthetic.jsonl"
        chunk = {"record": "chunk", "format": "kgb.well_annotation/1", "annotator": "synthetic", "chunk_id": "d#c000",
                 "status": "annotated", "n_facts": 1, "note": ""}
        chunk.update(chunk_changes or {})
        write_jsonl(path, [chunk, row])
        if raw is not None: path.write_text(json.dumps(chunk) + "\n" + raw + "\n", encoding="utf-8")
        issues = []
        load_annotations(path, {"d#c000": "The well reached 1000 ft MD. 3-14-2011"}, issues, "annotations/synthetic/batch_01.jsonl")
        return path, issues

    def test_diagnostic_paths(self):
        base = fact().model_dump(exclude_none=True); base["time"] = None
        cases = [
            ({"relation": "invalid"}, "relation", "unknown relation"),
            ({"subject": {"implicit": "wrong", "type": "Borehole"}}, "subject", "invalid implicit subject"),
            ({"object": {**base["object"], "unit": "bad"}}, "object", "invalid unit"),
            ({"time": {"text": "3-14-2011", "occ": -1, "iso": "2011-03-14", "precision": "day"}}, "time", "invalid span"),
            ({"relation": "other", "other_label": "synthetic", "qualifiers": {"correction": True}}, "qualifiers", "other does not allow qualifiers"),
            ({"qualifiers": {"correction": "yes"}}, "qualifiers.correction", "boolean qualifier required"),
            ({"evidence": {"text": "missing", "occ": 0}}, "evidence", "span not found"),
            ({"evidence": {"text": "The well", "occ": 0}}, "evidence", "evidence does not contain fact span"),
            ({"fact_no": 2}, "record", "fact numbering gap"),
            ({"polarity": "invalid"}, "polarity", "literal_error"),
        ]
        for changes, path, reason in cases:
            with self.subTest(path=path, reason=reason):
                _, issues = self._issues({**base, **changes})
                self.assertEqual([(i["path"], i["reason"]) for i in issues], [(path, reason)])
        _, issues = self._issues(base, {"status": "bad"})
        self.assertEqual([(i["path"], i["reason"]) for i in issues], [("chunk", "invalid chunk status")])
        _, issues = self._issues(base, raw="{invalid")
        self.assertEqual([(i["path"], i["reason"]) for i in issues], [("record", "invalid json")])

    def test_date_diagnostics_and_continuation(self):
        text = "The well reached 1000 ft MD. 3-14-2011"
        slot = {"text": "3-14-2011", "occ": 0, "iso": "2011-03-14", "precision": "day"}
        good = fact(relation="spudded_on", object={"kind": "date", **slot}, time=slot,
                    evidence={"text": text, "occ": 0}).model_dump(exclude_none=True)
        good["time"] = slot
        root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/well_facts_dates")
        path = root / "synthetic.jsonl"
        chunk = {"record": "chunk", "format": "kgb.well_annotation/1", "annotator": "synthetic", "chunk_id": "d#c000",
                 "status": "annotated", "n_facts": 2, "note": ""}
        for bad_paths in (("object",), ("time",), ("object", "time")):
            bad = copy.deepcopy(good)
            for key in bad_paths: bad[key].update(iso=None, precision="partial")
            next_good = {**good, "fact_no": 2}
            write_jsonl(path, [chunk, bad, next_good])
            issues = []
            loaded = load_annotations(path, {"d#c000": text}, issues, "annotations/synthetic/batch_01.jsonl")
            self.assertEqual(len(loaded), 1)
            self.assertEqual([i["path"] for i in issues], list(bad_paths))
            for issue in issues:
                self.assertEqual(issue["reason"], "date normalization mismatch")
                self.assertEqual(issue["detail"]["annotator"], {"iso": None, "precision": "partial"})
                self.assertEqual(issue["detail"]["parser"], {"iso": "2011-03-14", "precision": "day"})
                self.assertEqual(annotation_message(issue), 'annotations/synthetic/batch_01.jsonl:2: ' + issue["path"] +
                                 ': date normalization mismatch: span "3-14-2011"; annotator iso=null precision=partial; parser iso=2011-03-14 precision=day')
                self.assertEqual(annotation_message(issue, True), 'annotations/synthetic/batch_01.jsonl:2: ' + issue["path"])
            with self.assertRaises(ConfigError) as raised:
                load_annotations(path, {"d#c000": text}, label="annotations/synthetic/batch_01.jsonl")
            self.assertEqual(str(raised.exception).splitlines(), [annotation_message(i) for i in issues])
        bad["polarity"] = "bad"
        write_jsonl(path, [chunk, bad, next_good]); issues = []
        load_annotations(path, {"d#c000": text}, issues)
        self.assertEqual([i["path"] for i in issues], ["polarity"])

    def test_diagnostic_redaction(self):
        issue = {"file": "synthetic.jsonl", "line": 2, "path": "time", "reason": "date normalization mismatch",
                 "detail": {"text": "Synthetic private content", "annotator": {"iso": "private", "precision": "private"},
                            "parser": {"iso": None, "precision": "partial"}}}
        message = annotation_message(issue)
        self.assertNotIn("private", message)
        self.assertIn("<span length 25>", message)

    def test_graph_guideline_conversion(self):
        for relation, surface, kind, values in [
            ("spudded_on", "3-14-2011", "date", {"iso": "2011-03-14", "precision": "day"}),
            ("spudded_on", "3-14", "date", {"iso": None, "precision": "partial"}),
            ("open", "3-14", "entity", {}),
            ("open", '9-5/8"', "size", {"value": "9.625", "unit": "in"}),
            ("open", "13202'-24'", "interval", {"lower": "13202", "upper": "13224"}),
            ("open", '16.5 x 19"', "entity", {}),
            ("pressure_tested_to", "1000#", "pressure", {"value": "1000", "unit": "psi"}),
            ("tested_to", "1000#", "pressure", {"value": "1000", "unit": "psi"}),
            ("has_weight", "23#", "pressure", {"value": "23", "unit": "unknown"}),
            ("bledDownTo", "0#", "pressure", {"value": "0", "unit": "psi"}),
            ("pressure", "500 psi", "pressure", {"value": "500", "unit": "psi"}),
            ("tested_to_pressure", "1000#", "pressure", {"value": "1000", "unit": "psi"}),
        ]:
            with self.subTest(relation=relation, surface=surface):
                obj = graph_fact(relation, surface).object
                self.assertEqual(obj["kind"], kind)
                for key, value in values.items(): self.assertEqual(obj[key], value)
        a, b = (graph_fact("spudded_on", text).object for text in ("3/14/2011", "3-14-2011"))
        self.assertTrue(value_equal(a, b, {}))

    def test_status_guideline(self):
        for status in ("TA", "PA", "COM", "ST", "BP", "SI", "other"):
            obj = {"kind": "status", "text": status, "occ": 0, "value": status}
            self.assertEqual(fact(relation="has_well_status", object=obj).object, obj)
            if status != "other": self.assertEqual(graph_fact("has_well_status", status).object["value"], status)
        for status in ("invalid", "temporarily abandoned"):
            with self.assertRaises(ValueError):
                fact(relation="has_well_status", object={"kind": "status", "text": status, "occ": 0, "value": status})
            self.assertNotEqual(graph_fact("open", status).object["kind"], "status")

    def test_contract_and_spans(self):
        self.assertEqual(tuple(RELATION_SPEC), RELATIONS)
        text = "The well reached 1000 ft MD. The well reached 1000 ft MD."
        f = fact()
        row = f.model_dump(exclude_none=True); row["time"] = None
        row["object"]["occ"] = row["evidence"]["occ"] = 1
        resolved = resolve_fact(WellFact.model_validate(row), text)
        self.assertEqual(resolved.evidence["start"], 29)
        root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/well_facts")
        path = root / "annotations.jsonl"
        chunk = {"record": "chunk", "format": "kgb.well_annotation/1", "annotator": "synthetic", "chunk_id": "d#c000", "status": "annotated", "n_facts": 1, "note": ""}
        write_jsonl(path, [chunk, row])
        self.assertEqual(load_annotations(path, {"d#c000": text})[0].object["start"], 46)
        row["object"]["occ"] = 2; write_jsonl(path, [chunk, row])
        with self.assertRaisesRegex(ConfigError, r"annotations.jsonl:2"):
            load_annotations(path, {"d#c000": text})
        for changes in ({"qualifiers": {"correction": "true"}}, {"unexpected": 1},
                        {"subject": {"text": "plug", "occ": 0, "type": "Plug", "role": "report_well"}}):
            with self.assertRaises(ValueError): fact(**changes)

    def test_match_partitions(self):
        gold = [fact(), fact("2000", uncertainty="uncertain"), fact("3000", modality="planned"),
                fact("4000", relation="other", other_label="synthetic_depth")]
        pred = [fact(str(i * 1000)) for i in range(1, 6)]
        result = score(gold, pred, {})
        self.assertEqual({k: result["L1"][k] for k in ("tp", "fp", "fn", "matched_other", "asserted_nonasserted")},
                         {"tp": 1, "fp": 2, "fn": 0, "matched_other": 1, "asserted_nonasserted": 1})
        self.assertEqual(result["L2"]["fp"], 3)
        self.assertEqual(score([fact()], [fact(), fact()], {})["L3"]["tp"], 1)
        self.assertIsNone(score([], [], {})["L1"]["f1"])
        self.assertEqual(score([], [fact()], {})["L1"]["f1"], 0)
        unreadable = AnnotationFacts([fact()], {"d#c000": {"status": "unreadable"}})
        result = score(unreadable, [fact()], {})
        self.assertEqual((result["n_unreadable"], result["L1"]["tp"], result["L1"]["fp"]), (1, 0, 0))
        explicit = fact(subject={"text": "the well", "occ": 0, "type": "Borehole", "role": "report_well"})
        prediction = fact(subject={"text": "A002", "occ": 0, "type": "Borehole"})
        self.assertEqual(match([explicit], [prediction], {}, "L3"), [(0, 0)])
        row = fact().model_dump(); row["object"]["reference"] = "TVD"
        self.assertEqual(match([fact()], [WellFact.model_validate(row)], {}, "L1"), [])

    def test_qualifier_shapes(self):
        f = fact(relation="cemented_interval", qualifiers={"toc": True})
        self.assertTrue(f.qualifiers["toc"])
        with self.assertRaises(ValueError): fact(relation="cemented_interval", qualifiers={"toc": {"text": "TOC", "occ": 0}})
        with self.assertRaises(ValueError): fact(relation="set_plug_at", subject={"text": "plug", "occ": 0, "type": "Plug"}, qualifiers={"action": {"text": "Set", "occ": 0}})
        obj = {"kind": "density", "text": "17 ppg", "occ": 0, "value": "17", "unit": "ppg"}
        depth = {"text": "1000 ft TVD", "occ": 0, "value": "1000", "unit": "ft", "reference": "TVD", "datum": "unknown"}
        fact(relation="fit_lot_emw", object=obj, qualifiers={"at_depth": depth})
        with self.assertRaises(ValueError): fact(relation="fit_lot_emw", object=obj, qualifiers={"at_depth": {**depth, "bound": "eq"}})

    def test_statistics(self):
        mean = lambda rows: sum(rows) / len(rows) if rows else None
        self.assertEqual(bootstrap_ci([2, 2, 2], mean), (2, 2))
        self.assertEqual(paired_bootstrap([1, 2], [2, 3], mean)["ci95"], (1, 1))
        self.assertEqual(sign_test(3, 0), .25)
        self.assertEqual(sign_test(0, 0), 1)
