"""``python -m graph_builder.corpus qa <corpus_dir> --release <release_dir> [--out <dir>]``."""
from __future__ import annotations

from functools import cache
import json
from pathlib import Path

from filelock import FileLock

from ..ocr_engines import DEFAULT_MODELS
from .handoff import MANIFEST, VIEW, seal_view, source_problems
from .ledger import LEDGER_NAME, SUMMARY_NAME, build_qa

DEFAULT_OUT_ROOT = Path("data/interim/qa")
QA_ARTIFACTS = (MANIFEST, VIEW, "cell_evidence.jsonl", "cell_evidence_summary.json", "compound-span-projection.json",
                LEDGER_NAME, SUMMARY_NAME)


def run(corpus_dir: Path | None, release: Path | None, out: Path | None, config: Path | None, sidecar: Path | None,
        *, release_only: bool = False, **options) -> dict:
    if release is None:
        raise ValueError("qa requires --release <release_dir>")
    release = release.resolve()
    name = release.name + ("-diagnostics" if release_only else "")
    out_dir = (out or DEFAULT_OUT_ROOT / name).resolve()
    if out_dir.is_relative_to(release) or (out_dir / "SHA256SUMS").exists():
        raise ValueError("QA output must be outside K1 releases")
    out_dir.mkdir(parents=True, exist_ok=True)
    with FileLock(str(out_dir / ".qa.lock")):
        # Withdraw the old handoff before checking anything in the new attempt.
        for name in QA_ARTIFACTS:
            (out_dir / name).unlink(missing_ok=True)
        try:
            return _run(corpus_dir, release, out_dir, config, sidecar, release_only=release_only, **options)
        except BaseException:
            for name in QA_ARTIFACTS:
                (out_dir / name).unlink(missing_ok=True)
            raise


def _run(corpus_dir: Path | None, release: Path, out_dir: Path, config: Path | None, sidecar: Path | None,
        fidelity: bool = False, crossrep: bool = False, ops_margin: bool = False, annotations: bool = False,
        label_value: bool = False, form_conflict: bool = False, orientation: bool = False,
        form_overlap: bool | None = None, table_overlap: bool | None = None, cell_evidence: bool = False, *,
        table_tokenizer_path: Path | None = None, max_table_tokens: int | None = None,
        ruled_table_overlap: bool | None = None, compact_table_spans: bool | None = None,
        ruled_native_margin: bool = True, models: Path = DEFAULT_MODELS, release_only: bool = False) -> dict:
    if not (release / "manifest.json").is_file():
        raise ValueError(f"not a K1 release directory (manifest.json missing): {release}")
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    k1 = manifest.get("config", {}).get("k1", {})
    forms, rules = k1.get("forms", {}), k1.get("table_rules", {})
    default_form = bool(forms.get("daily_header") or forms.get("missing_report_fields") or k1.get("form_recognition"))
    default_hourly = "hourly_operations" in rules
    default_ruled = bool({"mud_properties", "casing", "ruled_panels"} & rules.keys())
    review_numeric = bool(k1.get("numeric_cell_focus"))
    form_overlap = default_form if form_overlap is None else form_overlap
    table_overlap = default_hourly if table_overlap is None else table_overlap
    ruled_table_overlap = default_ruled if ruled_table_overlap is None else ruled_table_overlap
    compact_table_spans = "ruled_panels" in rules if compact_table_spans is None else compact_table_spans
    joined_tables_enabled = bool(k1.get("table_join"))
    if corpus_dir is not None and not corpus_dir.is_dir():
        corpus_dir = None
    registry = None
    if crossrep:  # opt-in: compares the representations inside the release (A-403); reads only the release
        from .crossrep import register_crossrep
        from .ledger import default_registry
        registry = register_crossrep(default_registry())
    if fidelity:  # opt-in: reads the source PDFs, so the default ledger stays independent of them
        from .fidelity import register_fidelity
        from .ledger import default_registry
        registry = register_fidelity(registry or default_registry(), corpus_dir=corpus_dir)
    if ops_margin:  # opt-in: reads the source PDFs (A-401a); WARN signals only
        from .ledger import default_registry
        from .opsmargin import register_ops_margin
        registry = register_ops_margin(registry or default_registry(), corpus_dir=corpus_dir)
    if annotations:  # opt-in: reads the source PDFs (A-414); INFO signals and completeness PARTIAL_IN_SOURCE only
        from .annotations import register_annotations
        from .ledger import default_registry
        registry = register_annotations(registry or default_registry(), corpus_dir=corpus_dir)
    if label_value:  # opt-in (A-432): reads the source PDFs; WARN signal only
        from .labelvalue import register_label_value
        from .ledger import default_registry
        registry = register_label_value(registry or default_registry(), corpus_dir=corpus_dir)
    if form_conflict:  # opt-in (A-435): reads only the release; WARN signal only
        from .formconflict import register_form_conflict
        from .ledger import default_registry
        registry = register_form_conflict(registry or default_registry())
    if form_overlap:
        from .form_overlap import FormOverlap, register_form_overlap
        from .ledger import default_registry
        @cache
        def overlap() -> FormOverlap:
            return FormOverlap(release)

        registry = register_form_overlap(registry or default_registry(), overlap)
    if table_overlap:
        from .table_overlap import TableOverlap, register_table_overlap
        from .ledger import default_registry

        @cache
        def table_projection() -> TableOverlap:
            return TableOverlap(release, corpus_dir)

        registry = register_table_overlap(registry or default_registry(), table_projection)
    if cell_evidence or ruled_table_overlap:
        from .cell_evidence import CellEvidence, register_cell_evidence
        from .ledger import default_registry

        @cache
        def source_evidence() -> CellEvidence:
            return CellEvidence(release, corpus_dir, models=models)

        if cell_evidence:
            registry = register_cell_evidence(registry or default_registry(), source_evidence)
    if ruled_table_overlap:
        from .ledger import default_registry
        from .ruled_overlap import RuledOverlap, register_ruled_overlap

        @cache
        def ruled_projection() -> RuledOverlap:
            return RuledOverlap(release, corpus_dir, source_evidence, table_projection() if table_overlap else None,
                                native_margin=ruled_native_margin)

        registry = register_ruled_overlap(registry or default_registry(), ruled_projection)
    if orientation:  # opt-in (C-03): reads the orientation records stored in the work folder; WARN/INFO signals only
        from .ledger import default_registry
        from .orientation import register_orientation
        registry = register_orientation(registry or default_registry())
    try:
        budget = {"table_tokenizer_path": table_tokenizer_path, "max_table_tokens": max_table_tokens} if table_tokenizer_path is not None or max_table_tokens is not None else {}
        result = build_qa(release, out_dir, corpus_dir=corpus_dir, config_path=config, sidecar_path=sidecar, registry=registry, **budget)
        if result["validator"] != "pass":
            return result
        if release_only:
            result["source_validation"] = {"status": "diagnostic_only"}
        else:
            problems = source_problems(release, corpus_dir, manifest.get("corpus_fingerprint", ""))
            from ..k1_export import pdf_readers

            readers = pdf_readers(k1)
            if manifest.get("pdf_readers", readers) != readers:
                problems.append("QA PDF readers differ from the versions used to export K1.")
            if expected := manifest.get("scan_readers"):
                from ..scan_fields import scan_runtime

                if scan_runtime(models.resolve()) != expected:
                    problems.append("QA scan readers differ from the versions used to export K1.")
            if result["signals"].get("QA_ERROR") or result["signals"].get("FIDELITY_NO_REFERENCE"):
                problems.append("QA encountered a check error or an unreadable PDF reference. See the ledger.")
            result["source_validation"] = {"status": "fail", "errors": problems} if problems else {"status": "pass"}
            if problems:
                return result
        if cell_evidence:
            result["cell_evidence"] = source_evidence().write(out_dir)
        if release_only:
            return result
        if joined_tables_enabled:
            from .table_headers import continuation_headers
            headers = continuation_headers(release)
        else:
            headers = {}
        if result["source_validation"]["status"] == "pass":
            from ..store import atomic_write_jsonl, read_jsonl
            from .form_overlap import VIEW_KEYS

            path = out_dir / VIEW
            details = {}
            if form_overlap:
                state = overlap()
                rows = state.retrieval_rows()
                details["duplicate_fields_removed"] = sum(map(len, state.removed.values()))
            else:
                rows = ({**{key: chunk[key] for key in VIEW_KEYS if key in chunk}, "text": chunk["text"]}
                        for chunk in read_jsonl(release / "chunks.jsonl"))
            if table_overlap:
                state = table_projection()
                rows = state.project(rows)
                details.update(state.summary())
            if ruled_table_overlap:
                state = ruled_projection()
                rows = state.project(rows)
                details.update(state.summary())
            if headers:
                from .table_headers import add_continuation_headers
                rows = add_continuation_headers(rows, headers)
            compacted = []
            if compact_table_spans:
                from .compound_spans import project
                max_chars = manifest.get("config", {}).get("corpus", {}).get("chunking", {}).get("max_chars", 1500)
                rows = project(rows, release, max_chars, compacted)
            numeric_reviews = []
            if review_numeric:
                from .numeric_review import project as project_numeric_review

                rows = project_numeric_review(rows, release, manifest, numeric_reviews)
            result["retrieval_view"] = {"path": str(path), "chunks": atomic_write_jsonl(path, rows), **details}
            if numeric_reviews:
                result["retrieval_view"]["numeric_cells_marked_unverified"] = sum(len(row["cells"]) for row in numeric_reviews)
            if compact_table_spans:
                result["retrieval_view"].update(compacted_table_chunks=len(compacted),
                                                compacted_span_positions=sum(len(item["removed_positions"]) for item in compacted))
            if compacted:
                from ..store import atomic_write_json
                sidecar = out_dir / "compound-span-projection.json"
                atomic_write_json(sidecar, {"release": manifest["identity"], "edits": compacted})
                result["retrieval_view"]["compound_spans"] = str(sidecar)
            result["retrieval_view"]["manifest"] = str(seal_view(release, path, result["retrieval_view"]["chunks"]))
        return result
    finally:
        if registry is not None:
            from .fidelity import close_fidelity
            from .labelvalue import close_label_value
            close_fidelity(registry)
            close_label_value(registry)


def main_text(result: dict) -> str:
    return json.dumps(result, sort_keys=True)
