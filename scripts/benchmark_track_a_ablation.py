"""Ablate Track A post-conversion options on pinned Docling snapshots and controls."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import csv
from dataclasses import dataclass, field
import hashlib
import json
import math
from multiprocessing import get_context
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter, process_time
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

import pymupdf
from docling_core.types.doc import BoundingBox, DoclingDocument, ProvenanceItem, Size, TableCell, TableData

from graph_builder.corpus import process
from graph_builder.corpus.catalog import Corpus
from graph_builder.corpus.config import fingerprint, load_config, validate_config
from graph_builder.corpus.k1_config import load_k1_config, validate_k1_config
from graph_builder.corpus.k1_export import K1CompletenessError, export_k1
from graph_builder.corpus.ocr_engines import engine_fingerprint
from graph_builder.corpus.qa.cli import run as run_qa
from graph_builder.corpus.qa.fidelity import iter_jsonl, k1_page_texts, tokens
from graph_builder.corpus.store import file_sha256


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/corpus"
MODELS = ROOT / "data/interim/ocr_models"
UPSTREAM_REVISION = "4f00195b8dadbc1a67f4cefae6b619c47e4e515f"
EXTERNAL = ("2305.03393v1-pg9", "acroform_sample", "code_and_formula", "multi_page", "table_mislabeled_as_picture")
QA = ("fidelity", "crossrep", "ops_margin", "annotations", "label_value", "form_conflict", "orientation")
BOUNDS = {"well_label": "Well ID:", "report_label": "Report No:", "date_label": "Date:"}
PHASES = ("corpus", "k1", "qa")


@dataclass
class Sample:
    name: str
    cohort: str
    pdf: Path
    native: str | None
    pages: int
    critical: dict[int, list[str]]
    form_pairs: list[tuple[str, str]] = field(default_factory=list)
    source_metadata: dict = field(default_factory=dict)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def external_samples(checkout):
    actual = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    if actual != UPSTREAM_REVISION:
        raise ValueError(f"expected Docling {UPSTREAM_REVISION}, got {actual}")
    corpus = checkout / "tests/data/pdf"
    for name in EXTERNAL:
        pdf = corpus / "sources" / f"{name}.pdf"
        snapshot = (corpus / "groundtruth" / f"{name}.json").read_text(encoding="utf-8")
        with pymupdf.open(pdf) as source:
            pages = len(source)
        if len(json.loads(snapshot)["pages"]) != pages:
            raise ValueError(f"{name}: source and snapshot page counts differ")
        yield Sample(name.replace(".", "-"), "external", pdf, snapshot, pages, {})


def native_samples(manifest, pdf_dir):
    seen = set()
    for entry in read_json(manifest)["documents"]:
        file = Path(entry["file"])
        if file.name != entry["file"]:
            raise ValueError(f"manifest PDF must be a filename: {file}")
        source = pdf_dir / file
        digest = file_sha256(source)
        if digest != entry["sha256"] or digest in seen:
            raise ValueError(f"wrong or repeated PDF digest: {source}")
        seen.add(digest)
        with pymupdf.open(source) as pdf:
            if len(pdf) != entry["pages"]:
                raise ValueError(f"unexpected PDF page count: {source}")
        critical = {int(page): values for page, values in entry["critical_phrases"].items()}
        metadata = {key: entry[key] for key in ("well", "family", "source_url")}
        metadata["input"] = "original_pdf"
        yield Sample(entry["doc_id"], "holdout", source, None, entry["pages"], critical, source_metadata=metadata)
    if not seen:
        raise ValueError("native manifest contains no PDFs")


def control_sample(root, name, stacked=False):
    """Create source and fixed native output with independently specified expected signals."""
    pdf_path = root / f"{name}.pdf"
    native = DoclingDocument(name=name)
    critical = {}
    with pymupdf.open() as pdf:
        for number in range(1, 2 if stacked else 4):
            page = pdf.new_page(width=600, height=800)
            native.add_page(page_no=number, size=Size(width=600, height=800))
            critical[number] = []

            def line(y, value, marker=""):
                x = 35
                draw = marker + " " + value if marker else value
                page.insert_text((x, y), draw, fontsize=10)
                box_width = pymupdf.get_text_length(draw, fontsize=10)
                prov = ProvenanceItem(page_no=number, bbox=BoundingBox(l=x, t=y - 9, r=x + box_width, b=y + 2),
                                      charspan=(0, len(draw)))
                if marker:
                    native.add_list_item(text=value, marker=marker, orig=draw, enumerated=True,
                                         parent=native.add_list_group(), prov=prov)
                    critical[number].append(draw)
                else:
                    native.add_text(label="text", text=value, prov=prov)

            if stacked:
                for top, well, date, index in [(100, "Alpha", "01-Jan-20", 1), (300, "Beta", "02-Jan-20", 2)]:
                    page.draw_rect(pymupdf.Rect(25, top, 450, top + 40))
                    line(top + 12, f"Well ID: {well}")
                    line(top + 26, f"Report No: {index}     Date: {date}")
                    statement = f"Valve {well} inspected at {1500 + index} ft."
                    line(top + 65, statement)
                    critical[number].append(statement)
                page.draw_line((25, 450), (450, 450))
            else:
                line(28, "Experimental Drilling Report")
                line(240, "Verify pressure before opening valve.", f"{number}.")
                line(266, f"Measured depth is {1500 + number} ft.")
                line(290, "Seal inspection ....")
                critical[number].append("Seal inspection")
                weather = f"Temp: {58 + number}"
                line(773, weather)
                critical[number].append(weather)
        pdf.save(pdf_path, no_new_id=True)
    return Sample(name, "control", pdf_path, native.model_dump_json(), len(critical), critical)


def continuation_sample(root):
    name = "continuation-control"
    pdf_path = root / f"{name}.pdf"
    native = DoclingDocument(name=name)
    with pymupdf.open() as pdf:
        for number, top, start, end in [(1, 600, 1, 9), (2, 90, 9, 14)]:
            page = pdf.new_page(width=600, height=800)
            native.add_page(page_no=number, size=Size(width=600, height=800))
            rows = [["Item", "Depth ft", "Pressure psi"]]
            rows.extend([[f"Row{index}", str(1500 + index), str(300 + index)] for index in range(start, end)])
            cells = []
            for row, values in enumerate(rows):
                for column, value in enumerate(values):
                    page.insert_text((50 + 150 * column, top + 14 * row), value, fontsize=9)
                    cells.append(TableCell(text=value, start_row_offset_idx=row, end_row_offset_idx=row + 1,
                                           start_col_offset_idx=column, end_col_offset_idx=column + 1,
                                           column_header=row == 0))
            prov = ProvenanceItem(page_no=number, bbox=BoundingBox(l=49, t=top - 8, r=499,
                                                                   b=top + 14 * (len(rows) - 1) + 3),
                                  charspan=(0, len(rows)))
            native.add_table(data=TableData(num_rows=len(rows), num_cols=3, table_cells=cells), prov=prov)
        pdf.save(pdf_path, no_new_id=True)
    return Sample(name, "control", pdf_path, native.model_dump_json(), 2, {})


def options():
    candidates = CONFIG / "candidates"
    filtering = read_json(candidates / "rimbase_filter_options_candidate.json")["filters"]
    processing = read_json(candidates / "rimbase_table_quarantine_candidate.json")["chunking"]
    k1 = load_k1_config()
    form_candidate = load_k1_config(candidates / "k1_form_recognition_v1.json")
    return {
        "keep_line_patterns": ("corpus", "filters.keep_line_patterns", filtering["keep_line_patterns"]),
        "running_line_position_tolerance": ("corpus", "filters.running_line_position_tolerance",
                                            filtering["running_line_position_tolerance"]),
        "running_line_min_pages": ("corpus", "filters.running_line_min_pages", 3),
        "toc_leader_min_dots": ("corpus", "filters.toc_leader_min_dots", filtering["toc_leader_min_dots"]),
        "table_markdown": ("corpus", "chunking.table_markdown", "span_once_keyed"),
        "preserve_list_markers": ("corpus", "chunking.preserve_list_markers", True),
        "label_value": ("corpus", "chunking.label_value", processing["label_value"]),
        "quarantine": ("corpus", "chunking.quarantine", processing["quarantine"]),
        "page_orientation": ("corpus", "analysis.page_orientation", {"mode": "flag"}),
        "cache_code_version": ("corpus", "cache", {"code_version": True}),
        "operations_summary": ("k1", "table_rules", {"operations_summary": k1["table_rules"]["operations_summary"]}),
        "generic_forms": ("k1", "forms.generic", True),
        "section_context": ("k1", "section_context", read_json(CONFIG / "section_context.json")),
        "form_recognition": ("k1", "form_recognition", form_candidate["form_recognition"]),
        "table_join": ("k1", "table_join", read_json(CONFIG / "table_join.json")),
        **{f"qa_{name}": ("qa", name, True) for name in QA},
        "report_boundaries": ("k1", "report_boundaries", BOUNDS),
        "form_blocks": ("k1", "form_blocks", read_json(CONFIG / "form_blocks.json")),
    }


def variants(flags):
    # These two branches cannot simply be added to a supported cumulative maximum.
    common = [name for name in flags if name not in {"report_boundaries", "form_blocks"}]
    yield "zero", "baseline", []
    for name in flags:
        yield f"single-{name}", "one_at_a_time", [name]
    for end, name in enumerate(common, 1):
        yield f"step-{end:02d}-{name}", "cumulative", common[:end]
    yield "max-without-generic", "follow_up", [name for name in common if name != "generic_forms"]
    yield "max-report-guard", "branch", [name for name in common if name != "table_join"] + ["report_boundaries"]
    yield "report-guard-without-generic", "follow_up", [
        name for name in common if name not in {"table_join", "generic_forms"}
    ] + ["report_boundaries"]
    yield "max-form-blocks", "branch", [name for name in common if name != "form_recognition"] + ["form_blocks"]
    yield "join-plus-report-guard", "conflict_probe", [
        name for name in common if name != "generic_forms"
    ] + ["report_boundaries"]
    yield "all-flags", "conflict_probe", list(flags)


def configs(enabled, flags):
    corpus = load_config(CONFIG / "default.json")
    corpus["ocr"].update(engine="rapidocr", languages=["en"])
    k1 = load_k1_config()
    k1.pop("table_rules", None)  # Make the shipped Operations Summary rule an explicit ablation.
    k1["forms"].pop("daily_header", None)  # Keep the recorded baseline and flag combinations comparable.
    k1["forms"].pop("missing_report_fields", None)
    layouts = {"corpus": corpus, "k1": k1, "qa": dict.fromkeys(QA, False)}
    for name in enabled:
        target, path, value = flags[name]
        node = layouts[target]
        *parents, key = path.split(".")
        for parent in parents:
            node = node[parent]
        node[key] = deepcopy(value)
    return validate_config(corpus), validate_k1_config(k1), layouts["qa"]


def register_corpus(root, config, samples):
    corpus = Corpus.create(root, config)
    for sample in samples:
        status, message = corpus.add_file(sample.pdf, doc_id=sample.name,
                                          source=sample.source_metadata.get("source_url"))
        if status != "added":
            raise ValueError(f"{sample.name}: {status}, {message}")
    return corpus


def replay_corpus(root, config, samples):
    """Run the real corpus pipeline with the conversion result held fixed."""
    corpus = register_corpus(root, config, samples)
    by_name = {sample.name: sample for sample in samples}

    def converted(source, kind, mode, pages, cache, config, models):
        sample = by_name[source.parent.parent.name]
        if mode != "text" or pages != (1, sample.pages):
            raise ValueError(f"{sample.name}: expected one complete text segment, got {mode}, {pages}")
        meta = {"mode": mode, "pages": pages, "status": "success", "seconds": 0.0, "confidence": {}, "errors": []}
        return DoclingDocument.model_validate_json(sample.native), meta

    with patch.object(process, "convert_segment", side_effect=converted):
        process.run(corpus, MODELS, report=lambda _: None)
    return corpus


def conversion_options(config):
    analysis = dict(config["analysis"])
    orientation = analysis.pop("page_orientation", {})
    if orientation.get("mode") == "normalize":
        raise ValueError("a native seed cannot be reused with orientation normalization")
    return analysis, *(config[key] for key in ("ocr", "table_mode", "segment_pages", "document_timeout"))


def native_corpus(root, config, samples, seed_path):
    corpus = register_corpus(root, config, samples)
    if seed_path:
        seed = Corpus(seed_path)
        if conversion_options(seed.config) != conversion_options(config):
            raise ValueError("native seed conversion settings differ")
        digests = engine_fingerprint(MODELS, config["ocr"])["models"]
        seed_fp, target_fp = fingerprint(seed.config, digests), fingerprint(config, digests)
        original = {doc["doc_id"]: doc["sha256"] for doc in seed.documents()}
        for doc in corpus.documents():
            name = doc["doc_id"]
            cached = process.output_directory(seed, name, seed_fp)
            if original.get(name) != doc["sha256"] or not process.is_complete(cached):
                raise ValueError(f"native seed lacks a completed matching input: {name}")
            source = cached / "segments"
            segments = list(source.glob("*.json.gz"))
            if not segments or any(not path.with_suffix(".meta.json").is_file() for path in segments):
                raise ValueError(f"native seed lacks conversion artifacts: {name}")
            shutil.copytree(source, process.output_directory(corpus, name, target_fp) / "segments")
    process.run(corpus, MODELS, report=lambda _: None)
    return corpus


def prepare_native_seed(root, config, samples):
    start_wall, start_cpu = perf_counter(), process_time()
    corpus = register_corpus(root, config, samples)
    counts = process.run(corpus, MODELS)
    timing = {"wall_seconds": perf_counter() - start_wall, "cpu_seconds": process_time() - start_cpu,
              "peak_rss_mib": peak_rss_mib(), "counts": counts}
    (root / "timing.json").write_text(json.dumps(timing, indent=2) + "\n", encoding="utf-8")
    if counts["done"] != len(samples):
        raise RuntimeError(f"native seed conversion incomplete: {counts}")


def references(samples):
    result = {}
    for sample in samples:
        with pymupdf.open(sample.pdf) as pdf:
            result[sample.name] = [tokens(page.get_text()) for page in pdf]
    return result


@contextmanager
def measure(timings, phase):
    start_wall, start_cpu = perf_counter(), process_time()
    try:
        yield
    finally:
        timings[phase]["wall_seconds"] += perf_counter() - start_wall
        timings[phase]["cpu_seconds"] += process_time() - start_cpu


def peak_rss_mib():
    """Peak resident memory for the entire isolated profile process."""
    if sys.platform == "win32":
        import psutil
        return psutil.Process().memory_info().peak_wset / (1024 * 1024)
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024 if sys.platform == "darwin" else 1024)


def observed(release, sample, reference, qa):
    file_row = next(iter_jsonl(release / "files.jsonl"))
    page_text, sections = k1_page_texts(release, file_row["file_id"])
    words, numbers, critical = Counter(), Counter(), Counter()
    for page, (gold_words, gold_numbers) in enumerate(reference, 1):
        text = page_text.get(page, "")
        found_words, found_numbers = tokens(text + "\n" + sections.get(page, ""))
        for score, expected, found in [(words, gold_words, found_words), (numbers, gold_numbers, found_numbers)]:
            score.update(matched=sum((expected & found).values()), expected=sum(expected.values()),
                         predicted=sum(found.values()))
        numbers.update(novel=sum(count for value, count in found_numbers.items() if value not in gold_numbers),
                       excess_known=sum(max(0, count - gold_numbers[value]) for value, count in found_numbers.items()
                                        if value in gold_numbers))
        flat = " ".join((text.replace("|", " ") if sample.native is None else text).split())
        for probe in sample.critical.get(page, ()):
            boundary_match = re.search(rf"(?<!\w){re.escape(probe)}(?!\w)", flat)
            critical.update(expected=1, matched=int(boundary_match is not None))
    joined = [row for row in iter_jsonl(release / "tables.jsonl") if row["join"]["status"] == "joined"]
    form_pairs = {}
    if sample.form_pairs:
        expected = Counter(sample.form_pairs)
        found = Counter((" ".join(field["key"].split()), " ".join(field["value"].split()))
                        for row in iter_jsonl(release / "forms.jsonl") for field in row["fields"])
        form_pairs = {"expected": sum(expected.values()), "predicted": sum(found.values()),
                      "matched": sum((expected & found).values())}
    return {"status": qa["validator"], "pages": sample.pages, "words": dict(words), "numbers": dict(numbers),
            "critical": dict(critical), "form_pairs": form_pairs, "signals": qa["signals"], "counts": qa["totals"],
            "joined_tables": len(joined), "joined_boundaries": sum(len(row["pages"]) - 1 for row in joined),
            "content": {name: file_sha256(release / name) for name in ("chunks.jsonl", "tables.jsonl", "forms.jsonl")}}


def run_variant(corpus, k1, qa_flags, samples, reference, output, timings):
    documents = {}
    for doc_index, sample in enumerate(samples):
        export_name = f"doc-{doc_index:02d}"
        try:
            with measure(timings, "k1"):
                result = export_k1(corpus, export_name, MODELS, k1, only=[sample.name])
        except K1CompletenessError as error:
            blocked = error.report["blocked_documents"][0]
            documents[sample.name] = {"status": "blocked", "reason": blocked["reason"], "detail": blocked["detail"]}
        else:
            release = Path(result["export"])
            with measure(timings, "qa"):
                qa = run_qa(corpus.root, release, output / export_name, None, None, **qa_flags)
            documents[sample.name] = observed(release, sample, reference[sample.name], qa)
    return documents


def measure_variant(config, k1, qa_flags, samples, reference, seed_path=None):
    """Run inside a fresh process with a fresh corpus so timings do not depend on profile order."""
    timings = {phase: Counter() for phase in PHASES}
    with TemporaryDirectory(prefix="track-a-perf-") as directory:
        root = Path(directory)
        with measure(timings, "corpus"):
            if samples[0].native is None:
                corpus = native_corpus(root / "corpus", config, samples, seed_path)
            else:
                corpus = replay_corpus(root / "corpus", config, samples)
        documents = run_variant(corpus, k1, qa_flags, samples, reference, root / "qa", timings)
        return documents, {"phases": timings, "peak_rss_mib": peak_rss_mib()}


def summarize_performance(runs, input_pages, usd_per_vcpu_hour):
    summed = {
        metric: [sum(run["phases"][phase][metric] for phase in PHASES) for run in runs]
        for metric in ("wall_seconds", "cpu_seconds")
    }
    wall = statistics.median(summed["wall_seconds"])
    cpu = statistics.median(summed["cpu_seconds"])
    return {
        "repeats": len(runs), "input_pages": input_pages,
        "wall_seconds": wall, "wall_min_seconds": min(summed["wall_seconds"]),
        "wall_max_seconds": max(summed["wall_seconds"]), "cpu_seconds": cpu,
        "peak_rss_mib": max(run["peak_rss_mib"] for run in runs),
        "input_pages_per_second": input_pages / wall,
        "cpu_hours_per_1000_input_pages": cpu / 3600 * 1000 / input_pages,
        "estimated_usd_per_1000_input_pages": (
            None if usd_per_vcpu_hour is None else cpu / 3600 * 1000 / input_pages * usd_per_vcpu_hour
        ),
        "phases": {
            phase: {
                metric: statistics.median(run["phases"][phase][metric] for run in runs)
                for metric in summed
            }
            for phase in PHASES
        },
        "measurements": runs,
    }


def profile_summary(row, cohort, baseline):
    valid = [sample for sample in cohort if row["docs"].get(sample.name, {}).get("status") == "pass"]
    result = {"expected_docs": len(cohort), "valid_docs": len(valid),
              "compared_pages": sum(sample.pages for sample in valid),
              "required_critical": sum(len(probes) for sample in cohort for probes in sample.critical.values()),
              "joined_tables": sum(row["docs"][sample.name]["joined_tables"] for sample in valid),
              "joined_boundaries": sum(row["docs"][sample.name]["joined_boundaries"] for sample in valid),
              "changed_docs": sum(row["docs"][sample.name]["content"] != baseline["docs"].get(sample.name, {}).get("content")
                                  for sample in valid)}
    for key in ("words", "numbers", "critical", "form_pairs", "signals"):
        total = Counter()
        for sample in valid:
            total.update(row["docs"][sample.name][key])
        if key != "signals":
            for metric, denominator in [("recall", "expected"), ("precision", "predicted")]:
                if total[denominator]:
                    total[metric] = round(total["matched"] / total[denominator], 6)
        result[key] = dict(total)
    return result


def write_results(out, measurements, samples, flags, usd_per_vcpu_hour, conversion_mode):
    baseline = measurements[0]
    cohorts = list(dict.fromkeys(sample.cohort for sample in samples))
    for row in measurements:
        for cohort in cohorts:
            row[cohort] = profile_summary(row, [s for s in samples if s.cohort == cohort], baseline)
        row["status"] = ("invalid_config" if "error" in row else
                         "pass" if all(d["status"] == "pass" for d in row["docs"].values()) else "blocked")
    out.mkdir(parents=True, exist_ok=True)
    metadata = {sample.name: {"pages": sample.pages, "cohort": sample.cohort,
                             "pdf_sha256": file_sha256(sample.pdf),
                             "native_sha256": (hashlib.sha256(sample.native.encode("utf-8")).hexdigest()
                                               if sample.native is not None else None),
                             **sample.source_metadata}
                for sample in samples}
    drilling = [sample for sample in samples if sample.cohort == "drilling"]
    if drilling:
        with ZipFile(out / "drilling-dataset.zip", "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps({sample.name: metadata[sample.name] for sample in drilling},
                                                        indent=2) + "\n")
            for sample in drilling:
                archive.write(sample.pdf, f"pdf/{sample.name}.pdf")
                archive.writestr(f"native/{sample.name}.docling.json", sample.native)
    (out / "results.json").write_text(json.dumps({"upstream": UPSTREAM_REVISION if "external" in cohorts else None,
                                                "samples": metadata,
                                                "conversion_mode": conversion_mode,
                                                "assumed_usd_per_vcpu_hour": usd_per_vcpu_hour,
                                                "options": flags, "runs": measurements}, indent=2) + "\n",
                                     encoding="utf-8")
    with (out / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["id", "design", "active_option_count", "options", "status", "cohort",
                         "valid_docs", "expected_docs", "pages", "word_recall", "word_precision", "numeric_recall",
                         "numeric_precision", "critical_matched", "critical_compared", "critical_expected",
                         "changed_docs", "joined_tables", "joined_boundaries", "signals", "form_pairs_matched",
                         "form_pairs_expected", "form_pairs_predicted"])
        for row in measurements:
            for name in cohorts:
                cohort = row[name]
                writer.writerow([row["id"], row["design"], len(row["flags"]), " ".join(row["flags"]), row["status"],
                                 name, cohort["valid_docs"], cohort["expected_docs"], cohort["compared_pages"],
                                 cohort["words"].get("recall"), cohort["words"].get("precision"),
                                 cohort["numbers"].get("recall"), cohort["numbers"].get("precision"),
                                 cohort["critical"].get("matched"), cohort["critical"].get("expected"),
                                 cohort["required_critical"],
                                 cohort["changed_docs"], cohort["joined_tables"], cohort["joined_boundaries"],
                                 sum(cohort["signals"].values()),
                                 *(cohort["form_pairs"].get(key) for key in ("matched", "expected", "predicted"))])
    with (out / "performance.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        phase_fields = [(phase, metric) for phase in PHASES for metric in ("wall_seconds", "cpu_seconds")]
        fields = ("repeats", "input_pages", "wall_seconds", "wall_min_seconds", "wall_max_seconds", "cpu_seconds",
                  "peak_rss_mib", "input_pages_per_second", "cpu_hours_per_1000_input_pages",
                  "estimated_usd_per_1000_input_pages")
        writer.writerow(["id", "status", "active_option_count", "valid_docs", "expected_docs", "conversion_mode",
                         "assumed_usd_per_vcpu_hour", *fields, *(f"{p}_{m}" for p, m in phase_fields)])
        for row in measurements:
            perf = row.get("performance", {})
            phases = perf.get("phases", {})
            writer.writerow([row["id"], row["status"], len(row["flags"]),
                             sum(row[c]["valid_docs"] for c in cohorts), len(samples),
                             conversion_mode, usd_per_vcpu_hour, *(perf.get(key) for key in fields),
                             *(phases.get(p, {}).get(m) for p, m in phase_fields)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--docling-checkout", type=Path)
    inputs.add_argument("--drilling-gold", action="store_true", help="render the repository's drilling annotations")
    inputs.add_argument("--native-manifest", type=Path, help="benchmark verified original PDFs")
    parser.add_argument("--native-pdf-dir", type=Path)
    parser.add_argument("--native-seed", type=Path,
                        help="create or reuse this native conversion corpus for fixed settings")
    parser.add_argument("--drilling-font", type=Path, help="TrueType font for rendering drilling annotations")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only-variant", action="append", default=[],
                        help="run this profile in addition to baseline; may be specified multiple times")
    parser.add_argument("--repeats", type=int, default=1, help="number of fresh runs per measured profile")
    parser.add_argument("--repeat-variant", action="append", default=[],
                        help="repeat this profile only; may be specified multiple times")
    parser.add_argument("--usd-per-vcpu-hour", type=float, help="assumed CPU unit price for cost estimates")
    args = parser.parse_args()
    flags = options()
    cases = list(variants(flags))
    unknown = (set(args.repeat_variant) | set(args.only_variant)) - {name for name, _, _ in cases}
    if args.repeats < 1 or unknown:
        parser.error("provide positive repeats and known profile names")
    if args.drilling_gold and not args.drilling_font:
        parser.error("--drilling-gold requires --drilling-font")
    if bool(args.native_manifest) != bool(args.native_pdf_dir) or (args.native_seed and not args.native_manifest):
        parser.error("--native-manifest needs --native-pdf-dir; --native-seed requires both")
    if args.only_variant:
        cases = [case for case in cases if case[0] == "zero" or case[0] in args.only_variant]
    rate = args.usd_per_vcpu_hour
    if rate is not None and (not math.isfinite(rate) or rate < 0):
        parser.error("--usd-per-vcpu-hour must be finite and nonnegative")
    with TemporaryDirectory(prefix="track-a-ablation-") as temporary, ProcessPoolExecutor(
        max_workers=1, mp_context=get_context("spawn"), max_tasks_per_child=1,
    ) as pool:
        root = Path(temporary)
        if args.native_manifest:
            samples = list(native_samples(args.native_manifest, args.native_pdf_dir))
        elif args.drilling_gold:
            from track_a_drilling_samples import build_drilling_samples
            samples = [Sample(name, "drilling", pdf, native, pages, {}, pairs, metadata)
                       for name, pdf, native, pages, pairs, metadata
                       in build_drilling_samples(ROOT, root, args.drilling_font)]
        else:
            samples = list(external_samples(args.docling_checkout))
        if not args.native_manifest:
            samples.extend([control_sample(root, "retention-control"),
                            control_sample(root, "boundary-control", stacked=True), continuation_sample(root)])
        reference = references(samples)
        input_pages = sum(sample.pages for sample in samples)
        measurements = []
        if args.native_seed and not args.native_seed.exists():
            seed_config, _, _ = configs([], flags)
            pool.submit(prepare_native_seed, args.native_seed, seed_config, samples).result()
        for name, design, enabled in cases:
            row = {"id": name, "design": design, "flags": enabled, "docs": {}}
            try:
                config, k1, qa_flags = configs(enabled, flags)
            except ValueError as error:
                row["error"] = str(error)
            else:
                timings = []
                repeats = args.repeats if not args.repeat_variant or name in args.repeat_variant else 1
                for _ in range(repeats):
                    docs, run = pool.submit(measure_variant, config, k1, qa_flags, samples, reference,
                                            args.native_seed).result()
                    if timings and row["docs"] != docs:
                        raise RuntimeError(f"{name}: K1 or QA results changed across performance repeats")
                    row["docs"] = docs
                    timings.append(run)
                row["performance"] = summarize_performance(timings, input_pages, rate)
            measurements.append(row)
            print(name, row.get("error") or Counter(doc["status"] for doc in row["docs"].values()), flush=True)
        mode = "native_cache" if args.native_seed else "native_cold" if args.native_manifest else "fixture_replay"
        write_results(args.out, measurements, samples, flags, rate, mode)


if __name__ == "__main__":
    main()
