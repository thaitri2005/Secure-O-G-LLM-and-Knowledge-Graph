"""Independent silver formulas and equal-text corpus scope checks."""
from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

from helpers import PROJECT_ROOT, clean_dir, assert_expected_artifact
from kgbuilder.core.config import ConfigError, load_well_eval
from kgbuilder.core.text import sha256_file, write_json, write_jsonl
from kgbuilder.core.well_facts import load_annotations
from kgbuilder.evaluation import well_gold
from kgbuilder.evaluation.well_eval import evaluate_wells, make_silver, mention_spans, silver_score
from unit.test_bsee_corpus import corpus_fixture
from unit.test_well_facts import fact
from unit.test_well_gold import rule_prediction_fixture
from unit.test_well_link import link_fixture


def eval_fixture(name):
    root, run, tables, sources = link_fixture(name)
    corpus = root / "corpus"; corpus.mkdir()
    docs = json.loads((run / "graph.json").read_text())["documents"]
    for path in (run / "documents.jsonl", corpus / "corpus.jsonl", corpus / "eligible.jsonl", corpus / "test_subset.jsonl"):
        write_jsonl(path, docs)
    (corpus / "doc_sources.jsonl").write_bytes(sources.read_bytes())
    return root, run, tables, corpus


class WellEvalTest(unittest.TestCase):
    def test_v2_conversion_and_v1_bytes(self):
        from unit.test_well_attribution import case, evaluate
        triple = ["CIBP", "set_plug_at", "CIBP at 9,500'"]
        paths = case("recall_v1_golden", [{"triple": triple, "branch": "schema_short_circuit"}])
        root, run, corpus, gold = paths
        cfg = load_well_eval(PROJECT_ROOT / "configs/experiments/bsee_eval.yaml")
        old = evaluate_wells(run, corpus, cfg, root / "eval", None, None, gold, None, split="dev")
        evaluate(paths)
        self.assertNotIn("converter", old)
        self.assertNotIn("ai_gold_converter_v1", old["exports"]["full"])
        fixture = json.loads((PROJECT_ROOT / "tests/fixtures/bsee_guided/evaluation_expected.json").read_text())
        for name, entry in fixture.items():
            assert_expected_artifact(self, root / name, entry)
        freeze = json.loads((gold / "freeze.json").read_text())
        lexicon_key = "configs/domains/bsee/bsee_literals.yaml"
        freeze.update(converter="v2", frozen_inputs={lexicon_key: sha256_file(PROJECT_ROOT / lexicon_key)})
        write_json(gold / "freeze.json", freeze)
        result = evaluate_wells(run, corpus, cfg, root / "v2", None, None, gold, None, split="dev")
        for export in ("full", "strict"):
            self.assertEqual(result["converter"]["counts"][export]["C1"], 1)
            row = result["exports"][export]
            for level in ("L1", "L2", "L3"):
                self.assertEqual(row["ai_gold"][level]["tp"], 1)
                self.assertEqual(row["ai_gold_converter_v1"][level]["tp"], 0)
                self.assertEqual(set(row["ai_gold_converter_v1"][level]), {"tp", "fp", "fn", "precision", "recall", "f1"})
        graph = json.loads((run / "graph.json").read_text())
        graph["entities"][0]["name"] = "Hydraulic Choke"
        graph["entities"][1]["name"] = "250 psi low and 10,000 psi high"
        graph["statements"][0]["predicate"] = "tested_to_pressure"
        write_json(run / "graph.json", graph)
        result = evaluate_wells(run, corpus, cfg, root / "c3", None, None, gold, None, split="dev")
        self.assertEqual(result["converter"]["counts"]["full"]["C3"], 1)
        freeze["frozen_inputs"][lexicon_key] = "changed"
        write_json(gold / "freeze.json", freeze)
        with self.assertRaisesRegex(ConfigError, "converter lexicon hash differs from freeze"):
            evaluate_wells(run, corpus, cfg, root / "bad", None, None, gold, None, split="dev")

    def test_dev_split_scope_and_baseline(self):
        root, gold, _, corpus, text, status, planned = rule_prediction_fixture("guided_eval_dev")
        good = planned.model_copy(update={"modality": "done"})
        write_jsonl(gold / "adjudicated.jsonl", [status, good.model_dump()])
        write_json(gold / "split.json", {"dev": ["d"], "test": []})
        run = root / "run"; run.mkdir()
        docs = [{"doc_id": "d", "text": text}]
        write_jsonl(run / "documents.jsonl", docs)
        write_json(run / "graph.json", {"format": "kgb.graph/1", "run_name": "synthetic", "ablation": "A4",
                   "flags": {}, "documents": docs, "chunks": [], "entities": [], "statements": []})
        cfg = load_well_eval(PROJECT_ROOT / "configs/experiments/bsee_eval.yaml")
        with patch("kgbuilder.evaluation.well_eval.facts_from_graph", return_value=[good]):
            before = evaluate_wells(run, corpus, cfg, root / "test", None, None, gold, None)
            self.assertNotIn("gold_split", before)
            self.assertEqual(before["dev_excluded"], 1)
            result = evaluate_wells(run, corpus, cfg, root / "dev", None, None, gold, None, split="dev")
            self.assertEqual((result["gold_split"], result["dev_excluded"]), ("dev", 0))
            self.assertEqual(result["exports"]["full"]["ai_gold"]["L1"]["tp"], 1)
            with self.assertRaisesRegex(ConfigError, "baseline split mismatch"):
                evaluate_wells(run, corpus, cfg, root / "bad", None, None, gold, root / "test", split="dev")
        with self.assertRaisesRegex(ConfigError, "requires --gold"):
            evaluate_wells(run, corpus, cfg, root / "bad", None, None, None, None, split="dev")
        write_json(gold / "split.json", {"dev": [], "test": ["d"]})
        with self.assertRaisesRegex(ConfigError, "run scope outside dev split"):
            evaluate_wells(run, corpus, cfg, root / "bad", None, None, gold, None, split="dev")

    def test_strict_baseline_uses_full_only_when_strict_is_absent(self):
        root, gold, _, corpus, text, status, planned = rule_prediction_fixture("bsee_eval_strict_baseline")
        good = planned.model_copy(update={"modality": "done"})
        bad = good.model_copy(update={"object": {**good.object, "value": "9000", "text": "9000 psi"}})
        write_jsonl(gold / "adjudicated.jsonl", [status, good.model_dump()])
        graph = json.loads((PROJECT_ROOT / "tests/fixtures/bsee/text_graph.json").read_text())
        graph.update(documents=[{"doc_id": "d", "text": text, "title": None, "published_at": None, "source_uri": None}],
                     chunks=[], entities=[], statements=[])
        baseline_run, current_run = root / "A0", root / "A4"
        for run in (baseline_run, current_run):
            run.mkdir()
            write_json(run / "graph.json", graph)
            write_jsonl(run / "documents.jsonl", graph["documents"])
        write_json(current_run / "graph_strict.json", graph)
        cfg = load_well_eval(PROJECT_ROOT / "configs/experiments/bsee_eval.yaml")
        baseline = root / "baseline"
        for has_strict in (False, True):
            with self.subTest(has_strict=has_strict):
                if has_strict:
                    write_json(baseline_run / "graph_strict.json", graph)
                with patch("kgbuilder.evaluation.well_eval.facts_from_graph", side_effect=[[good, bad], [good]]):
                    prior = evaluate_wells(baseline_run, corpus, cfg, baseline, None, None, gold, None)
                self.assertEqual(set(prior["exports"]), {"full", "strict"} if has_strict else {"full"})
                with patch("kgbuilder.evaluation.well_eval.facts_from_graph", side_effect=[[good, bad], [good]]):
                    result = evaluate_wells(current_run, corpus, cfg, root / "paired", None, None, gold, baseline)
                for matching in ("L1", "L2", "L3"):
                    self.assertEqual(result["exports"]["full"]["ai_gold"]["paired"][matching]["difference"], 0)
                    strict = result["exports"]["strict"]
                    paired = strict["ai_gold"]["paired"][matching]
                    expected = 0 if has_strict else 1 - 2 / 3
                    self.assertAlmostEqual(paired["difference"], expected)
                    self.assertEqual(paired["ci95"], (expected, expected))
                    self.assertEqual((paired["n"], paired["sign_test"]), (1, 1))
                    overlap = strict["self_consistency"][matching]
                    self.assertEqual((overlap["tp"], overlap["fp"], overlap["fn"]), (1, 0, 0 if has_strict else 1))
                for field, message in (("policy_sha256", "policy hash"), ("references", "reference identity")):
                    broken = copy.deepcopy(prior); broken[field] = "different"
                    write_json(baseline / "scores.json", broken)
                    with self.assertRaisesRegex(ConfigError, "baseline " + message + " mismatch"):
                        evaluate_wells(current_run, corpus, cfg, root / "invalid", None, None, gold, baseline)
                write_json(baseline / "scores.json", prior)

    def test_compact_depth_mentions(self):
        for text, value, unit, reference in (("Tagged at 6100ft.", "6100", "ft", "unknown"),
                                              ("Reached TD at 600ft MD.", "600", "ft", "MD"),
                                              ("Drilled to 600m.", "600", "m", "unknown"),
                                              ("Tagged at 6100feet.", "6100", "ft", "unknown")):
            obj = {**fact(value).object, "unit": unit, "reference": reference}
            self.assertEqual(len(mention_spans(text, obj, {})), 1)
        self.assertEqual(mention_spans("Mixed 600 mud batches.", {**fact("600").object, "unit": "m"}, {}), [])
        self.assertEqual(mention_spans("Completed in Amber 6100ft Sand.", fact("6100").object, {}), [])

    def test_rules_predictions_filter_but_reference_preserves_nonassertions(self):
        root, gold, rules, corpus, text, status, planned = rule_prediction_fixture("bsee_eval_rule_predictions")
        run = root / "text"; run.mkdir()
        graph = json.loads((PROJECT_ROOT / "tests/fixtures/bsee/text_graph.json").read_text())
        graph.update(documents=[{"doc_id": "d", "text": text, "title": None, "published_at": None, "source_uri": None}],
                     chunks=[{"chunk_id": "d#c000", "doc_id": "d", "idx": 0, "char_start": 0, "char_end": len(text), "text": text}],
                     entities=[], statements=[])
        write_json(run / "graph.json", graph)
        write_jsonl(run / "documents.jsonl", graph["documents"])
        variants = [planned.model_copy(update=change) for change in (
            {}, {"modality": "attempted"}, {"modality": "approved"}, {"modality": "done", "polarity": "negative"},
            {"uncertainty": "uncertain"}, {"relation": "other", "other_label": "synthetic_test", "qualifiers": {}})]
        cfg = load_well_eval(PROJECT_ROOT / "configs/experiments/bsee_eval.yaml")
        for modality in ("planned", "done"):
            write_jsonl(gold / "adjudicated.jsonl", [status, planned.model_copy(update={"annotator": "adjudicated", "modality": modality}).model_dump()])
            single = evaluate_wells(run, corpus, cfg, root / ("single_" + modality), None, rules, gold, None)["exports"]["full"]["rules"]["rules_vs_ai_gold"]
            self.assertEqual(single["excluded_predictions"], {"G-": 1})
            self.assertEqual((single["L2"]["tp"], single["L2"]["fp"], single["L2"]["fn"]), (0, 0, int(modality == "done")))
            self.assertEqual(single["L2"]["f1"], None if modality == "planned" else 0)
        write_jsonl(rules / "rules.jsonl", [p.model_dump() for p in variants])
        cfg = load_well_eval(PROJECT_ROOT / "configs/experiments/bsee_eval.yaml")
        for modality in ("planned", "done"):
            reference = planned.model_copy(update={"annotator": "adjudicated", "modality": modality})
            write_jsonl(gold / "adjudicated.jsonl", [status, reference.model_dump()])
            result = evaluate_wells(run, corpus, cfg, root / modality, None, rules, gold, None)
            row = result["exports"]["full"]["rules"]["rules_vs_ai_gold"]
            self.assertEqual(row["excluded_predictions"], {"G-": 4, "G?": 1, "Gother": 1})
            self.assertEqual((row["L2"]["tp"], row["L2"]["fp"], row["L2"]["fn"]), (0, 0, int(modality == "done")))
            self.assertEqual(row["L2"]["f1"], None if modality == "planned" else 0)
        asserted = planned.model_copy(update={"modality": "done"})
        with patch("kgbuilder.evaluation.well_eval.facts_from_graph", return_value=[asserted]):
            result = evaluate_wells(run, corpus, cfg, root / "asserted", None, rules, gold, None)
        self.assertEqual(result["exports"]["full"]["rules"]["L2"]["asserted_nonasserted"], 1)
        write_jsonl(rules / "rules.jsonl", [p.model_dump() for p in [asserted, *variants]])
        result = evaluate_wells(run, corpus, cfg, root / "positive_rule", None, rules, gold, None)
        row = result["exports"]["full"]["rules"]["rules_vs_ai_gold"]
        self.assertEqual((row["L2"]["tp"], row["L2"]["fp"], row["L2"]["fn"]), (1, 0, 0))
        self.assertEqual(row["excluded_predictions"], {"G-": 4, "G?": 1, "Gother": 1})

    def test_punctuated_company_mentions(self):
        obj = {"kind": "entity", "text": "North Lantern Inc.", "type": "Company"}
        for text in ("Operated by North Lantern Inc.", "Operated by NORTH  LANTERN Inc., today."):
            spans = mention_spans(text, obj, {})
            self.assertEqual(len(spans), 1)
            self.assertTrue(text[spans[0][0]:spans[0][1]].endswith("Inc."))
        self.assertEqual(mention_spans("Operated by North Lantern Incognito.", obj, {}), [])
        text = "Operated by North Lantern Inc."
        self.assertEqual([text[a:b] for a, b in mention_spans(text, {**obj, "text": "North Lantern Inc"}, {})],
                         ["North Lantern Inc"])
        observations, predictions = [], []
        spans = mention_spans("Operated by North Lantern Inc.", obj, {})
        for i in range(5):
            chunk = f"company_{i}#c000"
            observations.append({"chunk_id": chunk, "field": "BUS_ASC_NAME", "relation": "operated_by", "value": obj,
                                 "mentioned": bool(spans), "mention_spans": [{"start": a, "end": b} for a, b in spans]})
            predictions.append(fact(relation="operated_by", chunk_id=chunk, object={**obj, "occ": 0}))
        result = silver_score(observations, predictions, {})
        self.assertEqual((result["answerable"], result["matched"], result["recall"]), (5, 5, 1))
        self.assertEqual(result["per_field"]["BUS_ASC_NAME"]["status"], "sufficient")

    def test_numeric_mentions_require_tokens_and_exclude_names(self):
        metre = {**fact("600").object, "unit": "m", "reference": "unknown"}
        feet = {**fact("6100").object, "reference": "unknown"}
        for text in ("Mixed 600 mud batches.", "At X600 m.", "At 1600 m.", "At 1,600 m.", "At 1.600 m."):
            self.assertEqual(mention_spans(text, metre, {}), [], text)
        for text in ("Completed in Amber 6100 ft Sand.", "Completed in BN 6100' Sand."):
            self.assertEqual(mention_spans(text, feet, {}), [], text)
        for text, obj, expected in (("TD at 600 m.", metre, "600 m"), ("TD at 6100 ft.", feet, "6100 ft"),
                                    ("Set plug at 6100 ft MD.", fact("6100").object, "6100 ft MD"),
                                    ("TD at 6000 ft MD in Amber 6100 ft Sand.", fact("6000").object, "6000 ft MD")):
            self.assertEqual([text[a:b] for a, b in mention_spans(text, obj, {})], [expected])
        for kind, unit, text in (("pressure", "psi", "Tested to 600 psigment."), ("density", "ppg", "Mixed 600 ppgextra."),
                                 ("volume", "gal", "Mixed 600 gallons."), ("size", "in", "Used 600 inserts.")):
            self.assertEqual(mention_spans(text, {"kind": kind, "value": "600", "unit": unit}, {}), [])

    def test_silver_field_identity_and_unmentioned_observations(self):
        for count in (1, 5):
            observations, predictions = [], []
            for i in range(count):
                chunk = f"report_{i}#c000"
                md = fact("5000", chunk_id=chunk)
                tvd = fact("4500", chunk_id=chunk, object={**fact("4500").object, "reference": "TVD"})
                for field, f, mentioned in (("BH_TOTAL_MD", md, True), ("WELL_BORE_TVD", tvd, False)):
                    observations.append({"chunk_id": chunk, "field": field, "relation": "reached_td", "value": f.object,
                                         "mentioned": mentioned, "mention_spans": [{"start": 23, "end": 33}] if mentioned else []})
                predictions.append(tvd)
            result = silver_score(observations, predictions, {})
            self.assertEqual((result["contradicted"], result["unassessable"], result["precision"], result["coverage"]), (0, count, None, 0))
            self.assertEqual(result["per_field"]["BH_TOTAL_MD"]["predictions"], 0)
            self.assertEqual(result["per_field"]["WELL_BORE_TVD"]["answerable"], 0)
            unknown = [p.model_copy(update={"object": {**p.object, "reference": "unknown"}}) for p in predictions]
            result = silver_score(observations, unknown, {})
            self.assertEqual((result["contradicted"], result["unassessable"]), (0, count))
            self.assertEqual(result["per_field"]["BH_TOTAL_MD"]["contradicted"], 0)
            wrong = [fact("4800", chunk_id=p.chunk_id) for p in predictions]
            self.assertEqual(silver_score(observations, wrong, {})["contradicted"], count)
            for row in observations:
                if row["field"] == "WELL_BORE_TVD":
                    row.update(field="BH_TOTAL_MD", value=fact("5100").object)
            predictions = [fact("5100", chunk_id=p.chunk_id) for p in predictions]
            result = silver_score(observations, predictions, {})
            self.assertEqual((result["matched"], result["contradicted"], result["unassessable"]), (0, 0, count))
            self.assertEqual(result["per_field"]["BH_TOTAL_MD"]["contradicted"], 0)
            wrong = [fact("5200", chunk_id=p.chunk_id) for p in predictions]
            self.assertEqual(silver_score(observations, wrong, {})["contradicted"], count)
        # Matching is global: an ambiguous prediction cannot be reused by two fields.
        observations = [{**observations[0], "field": field} for field in ("BH_TOTAL_MD", "WELL_BORE_TVD")]
        result = silver_score(observations, [fact("5000", chunk_id=observations[0]["chunk_id"])], {})
        self.assertEqual(result["matched"], 1)
        self.assertEqual(sum(row["matched"] for row in result["per_field"].values()), 1)

    def test_iaa_resolves_spans_and_preserves_run_scope(self):
        root, run, _, corpus = eval_fixture("bsee_eval_iaa")
        text = "TD 100 ft. TD 101 ft. TD 102 ft."
        docs = [{"doc_id": name, "text": text} for name in ("test_subset", "dev", "outside", "unreadable")]
        write_jsonl(corpus / "corpus.jsonl", docs)
        write_jsonl(run / "documents.jsonl", [d for d in docs if d["doc_id"] != "outside"])
        graph = json.loads((run / "graph.json").read_text())
        graph.update(documents=[{**d, "title": None, "published_at": None, "source_uri": None} for d in docs if d["doc_id"] != "outside"],
                     chunks=[], entities=[], statements=[])
        write_json(run / "graph.json", graph)
        gold = root / "gold"; gold.mkdir()
        write_json(gold / "freeze.json", {"corpus_sha256": sha256_file(corpus / "corpus.jsonl")})
        write_json(gold / "split.json", {"dev": ["dev"], "test": ["test_subset", "outside", "unreadable"]})
        statuses, rows_by_role = [], {}
        texts = {d["doc_id"] + "#c000": text for d in docs}
        for name in texts:
            statuses.append({"record": "chunk", "format": "kgb.well_annotation/1", "annotator": "adjudicated", "chunk_id": name,
                             "status": "unreadable" if name.startswith("unreadable") else "no_facts", "n_facts": 0,
                             "note": "synthetic unreadable" if name.startswith("unreadable") else ""})
        write_jsonl(gold / "adjudicated.jsonl", statuses)
        for role, numbers in (("annotator_a", (100, 101)), ("annotator_b", (101, 102))):
            rows = []
            for chunk in texts:
                rows.append({**next(s for s in statuses if s["chunk_id"] == chunk), "annotator": role, "status": "annotated", "n_facts": 2, "note": ""})
                for i, number in enumerate(numbers, 1):
                    rows.append(fact(str(number), annotator=role, chunk_id=chunk, fact_no=i,
                                     object={**fact(str(number)).object, "text": f"{number} ft", "reference": "unknown"},
                                     evidence={"text": f"TD {number} ft.", "occ": 0}).model_dump())
            folder = gold / "annotations" / role; folder.mkdir(parents=True)
            write_jsonl(folder / "batch_01.jsonl", rows)
            rows_by_role[role] = load_annotations(folder / "batch_01.jsonl", texts)
        cfg = load_well_eval(PROJECT_ROOT / "configs/experiments/bsee_eval.yaml")
        result = evaluate_wells(run, corpus, cfg, root / "scores", None, None, gold, None)
        iaa = result["exports"]["full"]["ai_gold"]["iaa_reference"]
        self.assertEqual(iaa["L1"]["f1"], 0.5)
        self.assertEqual(iaa["partitions"]["G+"], 2)
        # The standalone report uses exactly the same resolved facts and scope.
        write_json(gold / "split.json", {"dev": ["dev"], "test": ["test_subset"]})
        with patch.object(well_gold, "verify"), patch.object(well_gold, "_policy", return_value=cfg.model_dump()), \
             patch.object(well_gold, "_annotations", side_effect=lambda _, role: rows_by_role[role]), \
             patch.object(well_gold, "_packets", return_value={"batch": [{"chunk_id": k, "text": v} for k, v in texts.items()]}):
            agreement = well_gold.agreement({"root": gold, "annotators": ["annotator_a", "annotator_b"]}, root / "agreement", None)
        self.assertEqual(iaa, agreement["scopes"]["test"]["iaa"])
        # One annotator alone marks the chunk unreadable; the merged scope wins in both orders.
        unreadable = "unreadable#c000"
        rows_by_role["annotator_a"][:] = [f for f in rows_by_role["annotator_a"] if f.chunk_id != unreadable]
        rows_by_role["annotator_a"].statuses[unreadable].update(status="unreadable", n_facts=0, note="synthetic unreadable")
        write_json(gold / "split.json", {"dev": ["dev"], "test": ["test_subset", "unreadable"]})
        for roles in (("annotator_a", "annotator_b"), ("annotator_b", "annotator_a")):
            for destination, source in zip(("annotator_a", "annotator_b"), roles):
                loaded = rows_by_role[source]
                rows = []
                for chunk, status in loaded.statuses.items():
                    rows.append({**status, "annotator": destination})
                    rows.extend({**f.model_dump(), "annotator": destination} for f in loaded if f.chunk_id == chunk)
                write_jsonl(gold / "annotations" / destination / "batch_01.jsonl", rows)
            result = evaluate_wells(run, corpus, cfg, root / ("swapped_" + roles[0]), None, None, gold, None)
            actual = result["exports"]["full"]["ai_gold"]["iaa_reference"]
            with patch.object(well_gold, "verify"), patch.object(well_gold, "_policy", return_value=cfg.model_dump()), \
                 patch.object(well_gold, "_annotations", side_effect=lambda _, role: rows_by_role[role]), \
                 patch.object(well_gold, "_packets", return_value={"batch": [{"chunk_id": k, "text": v} for k, v in texts.items()]}):
                report = well_gold.agreement({"root": gold, "annotators": list(roles)}, root / ("agreement_" + roles[0]), None)
            self.assertEqual(actual, report["scopes"]["test"]["iaa"])
            self.assertEqual(actual["L1"]["f1"], 0.5)
            self.assertEqual(actual["partitions"]["G+"], 2)

    def test_guideline_date_mentions(self):
        obj = {"kind": "date", "iso": "2011-03-14", "precision": "day", "text": "3/14/2011"}
        for surface in ("3-14-2011", "3-14-11", "3/14/2011"):
            text = "Spudded on " + surface + "."
            self.assertEqual([text[a:b] for a, b in mention_spans(text, obj, {})], [surface])
        text = 'Synthetic 3/14-11, 3-14, 9-5/8" casing and 13202\'-24\'.'
        self.assertEqual(mention_spans(text, obj, {}), [])

    def test_guideline_context_mentions(self):
        size = {"kind": "size", "value": "19", "unit": "in"}
        self.assertEqual(mention_spans('Drilled 16.5 x 19" hole.', size, {}), [])
        text = 'Ran 13 3/8" casing.'
        self.assertEqual([text[a:b] for a, b in mention_spans(text, {**size, "value": "13.375"}, {})], ['13 3/8"'])
        pressure = {"kind": "pressure", "value": "23", "unit": "psi"}
        for text in ('Ran 7" 23# casing.', 'Ran 7" 23# casing. Tested to 500#.'): self.assertEqual(mention_spans(text, pressure, {}), [])
        for text, expected in [('Pressure tested to 23#.', '23#'), ('Ran casing at 23 psi.', '23 psi')]:
            self.assertEqual([text[a:b] for a, b in mention_spans(text, pressure, {})], [expected])

    def test_silver(self):
        observations = [{"id": str(i), "chunk_id": "d#c000", "relation": "reached_td", "value": fact(str(i * 1000)).object,
                         "mentioned": True, "mention_spans": [{"start": 0, "end": 10}], "field": "BH_TOTAL_MD"} for i in range(1, 5)]
        pred = [fact("1000"), fact("2000"), fact("9000"), fact("1000", relation="drilled_to"),
                fact("1000", chunk_id="another#c000")]
        result = silver_score(observations, pred, {})
        self.assertEqual((result["matched"], result["contradicted"], result["unassessable"]), (2, 1, 2))
        self.assertEqual((result["precision"], result["coverage"], result["recall"]), (2/3, 3/5, 2/4))
        duplicate = silver_score(observations, [fact("1000"), fact("1000")], {})
        self.assertEqual(duplicate["matched"], 1)
        unknown = fact("9000").model_copy(update={"object": {**fact("9000").object, "unit": "unknown"}})
        self.assertEqual(silver_score(observations, [unknown], {})["contradicted"], 0)
        self.assertEqual(silver_score(list(reversed(observations)), pred, {}), result)
        self.assertTrue(mention_spans("At 1000 ft MD.", fact().object, {}))
        self.assertFalse(mention_spans("At 1000 ft TVD.", fact().object, {}))

    def test_scope_and_projection(self):
        root, run, tables, corpus = eval_fixture("bsee_eval_unit")
        cfg = load_well_eval(PROJECT_ROOT / "configs/experiments/bsee_eval.yaml")
        labels = root / "labels"
        self.assertEqual(make_silver(tables, corpus, cfg, labels)["llm_calls"], 0)
        result = evaluate_wells(run, corpus, cfg, root / "evaluation", labels, None, None, None)
        self.assertEqual(result["n_documents"], 2)
        self.assertIn("silver", result["exports"]["full"])
        self.assertIsNone(result["exports"]["full"]["ai_gold"])
        changed = cfg.model_dump(); changed["tolerance"]["depth_ft"] = 2
        with self.assertRaisesRegex(ConfigError, "silver policy hash mismatch"):
            evaluate_wells(run, corpus, changed, root / "bad_policy", labels, None, None, None)
        make_silver(tables, corpus, changed, root / "alternate_labels")
        with self.assertRaisesRegex(ConfigError, "baseline policy hash mismatch"):
            evaluate_wells(run, corpus, changed, root / "bad_baseline", root / "alternate_labels", None, None, root / "evaluation")
        docs = list(json.loads(line) for line in (run / "documents.jsonl").read_text().splitlines())
        docs[0]["text"] += " Changed."
        write_jsonl(run / "documents.jsonl", docs)
        with self.assertRaisesRegex(ConfigError, "scope/hash"):
            evaluate_wells(run, corpus, cfg, root / "bad", labels, None, None, None)
