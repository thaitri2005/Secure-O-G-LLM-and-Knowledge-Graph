"""Score K1 reading of original well completion panels and raster PDF fields."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import unicodedata

from benchmark_compound_tables import load_view
from benchmark_track_a_natural_layouts import ROOT

from graph_builder.corpus.catalog import Corpus
from graph_builder.corpus.config import load_config, validate_config
from graph_builder.corpus.k1_config import load_k1_config
from graph_builder.corpus.k1_export import export_k1
from graph_builder.corpus.process import run as process
from graph_builder.corpus.qa.cli import run as run_qa
from graph_builder.corpus.store import atomic_write_json, file_sha256, read_jsonl

REFERENCE = ROOT / "configs/benchmarks/track_a_source_panels_e52.json"


def normalize(text):
    text = unicodedata.normalize("NFC", text).translate(str.maketrans("‘’“”′", "''\"\"'"))
    text = re.sub(r"\s*:\s*", ":", text.strip())
    return " ".join(text.casefold().rstrip(":").split())


def pairs(tables):
    return {tuple(map(normalize, (left, right))) for table in tables for row in table["grid"]
            for left, right in zip(row, row[1:]) if left and right}


def prepare_runs(root, pdf_dir, spec, models, config):
    import pymupdf

    settings = load_config(config or ROOT / "configs/corpus/default.json")
    if config is None:
        settings["ocr"].update(engine="rapidocr", languages=["en"])
        settings["filters"]["running_line_min_pages"] = 3
    settings = validate_config(settings)
    for doc_id, source in spec["sources"].items():
        folder = (root / doc_id).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        derived = folder / f"{doc_id}.pdf"
        if not (folder / "corpus").exists():
            with pymupdf.open(pdf_dir / source["file"]) as original, pymupdf.open() as window:
                for page in source["pages"]:
                    window.insert_pdf(original, from_page=page - 1, to_page=page - 1)
                if "crop_bottom_pt" in source:
                    window[0].set_cropbox(pymupdf.Rect(0, 0, window[0].rect.width, source["crop_bottom_pt"]))
                if derived.exists():
                    derived.unlink()
                window.save(derived)
            Corpus.create(folder / "corpus", settings)
        corpus = Corpus(folder / "corpus")
        if corpus.config != settings:
            raise ValueError(f"Existing corpus has different settings in {folder}")
        status, reason = corpus.add_file(derived, doc_id=doc_id)
        if status != "added" and (status != "duplicate" or reason != doc_id):
            raise RuntimeError(f"Could not register {derived}: {reason}")
        counts = process(corpus, models, workers=1, retry_failed=True, heartbeat=25,
                         report=lambda line: print(line, flush=True))
        if counts["done"] + counts.get("skipped", 0) != 1 or counts["failed"]:
            raise RuntimeError(f"Conversion failed for {derived}: {counts}")
        for stage, output in (("before", "baseline.json"), ("after", "after.json")):
            profile = load_k1_config()
            if stage == "before":
                for rule in ("scan_fields", "well_completion"):
                    profile["table_rules"].pop(rule, None)
            release = Path(export_k1(corpus, f"source-panels-{stage}", models, profile)["export"])
            qa_dir = folder / f"qa-{stage}"
            result = run_qa(corpus.root, release, qa_dir, None, None, crossrep=True, fidelity=True,
                            cell_evidence=True, models=models)
            if result["validator"] != "pass":
                raise RuntimeError(f"QA failed for {release}")
            atomic_write_json(folder / output, {"release": str(release), "qa": str(qa_dir)})


def score_stage(root, spec, stage):
    counts = Counter()
    results, all_tables = [], {}
    exact_scan_grids = []
    for doc_id, source in spec["sources"].items():
        folder = root / doc_id
        metadata = json.loads((folder / ("baseline.json" if stage == "before" else "after.json")).read_text(encoding="utf-8"))
        release = Path(metadata["release"])
        qa = Path(metadata.get("qa", folder / f"qa-{stage}"))
        load_view(qa / "retrieval_chunks.jsonl", release)
        bound = json.loads((qa / "cell_evidence_summary.json").read_text(encoding="utf-8"))
        if (bound["release_checksums_sha256"] != file_sha256(release / "SHA256SUMS")):
            raise ValueError(f"Evidence does not belong to {release}")
        tables = list(read_jsonl(release / "tables.jsonl"))
        all_tables[doc_id] = tables
        proven = {(e["table_id"], e["r"], e["c"], e["status"])
                  for e in read_jsonl(qa / "cell_evidence.jsonl") if e["bbox"]}
        for case in (case for case in spec["cases"] if case["doc_id"] == doc_id):
            page = source["pages"].index(case["page"]) + 1
            owned = [table for table in tables if table["pages"] == [page]]
            same_page = pairs(owned)
            kind = case["type"]
            status = "ocr_agreement" if kind == "ocr" else "source_supported"
            prefix = "ocr:scan_fields:" if kind == "ocr" else "textlayer:well_completion:"
            rebuilt = [table for table in owned if table["parts"][0]["source_ref"].startswith(prefix)]
            verified = {tuple(map(normalize, row)) for table in rebuilt
                        for index, row in enumerate(table["grid"][1:], 1)
                        if all((table["table_id"], index, col, status) in proven for col in (0, 1))}
            if kind == "ocr":
                expected = Counter(tuple(map(normalize, row)) for row in case["rows"])
                exact_scan_grids.append(len(rebuilt) == 1 and rebuilt[0]["grid"][0] == ["Field", "Value"]
                                        and Counter(tuple(map(normalize, row)) for row in rebuilt[0]["grid"][1:]) == expected)
            for label, value in case["rows"]:
                key = normalize(label), normalize(value)
                counts[kind + "_expected"] += 1
                counts[kind + "_matched"] += key in same_page
                counts[kind + "_verified"] += key in verified
                results.append({"doc_id": doc_id, "source_page": case["page"], "type": kind,
                                "label": label, "value": value, "matched": key in same_page, "verified": key in verified})
    control = spec["control"]
    page = spec["sources"][control["doc_id"]]["pages"].index(control["page"]) + 1
    matched = [table for table in all_tables[control["doc_id"]] if table["pages"] == [page]
               and control["column"] in table["grid"][0]]
    controls = []
    for table in matched:
        column = table["grid"][0].index(control["column"])
        controls.append([row[column] for row in table["grid"][table["header_rows"]:]])
    return {"counts": counts, "rows": results, "chapter_column_exact": controls == [control["values"]],
            "exact_annotated_scan_grids": sum(exact_scan_grids), "expected_annotated_scan_grids": len(exact_scan_grids)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--models", type=Path, help="Prepare both runs with these model weights before scoring")
    parser.add_argument("--corpus-config", type=Path)
    args = parser.parse_args()
    spec = json.loads(REFERENCE.read_text(encoding="utf-8"))
    for source in spec["sources"].values():
        if file_sha256(args.pdf_dir / source["file"]) != source["sha256"]:
            raise ValueError(f"Source PDF hash differs for {source['file']}")
    if args.models:
        prepare_runs(args.runs, args.pdf_dir, spec, args.models.resolve(), args.corpus_config)
    before, after = (score_stage(args.runs, spec, stage) for stage in ("before", "after"))
    old, new = before["counts"], after["counts"]
    gates = {"all_text_probes_verified": new["text_verified"] == new["text_expected"],
             "text_pair_coverage_improved": new["text_matched"] > old["text_matched"],
             "scan_pair_coverage_improved": new["ocr_matched"] > old["ocr_matched"],
             "all_scan_probes_verified": new["ocr_verified"] == new["ocr_expected"],
             "annotated_scan_rows_and_columns_exact": after["exact_annotated_scan_grids"] == after["expected_annotated_scan_grids"],
             "scan_chapter_column_retained": before["chapter_column_exact"] and after["chapter_column_exact"]}
    atomic_write_json(args.out, {"before": before, "after": after, "gates": gates})
    print({"before": old, "after": new, "gates": gates})
    return int(not all(gates.values()))


if __name__ == "__main__":
    raise SystemExit(main())
