"""Compare margin and pairing options on a conversion cache with pinned source probes."""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from time import perf_counter

import pymupdf

from benchmark_track_a_ablation import (
    Corpus, MODELS, export_k1, load_k1_config, native_corpus, native_samples, read_json, references, validate_config,
)
from benchmark_track_a_scale import changes, score, summarize
from graph_builder.corpus.qa.cli import run as run_qa
from graph_builder.corpus.store import atomic_write_json, read_jsonl


PROFILES = {
    "baseline": (False, False),
    "preserve_varying_numbers": (True, False),
    "geometry_pairing": (False, True),
    "combined": (True, True),
}


def compare(source_docs, before: dict, after: dict) -> dict:
    diff = changes(before, after)["all"]
    per_doc = {name: changes({name: before[name]}, {name: row})["all"] for name, row in after.items()}
    return {
        **diff,
        "wells_with_phrase_gains": sorted({source_docs[name]["well"] for name, delta in per_doc.items()
                                           if delta["phrases_gained"]}),
        "documents_with_probe_losses": sorted(name for name, delta in per_doc.items()
                                               if delta["phrases_lost"] or delta["cells_lost"]),
    }


def audit_added_fields(samples, baseline: Path, release: Path) -> dict:
    """Check new label/value rectangles against an independent PDF text reader."""
    def normalize(text):
        return "".join(text.split()).casefold()

    previous = defaultdict(set)
    for form in read_jsonl(baseline / "forms.jsonl"):
        previous[form["doc_id"], form["page"]].update((f["key"], f["value"]) for f in form["fields"])
    added = defaultdict(lambda: defaultdict(list))
    for form in read_jsonl(release / "forms.jsonl"):
        doc, page = form["doc_id"], form["page"]
        for field in form["fields"]:
            if (field["key"], field["value"]) not in previous[doc, page]:
                added[doc][page].append(field)
    fields_checked = 0
    mismatches = []
    for sample in samples:
        if sample.name not in added:
            continue
        with pymupdf.open(sample.pdf) as pdf:
            for number, fields in added[sample.name].items():
                tree = pdf[number - 1].get_text("rawdict", flags=pymupdf.TEXTFLAGS_TEXT)
                glyphs = []
                for block in tree["blocks"]:
                    for line in block.get("lines", ()):
                        for span in line["spans"]:
                            for char in span["chars"]:
                                left, top, right, bottom = char["bbox"]
                                glyphs.append(((left + right) / 2, (top + bottom) / 2, char["c"]))
                glyphs.sort(key=lambda glyph: glyph[0])
                for field in fields:
                    fields_checked += 1
                    for part in ("key", "value"):
                        left, top, right, bottom = field[f"{part}_bbox"]
                        visible = "".join(char for x, y, char in glyphs
                                          if left - 0.2 <= x <= right + 0.2 and top <= y <= bottom)
                        if normalize(visible) != normalize(field[part]):
                            mismatches.append({"doc_id": sample.name, "page": number, "part": part,
                                               "expected": field[part], "observed": visible})
    return {"fields_checked": fields_checked, "boxes_checked": 2 * fields_checked, "mismatches": mismatches}


def transfer_gate(regression: dict, holdout: dict) -> dict:
    def inputs(baseline):
        files = Path(baseline["release"]) / "files.jsonl"
        return {row["sha256"] for row in read_jsonl(files)}, {row["family"] for row in baseline["documents"].values()}

    old_files, old_families = inputs(regression["baseline"])
    new_files, new_families = inputs(holdout["baseline"])
    if old_files & new_files or old_families & new_families:
        raise ValueError("Regression and transfer inputs must use different PDF hashes and report families")
    candidates = {}
    for name in (holdout.keys() & regression.keys()) - {"baseline"}:
        old, new = regression[name], holdout[name]
        mismatch = "XREP_TABLE_CHUNK_MISMATCH"
        checks = {
            "held_out_phrase_gain": new["delta"]["phrases_gained"] > 0,
            "regression_probes_retained": not old["delta"]["documents_with_probe_losses"],
            "held_out_probes_retained": not new["delta"]["documents_with_probe_losses"],
            "table_consistency_retained": all(after["qa"]["signals"].get(mismatch, 0)
                                              <= before["qa"]["signals"].get(mismatch, 0)
                                              for before, after in ((regression["baseline"], old),
                                                                    (holdout["baseline"], new))),
        }
        if name == "source_fields":
            audits = [profile.get("source_span_audit") for profile in (old, new)]
            checks["added_source_spans_match"] = all(audit and audit["fields_checked"] and not audit["mismatches"]
                                                      for audit in audits)
        candidates[name] = {"pass": all(checks.values()), "checks": checks}
    return {"holdout_families": sorted(new_families), "candidates": dict(sorted(candidates.items()))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--seed", type=Path, required=True, help="complete native three-page-minimum corpus")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only-profile", action="append", choices=(*PROFILES, "source_fields"), default=[])
    parser.add_argument("--against", type=Path, help="regression results used to gate this separate holdout")
    args = parser.parse_args()
    manifest = read_json(args.manifest)
    samples = list(native_samples(args.manifest, args.pdf_dir))
    original = references(samples)
    source = {entry["doc_id"]: entry for entry in manifest["documents"]}
    seed = Corpus(args.seed)
    if (any(seed.config["filters"].get(key) for key in ("running_line_keep_varying_numbers", "keep_line_patterns"))
            or seed.config["chunking"].get("label_value")):
        raise ValueError("The seed must use the baseline margin and pairing settings")
    if {doc["doc_id"]: doc["sha256"] for doc in seed.documents()} != {s["doc_id"]: s["sha256"] for s in manifest["documents"]}:
        raise ValueError("Seed and manifest inputs differ")
    results = {}
    profiles = {**PROFILES, "source_fields": (False, False)} if "source_fields" in args.only_profile else PROFILES
    for name, (guard, pairing) in profiles.items():
        if args.only_profile and name != "baseline" and name not in args.only_profile:
            continue
        start = perf_counter()
        corpus = seed
        if guard or pairing:
            config = deepcopy(seed.config)
            if guard:
                config["filters"]["running_line_keep_varying_numbers"] = True
            if pairing:
                config["chunking"]["label_value"] = {
                    "split_label_cells": True, "rebuild_item_order": True, "review_unverified": True,
                }
            corpus = native_corpus(args.out / name / "corpus", validate_config(config), samples, args.seed)
        replay_seconds = perf_counter() - start
        start = perf_counter()
        k1 = load_k1_config()
        k1["forms"].pop("missing_report_fields", None)
        k1["table_rules"].pop("hourly_operations", None)
        if name == "source_fields":
            k1["forms"]["missing_report_fields"] = True
        release = Path(export_k1(corpus, "header-transfer-" + name, MODELS, k1)["export"])
        k1_seconds = perf_counter() - start
        start = perf_counter()
        qa = run_qa(corpus.root, release, args.out / name / "qa", None, None, fidelity=True,
                    crossrep=True, form_overlap=True, table_overlap=False, ruled_table_overlap=False,
                    compact_table_spans=False, label_value=pairing)
        if qa["validator"] != "pass":
            raise RuntimeError(f"Invalid {name} release: {qa['ledger']}")
        qa_seconds = perf_counter() - start
        docs = score(samples, source, original, release, qa)
        totals = summarize(docs)
        delta = compare(source, results.get("baseline", {"documents": docs})["documents"], docs)
        results[name] = {
            "summary": totals, "delta": delta, "documents": docs, "qa": qa, "release": str(release),
            "timings": {"cached_replay_seconds": replay_seconds, "k1_seconds": k1_seconds, "qa_seconds": qa_seconds},
        }
        if name == "source_fields":
            results[name]["source_span_audit"] = audit_added_fields(samples, Path(results["baseline"]["release"]), release)
        atomic_write_json(args.out / "results.json", results)
        counts = totals["all"]
        print(name, counts["phrases_matched"], "/", counts["phrases"],
              counts["cells_matched"], "/", counts["cells"], delta, flush=True)
    if args.against:
        gate = transfer_gate(read_json(args.against), results)
        atomic_write_json(args.out / "transfer_gate.json", gate)
        return int(not any(row["pass"] for row in gate["candidates"].values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
