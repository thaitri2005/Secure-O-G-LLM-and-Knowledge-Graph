"""Invented artifact paths exercise every attribution stage and verifier branch."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from helpers import PROJECT_ROOT, clean_dir, assert_expected_artifact
from kgbuilder.build.refine.canon import request_order
from kgbuilder.core.config import ConfigError, KgbError, load_well_eval
from kgbuilder.core.schema import load_schema, write_edc_csv
from kgbuilder.core.text import read_jsonl, sha256_file, write_json, write_jsonl
from kgbuilder.core.well_literals import load_lexicon
from kgbuilder.evaluation.well_attribution import STAGES, attribute, carries, request_key, triggers, recall_triggers, _recall_labels
from unit.test_well_facts import fact
from unit.test_well_gold import gold_fixture, TEST_CONFIG, TEST_CONFIG_V2


LEXICON = PROJECT_ROOT / "configs/domains/bsee/bsee_literals.yaml"
FIXTURE = PROJECT_ROOT / "tests/fixtures/bsee_guided/attribution"


def render_verify(text, triple, answer="A", relation="set_plug_at"):
    template = (PROJECT_ROOT / "third_party/edc/prompt_templates/sc_template.txt").read_text(encoding="utf-8")
    names = [relation, "tagged_at", "cut_at", "drilled_to", "reached_td"]
    choices = "".join(f"{letter}. '{name}': Synthetic definition.\n" for letter, name in zip("ABCDE", names)) + "F. None of the above.\n"
    prompt = template.format(input_text=text, query_triplet=triple, query_relation=triple[1], query_relation_definition="Synthetic relation.", choices=choices)
    return {"stage": "canon", "asked_max_tokens": 1, "messages": [{"role": "user", "content": prompt}],
            "content": answer, "finish_reason": "length" if len(answer) > 1 else "stop"}


def synthetic_run(root, docs, specifications, *, level="A4", verifier_normalization=False):
    """Write invented contracts with controllable extraction/canon/export paths."""
    run = root / "run"; run.mkdir(parents=True, exist_ok=True)
    chunks = [{"chunk_id": d["doc_id"] + "#c000", "doc_id": d["doc_id"], "idx": 0, "char_start": 0,
               "char_end": len(d["text"]), "text": d["text"]} for d in docs]
    candidates, canonical, statements, rejected, entities, calls, mentions = [], [], [], [], [], [], []
    items, responses = {}, {}
    for i, spec in enumerate(specifications):
        doc = next(d for d in docs if d["doc_id"] == spec.get("doc", docs[0]["doc_id"]))
        chunk = doc["doc_id"] + "#c000"
        for value in spec.get("mentions", []): mentions.append({"chunk_id": chunk, "surface": value})
        if spec.get("missing"): continue
        cid = spec.get("cid", f"c_{i:03}")
        subject, predicate, obj = spec.get("triple", ["CIBP", "set at", "9,500'"])
        ev = {"doc_id": doc["doc_id"], "chunk_id": chunk, "char_start": 0, "char_end": len(doc["text"]), "text": doc["text"], "grounding": "exact"}
        candidate = {"candidate_id": cid, "chunk_id": chunk, "source_doc_id": doc["doc_id"], "subject": subject,
                     "predicate": predicate, "object": obj, "extractor": spec.get("extractor", "kggen"),
                     "extractor_version": "synthetic", "evidence": ev, "trigger_relation": None}
        candidates.append(candidate)
        branch = spec.get("branch", "verified")
        target = spec.get("relation", "set_plug_at")
        mapped = branch not in {"no_call", "edc_undefined"} and spec.get("mapped", True)
        if level == "A0": mapped, target = True, predicate
        if level != "A0":
            triple = [subject, predicate, obj]
            items.setdefault(chunk, {"key": chunk, "text": doc["text"], "triples": []})["triples"].append(triple)
            result = {"canonical": [subject, target, obj] if mapped else None, "candidates": {target: .8} if branch == "verified" else {}}
            if branch == "schema_short_circuit": result["canonical"] = triple
            if branch == "edc_undefined": result["reason"] = "edc_undefined"
            responses.setdefault(chunk, {"key": chunk, "definitions": {}, "results": []})["results"].append(result)
            if branch == "verified": calls.append(render_verify(doc["text"], triple, spec.get("answer", "A" if mapped else "F"), target))
        if not mapped:
            rejected.append({"kind": "candidate", "id": cid, "stage": "canon", "reasons": ["edc_undefined" if branch == "edc_undefined" else "edc_unmapped"], "record": candidate})
            continue
        resolved = spec.get("resolved", obj)
        source = "inverse" if spec.get("inverse") else "open" if level == "A0" else "schema"
        if spec.get("inverse"): subject, resolved, target = obj, subject, spec["inverse"]
        entities.extend([{"entity_id": f"s{i}", "name": subject, "aliases": [], "kind": "entity", "mention_ids": [], "resolver": "synthetic"},
                         {"entity_id": f"o{i}", "name": resolved, "aliases": [], "kind": "entity", "mention_ids": [], "resolver": "synthetic"}])
        canonical.append({"candidate_id": cid, "predicate": target, "predicate_source": source, "subject_id": f"s{i}", "object_id": f"o{i}", "evidence": ev})
        statement = {"statement_id": f"statement_{i}", "subject_id": f"s{i}", "object_id": f"o{i}", "predicate": target,
                     "predicate_source": source, "source_doc_id": doc["doc_id"], "evidence_span": ev, "evidence": [ev],
                     "candidate_ids": [cid], "support_count": 1, "valid_from": None, "valid_to": None,
                     "extractor_version": "synthetic", "confidence": .9,
                     "status": "rejected" if spec.get("rejected") else "accepted",
                     "reasons": ["weak_evidence"] if spec.get("rejected") or spec.get("flagged") else []}
        if spec.get("rejected"): rejected.append({"kind": "statement", "id": statement["statement_id"], "stage": "validate", "reasons": statement["reasons"], "record": statement})
        else: statements.append(statement)
    graph = {"format": "kgb.graph/1", "run_name": "synthetic", "ablation": level, "flags": {}, "documents": docs,
             "chunks": chunks, "entities": entities, "statements": statements}
    write_json(run / "graph.json", graph)
    write_json(run / "graph_strict.json", {**graph, "statements": [s for s in statements if not s["reasons"]]})
    for name, rows in (("documents", docs), ("chunks", chunks), ("candidates", candidates), ("canonical", canonical),
                       ("entities", entities), ("statements", statements), ("mentions", mentions), ("rejected", rejected), ("llm_calls", calls)):
        write_jsonl(run / (name + ".jsonl"), rows)
    schema = PROJECT_ROOT / "contracts/ontology/bsee.yaml"
    write_json(run / "manifest.json", {"config": {"ablation": level, "canon": {"schema_path": "contracts/ontology/bsee.yaml", "verifier_normalize": verifier_normalization}}})
    if level != "A0" and items:
        write_edc_csv(load_schema(schema), run / "edc/schema.csv")
        write_json(run / "edc/request.json", {"enrich_schema": False, "items": list(items.values())})
        write_json(run / "edc/response.json", {"items": list(responses.values())})
    return run


def case(name, specifications, facts=None, *, level="A4", split="dev", verifier_normalization=False, config=TEST_CONFIG):
    root = clean_dir(PROJECT_ROOT / "runs/_test" / name)
    cfg = gold_fixture(complete=True, config=config)
    gold = cfg["root"]
    docs = [{"doc_id": "d", "text": "Set CIBP at 9,500'. Invented artifact text."}]
    corpus = root / "corpus"; corpus.mkdir()
    write_jsonl(corpus / "corpus.jsonl", docs)
    write_json(gold / "freeze.json", {"corpus_sha256": sha256_file(corpus / "corpus.jsonl"), **({"converter": "v2"} if config == TEST_CONFIG_V2 else {})})
    write_json(gold / "split.json", {"dev": ["d"] if split == "dev" else [], "test": ["d"] if split == "test" else [], "test_subset": ["d"]})
    for role in ("annotator_a", "annotator_b"):
        for path in (gold / "annotations" / role).glob("batch_*.jsonl"):
            path.unlink()
        write_jsonl(gold / "annotations" / role / "batch_01.jsonl", [{"record": "chunk", "format": "kgb.well_annotation/1",
                    "annotator": role, "chunk_id": "d#c000", "status": "no_facts", "n_facts": 0, "note": ""}])
    facts = facts if facts is not None else [fact("9500", "set_plug_at", subject={"text": "CIBP", "occ": 0, "type": "Plug"})]
    write_jsonl(gold / "adjudicated.jsonl", [{"record": "chunk", "chunk_id": "d#c000", "status": "annotated"}, *[f.model_dump() for f in facts]])
    run = synthetic_run(root, docs, specifications, level=level, verifier_normalization=verifier_normalization)
    return root, run, corpus, gold


def evaluate(paths, *, split="dev", export="full", name="out"):
    root, run, corpus, gold = paths
    return attribute(run, corpus, gold, load_well_eval(PROJECT_ROOT / "configs/experiments/bsee_eval.yaml").model_dump(), load_lexicon(LEXICON), split, export, root / name)


class WellAttributionTest(unittest.TestCase):
    def test_recall_v1_golden_bytes(self):
        paths = case("recall_v1_golden", [])
        result = evaluate(paths)
        self.assertNotIn("recall_diagnostics", result)
        self.assertNotIn("recall_triggers", result)
        fixture = json.loads((PROJECT_ROOT / "tests/fixtures/bsee_guided/attribution_expected.json").read_text())
        for name, entry in fixture.items():
            assert_expected_artifact(self, paths[0] / "out" / name, entry)

    def test_recall_sentence_labels_and_offsets(self):
        text = "Drilled to 100 ft successfully. Tested valve at 900 psi successfully. Set CIBP at 9,500'."
        start = text.index("Set CIBP")
        gold = fact("9500", "set_plug_at", subject={"text": "CIBP", "occ": 0, "type": "Plug"}, evidence={"text": text[start:], "occ": 0, "start": start, "end": len(text)})
        chunk = {"text": text, "char_start": 70}
        candidate = {"extractor": "guided", "predicate": "drilled_to", "evidence": {"char_start": 70, "char_end": 87}}
        expected = {"relation_absent": True, "sentence_silent": True, "multi_sentence": True, "chunk_abstained": False}
        self.assertEqual(_recall_labels(gold, chunk, [candidate]), expected)
        derived = {"extractor": "derived", "predicate": "set_plug_at", "evidence": {"char_start": 70, "char_end": 70 + len(text)}}
        self.assertEqual(_recall_labels(gold, chunk, [candidate, derived]), expected)
        self.assertEqual(_recall_labels(gold, chunk, [derived]), {**expected, "chunk_abstained": True})
        present = {**candidate, "predicate": "set_plug_at", "evidence": {"char_start": 70 + start, "char_end": 70 + len(text)}}
        self.assertFalse(_recall_labels(gold, chunk, [present])["sentence_silent"])
        self.assertFalse(_recall_labels(gold, chunk, [present])["relation_absent"])
        # Gold starts in whitespace: choose the sentence with greatest evidence overlap.
        between = gold.model_copy(update={"evidence": {"start": start - 1, "end": len(text)}})
        self.assertEqual(_recall_labels(between, chunk, [candidate]), expected)
        outside = gold.model_copy(update={"evidence": {"start": len(text) + 1, "end": len(text) + 2}})
        self.assertFalse(_recall_labels(outside, chunk, [candidate])["sentence_silent"])
        with patch("kgbuilder.evaluation.well_attribution.split_sentences_abbrev", return_value=[]):
            labels = _recall_labels(gold, chunk, [])
            self.assertTrue(labels["sentence_silent"])
            self.assertFalse(labels["multi_sentence"])

    def test_recall_synthetic_fixture_and_test_privacy(self):
        paths = case("recall_attribution_fixture", [], config=TEST_CONFIG_V2)
        fixture = PROJECT_ROOT / "tests/fixtures/bsee_recall/attribution"
        shutil.copytree(fixture, paths[1], dirs_exist_ok=True)
        docs = read_jsonl(paths[1] / "documents.jsonl")
        write_jsonl(paths[2] / "corpus.jsonl", docs)
        write_json(paths[3] / "freeze.json", {"corpus_sha256": sha256_file(paths[2] / "corpus.jsonl"), "converter": "v2"})
        text = docs[0]["text"]
        start = text.index("Set CIBP")
        gold = fact("9500", "set_plug_at", subject={"text": "CIBP", "occ": 0, "type": "Plug"},
                    evidence={"text": text[start:], "occ": 0, "start": start, "end": len(text)})
        write_jsonl(paths[3] / "adjudicated.jsonl", [{"record": "chunk", "chunk_id": "d#c000", "status": "annotated"}, gold.model_dump()])
        result = evaluate(paths)
        row = read_jsonl(paths[0] / "out/per_fact.jsonl")[0]
        self.assertEqual(row["stage"], "extract_missed")
        self.assertTrue(row["relation_absent"] and row["sentence_silent"] and row["multi_sentence"])
        self.assertFalse(row["chunk_abstained"])
        self.assertEqual(result["recall_diagnostics"]["extract_missed"]["sentence_silent"]["true"], 1)
        self.assertEqual(result["recall_triggers"]["guided_windows"]["n"], 1)
        strict = evaluate(paths, export="strict", name="strict")
        self.assertIn("recall_diagnostics", strict)
        self.assertNotIn("recall_triggers", strict)
        write_json(paths[3] / "split.json", {"dev": [], "test": ["d"], "test_subset": ["d"]})
        result = evaluate(paths, split="test", name="test")
        self.assertNotIn("recall_diagnostics", result)
        self.assertNotIn("recall_triggers", result)
        self.assertFalse((paths[0] / "test/per_fact.jsonl").exists())
        for path in (paths[0] / "test").iterdir():
            for value in ("CIBP", "9,500", "d#c000", text):
                self.assertNotIn(value, path.read_text())
        # Empty chunk: all three absence labels true.
        paths = case("recall_abstained", [], config=TEST_CONFIG_V2,
                     facts=[gold.model_copy(update={"evidence": {"text": "Set CIBP at 9,500\'.", "occ": 0, "start": 0, "end": 18}})])
        evaluate(paths)
        row = read_jsonl(paths[0] / "out/per_fact.jsonl")[0]
        self.assertTrue(all(row[key] for key in ("relation_absent", "sentence_silent", "chunk_abstained")))

    def test_recall_trigger_thresholds_and_chunk_minimum(self):
        rows = [{"chunk_id": str(i), "stage": "extract_missed", "relation": "set_plug_at",
                 "sentence_silent": True, "multi_sentence": True, "relation_absent": True} for i in range(3)]
        rows += [{"chunk_id": str(i), "stage": "canon_dropped", "relation": "casing_size", "tubular_head": True} for i in range(3)]
        stats = {"n_gplus": 12, "stages": dict.fromkeys(STAGES, 0)}
        stats["stages"]["tp_L3"] = 1
        result = recall_triggers(rows, stats)
        self.assertEqual(result["n_fn"], 11)
        for name in ("guided_windows", "guided_groups", "guided_recall", "derived_casing_size"):
            self.assertEqual(result[name], {"n": 3, "chunks": 3, "threshold": 3, "fired": True})
        self.assertFalse(recall_triggers([{**r, "chunk_id": "one"} for r in rows], stats)["guided_recall"]["fired"])
        self.assertFalse(recall_triggers(rows, {**stats, "n_gplus": 14})["guided_windows"]["fired"])
        excluded = [{**r, "sentence_silent": False, "relation_absent": False, "tubular_head": False} for r in rows]
        result = recall_triggers(excluded, stats)
        self.assertEqual([result[k]["n"] for k in ("guided_windows", "guided_groups", "guided_recall", "derived_casing_size")], [0, 0, 3, 0])

    def test_v2_c1_c3_and_subject_matching(self):
        examples = [
            (["CIBP", "set_plug_at", "CIBP at 9,500'"],
             fact("9500", "set_plug_at", subject={"text": "CIBP", "occ": 0, "type": "Plug"}), "convert_unparsed", "tp_L3"),
            (["well", "set_plug_at", "CIBP at 9,500'"],
             fact("9500", "set_plug_at", subject={"text": "CIBP", "occ": 0, "type": "Plug"}), "convert_unparsed", "tp_L2_only"),
            (["Hydraulic Choke", "tested_to_pressure", "250 psi low and 10,000 psi high"],
             fact(relation="tested_to_pressure", subject={"text": "Hydraulic Choke", "occ": 0, "type": "Equipment"},
                  object={"kind": "pressure", "text": "10,000 psi", "occ": 0, "value": "10000", "unit": "psi"}), "convert_mismatch", "tp_L3"),
        ]
        for index, (triple, gold_fact, old_stage, new_stage) in enumerate(examples):
            paths = case("recall_attr_" + str(index), [{"triple": triple, "relation": triple[1], "branch": "schema_short_circuit"}], [gold_fact])
            self.assertEqual(evaluate(paths)["stages"][old_stage], 1)
            freeze_path = paths[3] / "freeze.json"
            freeze = json.loads(freeze_path.read_text())
            write_json(freeze_path, {**freeze, "converter": "v2"})
            self.assertEqual(evaluate(paths, name="v2")["stages"][new_stage], 1)
            row = read_jsonl(paths[0] / "v2/per_fact.jsonl")[0]
            self.assertEqual(row["converted_kind"], gold_fact.object["kind"])
            if index == 2: self.assertEqual(row["converted_text"], "10,000 psi")

        pressure = fact(relation="tested_to_pressure", subject={"text": "Hydraulic Choke", "occ": 0, "type": "Equipment"},
                        object={"kind": "pressure", "text": "1000 psi", "occ": 0, "value": "1000", "unit": "psi"})
        paths = case("recall_attr_tolerance", [{"triple": ["Hydraulic Choke", "tested_to_pressure", "100 psi low and 990 psi high"],
                                            "relation": "tested_to_pressure", "branch": "schema_short_circuit"}], [pressure])
        freeze_path = paths[3] / "freeze.json"
        write_json(freeze_path, {**json.loads(freeze_path.read_text()), "converter": "v2"})
        self.assertEqual(evaluate(paths)["stages"]["tp_L3"], 1)
        self.assertEqual(read_jsonl(paths[0] / "out/per_fact.jsonl")[0]["converted_text"], "990 psi")

    def test_all_partitions_unreadable_and_score_crosscheck(self):
        from kgbuilder.core.well_facts import score
        from kgbuilder.evaluation.well_eval import evaluate_wells
        positive = fact("9500", "set_plug_at", subject={"text": "CIBP", "occ": 0, "type": "Plug"})
        facts = [positive, positive.model_copy(update={"fact_no": 2, "uncertainty": "uncertain"}),
                 positive.model_copy(update={"fact_no": 3, "polarity": "negative"}),
                 positive.model_copy(update={"fact_no": 4, "relation": "other", "other_label": "invented_relation"})]
        paths = case("guided_partitions", [{}, {"cid": "c_010", "triple": ["well", "was set", "CIBP at 9,500'"]}], facts)
        result = evaluate(paths)
        policy = load_well_eval(PROJECT_ROOT / "configs/experiments/bsee_eval.yaml")
        evaluated = evaluate_wells(paths[1], paths[2], policy, paths[0] / "eval", None, None, paths[3], None, split="dev")
        for level in ("L1", "L2", "L3"):
            self.assertEqual(result["scores"][level], {k: evaluated["exports"]["full"]["ai_gold"][level][k] for k in ("tp", "fp", "fn")})
        self.assertEqual(result["n_gplus"], 1)
        def wrong_score(*args):
            actual = score(*args)
            actual["L1"]["tp"] += 1
            return actual
        with patch("kgbuilder.evaluation.well_attribution.well_facts.score", side_effect=wrong_score):
            with self.assertRaisesRegex(KgbError, "attribution invariant: L1 TP"): evaluate(paths, name="bad_score")
        records = read_jsonl(paths[3] / "adjudicated.jsonl"); records[0]["status"] = "unreadable"
        write_jsonl(paths[3] / "adjudicated.jsonl", records)
        empty = evaluate(paths, name="unreadable")
        self.assertEqual((empty["n_chunks"], empty["n_gplus"], empty["predictions"]["n"]), (0, 0, 0))

    def test_furthest_path_a0_and_ambiguous_mechanisms(self):
        paths = case("guided_furthest", [{"mapped": False}, {"cid": "c_010", "triple": ["well", "set at", "CIBP at 9,500'"]}])
        self.assertEqual(evaluate(paths)["stages"]["convert_unparsed"], 1)
        row = read_jsonl(paths[0] / "out/per_fact.jsonl")[0]
        self.assertEqual(row["best_carrier"]["candidate_id"], "c_010")
        paths = case("guided_a0", [{}], level="A0")
        result = evaluate(paths)
        self.assertEqual(result["stages"]["tp_L1_only"], 1)
        self.assertEqual(result["sub"]["tp_L1_only"]["reason"]["open_predicate"], 1)
        self.assertEqual(result["canon"]["sent"], 0)
        paths = case("guided_ambiguous", [{"triple": ["well", "set at", "CIBP at 9,500' and 9,800'"]}])
        evaluate(paths)
        row = read_jsonl(paths[0] / "out/per_fact.jsonl")[0]
        self.assertTrue(row["relation_accepts_gold_kind"])
        self.assertFalse(row["typed_unique"])

    def test_stages_and_mechanisms(self):
        cases = [({}, "tp_L3"), ({"triple": ["unrelated subject", "set at", "9,500'"]}, "tp_L2_only"),
                 ({"relation": "tagged_at"}, "tp_L1_only"), ({"triple": ["CIBP", "set at", "9500 m"]}, "convert_mismatch"),
                 ({"triple": ["well", "set at", "CIBP at 9,500'"]}, "convert_unparsed"),
                 ({"rejected": True}, "validate_rejected"), ({"resolved": "other entity"}, "resolve_changed"),
                 ({"mapped": False}, "canon_dropped"), ({"triple": ["CIBP at 9,500'", "is", "plug"]}, "extract_wrong_slot"),
                 ({"missing": True, "mentions": ["9,500'"]}, "extract_entity_only"), ({"missing": True}, "extract_missed")]
        for spec, expected in cases:
            with self.subTest(stage=expected):
                paths = case("guided_stage_" + expected, [spec])
                result = evaluate(paths)
                self.assertEqual(result["stages"][expected], 1)
                self.assertEqual(sum(result["stages"].values()), 1)
                row = read_jsonl(paths[0] / "out/per_fact.jsonl")[0]
                if expected == "convert_unparsed":
                    self.assertTrue(row["relation_accepts_gold_kind"])
                    self.assertTrue(row["typed_unique"])
                if expected == "canon_dropped":
                    self.assertTrue(row["fallback_ok"])
                    self.assertEqual(row["sub"]["gold_relation_retrieved"], "true")
        paths = case("guided_stage_strict", [{"flagged": True}])
        self.assertEqual(evaluate(paths, export="strict")["stages"]["export_excluded"], 1)
        f = fact("9500", "set_plug_at", subject={"text": "CIBP", "occ": 0, "type": "Plug"})
        paths = case("guided_stage_assignment", [{}], [f, f.model_copy(update={"fact_no": 2})])
        result = evaluate(paths)
        self.assertEqual(result["stages"]["match_lost"], 1)
        self.assertEqual(result["stages"]["tp_L3"], 1)

    def test_verifier_branches_and_self_checks(self):
        for branch in ("schema_short_circuit", "edc_undefined", "no_call", "verified"):
            spec = {"branch": branch}
            if branch == "schema_short_circuit": spec["triple"] = ["CIBP", "set_plug_at", "9,500'"]
            paths = case("guided_branch_" + branch, [spec])
            result = evaluate(paths)
            self.assertEqual(result["verifier"]["branches"][branch], 1)
            if branch == "schema_short_circuit":
                self.assertEqual(result["stages"]["tp_L3"], 1)
                self.assertEqual(result["verifier"]["raw"][branch], 1)
                self.assertEqual(result["verifier"]["effective"][branch], 1)
            response_path = paths[1] / "edc/response.json"
            response = json.loads(response_path.read_text())
            response["items"][0]["results"][0]["canonical"] = None if branch in {"schema_short_circuit", "verified"} else ["CIBP", "set_plug_at", "9,500'"]
            write_json(response_path, response)
            with self.assertRaisesRegex(KgbError, "verifier reconstruction failed: " + branch): evaluate(paths, name="bad")
        paths = case("guided_short_extra_verify", [{"branch": "schema_short_circuit", "triple": ["CIBP", "set_plug_at", "9,500'"]}])
        req = json.loads((paths[1] / "edc/request.json").read_text())["items"][0]
        write_jsonl(paths[1] / "llm_calls.jsonl", [render_verify(req["text"], req["triples"][0])])
        with self.assertRaisesRegex(KgbError, "schema_short_circuit"): evaluate(paths)
        paths = case("guided_verified_none_mapped", [{"answer": "F"}])
        with self.assertRaisesRegex(KgbError, "verifier reconstruction failed: verified"): evaluate(paths)
        paths = case("guided_missing_verify", [{}])
        write_jsonl(paths[1] / "llm_calls.jsonl", [])
        with self.assertRaisesRegex(KgbError, "verifier reconstruction failed: verified"): evaluate(paths)

    def test_normalized_answers_and_truncation(self):
        for answer, fixable in ((" C", True), ("F", False)):
            paths = case("guided_verifier_answer", [{"answer": answer, "mapped": False}])
            result = evaluate(paths)
            row = read_jsonl(paths[0] / "out/per_fact.jsonl")[0]
            self.assertEqual(row["verifier_fixable"], fixable)
            if fixable:
                self.assertEqual(row["sub"]["verifier"], "unparsed")
                self.assertEqual(result["truncation"]["verify_raw"]["unparsed"], 1)
        paths = case("guided_normalized_on", [{"answer": " A"}], verifier_normalization=True)
        result = evaluate(paths)
        self.assertEqual(result["verifier"]["raw"]["unparsed"], 1)
        self.assertEqual(result["verifier"]["effective"]["choice"], 1)
        paths = case("guided_choice_word", [{"answer": "Answer: C"}])
        self.assertEqual(evaluate(paths)["verifier"]["choice_word"], 1)

    def test_reconstruction_and_target_schema(self):
        paths = case("guided_reconstruction", [{}])
        path = paths[1] / "edc/request.json"
        request = json.loads(path.read_text()); request["items"][0]["triples"][0][0] = "different"
        write_json(path, request)
        with self.assertRaisesRegex(KgbError, "edc mapping reconstruction failed"): evaluate(paths)
        request["enrich_schema"] = True; write_json(path, request)
        with self.assertRaisesRegex(ConfigError, "attribution needs a target-schema run"): evaluate(paths)
        paths = case("guided_mapped_predicate", [{}])
        rows = read_jsonl(paths[1] / "canonical.jsonl"); rows[0]["predicate"] = "wrong"
        write_jsonl(paths[1] / "canonical.jsonl", rows)
        with self.assertRaisesRegex(KgbError, "edc mapping reconstruction failed"): evaluate(paths)

    def test_mechanism_scope_and_tubular(self):
        paths = case("guided_wrong_relation", [{"triple": ["well", "completed", "CIBP at 9,500'"], "relation": "completed_in"}])
        evaluate(paths)
        row = read_jsonl(paths[0] / "out/per_fact.jsonl")[0]
        self.assertEqual(row["stage"], "convert_unparsed")
        self.assertFalse(row["relation_accepts_gold_kind"])
        self.assertFalse(row["typed_unique"])
        f = fact("9500").model_copy(update={"relation": "casing_size", "subject": {"text": '9-5/8" casing', "occ": 0, "type": "Tubular"},
                    "object": {"kind": "size", "text": '9-5/8"', "occ": 0, "value": "9.625", "unit": "in"}})
        paths = case("guided_tubular", [{"triple": ['9-5/8" casing', "cut at", "1,200'"], "relation": "cut_at"}], [f])
        evaluate(paths)
        row = read_jsonl(paths[0] / "out/per_fact.jsonl")[0]
        self.assertEqual(row["stage"], "extract_wrong_slot")
        self.assertTrue(row["tubular_head"])

    def test_test_privacy_test_subset_and_scope_guards(self):
        paths = case("guided_privacy", [{}], split="test")
        result = evaluate(paths, split="test")
        self.assertNotIn("per_chunk", result)
        self.assertIsNone(result["triggers"])
        self.assertFalse((paths[0] / "out/per_fact.jsonl").exists())
        for path in (paths[0] / "out").iterdir():
            text = path.read_text()
            for forbidden in ("CIBP", "9,500", "d#c000", "Invented artifact text"):
                self.assertNotIn(forbidden, text)
        write_json(paths[3] / "split.json", {"dev": [], "test": ["d"], "test_subset": []})
        with self.assertRaisesRegex(ConfigError, "run scope outside test_subset"): evaluate(paths, split="test", name="reserved")
        with self.assertRaisesRegex(ConfigError, "run scope outside dev split"): evaluate(paths, name="wrong_dev")

    def test_request_order_and_carries(self):
        values = [{"chunk_id": chunk, "candidate_id": cid, "extractor": extractor, "trigger_relation": None}
                  for chunk, cid, extractor in (("b", "z", "kggen"), ("a", "z", "edc"), ("a", "b", "kggen"), ("a", "a", "edc"), ("b", "a", "kggen"), ("c", "z", "guided"), ("c", "a", "guided"), ("c", "b", "derived"))]
        self.assertEqual([v["candidate_id"] for v in sorted(values, key=request_key)],
                         [v.candidate_id for v in request_order([SimpleNamespace(**v) for v in values])])
        self.assertEqual([v["candidate_id"] for v in sorted(values, key=request_key) if v["extractor"] == "guided"], ["a", "z"])
        self.assertTrue(carries("13202'-24'", {"kind": "interval", "lower": "13202", "upper": "13224"}, {}))
        self.assertTrue(carries('9-5/8" casing', {"kind": "size", "value": "9.625"}, {}))
        self.assertTrue(carries("Aster reservoir", {"kind": "entity", "text": "Aster sand"}, {}))
        self.assertFalse(carries("sand", {"kind": "entity", "text": "sand"}, {}))
        self.assertTrue(carries("TA'd", {"kind": "status", "text": "TA'd", "value": "TA"}, {}))
        self.assertTrue(carries("on 3/14/2011", {"kind": "date", "iso": "2011-03-14", "precision": "day"}, {}))
        self.assertTrue(carries("at 1001 m", {"kind": "depth", "value": "1000"}, {"tolerance": {"depth_ft": 1}}))
        self.assertFalse(carries("at 1002 ft", {"kind": "depth", "value": "1000"}, {"tolerance": {"depth_ft": 1}}))

    def test_trigger_mechanisms(self):
        rows = []
        for i in range(3):
            for stage, mechanism in (("canon_dropped", "verifier_fixable"), ("canon_dropped", "fallback_ok"),
                                     ("convert_unparsed", "typed_unique"), ("extract_wrong_slot", "tubular_head")):
                rows.append({"chunk_id": str(i), "stage": stage, "relation": "casing_size", "verifier_fixable": False,
                             "fallback_ok": False, "typed_unique": False, "relation_accepts_gold_kind": True, "tubular_head": False, mechanism: True})
        rows.append({**rows[-2], "typed_unique": False, "chunk_id": "other"})
        stages = {s: sum(r["stage"] == s for r in rows) for s in STAGES}
        result = triggers({"n_gplus": len(rows), "stages": stages, "per_fact": rows})
        self.assertTrue(all(result[k]["fired"] for k in ("verifier_normalization", "canon_fallback", "typed_literals", "derived_casing_size", "guided_extraction")))
        self.assertEqual(result["typed_literals"]["n"], 3)
        self.assertEqual(result["guided_extraction"]["threshold"], 4)

    def test_committed_short_circuit_fixture(self):
        paths = case("guided_static_fixture", [])
        shutil.copytree(FIXTURE, paths[1], dirs_exist_ok=True)
        result = evaluate(paths)
        self.assertEqual(result["verifier"]["branches"], {k: 1 for k in ("schema_short_circuit", "edc_undefined", "no_call", "verified")})
        self.assertEqual(result["stages"]["tp_L3"], 1)
