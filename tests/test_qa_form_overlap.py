"""Regression cases for the K1 form overlap check and retrieval projection."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from graph_builder.corpus.k1_build import form_text
from graph_builder.corpus.k1_config import load_k1_config
STANDARD_24NOV = __import__('pathlib').Path(__file__).resolve().parents[1] / "configs/corpus/candidates/k1_standard_24nov.json"  # the profile main shipped on 24 November (D2/D4 decisions made the default smaller)
from graph_builder.corpus.qa.cli import run as run_qa
from graph_builder.corpus.qa.form_overlap import CONFLICT, DUPLICATE, FormOverlap, register_form_overlap
from graph_builder.corpus.qa.signals import CheckContext, Registry
from graph_builder.corpus.store import atomic_write_jsonl, read_jsonl
from graphrag.data import load_chunks


PAGE = {"file_id": "file", "doc_id": "dailyreport", "page": 1}
FORM = {"form_id": "form", **PAGE}
CHUNK = {"pages": [1], "context": {}, **PAGE}


def field(key, value, y=100):
    return {"key": key, "value": value, "source_word_boxes": True,
            "key_bbox": [10, y, 20, y + 5], "value_bbox": [23, y, 40, y + 5]}


def passage(text, chunk_id="text", **kwargs):
    return {**CHUNK, "type": "text", "text": text, "chunk_id": chunk_id,
            "regions": [{"page": 1, "bbox": [10, 101, 40, 104]}],
            "source_spans": [{"start": 0, "end": len(text), "page": 1, "source_ref": "#/texts/4"}], **kwargs}


class FormOverlapTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.release = Path(directory.name)

    def state(self, fields, *chunks):
        form = {**FORM, "fields": fields}
        form_chunk = {**CHUNK, "type": "form", "text": form_text(form), "form_id": "form", "chunk_id": "form-child"}
        atomic_write_jsonl(self.release / "forms.jsonl", [form])
        atomic_write_jsonl(self.release / "chunks.jsonl", [*chunks, form_chunk])
        return FormOverlap(self.release)

    def test_removes_only_full_match_and_keeps_chunk_ids_and_original_bytes(self):
        chunks = [passage("Depth: 17 ft"), passage("Other: 17 ft", "other")]
        state = self.state([field("Depth:", "17  ft"), field("Other:", "17 ft", y=300), field("Blank:", "")], *chunks)
        original = (self.release / "chunks.jsonl").read_bytes()
        view = self.release / "retrieval_chunks.jsonl"
        self.assertEqual(state.write_view(view), 3)
        self.assertEqual([(c.id, c.text) for c in load_chunks(path=view)],
                         [("text", "Depth: 17 ft"), ("other", "Other: 17 ft"), ("form-child", "Other: 17 ft\nBlank: ")])
        self.assertEqual((self.release / "chunks.jsonl").read_bytes(), original)
        match, = state.findings[("file", 1)]
        self.assertEqual((match["code"], match["field_index"], match["source_ref"]), (DUPLICATE, 0, "#/texts/4"))

    def test_drops_an_entire_redundant_form_child(self):
        state = self.state([field("Depth:", "17 ft")], passage("Depth: 17 ft"))
        self.assertEqual([row["chunk_id"] for row in state.retrieval_rows()], ["text"])

    def test_qa_projects_default_k1_and_can_regenerate_unprojected_view(self):
        self.state([field("Depth:", "17 ft")], passage("Depth: 17 ft"))
        config = load_k1_config(STANDARD_24NOV)
        self.assertEqual(config["table_rules"]["ruled_panels"]["panels"],
                         ["survey", "bit", "bha", "inventory", "formation_depths", "pump"])
        self.assertIn("mud_properties", config["table_rules"])
        (self.release / "manifest.json").write_text(json.dumps({"config": {"k1": config}}), encoding="utf-8")
        (self.release / "SHA256SUMS").write_text("fixture", encoding="utf-8")
        atomic_write_jsonl(self.release / "tables.jsonl", [])
        original = (self.release / "chunks.jsonl").read_bytes()
        with TemporaryDirectory() as directory, patch("graph_builder.corpus.qa.cli.build_qa",
                side_effect=[{"validator": "pass", "signals": {}}, {"validator": "pass", "signals": {}}]), \
                patch("graph_builder.corpus.qa.cli.source_problems", return_value=[]):
            out = Path(directory)
            result = run_qa(None, self.release, out, None, None)["retrieval_view"]
            self.assertEqual(result["duplicate_fields_removed"], 1)
            self.assertEqual(result["duplicate_table_cells_removed"], 0)
            self.assertEqual(result["ruled_compound_cells_resolved"], 0)
            view = out / "retrieval_chunks.jsonl"
            self.assertEqual([row["chunk_id"] for row in read_jsonl(view)], ["text"])
            run_qa(None, self.release, out, None, None, form_overlap=False, table_overlap=False,
                   ruled_table_overlap=False, compact_table_spans=False)
            self.assertEqual([row["chunk_id"] for row in read_jsonl(view)], ["text", "form-child"])
        self.assertEqual((self.release / "chunks.jsonl").read_bytes(), original)

    def test_inconsistent_form_chunk_is_kept_verbatim(self):
        self.state([field("Depth:", "17 ft")], passage("Depth: 17 ft"))
        path = self.release / "chunks.jsonl"
        chunks = list(read_jsonl(path))
        chunks[-1]["text"] += "\nOnly recorded here."
        atomic_write_jsonl(path, chunks)
        state = FormOverlap(self.release)
        self.assertFalse(state.findings)
        self.assertEqual([row["text"] for row in state.retrieval_rows()], [row["text"] for row in chunks])

    def test_conflicting_units_are_flagged_and_both_values_stay(self):
        state = self.state([field("Depth:", "17 ft")], passage("Depth: 17 m"))
        registry = register_form_overlap(Registry(), lambda: state)
        context = CheckContext(registry, {}, self.release, {})
        ids = {"file_id": "file", "page": 1}
        signals, _, granted = registry.run("page", context, {"ids": ids}, ids)
        signal, = signals
        self.assertEqual((signal["code"], signal["severity"], granted), (CONFLICT, "WARN", None))
        pair, = signal["evidence"]["pairs"]
        self.assertEqual((pair["form_value"], pair["chunk_value"]), ("17 ft", "17 m"))
        self.assertEqual([row["text"] for row in state.retrieval_rows()], ["Depth: 17 m", "Depth: 17 ft"])

    def test_uncertain_evidence_is_preserved(self):
        for chunk in (passage("Depth: 17 ft", pages=[1, 2]), passage("Depth: 17 ft", ocr=True),
                      passage("Depth: 17 ft", context={"report_no": "2"}), passage("Depth: 17 ft", regions=[]),
                      passage("Depth: 17 ft", type="table"), passage("Depth: 17 ft", source_spans=[]),
                      passage("Depth: 17 ft\nfrom sea level")):
            with self.subTest(chunk=chunk):
                state = self.state([field("Depth:", "17 ft")], chunk)
                self.assertFalse(state.removed)
                self.assertFalse(state.findings)

    def test_repeated_labels_are_ambiguous_and_broad_regions_cannot_warn(self):
        repeated = self.state([field("Depth:", "17 ft"), field("Depth:", "18 ft")], passage("Depth: 17 ft"))
        self.assertFalse(repeated.findings)
        repeated = self.state([field("Depth:", "17 ft")],
                              passage("Depth: 17 ft"), passage("Depth: 18 ft", "other"))
        self.assertFalse(repeated.findings)
        broad = self.state([field("Depth:", "17 ft")],
                           passage("Depth: 17 m", regions=[{"page": 1, "bbox": [0, 1, 400, 500]}]))
        self.assertFalse(broad.findings)


if __name__ == "__main__":
    unittest.main()
