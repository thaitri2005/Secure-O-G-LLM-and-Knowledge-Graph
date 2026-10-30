"""Synthetic freeze, validation, immutable seals and canonical protocol copies."""
from __future__ import annotations

import json
import re
import shutil
import unittest
from unittest.mock import patch

import yaml

from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.core.config import ConfigError
from kgbuilder.core.text import iter_jsonl, sha256_file, write_json, write_jsonl
from kgbuilder.core.well_facts import AnnotationFacts, resolve_fact
from kgbuilder.evaluation import well_gold
from kgbuilder.evaluation.well_rules import annotate


TEST_CONFIG = PROJECT_ROOT / "tests/fixtures/bsee/gold_cases/bsee_gold_test.yaml"
TEST_CONFIG_V2 = PROJECT_ROOT / "tests/fixtures/bsee_recall/gold_cases/bsee_gold_test_v2.yaml"
FIXTURE = PROJECT_ROOT / "tests/fixtures/bsee/gold_cases/sealed"


def rule_prediction_fixture(name):
    root = clean_dir(PROJECT_ROOT / "runs/_test" / name)
    text = "Scheduled to test tubing to 1200 psi."
    predicted = annotate("d", "d#c000", text)
    assert len(predicted) == 1 and predicted[0].modality == "planned"
    status = {"record": "chunk", "format": "kgb.well_annotation/1", "annotator": "adjudicated", "chunk_id": "d#c000",
              "status": "annotated", "n_facts": 1, "note": ""}
    gold, rules, corpus = root / "gold", root / "rules", root / "corpus"
    for path in (gold, rules, corpus): path.mkdir()
    write_jsonl(corpus / "corpus.jsonl", [{"doc_id": "d", "text": text}])
    write_json(gold / "freeze.json", {"corpus_sha256": sha256_file(corpus / "corpus.jsonl")})
    write_json(gold / "split.json", {"dev": [], "test": ["d"]})
    write_jsonl(rules / "rules.jsonl", [p.model_dump() for p in predicted])
    return root, gold, rules, corpus, text, status, predicted[0]


def gold_fixture(complete=False, merged=True, *, config=TEST_CONFIG):
    cfg = well_gold.load_config(config)
    root = clean_dir(cfg["root"])
    forbidden = PROJECT_ROOT / "runs/_test/bsee_gold_forbidden"
    if forbidden.exists(): shutil.rmtree(forbidden)
    shutil.copytree(FIXTURE / "protocol", root / "protocol")
    shutil.copytree(FIXTURE / "corpus", root / "corpus")
    well_gold.prepare(cfg, root / "corpus")
    shutil.copytree(FIXTURE / "annotations", root / "annotations")
    if complete:
        for role in cfg["annotators"]: well_gold.seal(cfg, role)
        well_gold.adjudication_packet(cfg)
        shutil.copytree(FIXTURE / "adjudication", root / "adjudication", dirs_exist_ok=True)
        well_gold.seal(cfg, "adjudicator")
        if merged: well_gold.merge(cfg)
    return cfg


def amendment_fixture(dates=False, both=False):
    """Build isolated synthetic archives; no real gold data is read."""
    base = clean_dir(PROJECT_ROOT / "runs/_test/bsee_gold_amend")
    config = yaml.safe_load(TEST_CONFIG.read_text(encoding="utf-8"))
    config["root"] = "runs/_test/bsee_gold_amend/root"
    config["frozen_inputs"].append("runs/_test/bsee_gold_amend/probe.txt")
    (base / "probe.txt").write_text("before\n", encoding="utf-8")
    config_path = base / "bsee_gold_amend.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    cfg = well_gold.load_config(config_path); root = cfg["root"]
    for name in config["forbidden_before_seal"]:
        path = PROJECT_ROOT / name
        if path.is_dir(): shutil.rmtree(path)
        elif path.exists(): path.unlink()
    shutil.copytree(FIXTURE / "protocol", root / "protocol")
    shutil.copytree(FIXTURE / "corpus", root / "corpus")
    if dates:
        docs = [{"doc_id": f"synthetic_date_{i}", "text": "Spudded on 3-14-2011."} for i in range(2)]
        write_jsonl(root / "corpus/corpus.jsonl", docs)
        write_json(root / "corpus/selection.json", {"dev": [docs[0]["doc_id"]], "test": [docs[1]["doc_id"]],
                                                    "corpus_sha256": sha256_file(root / "corpus/corpus.jsonl")})
    well_gold.prepare(cfg, root / "corpus")
    if dates:
        for name, packet in well_gold._packets(cfg).items():
            rows = []
            for chunk in packet:
                rows.append({"record": "chunk", "format": "kgb.well_annotation/1", "annotator": "annotator_a", "chunk_id": chunk["chunk_id"],
                             "status": "annotated", "n_facts": 1, "note": ""})
                slot = {"text": "3-14-2011", "occ": 0, "iso": None, "precision": "partial"}
                rows.append({"record": "fact", "format": "kgb.well_annotation/1", "annotator": "annotator_a", "chunk_id": chunk["chunk_id"],
                             "fact_no": 1, "relation": "spudded_on", "subject": {"implicit": "report_well", "type": "Borehole"},
                             "object": {"kind": "date", **slot}, "time": dict(slot) if both else None, "qualifiers": {},
                             "polarity": "positive", "modality": "done", "uncertainty": "certain", "note": "",
                             "evidence": {"text": chunk["text"], "occ": 0}})
            write_jsonl(root / "annotations/annotator_a" / name, rows)
        from kgbuilder.core.well_values import parse_us_date
        def slash_only(text): return (None, "partial") if "-" in text else parse_us_date(text)
        with patch("kgbuilder.core.well_facts.parse_us_date", side_effect=slash_only): well_gold.seal(cfg, "annotator_a")
    else:
        shutil.copytree(FIXTURE / "annotations", root / "annotations")
        well_gold.seal(cfg, "annotator_a")
    return cfg, config_path, base / "probe.txt"


def post_amendment_fixture(chain=False):
    cfg, config, probe = amendment_fixture()
    if chain:
        probe.write_text("amendment one\n", encoding="utf-8")
        well_gold.amend(cfg, "Synthetic pre-adjudication change")
        well_gold.seal(cfg, "annotator_a")
    well_gold.seal(cfg, "annotator_b")
    well_gold.adjudication_packet(cfg)
    shutil.copytree(FIXTURE / "adjudication", cfg["root"] / "adjudication", dirs_exist_ok=True)
    well_gold.seal(cfg, "adjudicator")
    return cfg, config, probe


PRECHANGE_FREEZE = {'annotators': ['annotator_a', 'annotator_b'], 'batch_size': 2, 'checked_absent': ['runs/_test/bsee_gold_forbidden'], 'corpus_sha256': '1138028f8ba190d9f8e997477f4d55568aed60e561c217920a04527e55ba87ed', 'format': 'kgb.well_freeze/1', 'frozen_inputs': {'configs/experiments/bsee_eval.yaml': 'a61486118b88a458c04b0390d344a8222c71ed93c1b1e345df5e9c5472fe760d', 'contracts/ontology/bsee.yaml': '8b35dc56ba8e4e87f7f81ed2b8f5354ff0c2afa7d517cbf18809507365d699c3', 'src/kgbuilder/core/well_facts.py': '3ac287f526fa521824bad11375b3fc0977e867841af5e724e695c8ff914a11e8', 'src/kgbuilder/core/well_values.py': 'bdc1be14eb09a39d4564290a852b8672f3889aa69bb59156816e9d0e74c6be8b', 'src/kgbuilder/evaluation/well_rules.py': 'd198a854f83992a838f90b6ec714cda3940b618a2f90ee37eaa7c308049d3518'}, 'n_dev': 1, 'n_gold': 3, 'n_test': 2, 'packets': {'packets/batch_01.jsonl': '128accad3f5e34f8b6e27cf8bc59add4e1dc62d542598cadb44c95fceb4c7f26', 'packets/batch_02.jsonl': '4ff5843fe7ab6c03f168d12f96010e7fdd7a0f915dff46bbcbff07e141be8889'}, 'protocol': {'protocol/guideline.md': 'd4ec61199bc72beae966977dd96057daa151842bd00e04223dc6e6f54015dd0d'}, 'seed': 42, 'split_sha256': '130e74185e4d7e52a3e21a86b1c12e381ff9c091721d86397f911dd68e3f1f97', 'statement': 'no system, silver or rule output on real data existed at freeze'}


class WellGoldTest(unittest.TestCase):
    def publication_fixture(self):
        cfg = gold_fixture(complete=True)
        root = cfg["root"]
        (root / "freeze.json").unlink()
        shutil.rmtree(root / "seals")
        return {**cfg, "forbidden_before_seal": []}

    def test_publication_preserves_labels_and_verifies(self):
        cfg = self.publication_fixture()
        root = cfg["root"]
        before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        result = well_gold.publish(cfg, root / "corpus")
        self.assertTrue(all(value == "OK" for value in result.values()))
        self.assertEqual(well_gold.verify(cfg), result)
        for name, content in before.items():
            self.assertEqual((root / name).read_bytes(), content)
        with self.assertRaisesRegex(ConfigError, "already exist"):
            well_gold.publish(cfg, root / "corpus")

    def test_publication_rejects_changed_labels_without_partial_seals(self):
        cfg = self.publication_fixture()
        root = cfg["root"]
        rows = list(iter_jsonl(root / "adjudicated.jsonl"))
        rows[0]["note"] = "Changed annotation"
        write_jsonl(root / "adjudicated.jsonl", rows)
        before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        with self.assertRaisesRegex(ConfigError, "differ from merged decisions"):
            well_gold.publish(cfg, root / "corpus")
        self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()})
        self.assertFalse((root / "freeze.json").exists())
        self.assertFalse((root / "seals").exists())

    def test_v2_guideline_transform(self):
        versions = [PROJECT_ROOT / "data/benchmarks/bsee_gold" / v for v in ("v1", "v2")]
        texts = [(root / "protocol/guideline.md").read_text(encoding="utf-8") for root in versions]
        def rules(text):
            tail = "\n".join(text.split("\n")[5:])
            return tail.replace("bsee_gold/v2/", "bsee_gold/v1/").replace("Each chunk of the v2 set", "Each chunk of the v1 set").replace("the v2 packets are EOR only", "the v1 packets are EOR only")
        self.assertEqual(rules(texts[0]), rules(texts[1]))

    def test_v2_protocol_copies(self):
        root = PROJECT_ROOT / "data/benchmarks/bsee_gold/v2"
        freeze = json.loads((root / "freeze.json").read_text())
        self.assertEqual(set(freeze["protocol"]), {"protocol/guideline.md"})
        self.assertEqual({p.name for p in (root / "protocol").iterdir()}, {"guideline.md"})
        self.assertEqual(sha256_file(root / "protocol/guideline.md"), freeze["protocol"]["protocol/guideline.md"])
        self.assertEqual(freeze["statement"], "re-sealed for publication; label content identical")

    def test_converter_config_and_freeze(self):
        cfg = gold_fixture()
        freeze = json.loads((cfg["root"] / "freeze.json").read_text())
        freeze.pop("created_at")
        self.assertEqual(freeze, PRECHANGE_FREEZE)
        cfg = gold_fixture(config=TEST_CONFIG_V2)
        self.assertEqual(well_gold._freeze(cfg)["converter"], "v2")
        with self.assertRaisesRegex(ConfigError, "gold freeze settings mismatch"):
            well_gold._freeze({k: v for k, v in cfg.items() if k != "converter"})
        root = clean_dir(PROJECT_ROOT / "runs/_test/recall_gold_config")
        raw = yaml.safe_load(TEST_CONFIG.read_text())
        malformed = [{**raw, "converter": value} for value in ("v1", "x", None)]
        malformed += [{**raw, "root": "data/benchmarks/bsee_gold/v1", "converter": "v2"},
                      {**raw, "root": "data/benchmarks/bsee_gold/v2"},
                      {**raw, "converter": "v2"}, {**raw, "root": "runs/_test"}, {**raw, "extra": True}]
        for body in malformed:
            path = root / "config.yaml"
            path.write_text(yaml.safe_dump(body), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "invalid gold configuration"): well_gold.load_config(path)

    def test_post_adjudication_date_flags_and_keep_time(self):
        cfg, _, probe = amendment_fixture(dates=True); root = cfg["root"]
        (root / "seals/annotator_a.json").unlink()
        for path in (root / "annotations/annotator_a").glob("*.jsonl"):
            rows = list(iter_jsonl(path))
            for row in rows:
                if row["record"] == "fact": row["object"].update(iso="2011-03-14", precision="day")
            annotator_b = [{**row, "annotator": "annotator_b"} for row in rows]
            write_jsonl(root / "annotations/annotator_b" / path.name, annotator_b)
            rows[1]["time"] = {k: v for k, v in rows[1]["object"].items() if k != "kind"}
            write_jsonl(path, rows)
        for role in cfg["annotators"]: well_gold.seal(cfg, role)
        well_gold.adjudication_packet(cfg)
        for path in (root / "adjudication").glob("packet_*.jsonl"):
            rows = [{"format": "kgb.well_adjudication/1", "record": "decision", "chunk_id": r["chunk_id"], "item_id": r["item_id"],
                     "decision": "keep", "fact": None, "citation": None, "rationale": "Synthetic agreement."} for r in iter_jsonl(path)]
            write_jsonl(path.with_name(path.name.replace("packet_", "decisions_")), rows)
        well_gold.seal(cfg, "adjudicator")
        probe.write_text("changed\n", encoding="utf-8")
        before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        with patch("kgbuilder.core.well_facts.parse_us_date", return_value=(None, "partial")):
            with self.assertRaises(ConfigError) as raised: well_gold.amend(cfg, "Synthetic date guard")
        message = str(raised.exception)
        self.assertIn("amendment guard: flagged locations", message)
        self.assertIn("annotations/annotator_a/batch_01.jsonl:2: object", message)
        self.assertNotIn("3-14-2011", message)
        self.assertNotIn("2011-03-14", message)
        self.assertEqual(before, {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()})
        well_gold.amend(cfg, "Synthetic accepted change")
        for role in cfg["annotators"]: well_gold.seal(cfg, role)
        well_gold.adjudication_packet(cfg); well_gold.seal(cfg, "adjudicator"); well_gold.merge(cfg)
        self.assertEqual(well_gold.agreement(cfg, root / "agreement", None)["keep_time_differs"], 1)

    def test_post_decision_scan_collects_all_locations(self):
        cfg, _, probe = post_amendment_fixture(); root = cfg["root"]
        probe.write_text("changed\n", encoding="utf-8")
        def invalid_citation(span, text): raise ValueError("Synthetic invalid citation")
        # Corrupt only synthetic decisions, then certify those bytes to isolate guard (c).
        path = root / "adjudication/decisions_01.jsonl"
        rows = list(iter_jsonl(path))
        for row in rows: row["citation"] = {"text": "Synthetic citation", "occ": 0}
        write_jsonl(path, rows)
        seal_path = root / "seals/adjudicator.json"; sealed = json.loads(seal_path.read_text())
        sealed["files"]["adjudication/decisions_01.jsonl"] = sha256_file(path); write_json(seal_path, sealed)
        with patch.object(well_gold, "resolve_span", side_effect=invalid_citation):
            with self.assertRaises(ConfigError) as raised: well_gold.amend(cfg, "Decision scan")
        for number in range(1, len(rows) + 1): self.assertIn(f"adjudication/decisions_01.jsonl:{number}: decision", str(raised.exception))
        self.assertNotIn("Synthetic citation", str(raised.exception))
        self.assertFalse((root / "amendments").exists())

    def test_post_adjudication_amendment_and_chain(self):
        cfg = gold_fixture(complete=True, merged=False)
        self.assertFalse((cfg["root"] / "adjudicated.jsonl").exists())
        for chain in (False, True):
            with self.subTest(chain=chain):
                cfg, _, probe = post_amendment_fixture(chain); root = cfg["root"]
                number = 2 if chain else 1
                before = {p.relative_to(root).as_posix(): p.read_bytes() for folder in ("packets", "annotations", "adjudication")
                          for p in (root / folder).rglob("*") if p.is_file()}
                outputs, key, counts = well_gold._build_adjudication(cfg)
                well_gold._packet_identity(cfg, outputs, key)
                probe.write_text("post-adjudication change\n", encoding="utf-8")
                result = well_gold.amend(cfg, "Synthetic post-adjudication amendment")
                self.assertEqual(result["state"], "post_adjudication")
                self.assertEqual(result["regenerated"], {"packets": "identical", "items": counts})
                self.assertEqual(set(result["superseded_seals"]), {"annotator_a", "annotator_b", "adjudication_packet", "adjudicator"})
                self.assertEqual(list((root / "seals").iterdir()), [])
                for name, data in before.items(): self.assertEqual((root / name).read_bytes(), data)
                self.assertEqual(well_gold.amend(cfg, "Same change")["status"], "no change")
                with self.assertRaises(ConfigError): well_gold.adjudication_packet(cfg)
                with self.assertRaises(ConfigError): well_gold.seal(cfg, "adjudicator")
                batch = root / "annotations/annotator_a/batch_01.jsonl"; saved = batch.read_bytes()
                batch.write_bytes(saved + b" ")
                with self.assertRaisesRegex(ConfigError, "annotations/annotator_a/batch_01.jsonl"): well_gold.seal(cfg, "annotator_a")
                batch.write_bytes(saved)
                well_gold.seal(cfg, "annotator_a")
                with self.assertRaises(ConfigError): well_gold.adjudication_packet(cfg)
                well_gold.seal(cfg, "annotator_b")
                recertified = well_gold.adjudication_packet(cfg)
                self.assertTrue(recertified["recertified"])
                self.assertEqual(recertified["items"], counts)
                well_gold.seal(cfg, "adjudicator")
                changes = well_gold._check_amendments(cfg)
                self.assertEqual([r["amendment"] for r in changes["annotator_a"]], list(range(1, number + 1)))
                self.assertEqual([r["amendment"] for r in changes["annotator_b"]], [number])
                self.assertEqual(changes["annotator_a"][-1]["changed"], 0)
                well_gold.merge(cfg)
                self.assertEqual(well_gold.verify(cfg)["amendments"], "OK")

    def test_post_adjudication_guards_write_nothing(self):
        for case in ("decision", "protocol", "policy", "merged", "missing_seal", "extra_adjudication", "extra_seal", "rank"):
            with self.subTest(case=case):
                cfg, _, probe = post_amendment_fixture(); root = cfg["root"]
                probe.write_text("changed\n", encoding="utf-8")
                if case in {"decision", "protocol"}:
                    path = root / ("adjudication/decisions_01.jsonl" if case == "decision" else "protocol/guideline.md")
                    path.write_bytes(path.read_bytes() + b" ")
                elif case == "policy":
                    source = next(p for p in cfg["frozen_inputs"] if p.endswith("bsee_eval.yaml"))
                    target = probe.parent / "bsee_eval.yaml"; target.write_bytes((PROJECT_ROOT / source).read_bytes())
                    replacement = target.relative_to(PROJECT_ROOT).as_posix()
                    cfg["frozen_inputs"] = [replacement if p == source else p for p in cfg["frozen_inputs"]]
                    # Rebuild only the synthetic freeze and its dependent seals before the edit.
                    freeze = json.loads((root / "freeze.json").read_text()); freeze["frozen_inputs"][replacement] = freeze["frozen_inputs"].pop(source)
                    write_json(root / "freeze.json", freeze)
                    for role in ("annotator_a", "annotator_b", "adjudication_packet", "adjudicator"):
                        path = root / "seals" / (role + ".json"); seal = json.loads(path.read_text())
                        seal["freeze_sha256"] = sha256_file(root / "freeze.json")
                        seal["dependencies"] = {name: sha256_file(root / name) for name in seal["dependencies"]}
                        write_json(path, seal)
                    target.write_bytes(target.read_bytes() + b" ")
                elif case == "merged": (root / "adjudicated.jsonl").write_text("synthetic")
                elif case == "missing_seal": (root / "seals/adjudicator.json").unlink()
                elif case == "extra_adjudication": (root / "adjudication/extra.txt").write_text("synthetic")
                elif case == "extra_seal": write_json(root / "seals/extra.json", {"role": "extra"})
                before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                from kgbuilder.core.well_facts import _level
                def changed(g, p, policy, symmetric=False): return min(_level(g, p, policy, symmetric=symmetric), 2)
                with patch("kgbuilder.core.well_facts._level", side_effect=changed if case == "rank" else _level):
                    with self.assertRaises(ConfigError) as raised: well_gold.amend(cfg, "Synthetic guard")
                if case == "rank":
                    self.assertIn("adjudication packets differ", str(raised.exception))
                    self.assertTrue(re.search(r"(?m)^[0-9a-f]{16}$", str(raised.exception)))
                if case in {"policy", "protocol"}: self.assertIn("post-adjudication scope", str(raised.exception))
                self.assertEqual(before, {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()})
                self.assertFalse((root / "amendments").exists())

    def test_post_adjudication_cleanup_and_pending_change(self):
        for alteration in (None, "adjudication"):
            cfg, _, probe = post_amendment_fixture(); root = cfg["root"]
            probe.write_text("changed\n", encoding="utf-8")
            well_gold.amend(cfg, "Synthetic post amendment")
            old = probe.read_bytes(); probe.write_text("another change\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "re-seal the superseded roles first"): well_gold.amend(cfg, "Pending")
            probe.write_bytes(old)
            shutil.copyfile(root / "amendments/001/superseded/seals/adjudicator.json", root / "seals/adjudicator.json")
            if alteration:
                path = root / "adjudication/decisions_01.jsonl"; path.write_bytes(path.read_bytes() + b" ")
                with self.assertRaisesRegex(ConfigError, "amendment integrity"): well_gold.amend(cfg, "Cleanup")
                self.assertTrue((root / "seals/adjudicator.json").exists())
            else:
                self.assertEqual(well_gold.amend(cfg, "Cleanup")["status"], "cleanup completed")
                self.assertFalse((root / "seals/adjudicator.json").exists())

    def test_at_depth_conflict_packet_is_partial(self):
        from unit.test_well_facts import fact
        cfg = gold_fixture()
        text = "FIT at 600 ft MD held 12 ppg; FIT at 600 ft TVD held 12 ppg."
        obj = {"kind": "density", "text": "12 ppg", "occ": 0, "value": "12", "unit": "ppg"}
        facts = {}
        for role, reference in (("annotator_a", "MD"), ("annotator_b", "TVD")):
            depth = {"text": "600 ft " + reference, "occ": 0, "value": "600", "unit": "ft", "reference": reference, "datum": "unknown"}
            facts[role] = [resolve_fact(fact(relation="fit_lot_emw", object=obj, qualifiers={"at_depth": depth},
                                            evidence={"text": text, "occ": 0}), text)]
        with patch.object(well_gold, "_packets", return_value={"batch_01.jsonl": [{"chunk_id": "d#c000", "text": text}]}), \
             patch.object(well_gold, "_annotations", side_effect=lambda _, role, **kwargs: facts[role]):
            result = well_gold.adjudication_packet(cfg)
        self.assertEqual(result["items"], {"partial": 1})

    def test_rules_predictions_exclude_nonassertions(self):
        root, gold, rules, _, text, status, planned = rule_prediction_fixture("bsee_gold_rule_predictions")
        empty = AnnotationFacts([], {"d#c000": {**status, "status": "no_facts", "n_facts": 0}})
        cfg = {"root": gold, "annotators": ["annotator_a", "annotator_b"]}
        for modality in ("planned", "done"):
            reference = planned.model_copy(update={"annotator": "adjudicated", "modality": modality})
            write_jsonl(gold / "adjudicated.jsonl", [status, reference.model_dump()])
            with patch.object(well_gold, "verify"), patch.object(well_gold, "_policy", return_value={}), \
                 patch.object(well_gold, "_annotations", return_value=empty), \
                 patch.object(well_gold, "_packets", return_value={"batch": [{"chunk_id": "d#c000", "text": text}]}):
                result = well_gold.agreement(cfg, root / modality, rules)["scopes"]["test"]["rules_vs_ai_gold"]
            self.assertEqual(result["excluded_predictions"], {"G-": 1})
            for level in ("L1", "L2", "L3"):
                row = result[level]
                self.assertEqual((row["tp"], row["fp"], row["asserted_nonasserted"]), (0, 0, 0))
                self.assertEqual(row["fn"], int(modality == "done"))
                self.assertIsNone(row["precision"])
                self.assertEqual(row["f1"], None if modality == "planned" else 0)
        asserted = planned.model_copy(update={"modality": "done"})
        write_jsonl(rules / "rules.jsonl", [planned.model_dump(), asserted.model_dump()])
        with patch.object(well_gold, "verify"), patch.object(well_gold, "_policy", return_value={}), \
             patch.object(well_gold, "_annotations", return_value=empty), \
             patch.object(well_gold, "_packets", return_value={"batch": [{"chunk_id": "d#c000", "text": text}]}):
            result = well_gold.agreement(cfg, root / "positive_rule", rules)["scopes"]["test"]["rules_vs_ai_gold"]
        self.assertEqual((result["L2"]["tp"], result["L2"]["fp"], result["L2"]["fn"]), (1, 0, 0))
        self.assertEqual(result["excluded_predictions"], {"G-": 1})

    def test_amendment_archive_and_complete_sequence(self):
        cfg, _, probe = amendment_fixture(); root = cfg["root"]
        old = (root / "freeze.json").read_bytes()
        old_hash = sha256_file(root / "freeze.json")
        inventory = {p.relative_to(root).as_posix(): p.read_bytes() for folder in ("packets", "annotations", "seals")
                     for p in (root / folder).rglob("*") if p.is_file()}
        split = (root / "split.json").read_bytes()
        probe.write_text("after\n", encoding="utf-8")
        result = well_gold.amend(cfg, "Synthetic input change")
        self.assertEqual(result["amendment"], 1)
        self.assertEqual((root / "amendments/001/previous_freeze.json").read_bytes(), old)
        self.assertEqual(sha256_file(root / "amendments/001/previous_freeze.json"), old_hash)
        self.assertEqual((root / "split.json").read_bytes(), split)
        for name, data in inventory.items():
            if name.startswith("seals/"):
                self.assertFalse((root / name).exists())
                self.assertEqual((root / "amendments/001/superseded" / name).read_bytes(), data)
            else: self.assertEqual((root / name).read_bytes(), data)
        frozen = (root / "freeze.json").read_bytes()
        self.assertEqual(well_gold.amend(cfg, "Same change")["status"], "no change")
        self.assertEqual((root / "freeze.json").read_bytes(), frozen)
        sealed = well_gold.seal(cfg, "annotator_a")
        self.assertEqual(sealed["amendment_changes"][0], {"amendment": 1, "flagged": 0, "changed": 0,
                         "changed_by_path": {}, "changed_by_relation": {}, "flagged_unchanged": 0})
        well_gold.seal(cfg, "annotator_b"); well_gold.adjudication_packet(cfg)
        shutil.copytree(FIXTURE / "adjudication", root / "adjudication", dirs_exist_ok=True)
        well_gold.seal(cfg, "adjudicator"); well_gold.merge(cfg)
        self.assertEqual(well_gold.verify(cfg)["amendments"], "OK")
        for name in ("record.json", "previous_freeze.json", "superseded/seals/annotator_a.json", "superseded/annotations/annotator_a/batch_01.jsonl"):
            path = root / "amendments/001" / name; saved = path.read_bytes()
            path.write_bytes(saved + b" ")
            with self.assertRaises(ConfigError): well_gold.verify(cfg)
            path.write_bytes(saved)

    def test_amendment_protocol_reuse_and_staging(self):
        cfg, _, _ = amendment_fixture(); root = cfg["root"]
        staging = root / "amendments/001.staging"; staging.mkdir(parents=True)
        (staging / "marker").write_text("keep", encoding="utf-8")
        before = {p.relative_to(root).as_posix(): sha256_file(p) for p in root.rglob("*") if p.is_file()}
        self.assertEqual(well_gold.amend(cfg, "No pending change")["status"], "no change")
        self.assertTrue(staging.is_dir())
        self.assertEqual(before, {p.relative_to(root).as_posix(): sha256_file(p) for p in root.rglob("*") if p.is_file()})
        (root / "protocol/guideline.md").write_text("Synthetic revised protocol\n", encoding="utf-8")
        (root / "protocol/prompt_x.md").write_text("Synthetic extra prompt\n", encoding="utf-8")
        result = well_gold.amend(cfg, "Protocol only")
        self.assertEqual(set(result["changed_protocol"]), {"protocol/guideline.md"})
        self.assertEqual(set(result["added_protocol"]), {"protocol/prompt_x.md"})
        self.assertEqual(result["changed_frozen_inputs"], {})
        self.assertEqual(len(result["abandoned"]), 1)
        self.assertEqual((root / result["abandoned"][0]["new"] / "marker").read_text(), "keep")
        self.assertEqual(well_gold.validate(cfg, "annotator_a")["present"], 2)
        well_gold.seal(cfg, "annotator_a")
        reseal = (root / "seals/annotator_a.json").read_bytes(); freeze = (root / "freeze.json").read_bytes()
        self.assertEqual(well_gold.amend(cfg, "No further change")["status"], "no change")
        self.assertEqual((root / "seals/annotator_a.json").read_bytes(), reseal)
        self.assertEqual((root / "freeze.json").read_bytes(), freeze)
        orphan = root / "amendments/002"; orphan.mkdir(); (orphan / "marker").write_text("orphan")
        (root / "protocol/prompt_x.md").write_text("Synthetic second revision\n", encoding="utf-8")
        result = well_gold.amend(cfg, "Second amendment")
        self.assertEqual(result["amendment"], 2)
        self.assertEqual(len(result["abandoned"]), 1)
        self.assertEqual((root / "amendments/002/superseded/seals/annotator_a.json").read_bytes(), reseal)
        self.assertEqual(well_gold._check_amendments(cfg)["annotator_a"][-1]["amendment"], 2)

    def test_amendment_guards_write_nothing(self):
        cases = ("blank", "multiline", "long", "adjudication", "packet_seal", "adjudicated", "forbidden", "packet",
                 "split", "input_inventory", "bad_seal", "unknown_seal_freeze", "protocol_removed", "annotation_inventory")
        for case in cases:
            with self.subTest(guard=case):
                cfg, _, probe = amendment_fixture(); root = cfg["root"]
                probe.write_text("after\n", encoding="utf-8")
                reason = "Synthetic guard"
                if case == "blank": reason = " "
                elif case == "multiline": reason = "two\nlines"
                elif case == "long": reason = "x" * 501
                elif case == "adjudication":
                    (root / "adjudication").mkdir(); (root / "adjudication/marker").write_text("synthetic")
                elif case == "packet_seal": write_json(root / "seals/adjudication_packet.json", {})
                elif case == "adjudicated": (root / "adjudicated.jsonl").write_text("synthetic")
                elif case == "forbidden": (PROJECT_ROOT / cfg["forbidden_before_seal"][0]).mkdir(parents=True)
                elif case in {"packet", "split", "bad_seal"}:
                    path = root / {"packet": "packets/batch_01.jsonl", "split": "split.json", "bad_seal": "annotations/annotator_a/batch_01.jsonl"}[case]
                    path.write_bytes(path.read_bytes() + b" ")
                elif case == "input_inventory": cfg["frozen_inputs"] = cfg["frozen_inputs"][:-1]
                elif case == "unknown_seal_freeze":
                    path = root / "seals/annotator_a.json"; value = json.loads(path.read_text()); value["freeze_sha256"] = "0" * 64; write_json(path, value)
                elif case == "protocol_removed": (root / "protocol/guideline.md").unlink()
                elif case == "annotation_inventory": (root / "annotations/annotator_b/batch_99.jsonl").write_text("synthetic")
                before = {p.relative_to(root).as_posix(): sha256_file(p) for p in root.rglob("*") if p.is_file()}
                with self.assertRaises(ConfigError): well_gold.amend(cfg, reason)
                self.assertEqual(before, {p.relative_to(root).as_posix(): sha256_file(p) for p in root.rglob("*") if p.is_file()})

    def test_amendment_crash_cleanup(self):
        for alteration in (None, "seal", "annotation", "packet", "archive"):
            with self.subTest(alteration=alteration):
                cfg, _, probe = amendment_fixture(); root = cfg["root"]
                probe.write_text("after\n", encoding="utf-8"); well_gold.amend(cfg, "Synthetic cleanup")
                archived = root / "amendments/001/superseded/seals/annotator_a.json"
                live = root / "seals/annotator_a.json"; shutil.copyfile(archived, live)
                if alteration:
                    path = {"seal": live, "annotation": root / "annotations/annotator_a/batch_01.jsonl",
                            "packet": root / "packets/batch_01.jsonl", "archive": archived}[alteration]
                    path.write_bytes(path.read_bytes() + b" ")
                    with self.assertRaises(ConfigError) as raised: well_gold.amend(cfg, "Synthetic cleanup")
                    if alteration in {"annotation", "archive"}: self.assertIn("amendment integrity", str(raised.exception))
                    self.assertTrue(live.exists())
                else:
                    self.assertEqual(well_gold.amend(cfg, "Synthetic cleanup")["status"], "cleanup completed")
                    self.assertFalse(live.exists())
                    self.assertEqual(well_gold._check_amendments(cfg)["annotator_a"][0]["changed"], 0)

    def test_amendment_flagged_slots_and_counts(self):
        cfg, _, probe = amendment_fixture(dates=True); root = cfg["root"]
        probe.write_text("after\n", encoding="utf-8")
        result = well_gold.amend(cfg, "Synthetic date correction")
        self.assertEqual(result["flagged"]["annotator_a"], ["annotations/annotator_a/batch_01.jsonl:2: object", "annotations/annotator_a/batch_01.jsonl:4: object"])
        path = root / "annotations/annotator_a/batch_01.jsonl"
        rows = list(iter_jsonl(path))
        rows[1]["object"].update(iso="2011-03-14", precision="day"); write_jsonl(path, rows)
        self.assertEqual(well_gold._check_amendments(cfg)["annotator_a"][0], {"amendment": 1, "flagged": 2, "changed": 1,
                         "changed_by_path": {"object": 1}, "changed_by_relation": {"spudded_on": 1}, "flagged_unchanged": 1})
        with self.assertRaises(ConfigError): well_gold.seal(cfg, "annotator_a")
        rows[3]["object"].update(iso="2011-03-14", precision="day"); write_jsonl(path, rows)
        for index, key in ((0, "note"), (1, "note")):
            edited = json.loads(json.dumps(rows)); edited[index][key] = "Unflagged change"; write_jsonl(path, edited)
            with self.assertRaisesRegex(ConfigError, f"batch_01.jsonl:{index + 1}"): well_gold.seal(cfg, "annotator_a")
        edited = json.loads(json.dumps(rows)); edited[1]["object"].update(text="3-14", iso=None, precision="partial"); write_jsonl(path, edited)
        with self.assertRaisesRegex(ConfigError, "batch_01.jsonl:2"): well_gold.seal(cfg, "annotator_a")
        write_jsonl(path, rows)
        result = well_gold.seal(cfg, "annotator_a")
        self.assertEqual(result["amendment_changes"][0], {"amendment": 1, "flagged": 2, "changed": 2,
                         "changed_by_path": {"object": 2}, "changed_by_relation": {"spudded_on": 2}, "flagged_unchanged": 0})
        self.assertNotIn("3-14-2011", json.dumps(result)); self.assertNotIn("2011-03-14", json.dumps(result))

    def test_amendment_two_date_slots(self):
        cfg, _, probe = amendment_fixture(dates=True, both=True); root = cfg["root"]
        probe.write_text("after\n", encoding="utf-8")
        result = well_gold.amend(cfg, "Two date slots")
        self.assertEqual(result["counts"]["annotator_a"], {"flagged": 4, "by_path": {"object": 2, "time": 2}})
        with self.assertRaises(ConfigError) as raised: well_gold.validate(cfg, "annotator_a", locations_only=True)
        self.assertEqual(str(raised.exception).splitlines(), result["flagged"]["annotator_a"])
        self.assertNotIn("2011", str(raised.exception))
        with self.assertRaises(ConfigError) as raised: well_gold.validate(cfg, "annotator_a")
        self.assertIn('span "3-14-2011"; annotator iso=null precision=partial; parser iso=2011-03-14 precision=day', str(raised.exception))
        path = root / "annotations/annotator_a/batch_01.jsonl"; rows = list(iter_jsonl(path))
        for row in rows:
            if row["record"] == "fact": row["object"].update(iso="2011-03-14", precision="day")
        write_jsonl(path, rows)
        with self.assertRaises(ConfigError) as raised: well_gold.validate(cfg, "annotator_a", locations_only=True)
        self.assertEqual(str(raised.exception).splitlines(), [s for s in result["flagged"]["annotator_a"] if s.endswith(": time")])
        for row in rows:
            if row["record"] == "fact": row["time"].update(iso="2011-03-14", precision="day")
        write_jsonl(path, rows)
        self.assertEqual(well_gold.seal(cfg, "annotator_a")["amendment_changes"][0]["changed"], 4)

    def test_validate_error_cap_and_bad_line_continuation(self):
        cfg = gold_fixture(); root = cfg["root"]
        path = root / "annotations/annotator_a/batch_01.jsonl"
        path.write_text("{\n" * 60, encoding="utf-8")
        with self.assertRaises(ConfigError) as raised: well_gold.validate(cfg, "annotator_a", locations_only=True)
        self.assertEqual(str(raised.exception).splitlines(), [f"annotations/annotator_a/batch_01.jsonl:{i}: record" for i in range(1, 51)])
        issues = []
        from kgbuilder.core.well_facts import load_annotations
        load_annotations(path, {}, issues)
        self.assertEqual(len(issues), 60)
        capped = well_gold._ValidationIssues(2)
        with patch("kgbuilder.core.well_facts.json.loads", wraps=json.loads) as read:
            load_annotations(path, {}, capped)
        self.assertEqual(read.call_count, 2)
        self.assertEqual(len(capped), 2)

    def test_empty_chunk_visible_and_invalid_decision(self):
        from kgbuilder.core.text import iter_jsonl, write_jsonl
        cfg = gold_fixture(); root = cfg["root"]
        for role in cfg["annotators"]:
            for path in (root / "annotations" / role).glob("*.jsonl"):
                rows = list(iter_jsonl(path))
                rows = [r for r in rows if not (r["chunk_id"] == "synthetic_0#c000" and r["record"] == "fact")]
                for row in rows:
                    if row["chunk_id"] == "synthetic_0#c000": row.update(status="no_facts", n_facts=0)
                write_jsonl(path, rows)
            well_gold.seal(cfg, role)
        well_gold.adjudication_packet(cfg)
        packets = [r for p in (root / "adjudication").glob("packet_*.jsonl") for r in iter_jsonl(p)]
        marker = next(r for r in packets if r["chunk_id"] == "synthetic_0#c000")
        self.assertEqual(marker["items"], [])
        self.assertIn("text", marker)
        for path in (root / "adjudication").glob("packet_*.jsonl"):
            rows = [{"record": "decision", "format": "kgb.well_adjudication/1", "chunk_id": item["chunk_id"],
                     "item_id": item["item_id"], "decision": "accept_both", "fact": None,
                     "citation": {"text": item["text"], "occ": 0}, "rationale": "Synthetic invalid agreement decision."}
                    for item in iter_jsonl(path) if "item_id" in item]
            write_jsonl(path.with_name(path.name.replace("packet_", "decisions_")), rows)
        with self.assertRaises(ConfigError): well_gold.validate(cfg, "adjudicator")

    def test_shortfall_packets_and_whole_chunk(self):
        from kgbuilder.core.text import write_json, write_jsonl
        cfg = gold_fixture(); root = cfg["root"]
        for name in ("annotations", "packets"):
            shutil.rmtree(root / name)
        (root / "freeze.json").unlink()
        cfg["batch_size"] = 20
        docs = [{"doc_id": f"s{i:02d}", "text": "Synthetic well operations."} for i in range(63)]
        write_jsonl(root / "corpus/corpus.jsonl", docs)
        write_json(root / "corpus/selection.json", {"dev": [d["doc_id"] for d in docs[:15]], "test": [d["doc_id"] for d in docs[15:]],
                   "corpus_sha256": sha256_file(root / "corpus/corpus.jsonl")})
        result = well_gold.prepare(cfg, root / "corpus")
        self.assertEqual(result["batches"], 4)
        self.assertEqual([len(p.read_text().splitlines()) for p in sorted((root / "packets").glob("*.jsonl"))], [20, 20, 20, 3])
        for path in (root / "packets").glob("*.jsonl"):
            for line in path.read_text().splitlines():
                self.assertEqual(set(json.loads(line)), {"format", "doc_id", "chunk_id", "text", "source_type"})

    def test_complete_adjudication(self):
        cfg = gold_fixture(complete=True)
        self.assertTrue(all(v == "OK" for v in well_gold.verify(cfg).values()))
        result = well_gold.agreement(cfg, cfg["root"] / "agreement", None)
        self.assertEqual(result["decision_counts"], {"keep": 3})
        for scope in result["scopes"].values():
            self.assertEqual(scope["iaa"]["L3"]["f1"], 1)
            self.assertEqual(scope["span_exact"], 1)
            self.assertEqual(scope["evidence_iou"], 1)
        with self.assertRaisesRegex(ConfigError, "already sealed"): well_gold.adjudication_packet(cfg)
        for packet in (cfg["root"] / "adjudication").glob("packet_*.jsonl"):
            self.assertNotIn('"annotator"', packet.read_text())
        path = cfg["root"] / "adjudication/key.json"
        path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ConfigError, "hash mismatch"): well_gold.verify(cfg)

    def test_freeze_partial_validation_and_seals(self):
        cfg = gold_fixture(); root = cfg["root"]
        self.assertEqual(len(list((root / "packets").glob("*.jsonl"))), 2)
        self.assertEqual(well_gold.validate(cfg, "annotator_a")["status"], "present 2/2")
        missing = root / "annotations/annotator_a/batch_02.jsonl"
        saved = missing.read_bytes(); missing.unlink()
        self.assertEqual(well_gold.validate(cfg, "annotator_a")["status"], "present 1/2")
        with self.assertRaisesRegex(ConfigError, "missing batches"): well_gold.seal(cfg, "annotator_a")
        missing.write_bytes(b"\xef\xbb\xbf" + saved.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        self.assertEqual(well_gold.seal(cfg, "annotator_a")["files"], 2)
        seal_hash = sha256_file(root / "seals/annotator_a.json")
        with self.assertRaisesRegex(ConfigError, "already exists"): well_gold.seal(cfg, "annotator_a")
        self.assertEqual(sha256_file(root / "seals/annotator_a.json"), seal_hash)
        with self.assertRaisesRegex(ConfigError, "already exists"): well_gold.prepare(cfg, root / "corpus")

    def test_ordering_and_protocol(self):
        cfg = gold_fixture(); root = cfg["root"]
        (PROJECT_ROOT / cfg["forbidden_before_seal"][0]).mkdir()
        with self.assertRaisesRegex(ConfigError, "forbidden"): well_gold.seal(cfg, "annotator_a")
        shutil.rmtree(PROJECT_ROOT / cfg["forbidden_before_seal"][0])
        (root / "protocol/guideline.md").unlink()
        with self.assertRaisesRegex(ConfigError, "protocol"): well_gold.validate(cfg, "annotator_b")

    def test_protocol_copies(self):
        root = PROJECT_ROOT / "data/benchmarks/bsee_gold/v1"
        freeze = json.loads((root / "freeze.json").read_text())
        self.assertEqual(set(freeze["protocol"]), {"protocol/guideline.md"})
        self.assertEqual({p.name for p in (root / "protocol").iterdir()}, {"guideline.md"})
        self.assertEqual(sha256_file(root / "protocol/guideline.md"), freeze["protocol"]["protocol/guideline.md"])
        self.assertEqual(freeze["statement"], "re-sealed for publication; label content identical")

    def test_partial_items_and_citations(self):
        cfg = gold_fixture(); root = cfg["root"]
        # One modality disagreement and one fact present only on A or B.
        for path in (root / "annotations/annotator_b").glob("*.jsonl"):
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            for row in rows:
                if row["record"] == "fact" and row["chunk_id"] == "synthetic_1#c000": row["modality"] = "planned"
                if row["record"] == "chunk" and row["chunk_id"] == "synthetic_2#c000": row.update(status="unreadable", n_facts=0, note="person name present")
            rows = [r for r in rows if not (r["record"] == "fact" and r["chunk_id"] == "synthetic_2#c000")]
            path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        for role in cfg["annotators"]: well_gold.seal(cfg, role)
        result = well_gold.adjudication_packet(cfg)
        self.assertEqual(result["items"].get("partial"), 1)
        self.assertEqual(result["items"].get("agreed"), 1)
        target = None
        for path in (root / "adjudication").glob("packet_*.jsonl"):
            decisions = []
            for item in [json.loads(line) for line in path.read_text().splitlines()]:
                choice = "keep" if item["kind"] == "agreed" else "accept_A" if item["A"] else "accept_B"
                citation = None if choice == "keep" else {"text": item["text"], "occ": 0}
                decisions.append({"record": "decision", "format": "kgb.well_adjudication/1", "chunk_id": item["chunk_id"],
                                  "item_id": item["item_id"], "decision": choice, "fact": None, "citation": citation, "rationale": "Synthetic evidence."})
            decision_path = path.with_name(path.name.replace("packet_", "decisions_"))
            decision_path.write_text("\n".join(json.dumps(r) for r in decisions) + "\n", encoding="utf-8")
            if any(r["citation"] for r in decisions): target = decision_path
        self.assertEqual(well_gold.validate(cfg, "adjudicator")["present"], 2)
        saved = target.read_bytes()
        rows = [json.loads(line) for line in target.read_text().splitlines()]
        next(r for r in rows if r["citation"])["citation"] = None
        target.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        with self.assertRaises(ConfigError): well_gold.validate(cfg, "adjudicator")
        target.write_bytes(saved)
        well_gold.seal(cfg, "adjudicator"); well_gold.merge(cfg)
        result = well_gold.agreement(cfg, root / "agreement", None)
        self.assertEqual(result["n_unreadable"], 1)
