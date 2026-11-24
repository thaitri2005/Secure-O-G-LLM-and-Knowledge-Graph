"""Score an evidence-backed retrieval projection against another view of the same K1 release."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import sys

from benchmark_track_a_ablation import ROOT, native_samples, read_json, references
from benchmark_track_a_scale import changes, score, score_hourly, summarize
from benchmark_table_overlap import unique_source_losses
from graph_builder.corpus.qa.ruled_overlap import PREFIXES, value_tokens
from graph_builder.corpus.qa.table_overlap import SOURCE
from graph_builder.corpus.store import atomic_write_json, file_sha256, read_jsonl

sys.path.insert(0, str(ROOT))
from graphrag.data import load_chunks  # noqa: E402
from graphrag.retrieval import BM25  # noqa: E402


def exact_rows(tables, probes):
    resolved = []
    for probe in probes:
        ref = f"textlayer:{probe['rule']}:"
        matches = [(table["table_id"], row) for table in tables
                   if table["doc_id"] == probe["doc_id"] and table["pages"] == [probe["page"]]
                   and any(part["source_ref"].startswith(ref) for part in table["parts"])
                   for row, cells in enumerate(table["grid"]) if cells == probe["row"]]
        if len(matches) != 1:
            raise ValueError(f"Ambiguous or missing pinned source row: {probe}")
        resolved.append((probe, *matches[0]))
    return resolved


def top_k(view, path, probes, k):
    by_page = defaultdict(set)
    for entry in view.values():
        if entry["pages"] == [entry["page"]]:
            by_page[entry["doc_id"], entry["page"]].add(entry["chunk_id"])
    retriever = BM25(load_chunks(path=path))
    result = []
    for probe, owner, row in probes:
        gold = {chunk_id for chunk_id, item in view.items() if item.get("table_id") == owner
                and item["row_start"] <= row < item["row_end"]}
        ranked = [chunk_id for chunk_id, _ in retriever.search(probe["query"], k, by_page[probe["doc_id"], probe["page"]])]
        fingerprint = Counter(token.casefold() for cell in probe["row"] for token in value_tokens(cell))
        duplicates = [chunk_id for chunk_id in ranked if chunk_id not in gold
                      and fingerprint <= Counter(token.casefold() for token in value_tokens(view[chunk_id]["text"]))]
        rank = next((index for index, chunk_id in enumerate(ranked, 1) if chunk_id in gold), None)
        result.append({"query": probe["query"], "page": probe["page"], "doc_id": probe["doc_id"], "source_rank": rank,
                       "competing_chunks": duplicates})
    return {"source_hits": sum(row["source_rank"] is not None for row in result), "queries": len(result),
            "competing_chunks": sum(len(row["competing_chunks"]) for row in result), "details": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "configs/benchmarks/track_a_scale_holdout.json")
    parser.add_argument("--probes", type=Path, default=ROOT / "configs/benchmarks/track_a_ruled_retrieval.json")
    parser.add_argument("--hourly-reference", type=Path, default=ROOT / "configs/benchmarks/track_a_hourly_palm.json")
    for key in ("pdf-dir", "release", "before", "after", "out"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    args = parser.parse_args()
    expected = {doc["doc_id"]: doc for doc in read_json(args.manifest)["documents"]}
    files = {row["doc_id"]: row["sha256"] for row in read_jsonl(args.release / "files.jsonl")}
    if {name: doc["sha256"] for name, doc in expected.items()} != files:
        raise ValueError("Release and benchmark PDF digests differ")
    checksum = file_sha256(args.release / "SHA256SUMS")
    for view in (args.before, args.after):
        ledger = read_json(view.with_name("qa-ledger.json"))
        if ledger["link"]["sha256sums_sha256"] != checksum or ledger["k1_validator"]["status"] != "pass":
            raise ValueError(f"View does not belong to the validated release: {view}")
    samples = list(native_samples(args.manifest, args.pdf_dir))
    original = references(samples)
    tables = list(read_jsonl(args.release / "tables.jsonl"))
    gold = exact_rows(tables, read_json(args.probes))
    canonical = {table["table_id"] for table in tables
                 if any(part["source_ref"].startswith((*PREFIXES, SOURCE)) for part in table["parts"])}
    outputs, views, docs = {}, {}, {}
    for tag, path in (("before", args.before), ("after", args.after)):
        views[tag] = {row["chunk_id"]: row for row in read_jsonl(path)}
        qa = {"retrieval_view": {"path": str(path)}}
        docs[tag] = score(samples, expected, original, args.release, qa, allow_table_overlap=True)
        outputs[tag] = {"coverage": summarize(docs[tag])["all"], "top_5": top_k(views[tag], path, gold, 5)}

    before, after = views["before"], views["after"]
    lost = unique_source_losses(before, after, original)
    diff = changes(docs["before"], docs["after"])["all"]
    hourly = score_hourly(read_json(args.hourly_reference), args.release)
    gates = {"source_tokens_retained": not lost, "pinned_probes_retained": not (diff["phrases_lost"] or diff["cells_lost"]),
             "canonical_table_chunks_retained": all(after.get(chunk_id) == row for chunk_id, row in before.items()
                                                    if row.get("table_id") in canonical),
             "hourly_rows_retained": not hourly["incomplete_pages"],
             "numeric_surplus_reduced": outputs["after"]["coverage"]["numeric_surplus"] < outputs["before"]["coverage"]["numeric_surplus"],
             "top_5_source_hits_retained": outputs["after"]["top_5"]["source_hits"] >= outputs["before"]["top_5"]["source_hits"]}
    outputs.update(gates=gates, lost_unique_source_tokens=lost, changed_chunks=sum(after.get(cid) != row for cid, row in before.items()),
                   hourly=hourly["all"], pinned_probe_delta=diff)
    atomic_write_json(args.out, outputs)
    print({tag: {**outputs[tag]["coverage"], **{key: value for key, value in outputs[tag]["top_5"].items() if key != "details"}}
           for tag in ("before", "after")}, gates)
    return int(not all(gates.values()))


if __name__ == "__main__":
    raise SystemExit(main())
