"""Synthetic guided extraction, parsing, evidence and failure accounting."""
from __future__ import annotations

import hashlib
import json
import unittest
from threading import Lock
from unittest.mock import patch

from helpers import PROJECT_ROOT
from kgbuilder import __version__
from kgbuilder.build.extract import guided
from kgbuilder.build.extract.route import route_documents
from kgbuilder.build.parse.chunking import chunk_documents
from kgbuilder.core.config import KgbError, load_config
from kgbuilder.core.contracts import Document
from kgbuilder.core.schema import load_schema
from kgbuilder.core.text import cj, h, sha256_file, surface_key
from kgbuilder.core.well_values import RELATIONS


class GuidedTest(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml", sets=[
            "extract.backend=guided", "extract.guided_prompt=configs/prompts/bsee_guided.txt",
            "canon.schema_path=contracts/ontology/bsee.yaml"])
        self.schema = load_schema(self.cfg.canon.schema_path)
        self.docs = [Document(doc_id="invented", text="Set bridge plug at 4,210 ft MD. Drilled to 5,480 ft.")]
        self.chunks = chunk_documents(self.docs, 2000)

    def run_reply(self, reply):
        return guided.run_extract(self.docs, self.chunks, self.cfg, "http://127.0.0.1:9/v1",
                                  self.schema, ask=lambda messages: reply)

    def test_recall_chunk_golden_bytes(self):
        prompt = self.cfg.extract.guided_prompt.read_text(encoding="utf-8")
        messages = guided.render(prompt, self.schema, self.chunks[0].text, relations=None)
        self.assertEqual(hashlib.sha256(cj(messages).encode()).hexdigest(),
                         "d3ecc7bbe066ef9efbc9d25e4d57c7ff39824ea21a8fa09f39fdee6b02d94f1f")
        seen = []
        def ask(value):
            seen.append(value)
            return cj([{"subject": "bridge plug", "relation": "set_plug_at", "object": "4,210 ft MD"}])
        result = guided.run_extract(self.docs, self.chunks, self.cfg, "http://127.0.0.1:9/v1", self.schema, ask=ask)
        self.assertEqual(seen, [messages])
        self.assertEqual(hashlib.sha256(cj([c.model_dump(mode="json") for c in result.candidates]).encode()).hexdigest(),
                         "f9f6886bca765cf709d17653b572ca474ae92e6ccdbad792a9ea812b86fc2666")

    def test_recall_windows_validation_and_unit_failure(self):
        self.cfg.extract.guided_mode = "windows2"
        self.cfg.llm.max_concurrency = 1
        text = "Drilled to 100 ft successfully. Tested valve at 900 psi successfully. Set plug at 300 ft safely."
        docs = [Document(doc_id="invented", text=text)]
        chunks = chunk_documents(docs, 2000)
        calls = []
        wrong = {"subject": "well", "relation": "set_plug_at", "object": "300 ft"}
        def ask(messages):
            calls.append(messages)
            return cj([wrong])
        result = guided.run_extract(docs, chunks, self.cfg, "http://127.0.0.1:9/v1", self.schema, ask=ask)
        self.assertEqual(len(calls), 2)
        self.assertIn("Text:\nDrilled to 100 ft successfully. Tested valve at 900 psi successfully.", calls[0][1]["content"])
        self.assertIn("Text:\nSet plug at 300 ft safely.", calls[1][1]["content"])
        self.assertEqual([r.reasons for r in result.rejections], [["guided_not_in_text"]])
        self.assertEqual(len(result.candidates), 1)
        c = result.candidates[0]
        self.assertTrue(c.extractor_version.endswith(";mode=windows2"))
        self.assertEqual(c.evidence.char_start, text.index("Set plug"))
        for replies, failed in ((["bad", "[]"], 0), (["bad", "bad"], 1)):
            self.cfg.extract.max_failed_chunk_ratio = 1
            iterator = iter(replies)
            result = guided.run_extract(docs, chunks, self.cfg, "http://127.0.0.1:9/v1", self.schema, ask=lambda _: next(iterator))
            self.assertEqual(result.failed_chunks, failed)
        one = [Document(doc_id="one", text="Drilled to 100 ft.")]
        calls.clear()
        guided.run_extract(one, chunk_documents(one, 2000), self.cfg, "http://127.0.0.1:9/v1", self.schema, ask=ask)
        self.assertEqual(len(calls), 1)
        calls.clear()
        with patch.object(guided, "split_sentences_abbrev", return_value=[]):
            guided.run_extract(one, chunk_documents(one, 2000), self.cfg, "http://127.0.0.1:9/v1", self.schema, ask=ask)
        self.assertEqual(len(calls), 1)

    def test_recall_groups_and_recall_union(self):
        self.cfg.llm.max_concurrency = 1
        item = {"subject": "bridge plug", "relation": "set_plug_at", "object": "4,210 ft MD"}
        self.cfg.extract.guided_mode = "groups4"
        self.cfg.extract.guided_prompt = PROJECT_ROOT / "configs/prompts/bsee_guided_groups.txt"
        calls = []
        def ask(messages):
            calls.append(messages)
            return cj([item, {**item, "relation": "invented"}])
        result = guided.run_extract(self.docs, self.chunks, self.cfg, "http://127.0.0.1:9/v1", self.schema, ask=ask)
        self.assertEqual(len(calls), 4)
        expected_groups = (
            ("spudded_on", "reached_td", "drilled_to", "fit_lot_emw", "has_mud_weight", "encountered_marker"),
            ("set_casing_at", "casing_size", "casing_spec", "cemented_interval", "cut_at"),
            ("set_plug_at", "set_equipment_at", "tagged_at", "tested_to_pressure", "pumped"),
            ("perforated_interval", "completed_in", "has_well_status", "used_rig", "operated_by"))
        self.assertEqual(guided.GROUPS4, expected_groups)
        for messages, group in zip(calls, expected_groups):
            definitions = messages[1]["content"].split("Allowed relations:\n")[1].split("\n\nText:")[0]
            self.assertEqual(tuple(line.split(":", 1)[0] for line in definitions.splitlines()), group)
        self.assertEqual((len(result.candidates), result.duplicate_candidates), (1, 3))
        self.assertTrue(result.candidates[0].extractor_version.endswith(";mode=groups4"))
        self.assertEqual([r.reasons for r in result.rejections], [["guided_out_of_schema"]] * 4)
        self.cfg.extract.guided_mode = "chunk"
        self.cfg.extract.guided_prompt = PROJECT_ROOT / "configs/prompts/bsee_guided.txt"
        self.cfg.extract.guided_recall_prompt = PROJECT_ROOT / "configs/prompts/bsee_guided_recall.txt"
        calls.clear()
        second = {"subject": "well", "relation": "drilled_to", "object": "5,480 ft"}
        def recall_ask(messages):
            calls.append(messages)
            return cj([item] if len(calls) == 1 else [item, second])
        result = guided.run_extract(self.docs, self.chunks, self.cfg, "http://127.0.0.1:9/v1", self.schema, ask=recall_ask)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], guided.render(self.cfg.extract.guided_prompt.read_text(encoding="utf-8"), self.schema, self.chunks[0].text))
        self.assertEqual([c.predicate for c in result.candidates], ["set_plug_at", "drilled_to"])
        self.assertEqual(result.duplicate_candidates, 1)
        self.assertIn("guided@bsee_guided:", result.candidates[0].extractor_version)
        self.assertIn("guided@bsee_guided_recall:", result.candidates[1].extractor_version)

    def test_parse(self):
        value = [{"subject": "well", "relation": "drilled_to", "object": "5,480 ft"}]
        for content in (cj(value), "```json\n" + cj(value) + "\n```", "```\n[]\n```",
                        "Extracted: " + cj(value) + " End."):
            self.assertEqual(guided.parse(content), [] if content == "```\n[]\n```" else value)
        for content in ("no array", "{}", "[broken]", "null", "["):
            self.assertIsNone(guided.parse(content))

    def test_render_relations_and_literal_braces(self):
        text = "Source has {relations}, {text} and {braces}."
        prompt = self.cfg.extract.guided_prompt.read_text(encoding="utf-8")
        messages = guided.render(prompt, self.schema, text)
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        definitions = "\n".join(f"{r}: {self.schema.relations[r].definition}" for r in RELATIONS)
        self.assertIn(definitions, messages[1]["content"])
        self.assertIn(text, messages[1]["content"])
        self.assertIn('{"subject":"8-inch casing"', messages[0]["content"])
        for bad in ("no separator", "=== USER ===\n{text}", "=== USER ===\n{relations}{text}\n=== USER ==="):
            with self.assertRaises(KgbError) as caught:
                guided.render(bad, self.schema, text)
            self.assertEqual(caught.exception.code, 2)

    def test_valid_duplicate_mentions_and_version(self):
        item = {"subject": "bridge plug", "relation": "set_plug_at", "object": "4,210 ft MD", "ignored": True}
        result = self.run_reply(cj([item, item, {"subject": "well", "relation": "drilled_to", "object": "5,480 ft"}]))
        self.assertEqual((len(result.candidates), result.duplicate_candidates, result.failed_chunks), (2, 1, 0))
        self.assertEqual(result.rejections, [])
        candidate = result.candidates[0]
        self.assertEqual(candidate.candidate_id, "c_" + h(self.chunks[0].chunk_id, "guided", *[
            surface_key(item[k]) for k in ("subject", "relation", "object")])[:16])
        self.assertEqual(candidate.extractor, "guided")
        self.assertEqual(candidate.evidence.grounding, "exact")
        ev = candidate.evidence
        self.assertEqual(ev.text, self.docs[0].text[ev.char_start:ev.char_end])
        expected = f"kgb/{__version__};extract=guided@bsee_guided:{sha256_file(self.cfg.extract.guided_prompt)[:8]};llm={self.cfg.llm.model}"
        self.assertEqual(candidate.extractor_version, expected)
        self.assertEqual(len(result.mentions), 4)
        implicit = next(m for m in result.mentions if m.surface == "well")
        self.assertIsNone(implicit.char_start)
        self.assertEqual(sum(result.ground_rules.values()), 2)
        for mention in result.mentions:
            if mention.char_start is not None:
                self.assertEqual(self.docs[0].text[mention.char_start:mention.char_end], mention.surface)

    def test_rejections_and_case_insensitive_substrings(self):
        good = {"subject": "BRIDGE PLUG", "relation": "set_plug_at", "object": "4,210 FT MD"}
        items = [None, [], {"subject": 2}, {**good, "object": ""}, {**good, "object": "x" * 301},
                 {**good, "relation": "drilled_by"}, {**good, "object": "9,999 ft"},
                 {**good, "subject": "missing equipment"}, good]
        result = self.run_reply(cj(items))
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual([r.reasons[0] for r in result.rejections],
                         ["guided_invalid_item"] * 5 + ["guided_out_of_schema"] + ["guided_not_in_text"] * 2)
        self.assertEqual(result.failed_chunks, 0)

    def test_failure_ratio_empty_array_and_transport(self):
        self.assertEqual(self.run_reply("[]").failed_chunks, 0)
        with self.assertRaises(KgbError) as caught:
            self.run_reply("prose only")
        self.assertEqual(caught.exception.code, 6)
        self.cfg.extract.max_failed_chunk_ratio = 1
        self.assertEqual(self.run_reply("prose only").failed_chunks, 1)
        def failed(messages):
            raise OSError("synthetic transport failure")
        result = guided.run_extract(self.docs, self.chunks, self.cfg, "http://127.0.0.1:9/v1", self.schema, ask=failed)
        self.assertEqual(result.failed_chunks, 1)
        self.assertEqual(result.candidates, [])

    def test_chunk_order_workers_and_exact_failure_boundary(self):
        docs = [Document(doc_id=name, text=f"{name} drilled to 5,480 ft.") for name in ("z", "b", "a", "c", "d")]
        chunks = chunk_documents(docs, 2000)
        calls, lock = [], Lock()
        def ask(messages):
            with lock:
                calls.append(messages)
            return "bad" if "z drilled" in messages[1]["content"] else cj([
                {"subject": "well", "relation": "drilled_to", "object": "5,480 ft"}])
        with patch.object(guided, "ThreadPoolExecutor", wraps=guided.ThreadPoolExecutor) as pool:
            result = guided.run_extract(docs, chunks, self.cfg, "http://127.0.0.1:9/v1", self.schema, ask=ask)
        pool.assert_called_once_with(max_workers=self.cfg.llm.max_concurrency)
        self.assertEqual((len(calls), result.failed_chunks), (5, 1))
        ids = [c.chunk_id for c in result.candidates]
        self.assertEqual(ids, sorted(ids))
        self.cfg.extract.max_failed_chunk_ratio = .19
        with self.assertRaises(KgbError):
            guided.run_extract(docs, chunks, self.cfg, "http://127.0.0.1:9/v1", self.schema, ask=ask)

    def test_auto_never_routes_to_guided(self):
        self.cfg.extract.backend = "auto"
        self.assertEqual([r.backend for r in route_documents(self.docs, None, self.cfg)], ["kggen"])
        import numpy as np
        for vector, expected in (([1., 0.], "edc"), ([0., 1.], "kggen")):
            def encode(values):
                return np.array([[1., 0.]] * len(values) if len(values) == 21 else [vector] * len(values))
            self.assertEqual([r.backend for r in route_documents(self.docs, self.schema, self.cfg, encode)], [expected])


if __name__ == "__main__":
    unittest.main()
