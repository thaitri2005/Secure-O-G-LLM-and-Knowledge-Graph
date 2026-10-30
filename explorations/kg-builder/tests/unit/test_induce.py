"""In-process induction checks with injected concept responses and tiny graphs."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

import yaml

from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.build.refine import induce as mod
from kgbuilder.core.config import ConfigError, KgbError, load_config
from kgbuilder.core.contracts import GraphRecord, dump
from kgbuilder.core.schema import load_schema
from kgbuilder.core.text import read_jsonl, write_json, write_jsonl


class InduceTest(unittest.TestCase):
    def setUp(self):
        self.root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/induce" / self._testMethodName)
        self.src = self.root / "src"
        self.src.mkdir()
        self.g = GraphRecord.model_validate_json((PROJECT_ROOT / "tests/fixtures/graph_small.json").read_text(encoding="utf-8"))
        self.rows = [{"candidate_id": c, "predicate": s.predicate,
                      "open_predicate": "runs" if s.statement_id == "s3" else s.predicate,
                      "edc_definition": "The subject runs the object." if s.statement_id == "s3" else
                      "The subject person is employed by or works at the object organization."}
                     for s in self.g.statements for c in s.candidate_ids]
        self.save()
        self.cfg = load_config(PROJECT_ROOT / "configs/experiments/showcase_noschema.yaml", sets=["induce.max_entities=2"])

    def save(self):
        write_json(self.src / "graph.json", dump(self.g))
        write_jsonl(self.src / "canonical.jsonl", self.rows)
        write_json(self.src / "edc/request.json", {"enrich_schema": True})

    def run_induce(self, ask, **settings):
        cfg = self.cfg.model_copy(update={"induce": self.cfg.induce.model_copy(update=settings)})
        return mod.induce(self.src, cfg, "http://127.0.0.1:1/v1", self.root / "out", ask=ask)

    def test_helpers(self):
        for value, expected in [("works on", "works_on"), ("birthPlace", "birth_place"), ("is part of", "is_part_of"),
                                ("1st member of", "r_1st_member_of"), ("!!", "related_to"), ("x" * 80, "x" * 64)]:
            self.assertEqual(mod.relation_name(value), expected)
        templates = mod.load_concept_templates()
        self.assertTrue({"event", "entity", "relation"} <= templates.keys())
        self.assertIn("[ENTITY]", templates["entity"])
        self.assertIn("[CONTEXT]", templates["entity"])
        self.assertEqual(mod.parse_concepts("Organization, company, IBM, , company", "IBM", 5), ["organization", "company"])
        self.assertEqual(mod.parse_concepts("Organization, company, IBM", "IBM", 1), ["organization"])
        self.assertEqual([e.entity_id for e in mod.entity_order(self.g)], ["e2", "e1", "e4", "e3"])
        for eid, expected in {"e2": "Alice works at", "e1": "works at Acme Labs", "e4": "operates Acme Labs", "e3": "Alice works at"}.items():
            self.assertEqual(mod.entity_context(self.g, eid), expected)

    def test_inventory(self):
        rows, counts = mod.relation_inventory(self.g, self.rows[::-1], self.cfg.induce)
        self.assertEqual([(r["name"], r["support"]) for r in rows], [("works_at", 2), ("operates", 1)])
        self.assertEqual(rows[0]["definition"], self.rows[0]["edc_definition"])
        self.assertEqual(rows[1]["definition"], "The subject entity is related to the object entity by the relation 'operates'.")
        self.assertEqual(counts, {"dropped_low_support": 0, "dropped_max_relations": 0})
        rows, counts = mod.relation_inventory(self.g, self.rows, self.cfg.induce.model_copy(update={"max_relations": 1}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(counts["dropped_max_relations"], 1)

    def test_induce_deterministic(self):
        calls = []
        def fake(messages):
            calls.append(messages)
            return "organization, company" if "ENTITY: Acme Labs" in messages[1]["content"] else "person, employee"
        summary = self.run_induce(fake)
        self.assertEqual(len(calls), 2)
        types = {r["entity_id"]: r["type"] for r in read_jsonl(self.root / "out/concepts.jsonl")}
        self.assertEqual(types, {"e2": "organization", "e1": "person", "e3": "entity", "e4": "entity"})
        schema = yaml.safe_load((self.root / "out/schema_induced.yaml").read_text(encoding="utf-8"))
        self.assertEqual((schema["relations"]["works_at"]["domain"], schema["relations"]["works_at"]["range"]), ("person", "organization"))
        self.assertEqual((schema["relations"]["operates"]["domain"], schema["relations"]["operates"]["range"]), ("entity", "organization"))
        self.assertEqual(len(load_schema(self.root / "out/schema_induced.yaml").relations), 2)
        self.assertEqual([summary["relations"][k] for k in ("open_types", "canonical_types", "induced_types", "open_redundancy")], [2, 2, 2, 0.0])
        self.assertEqual(summary["coverage"], {"statements": 1.0, "entities": 4, "entities_asked": 2, "entities_typed": 2, "concept_errors": 0})
        before = (self.root / "out/schema_induced.yaml").read_bytes()
        for source in [Path(str(self.src).replace("/", "\\")), Path(self.src.as_posix())]:
            mod.induce(source.resolve(), self.cfg, "http://127.0.0.1:1/v1", self.root / "out", ask=fake)
            self.assertEqual((self.root / "out/schema_induced.yaml").read_bytes(), before)
        self.assertEqual(schema["induced"]["source_run"], self.src.relative_to(PROJECT_ROOT).as_posix())

    def test_zero_calls_and_filter(self):
        def boom(_):
            self.fail("zero-entity mode must not call")
        summary = self.run_induce(boom, max_entities=0, min_support=2)
        self.assertEqual(summary["coverage"]["statements"], 0.6667)
        self.assertEqual(summary["coverage"]["entities_asked"], 0)
        self.assertEqual(summary["llm"]["llm_calls"], 0)
        self.assertEqual(summary["relations"]["dropped_low_support"], 1)
        schema = yaml.safe_load((self.root / "out/schema_induced.yaml").read_text(encoding="utf-8"))
        self.assertEqual(list(schema["relations"]), ["works_at"])
        self.assertEqual(schema["induced"]["method"], "edc_self_canon")

    def test_errors(self):
        request = self.src / "edc/request.json"
        request.unlink()
        with self.assertRaisesRegex(ConfigError, "self-canonicalised"):
            self.run_induce(lambda _: "person")
        write_json(request, {"enrich_schema": False})
        with self.assertRaisesRegex(ConfigError, "self-canonicalised"):
            self.run_induce(lambda _: "person")
        self.save()
        for error in (URLError("offline"), KeyError("choices")):
            def boom(_):
                raise error
            with self.assertRaises(KgbError) as caught:
                self.run_induce(boom)
            self.assertEqual(caught.exception.code, 6)
        self.g = self.g.model_copy(update={"statements": []})
        self.save()
        with self.assertRaisesRegex(ConfigError, "no accepted statements"):
            self.run_induce(lambda _: "person")

    def test_voting(self):
        base = self.g.statements[0]
        self.g = self.g.model_copy(update={"statements": [base.model_copy(update={"statement_id": f"v{i}", "object_id": eid})
                                                          for i, eid in enumerate(["e2", "e3", "e4"])]})
        for assigned, expected in [({"Acme Labs": "literal", "Nova AI": "literal", "IBM": "organization"}, "literal"),
                                   ({}, "entity"), ({"Acme Labs": "organization", "Nova AI": "person"}, "organization")]:
            # Literal kind supplies votes without an LLM call.
            entities = [e.model_copy(update={"kind": "literal" if assigned.get(e.name) == "literal" else "entity"}) for e in self.g.entities]
            self.g = self.g.model_copy(update={"entities": entities})
            self.save()
            def fake(messages):
                return next((t for name, t in assigned.items() if f"ENTITY: {name}\n" in messages[1]["content"]), "")
            self.run_induce(fake, max_entities=10)
            schema = yaml.safe_load((self.root / "out/schema_induced.yaml").read_text(encoding="utf-8"))
            self.assertEqual(schema["relations"]["works_at"]["range"], expected)

    def test_template_changed(self):
        source = self.root / "prompt.py"
        source.write_text('CONCEPT_INSTRUCTIONS = {"en": {"entity": "changed"}}', encoding="utf-8")
        with patch.object(mod.config, "autoschemakg_prompts", return_value=source):
            with self.assertRaisesRegex(KgbError, "not found or changed"):
                mod.load_concept_templates()
