"""K1 package: ids, parents, forms, report context, schemas, export determinism and validation."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from docling_core.types.doc import DocItemLabel
from jsonschema import Draft202012Validator
from pypdf import PdfWriter

from graph_builder.corpus.catalog import Corpus
from graph_builder.corpus.config import fingerprint as make_fingerprint, load_config
from graph_builder.corpus.k1_build import canonical, file_id, map_children, separate_contexts
from graph_builder.corpus.k1_config import load_k1_config
from graph_builder.corpus.k1_export import K1CompletenessError, export_k1
from graph_builder.corpus.k1_validate import GROUPS, LEGACY_MAP, summary, validate_k1
from graph_builder.corpus.legacy_ids import LEGACY_DOCUMENT
from graph_builder.corpus.process import page_texts, process_document
from graph_builder.corpus.store import file_sha256
from graph_builder.corpus.validate import SCHEMAS
from test_chunking import add_table, add_text, make_document

ROOT = Path(__file__).resolve().parents[1]
FID = "f" + "0" * 16
OCR = {"settings": {"engine": "easyocr"}, "runtime": {"easyocr": "1.0"}, "models": {}}
K1_CONFIG = load_k1_config()
CONTEXT = {"report_date": "31-Aug-16", "well": "AK-3"}


def corpus_chunk(text="Original prose.", page=1, **fields):
    chunk = dict(chunk_id="old", doc_id="sample", type="text", text=text, section=None, section_path=[], page=page,
                 pages=[page], regions=[], source_spans=[], table_id=None, row_start=None, row_end=None)
    return dict(chunk, **fields)


class MapChildrenTests(unittest.TestCase):
    def test_form_parent_context_and_verbatim_text(self):
        fields = [dict(key="Report For", value="31-Aug-16", key_bbox=[1, 1, 2, 2], value_bbox=[3, 1, 5, 2]),
                  dict(key="Well ID:", value="AK-3", key_bbox=[1, 3, 2, 4], value_bbox=[3, 3, 5, 4])]
        forms = [dict(page=1, fields=fields, verified=True)]
        children, parents = map_children(FID, "sample", "daily_report", [corpus_chunk()], [], forms, {1: CONTEXT})
        self.assertEqual(children[0]["text"], "Original prose.")
        self.assertEqual(children[0]["context"], CONTEXT)
        self.assertEqual(children[1]["text"], "Report For: 31-Aug-16\nWell ID: AK-3")
        self.assertEqual(children[1]["parent_id"], forms[0]["form_id"])
        self.assertEqual(children[1]["type"], "form")
        self.assertEqual(parents[-1]["type"], "form")
        self.assertEqual(len(children[1]["regions"]), 4)

    def test_page_rebuild_uses_span_order(self):
        chunks = [dict(text="left RIGHT", page=1, source_spans=[dict(page=1, start=0, end=4), dict(page=2, start=5, end=10)]),
                  dict(text="again", page=2, source_spans=[])]
        self.assertEqual(page_texts(chunks), {1: "left", 2: "RIGHT\nagain"})

    def test_cross_page_passage_splits_when_report_context_changes(self):
        chunks = [dict(text="first second", page=1, pages=[1, 2], regions=[],
                       source_spans=[dict(page=1, start=0, end=5), dict(page=2, start=6, end=12)])]
        contexts = {1: {"report_date": "today", "well": "A"}, 2: {"report_date": "tomorrow", "well": "A"}}
        split = separate_contexts(chunks, contexts)
        self.assertEqual([row["text"] for row in split], ["first", "second"])
        self.assertEqual(page_texts(chunks), page_texts(split))
        self.assertEqual(len(separate_contexts(chunks, {1: CONTEXT, 2: CONTEXT})), 1)

    def test_serialization_rounds_geometry_only(self):
        value = {"bbox": [1.00001, 2.99999, 3.0, 4.0], "threshold": .12345, "text": "1.00001", "width": 600.004}
        self.assertEqual(canonical(value), {"bbox": [1.0, 3.0, 3.0, 4.0], "threshold": .12345, "text": "1.00001", "width": 600.0})

    def test_ids_follow_the_k1_formats(self):
        table = dict(table_id=f"{FID}:t1", logical_id="sample#t0001", pages=[1])
        chunks = [corpus_chunk("Intro.", section_path=["A"]), corpus_chunk("Table text", type="table", table_id="sample#t0001",
                                                                           row_start=0, row_end=3),
                  corpus_chunk("More.", section_path=["B"]), corpus_chunk("Again.", section_path=["B"])]
        children, parents = map_children(FID, "sample", "other", chunks, [table], [], {})
        self.assertEqual(file_id("ab" * 32), "fabababababababab")
        for child in children:
            self.assertRegex(child["chunk_id"], rf"^{FID}:[stf][1-9][0-9]*:c[0-9]+$")
        for parent in parents:
            self.assertRegex(parent["parent_id"], rf"^{FID}:[stf][1-9][0-9]*$")
        self.assertEqual([c["chunk_id"] for c in children], [f"{FID}:s1:c0", f"{FID}:t1:c0", f"{FID}:s3:c0", f"{FID}:s3:c1"])

    def test_table_chunks_keep_their_row_range_and_parent(self):
        table = dict(table_id=f"{FID}:t1", logical_id="sample#t0001", pages=[1])
        chunk = corpus_chunk("Table text", type="table", table_id="sample#t0001", row_start=2, row_end=5)
        children, parents = map_children(FID, "sample", "other", [chunk], [table], [], {})
        self.assertEqual((children[0]["table_id"], children[0]["row_start"], children[0]["row_end"]), (f"{FID}:t1", 2, 5))
        self.assertEqual(children[0]["parent_id"], f"{FID}:t1")
        self.assertEqual(parents[0]["type"], "table")

    def test_child_indices_are_contiguous_and_offsets_cover_the_joined_text(self):
        chunks = [corpus_chunk(f"Passage {n}.") for n in range(4)]
        children, _ = map_children(FID, "sample", "other", chunks, [], [], {})
        self.assertEqual([c["child_index"] for c in children], [0, 1, 2, 3])
        joined = "\n\n".join(c["text"] for c in children)
        self.assertTrue(all(joined[c["char_start"]:c["char_end"]] == c["text"] for c in children))


def make_pdf(path: Path, pages: int = 2, width: int = 600) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=width, height=1000)
    writer.write(path)
    return path


def add_sample(corpus: Corpus, root: Path, doc_id: str, fingerprint: str, process: bool = True, width: int = 600) -> dict:
    pdf = make_pdf(root / f"{doc_id}.pdf", width=width)
    status, added = corpus.add_file(pdf, doc_id=doc_id, license_id="CC-BY-4.0", license_url="https://creativecommons.org/licenses/by/4.0/")
    assert status == "added", added
    if not process:
        return next(doc for doc in corpus.documents() if doc["doc_id"] == doc_id)
    document = make_document(2)
    add_text(document, "Overview", label=DocItemLabel.SECTION_HEADER)
    add_text(document, "First passage on page one.")
    add_table(document, rows=4)
    add_text(document, "Second passage on page two.", page=2)
    doc = next(doc for doc in corpus.documents() if doc["doc_id"] == doc_id)
    analysis = [SimpleNamespace(to_dict=lambda n=n: {"page": n, "mode": "text", "reasons": ["text_layer_ok"]}) for n in (1, 2)]
    meta = {"mode": "text", "pages": (1, 2), "status": "success", "seconds": 1.0, "confidence": {}, "errors": []}
    with patch("graph_builder.corpus.process.analyze_pdf", return_value=analysis), \
            patch("graph_builder.corpus.process.convert_segment", return_value=(document, meta)):
        process_document(str(corpus.root), doc, corpus.config, fingerprint, OCR, "models")
    corpus.record_job(doc_id, fingerprint, "done", None, "start", 1.0, {})
    return doc


class PackageCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        config = load_config(ROOT / "configs/corpus/default.json")
        self.corpus = Corpus.create(self.root / "corpus", config)
        self.fingerprint = make_fingerprint(self.corpus.config, {})
        patcher = patch("graph_builder.corpus.ocr_engines.engine_fingerprint", return_value=OCR)
        patcher.start()
        self.addCleanup(patcher.stop)

    def export(self, name="one", only=None, config=K1_CONFIG):
        return Path(export_k1(self.corpus, name, Path("models"), config, only=only)["export"])


class SchemaTests(PackageCase):
    def test_every_schema_is_valid_accepts_a_real_row_and_rejects_a_broken_one(self):
        add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        release = self.export()
        singular = {"files": "file", "pages": "page", "tables": "table", "forms": "form", "parents": "parent", "chunks": "chunk"}
        for group in GROUPS:
            schema = json.loads((SCHEMAS / f"k1_{singular[group]}.schema.json").read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            self.assertEqual(schema["$id"], f"k1_{singular[group]}.schema.json")
            validator = Draft202012Validator(schema)
            rows = [json.loads(line) for line in (release / f"{group}.jsonl").read_text(encoding="utf-8").splitlines()]
            if group == "forms":
                rows = [self.valid_form()]
            self.assertTrue(rows, group)
            self.assertEqual(list(validator.iter_errors(rows[0])), [], group)
            broken = dict(rows[0])
            broken.pop(next(iter(schema["required"])))
            self.assertTrue(list(validator.iter_errors(broken)), group)
            self.assertTrue(list(validator.iter_errors(dict(rows[0], unexpected=1))), group)

    @staticmethod
    def valid_form():
        field = dict(key="Report For", value="31-Aug-16", key_bbox=[1, 1, 2, 2], value_bbox=[3, 1, 5, 2], verified=True)
        return dict(form_id=f"{FID}:f1", file_id=FID, doc_id="sample", page=1, status="success", fields=[field],
                    reference_text="Report For 31-Aug-16", header_boundary=100.0, bbox_frame="displayed physical page",
                    rotation=0, text_layer_only=True, visible_glyph_clipping=True, method="rimbase_template",
                    verified=True, template_label_share=0.5, template_minimum_share=0.4)

    def test_chunk_schema_checks_ids_types_and_context_keys(self):
        add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        release = self.export()
        chunk = json.loads((release / "chunks.jsonl").read_text(encoding="utf-8").splitlines()[0])
        validator = Draft202012Validator(json.loads((SCHEMAS / "k1_chunk.schema.json").read_text(encoding="utf-8")))
        self.assertEqual(list(validator.iter_errors(dict(chunk, type="form", context=CONTEXT))), [])
        for change in (dict(type="image"), dict(chunk_id="sample#c00001"), dict(doc_id="Sample"), dict(context={"day": "1"})):
            self.assertTrue(list(validator.iter_errors(dict(chunk, **change))), change)


class ExportTests(PackageCase):
    def test_two_exports_have_identical_checksums_and_validate(self):
        add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        first, second = self.export("one"), self.export("two")
        self.assertEqual((first / "SHA256SUMS").read_bytes(), (second / "SHA256SUMS").read_bytes())
        result = summary(first)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["page_rebuild_matches"], result["page_rebuild_total"])
        self.assertEqual(result["page_rebuild_total"], 2)
        self.assertEqual(result["counts"]["tables"], 1)
        self.assertEqual(result["counts"]["files"], 1)

    def test_package_has_no_paths_timestamps_or_crlf(self):
        add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        release = self.export()
        manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["format"], "K1")
        self.assertNotIn("created_at", manifest)
        for path in release.rglob("*"):
            if path.is_file():
                data = path.read_bytes()
                self.assertNotIn(b"\r", data, path.name)
                self.assertNotIn(str(self.root).encode(), data, path.name)
        files = [json.loads(line) for line in (release / "files.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(files[0]["text"], f"text/{files[0]['file_id']}.txt")
        self.assertEqual(files[0]["license"]["id"], "CC-BY-4.0")
        self.assertRegex(files[0]["file_id"], r"^f[0-9a-f]{16}$")

    def test_table_grid_and_row_range_come_from_the_corpus_table(self):
        add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        release = self.export()
        table = json.loads((release / "tables.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(table["grid"], [["Column"], ["Row 1"], ["Row 2"], ["Row 3"]])
        self.assertEqual(table["join"], {"reasons": [], "status": "single"})
        self.assertEqual((table["parts"][0]["row_start"], table["parts"][0]["row_end"]), (0, 4))
        self.assertRegex(table["table_id"], r"^f[0-9a-f]{16}:t1$")
        chunks = [json.loads(line) for line in (release / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
        corpus_chunks = [json.loads(line) for line in (self.corpus.work / "sample-report" / self.fingerprint / "chunks.jsonl")
                         .read_text(encoding="utf-8").splitlines()]
        table_chunks = [c for c in chunks if c["type"] == "table"]
        original = [c for c in corpus_chunks if c["type"] == "table"]
        self.assertEqual([(c["table_id"], c["row_start"], c["row_end"]) for c in table_chunks],
                         [(table["table_id"], c["row_start"], c["row_end"]) for c in original])

    def test_only_selects_documents_and_unknown_ids_fail(self):
        add_sample(self.corpus, self.root, "sample-first", self.fingerprint)
        add_sample(self.corpus, self.root, "sample-second", self.fingerprint, width=700)
        manifest = json.loads((self.export("both") / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual([d["doc_id"] for d in manifest["documents"]], ["sample-first", "sample-second"])
        manifest = json.loads((self.export("one", only=["sample-second"]) / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual([d["doc_id"] for d in manifest["documents"]], ["sample-second"])
        self.assertEqual(manifest["held_back"], [])
        with self.assertRaises(K1CompletenessError) as caught:
            export_k1(self.corpus, "three", Path("models"), K1_CONFIG, only=["nothing"])
        self.assertEqual(caught.exception.report["blocked_documents"][0]["reason"], "unknown_required_document")

    def test_unprocessed_required_document_blocks_publication(self):
        add_sample(self.corpus, self.root, "sample-first", self.fingerprint)
        add_sample(self.corpus, self.root, "sample-pending", self.fingerprint, process=False, width=700)
        with self.assertRaises(K1CompletenessError) as caught:
            self.export()
        report = caught.exception.report
        self.assertEqual(report["missing_document_ids"], ["sample-pending"])
        self.assertEqual(report["blocked_documents"][0]["status"], "NOT_PROCESSED")
        self.assertFalse((self.corpus.exports/"one/CURRENT.json").exists())

    def test_names_and_legacy_map_without_its_document_are_refused(self):
        with self.assertRaises(ValueError):
            export_k1(self.corpus, "Bad Name", Path("models"), K1_CONFIG)
        add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        with self.assertRaisesRegex(ValueError, f"needs the document {LEGACY_DOCUMENT}"):
            export_k1(self.corpus, "name", Path("models"), K1_CONFIG, legacy_chunks=Path("chunks.jsonl"))

    def test_legacy_chunk_ids_are_mapped_checksummed_and_validated(self):
        add_sample(self.corpus, self.root, LEGACY_DOCUMENT, self.fingerprint)
        legacy = self.root / "legacy.jsonl"
        rows = [dict(doc_id=LEGACY_DOCUMENT, chunk_id=f"{LEGACY_DOCUMENT}#c000{n}", page=page, text=text)
                for n, (page, text) in enumerate([(1, "First passage  on page one."), (2, "Second passage on page two."),
                                                  (2, "Not in the new package")])]
        rows.append(dict(doc_id="other", chunk_id="other#c0000", page=1, text="First passage on page one."))
        legacy.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n")
        result = export_k1(self.corpus, "mapped", Path("models"), K1_CONFIG, legacy_chunks=legacy)
        self.assertEqual({k: result["legacy_map"][k] for k in ("old_chunks", "exact", "near", "unmapped")},
                         {"old_chunks": 3, "exact": 2, "near": 0, "unmapped": 1})
        release = Path(result["export"])
        records = json.loads((release / LEGACY_MAP).read_text(encoding="utf-8"))
        self.assertEqual([r["method"] for r in records], ["exact", "exact", "unmapped"])
        self.assertIn(LEGACY_MAP, (release / "SHA256SUMS").read_text(encoding="utf-8"))
        self.assertEqual(validate_k1(release), [])
        chunk_ids = {json.loads(line)["chunk_id"] for line in (release / "chunks.jsonl").read_text(encoding="utf-8").splitlines()}
        self.assertTrue({r["new_chunk_id"] for r in records if r["new_chunk_id"]} <= chunk_ids)


class CompletenessGateTests(PackageCase):
    def test_guard_blocks_and_preserves_previous_current_and_source_counts(self):
        from graph_builder.corpus.k1_build import ReportBoundaryError
        doc = add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        release = self.export()
        pointer = self.corpus.exports / "one/CURRENT.json"
        previous = pointer.read_bytes()
        old_releases = list((pointer.parent / "releases").iterdir())
        with patch("graph_builder.corpus.k1_export.build_document", side_effect=ReportBoundaryError("ambiguous", page=1)), \
             patch("graph_builder.corpus.k1_export.publish") as publish:
            with self.assertRaises(K1CompletenessError) as caught:
                self.export()
        publish.assert_not_called()
        self.assertEqual(pointer.read_bytes(), previous)
        self.assertEqual(list((pointer.parent / "releases").iterdir()), old_releases)
        self.assertEqual(validate_k1(release), [])
        report = json.loads(caught.exception.report_path.read_text(encoding="utf-8"))
        self.assertFalse(report["published"])
        held = report["blocked_documents"][0]
        self.assertEqual(held["status"], "BLOCKED")
        self.assertEqual(held["sha256"], doc["sha256"])
        self.assertEqual(held["source"], doc["source"])
        self.assertEqual(held["detail"], dict(reason="ambiguous", page=1))
        self.assertEqual(held["pages_held"], 2)
        original = (self.corpus.work / doc["doc_id"] / self.fingerprint / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(held["corpus_chunks_held"], len(original))
        self.assertEqual(report["counts"]["corpus_chunks_held_known"],len(original))
        self.assertEqual(report["counts"]["pages_held_known"],2)
        self.assertEqual(report["counts"]["k1_chunks_held_unknown_documents"],1)
        self.assertIsNone(held["k1_chunks_held"])
        self.assertTrue(held["source_references"][0]["source_spans"])

    def test_zero_chunks_explicit_block_and_page_or_identity_loss_block(self):
        import copy
        from graph_builder.corpus.k1_build import build_document
        doc = add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        built = build_document(self.corpus,doc,self.fingerprint,K1_CONFIG)
        for label in ("zero_chunks", "explicit_block", "missing_page", "missing_page_content", "wrong_identity"):
            with self.subTest(label=label):
                changed = copy.deepcopy(built)
                if label == "zero_chunks":
                    changed["chunks"] = []
                elif label == "explicit_block":
                    changed["status"] = "UNSUPPORTED"
                elif label == "missing_page":
                    changed["pages"].pop()
                elif label == "missing_page_content":
                    changed["pages"][0]["status"] = "missing"
                else:
                    changed["files"][0]["sha256"] = "0" * 64
                with patch("graph_builder.corpus.k1_export.build_document", return_value=changed), \
                     patch("graph_builder.corpus.k1_export.publish") as publish:
                    with self.assertRaises(K1CompletenessError) as caught:
                        self.export(label)
                publish.assert_not_called()
                held = caught.exception.report["blocked_documents"][0]
                self.assertEqual(held["k1_chunks_held"],len(changed["chunks"]))
                self.assertFalse((self.corpus.exports / label / "CURRENT.json").exists())

    def test_schema_valid_empty_package_cannot_bypass_required_document_gate(self):
        add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        source = self.export()
        empty = self.root / "valid-empty"
        shutil.copytree(source,empty)
        for group in GROUPS:
            (empty / f"{group}.jsonl").write_text("",encoding="utf-8")
        manifest = json.loads((empty / "manifest.json").read_text(encoding="utf-8"))
        manifest.update(counts={g:0 for g in GROUPS},documents=[])
        (empty / "manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
        ValidationTests.rewrite_sums(empty)
        self.assertEqual(validate_k1(empty), [])
        built = {g:[] for g in GROUPS}
        with patch("graph_builder.corpus.k1_export.build_document",return_value=built), \
             patch("graph_builder.corpus.k1_export.validate_k1",return_value=[]), \
             patch("graph_builder.corpus.k1_export.publish") as publish:
            with self.assertRaises(K1CompletenessError):
                self.export("missing")
        publish.assert_not_called()

    def test_failed_job_build_error_and_unknown_required_document_are_reported(self):
        doc = add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        self.corpus.record_job(doc["doc_id"],self.fingerprint,"failed","fixture failure","start",1,{})
        with self.assertRaises(K1CompletenessError) as caught:
            self.export("failed")
        self.assertEqual(caught.exception.report["blocked_documents"][0]["detail"],"fixture failure")
        self.assertEqual(caught.exception.report["blocked_documents"][0]["status"],"FAILED")
        self.corpus.record_job(doc["doc_id"],self.fingerprint,"done",None,"start",1,{})
        with patch("graph_builder.corpus.k1_export.build_document",side_effect=ValueError("bad source")):
            with self.assertRaises(K1CompletenessError) as caught:
                self.export("builder")
        self.assertEqual(caught.exception.report["blocked_documents"][0]["reason"],"k1_build_failed")
        with self.assertRaises(K1CompletenessError) as caught:
            self.export("unknown",only=[doc["doc_id"],"absent-source"])
        self.assertEqual(caught.exception.report["missing_document_ids"],["absent-source"])
        self.assertIsNone(caught.exception.report["blocked_documents"][0]["pages_held"])

    def test_cli_returns_nonzero_and_keeps_current_on_block(self):
        from graph_builder.corpus.__main__ import main
        from graph_builder.corpus.k1_build import ReportBoundaryError
        add_sample(self.corpus,self.root,"sample-report",self.fingerprint)
        self.export()
        pointer = self.corpus.exports / "one/CURRENT.json"
        previous = pointer.read_bytes()
        with patch("graph_builder.corpus.__main__.setup_logging",return_value=None), \
             patch("graph_builder.corpus.k1_export.build_document",side_effect=ReportBoundaryError("ambiguous")):
            result = main(["k1",str(self.corpus.root),"--name","one","--models","models"])
        self.assertEqual(result,1)
        self.assertEqual(pointer.read_bytes(),previous)
        self.assertEqual(len(list((self.corpus.exports/".k1-failures").glob("*/failure.json"))),1)

    def test_unsupported_format_and_broken_builder_report_without_publish(self):
        doc = add_sample(self.corpus,self.root,"sample-report",self.fingerprint)
        unsupported = dict(doc,format="text")
        with patch.object(self.corpus,"documents",return_value=[unsupported]):
            with self.assertRaises(K1CompletenessError) as caught:
                self.export("unsupported")
        held = caught.exception.report["blocked_documents"][0]
        self.assertEqual(held["status"],"UNSUPPORTED")
        self.assertEqual(held["reason"],"unsupported_format")
        with patch("graph_builder.corpus.k1_export.build_document",return_value={}):
            with self.assertRaises(K1CompletenessError) as caught:
                self.export("broken")
        self.assertEqual(caught.exception.report["blocked_documents"][0]["reason"],"k1_build_failed")

    def test_failure_before_first_release_does_not_poison_later_complete_export(self):
        add_sample(self.corpus,self.root,"sample-report",self.fingerprint,process=False)
        with self.assertRaises(K1CompletenessError):
            self.export("retry")
        self.assertFalse((self.corpus.exports/"retry").exists())
        # Reuse a separate processed fixture as the explicit required scope.
        add_sample(self.corpus,self.root,"sample-ready",self.fingerprint,width=700)
        release = self.export("retry",only=["sample-ready"])
        self.assertEqual(validate_k1(release),[])
        self.assertTrue((self.corpus.exports/"retry/CURRENT.json").exists())


class ValidationTests(PackageCase):
    def published_copy(self):
        add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        copy = self.root / "copy"
        shutil.copytree(self.export(), copy)
        return copy

    @staticmethod
    def rewrite_sums(directory: Path):
        files = sorted(p for p in directory.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
        (directory / "SHA256SUMS").write_text("".join(f"{file_sha256(p)}  {p.relative_to(directory).as_posix()}\n" for p in files),
                                              encoding="utf-8", newline="\n")

    def replace_in(self, directory: Path, name: str, old: str, new: str):
        path = directory / name
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")

    def test_a_pristine_copy_passes(self):
        self.assertEqual(validate_k1(self.published_copy()), [])

    def test_changed_checksum_is_named(self):
        copy = self.published_copy()
        self.replace_in(copy, "chunks.jsonl", "First passage", "Third passage")
        errors = validate_k1(copy)
        self.assertIn("chunks.jsonl: SHA256 differs from SHA256SUMS", errors)

    def test_changed_chunk_text_is_named_even_with_matching_checksums(self):
        copy = self.published_copy()
        self.replace_in(copy, "chunks.jsonl", "First passage", "Third passage")
        self.rewrite_sums(copy)
        errors = validate_k1(copy)
        self.assertTrue(any(re.search(r"chunks .*:s\d+:c\d+: text offset mismatch", e) for e in errors), errors)
        self.assertTrue(any("sha256 differs from its text" in e for e in errors), errors)

    def test_file_missing_from_the_sums_is_reported(self):
        copy = self.published_copy()
        (copy / "extra.txt").write_text("x", encoding="utf-8")
        self.assertIn("extra.txt: not listed in SHA256SUMS", validate_k1(copy))

    def test_page_rebuild_difference_is_reported(self):
        copy = self.published_copy()
        path = copy / "pages.jsonl"
        path.write_text(re.sub(r'"filtered_text_sha256":"[0-9a-f]{64}"', f'"filtered_text_sha256":"{"0" * 64}"',
                               path.read_text(encoding="utf-8"), count=1), encoding="utf-8", newline="\n")
        self.rewrite_sums(copy)
        result = summary(copy)
        self.assertEqual((result["page_rebuild_matches"], result["page_rebuild_total"]), (1, 2))
        self.assertTrue(any("page rebuild differs" in e for e in result["errors"]), result["errors"])

    def test_schema_violation_is_named(self):
        copy = self.published_copy()
        self.replace_in(copy, "chunks.jsonl", '"type":"text"', '"type":"image"')
        self.rewrite_sums(copy)
        self.assertTrue(any(e.startswith("chunks ") and "'image' is not one of" in e for e in validate_k1(copy)))

    def test_unknown_parent_is_named(self):
        copy = self.published_copy()
        self.replace_in(copy, "parents.jsonl", '"parent_id":"', '"parent_id":"x')
        self.rewrite_sums(copy)
        errors = validate_k1(copy)
        self.assertTrue(any(e.startswith("parents ") for e in errors), errors)

    def test_region_outside_the_page_is_reported(self):
        copy = self.published_copy()
        self.replace_in(copy, "pages.jsonl", '"height":1000.0', '"height":10.0')
        self.rewrite_sums(copy)
        self.assertTrue(any("region outside page" in e for e in validate_k1(copy)))

    def test_legacy_map_must_point_at_existing_chunks(self):
        copy = self.published_copy()
        (copy / "legacy_chunk_ids.json").write_text(json.dumps([{"old_chunk_id": "a#c0001", "new_chunk_id": "missing"}]),
                                                    encoding="utf-8", newline="\n")
        self.rewrite_sums(copy)
        self.assertTrue(any("points to missing chunk" in e for e in validate_k1(copy)))


class ContextTests(PackageCase):
    def run_with(self, contexts, missing):
        add_sample(self.corpus, self.root, "sample-dailyreport", self.fingerprint)
        with patch("graph_builder.corpus.k1_build.report_contexts", return_value=(contexts, [], missing)):
            return self.export()

    def test_full_coverage_is_reported_per_document(self):
        release = self.run_with({1: CONTEXT, 2: CONTEXT}, [])
        manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
        coverage = manifest["context_coverage"]["sample-dailyreport"]
        self.assertGreater(coverage["chunks"], 0)
        self.assertEqual(coverage["chunks"], coverage["with_context"])
        self.assertEqual(manifest["pages_without_context"], [])
        self.assertEqual(summary(release)["context_coverage"], manifest["context_coverage"])

    def test_pages_without_context_are_exceptions_named_in_the_manifest(self):
        release = self.run_with({1: CONTEXT}, [2])
        manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["pages_without_context"], [{"doc_id": "sample-dailyreport", "page": 2}])
        coverage = manifest["context_coverage"]["sample-dailyreport"]
        self.assertEqual(coverage["with_context"], coverage["chunks"] - 1)
        self.assertEqual(validate_k1(release), [])
        copy = self.root / "copy"
        shutil.copytree(release, copy)
        manifest["pages_without_context"] = []
        (copy / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
        ValidationTests.rewrite_sums(copy)
        self.assertTrue(any("daily report chunk without report_date and well" in e for e in validate_k1(copy)))

    def test_other_document_types_need_no_context(self):
        add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        release = self.export()
        self.assertEqual(json.loads((release / "manifest.json").read_text(encoding="utf-8"))["context_coverage"], {})
        self.assertEqual(validate_k1(release), [])


DOCUMENT_CONTEXT = {"document_types": ["eowr"], "pages": 1,
                    "well_patterns": ["(?m)^[ \\t]*(?:.*\\bWell[ \\t]+)?([A-Z]{1,4}-\\d{1,3}|\\d{1,3}-\\d{1,3})[ \\t]*$"]}


class DocumentContextTests(PackageCase):
    """Optional document_context: the well of an end-of-well report on every one of its chunks (D1)."""

    def run_with(self, cover, config=None):
        add_sample(self.corpus, self.root, "sample_eowr", self.fingerprint)
        config = config if config is not None else dict(K1_CONFIG, document_context=DOCUMENT_CONTEXT)
        with patch("graph_builder.corpus.report_context.pdf_page_texts", return_value={1: cover}):
            result = export_k1(self.corpus, "one", Path("models"), config)
        release = Path(result["export"])
        chunks = [json.loads(line) for line in (release / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
        return result, release, json.loads((release / "manifest.json").read_text(encoding="utf-8")), chunks

    def test_every_chunk_carries_the_well_of_the_cover_page(self):
        result, release, manifest, chunks = self.run_with("Akutan Geothermal Project\r\nAK-3\r\nEnd of Well Report\r\n")
        self.assertTrue(chunks)
        self.assertEqual({json.dumps(chunk["context"]) for chunk in chunks}, {json.dumps({"well": "AK-3"})})
        self.assertEqual(manifest["context_coverage"]["sample_eowr"], {"chunks": len(chunks), "with_context": len(chunks)})
        self.assertEqual(manifest["pages_without_context"], [])
        self.assertEqual(result["document_context"], {"sample_eowr": {"well": "AK-3", "candidates": ["AK-3"]}})
        self.assertEqual(validate_k1(release), [])

    def test_unresolved_well_lists_the_pages_and_the_validator_requires_them(self):
        result, release, manifest, chunks = self.run_with("AK-3\nTG-2\nEnd of Well Report")
        self.assertEqual(result["document_context"]["sample_eowr"], {"well": "", "candidates": ["AK-3", "TG-2"]})
        self.assertTrue(all(chunk["context"] == {} for chunk in chunks))
        self.assertEqual(manifest["pages_without_context"], [{"doc_id": "sample_eowr", "page": 1}, {"doc_id": "sample_eowr", "page": 2}])
        self.assertEqual(validate_k1(release), [])
        copy = self.root / "copy"
        shutil.copytree(release, copy)
        manifest["pages_without_context"] = []
        (copy / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
        ValidationTests.rewrite_sums(copy)
        self.assertTrue(any("eowr chunk without well" in e for e in validate_k1(copy)))

    def test_without_the_option_end_of_well_chunks_stay_without_context(self):
        result, release, manifest, chunks = self.run_with("AK-3\nEnd of Well Report", config=K1_CONFIG)
        self.assertTrue(all(chunk["context"] == {} for chunk in chunks))
        self.assertEqual(manifest["context_coverage"], {})
        self.assertNotIn("document_context", result)
        self.assertNotIn("document_context", manifest["config"]["k1"])


if __name__ == "__main__":
    unittest.main()
