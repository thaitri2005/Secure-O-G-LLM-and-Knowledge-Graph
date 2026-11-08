"""Check that a K1 package works with Track B's graphrag readers, without changing graphrag.

graphrag is imported read-only. Only CPU code runs: file loading and BM25 retrieval. Nothing here needs llama.cpp,
a GPU, an embedding endpoint or a language model, and no such step is run.

    python scripts/check_k1_graphrag_compat.py --k1 data/interim/k1-run/corpus/exports/k1-legacy/releases/<release>
    python scripts/check_k1_graphrag_compat.py --k1 <release dir> --legacy-map <legacy_chunk_ids.json>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from graph_builder.corpus.legacy_ids import summarize_legacy_map  # noqa: E402
from graphrag.data import AK3, FACTS, Chunk, chunks_on_pages, daily_rows, load_chunks, load_questions  # noqa: E402
from graphrag.ontology import table_rows  # noqa: E402
from graphrag.retrieval import BM25  # noqa: E402

CUTOFFS = (1, 3, 5, 10)
ID_FORMAT_GAPS = (
    ("graphrag/citations.py", 'f"{doc_id}#', "A cited chunk id without '#' gets '<doc_id>#' prefixed, so a K1 id such as f<hex>:s1:c0 turns into <doc_id>#f<hex>:s1:c0 and never matches a hit."),
    ("graphrag/baseline.py", 'cid.split("#")[-1]', "The passage label is the part after '#'. A K1 id has no '#', so the label is the whole id (longer prompts, no short c0004-style labels)."),
    ("graphrag/validate.py", 'chunk_id.split("#")[0]', "Well names are grouped per document by the part before '#'. A K1 id has no '#', so every chunk becomes its own group."),
    ("graphrag/validate.py", 'fact["chunk"].split("#")[0]', "A fact's document is the part before '#'. With K1 ids this is the chunk id, so the well check compares against that one chunk only."),
)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_load(chunks_path: Path) -> tuple[list[Chunk], bool]:
    rows = read_jsonl(chunks_path)
    chunks = load_chunks(path=chunks_path)
    ok = len(chunks) == len(rows) and all(c.id == r["chunk_id"] and c.doc_id == r["doc_id"] for c, r in zip(chunks, rows))
    print(f"(1) graphrag.data.load_chunks: {len(chunks)} of {len(rows)} rows loaded, ids and doc_ids equal: {'PASS' if ok else 'FAIL'}")
    return chunks, ok


def check_daily_reports(chunks_path: Path) -> bool:
    rows = daily_rows(chunks_path)
    documents = sorted({row["doc_id"] for row in rows})
    numbers = sorted(doc.split("-appx-")[1][:2] for doc in documents)
    sample = chunks_on_pages([{"appx": "30", "page": 17}], rows)
    ok = numbers == ["27", "28", "29", "30"] and bool(sample)
    print(f"(2) 'dailyreport' in doc_id: {len(documents)} documents, {len(rows)} chunks; doc_id.split('-appx-')[1][:2] = {numbers}; "
          f"chunks_on_pages(appx 30, page 17) = {len(sample)} chunks: {'PASS' if ok else 'FAIL'}")
    for doc in documents:
        print(f"      {doc}")
    return ok


def check_tables(chunks_path: Path) -> bool:
    tables = read_jsonl(chunks_path.with_name("tables.jsonl"))
    missing = [t["table_id"] for t in tables if not all(key in t for key in ("table_id", "doc_id", "cells"))]
    empty = [t["table_id"] for t in tables if not table_rows(t)]
    ids = {t["table_id"] for t in tables}
    orphans = [r["chunk_id"] for r in read_jsonl(chunks_path) if r["type"] == "table" and r["table_id"] not in ids]
    ok = not (missing or empty or orphans)
    print(f"(3) tables.jsonl: {len(tables)} tables, rows missing table_id/doc_id/cells: {len(missing)}, "
          f"tables for which graphrag.ontology.table_rows gives no rows: {len(empty)}, table chunks without a table: {len(orphans)}: "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


def search_ranks(retriever, questions: list[dict], wanted_for) -> list[int | None]:
    """First rank of a wanted chunk in the top 20; the same lines as graphrag.baseline.evaluate_retrieval."""
    ranks = []
    for q in questions:
        hits = [cid for cid, _ in retriever.search(q["question"], 20)]
        wanted = wanted_for(q)
        ranks.append(next((i + 1 for i, cid in enumerate(hits) if cid in wanted), None))
    return ranks


def rates(ranks: list[int | None]) -> dict[str, float]:
    return {f"hit@{k}": round(sum(r is not None and r <= k for r in ranks) / len(ranks), 3) for k in CUTOFFS}


def check_retrieval(chunks: list[Chunk], legacy_map: list[dict]) -> None:
    questions, gold = load_questions()
    with_gold = [q for q in questions if q["gold"]]
    mapping = {r["old_chunk_id"]: r["new_chunk_id"] for r in legacy_map}
    old_pages = {r["old_chunk_id"]: r["old_page"] for r in legacy_map}
    eowr = [c for c in chunks if c.doc_id == AK3]

    def old_ids(q):
        return {c for g in q["gold"] for c in gold[g]["chunks"]}

    def mapped(q):
        return {mapping[c] for c in old_ids(q) if mapping.get(c)}

    def unmapped(q):
        return sorted(c for c in old_ids(q) if not mapping.get(c))

    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    print(f"    id map: {summarize_legacy_map(legacy_map, facts)}")
    reference = BM25(load_chunks([AK3]))
    retriever = BM25(eowr)
    print(f"(4) BM25 over {len(eowr)} new EOWR chunks, {len(with_gold)} of the {len(questions)} prototype questions have gold chunks; "
          "their gold chunk ids are remapped through the id map")
    print(f"    reference, old bundle with old ids: {rates(search_ranks(reference, with_gold, old_ids))}")
    ranks = search_ranks(retriever, with_gold, mapped)
    print(f"    K1 through the map (a question whose gold chunks are all unmapped counts as a miss): {rates(ranks)}")
    cited_pages = {q["id"]: {old_pages[c] for c in unmapped(q)} for q in with_gold}

    def page_wanted(q):
        pages = cited_pages[q["id"]]
        return mapped(q) | {c.id for c in eowr if c.page in pages}

    page_ranks = search_ranks(retriever, with_gold, page_wanted)
    print(f"    secondary, page level (an unmapped gold chunk is satisfied by any chunk on its old page): {rates(page_ranks)}")
    misses = [(q, r) for q, r in zip(with_gold, ranks) if r is None or r > 5]
    print(f"    chunk-level misses at hit@5: {len(misses)}")
    for q, rank in misses:
        lost = unmapped(q)
        print(f"      {q.get('id', '?')}: rank {rank}; gold {sorted(old_ids(q))}; unmapped: "
              f"{[f'{c} (old page {old_pages.get(c)})' for c in lost] or 'none (retrieval miss)'}")
        print(f"        {q['question']}")
    unmapped_all = sorted({c for q in with_gold for c in unmapped(q)})
    print(f"    gold chunks left unmapped: {len(unmapped_all)} {unmapped_all}")


def report_id_format_gaps(sample_id: str) -> None:
    print("(5) K1 id-format gaps in graphrag (read-only; graphrag is not modified)")
    print(f"    example K1 id: {sample_id}; has '#': {'#' in sample_id}")
    for relative, pattern, effect in ID_FORMAT_GAPS:
        lines = (ROOT / relative).read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, start=1):
            if pattern in line:
                print(f"    {relative}:{number}: {effect}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--k1", type=Path, required=True, help="K1 release directory (holds chunks.jsonl and tables.jsonl)")
    parser.add_argument("--no-daily-reports", action="store_true", help="skip check (2) for a package that holds only the end-of-well report")
    parser.add_argument("--legacy-map", type=Path, help="legacy_chunk_ids.json; default: the one inside the release, if any")
    args = parser.parse_args()
    chunks_path = args.k1 / "chunks.jsonl"
    print(f"K1 release: {args.k1.name}")
    print("Scope: file loading and BM25 only. No llama.cpp, GPU, embedding endpoint or language model step was run.")
    chunks, loaded = check_load(chunks_path)
    daily = check_daily_reports(chunks_path) if not args.no_daily_reports else True
    if args.no_daily_reports:
        print("(2) skipped by --no-daily-reports")
    tables = check_tables(chunks_path)
    legacy = args.legacy_map or args.k1 / "legacy_chunk_ids.json"
    if legacy.is_file():
        check_retrieval(chunks, json.loads(legacy.read_text(encoding="utf-8")))
    else:
        print("(4) skipped: no legacy id map (pass --legacy-map or export with --legacy-chunks)")
    report_id_format_gaps(chunks[0].id if chunks else "")
    return 0 if loaded and daily and tables else 1


if __name__ == "__main__":
    raise SystemExit(main())
