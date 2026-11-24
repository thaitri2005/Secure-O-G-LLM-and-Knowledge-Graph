"""Ablate the table-overlap retrieval projection on an existing validated K1 release."""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from time import perf_counter

from benchmark_track_a_ablation import ROOT, native_samples, read_json, references, tokens
from benchmark_track_a_scale import changes, score, score_hourly, summarize
from graph_builder.corpus.qa.cli import run as run_qa
from graph_builder.corpus.qa.table_overlap import SOURCE
from graph_builder.corpus.store import atomic_write_json, file_sha256, read_jsonl


def unique_source_losses(before, after, original):
    def page_terms(rows):
        page_text = defaultdict(list)
        for row in rows.values():
            if row["pages"] == [row["page"]]:
                page_text[row["doc_id"], row["page"]].append(row["text"])
        return {key: tokens("\n".join(text)) for key, text in page_text.items()}

    old, new = page_terms(before), page_terms(after)
    losses = []
    for (doc, page), terms in old.items():
        for kind, expected, found, retained in zip(("word", "number"), original[doc][page - 1], terms,
                                                   new.get((doc, page), ({}, {}))):
            removed = sorted(set(expected) & set(found) - set(retained))
            if removed:
                losses.append({"doc_id": doc, "page": page, "kind": kind, "lost": removed})
    return losses


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "configs/benchmarks/track_a_scale_holdout.json")
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--hourly-reference", type=Path)
    args = parser.parse_args()
    source = {entry["doc_id"]: entry for entry in read_json(args.manifest)["documents"]}
    expectation = {name: doc["sha256"] for name, doc in source.items()}
    release_files = {row["doc_id"]: row["sha256"] for row in read_jsonl(args.release / "files.jsonl")}
    if expectation != release_files:
        raise ValueError("Release and benchmark source documents differ")
    samples = list(native_samples(args.manifest, args.pdf_dir))
    original = references(samples)
    paths = [path for path in args.release.rglob("*") if path.is_file()]
    digests = {path: file_sha256(path) for path in paths}
    results, views = {}, {}
    for name, enabled in (("before", False), ("table_overlap", True)):
        start = perf_counter()
        qa = run_qa(args.corpus, args.release, args.out / name / "qa", None, None, fidelity=True, crossrep=True,
                    form_overlap=True, table_overlap=enabled, ruled_table_overlap=False, compact_table_spans=False)
        seconds = perf_counter() - start
        if qa["validator"] != "pass":
            raise ValueError(f"Structural QA failed: {qa['ledger']}")
        docs = score(samples, source, original, args.release, qa, allow_table_overlap=enabled)
        results[name] = {"summary": summarize(docs), "documents": docs, "qa_seconds": seconds, "qa": qa}
        views[name] = {row["chunk_id"]: row for row in read_jsonl(Path(qa["retrieval_view"]["path"]))}

    previous, projected = views["before"], views["table_overlap"]
    canonical_ids = {table["table_id"] for table in read_jsonl(args.release / "tables.jsonl")
                     if any(part["source_ref"].startswith(SOURCE) for part in table["parts"])}
    target_documents = {row["doc_id"] for row in previous.values() if row.get("table_id") in canonical_ids}
    diff = changes(results["before"]["documents"], results["table_overlap"]["documents"])["all"]
    losses = unique_source_losses(previous, projected, original)
    gate = {"exact_probes_retained": not (diff["phrases_lost"] or diff["cells_lost"]),
            "no_unique_source_tokens_lost": not losses,
            "hourly_table_chunks_retained": all(projected.get(chunk_id) == row for chunk_id, row in previous.items()
                                                if row.get("table_id") in canonical_ids),
            "other_documents_retained": all(projected.get(chunk_id) == row for chunk_id, row in previous.items()
                                            if row["doc_id"] not in target_documents),
            "release_files_unchanged": digests == {path: file_sha256(path) for path in paths}}
    results["delta"] = diff
    results["unique_source_losses"] = losses
    results["changed_view_chunks"] = sum(projected.get(chunk_id) != row for chunk_id, row in previous.items())
    if args.hourly_reference:
        reference = read_json(args.hourly_reference)
        if expectation[reference["doc_id"]] != reference["sha256"]:
            raise ValueError("Hourly reference and benchmark source differ")
        results["hourly_reference"] = score_hourly(reference, args.release)
        gate["complete_hourly_reference"] = not results["hourly_reference"]["incomplete_pages"]
        gate["numeric_surplus_reduced"] = (results["table_overlap"]["summary"]["all"]["numeric_surplus"]
                                           < results["before"]["summary"]["all"]["numeric_surplus"])
    results["gate"] = gate
    atomic_write_json(args.out / "results.json", results)
    print({name: results[name]["summary"]["all"] for name in views}, gate, flush=True)
    return int(not all(gate.values()))


if __name__ == "__main__":
    raise SystemExit(main())
