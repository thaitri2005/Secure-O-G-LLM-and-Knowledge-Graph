"""Score printed row anchors, values and column ownership in K1 and its QA retrieval view."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_compound_tables import load_view
from benchmark_track_a_scan_cells import digest, read_release, verify_input

from graph_builder.corpus.qa.crossrep import parse_table_chunk
from graph_builder.corpus.store import atomic_write_json, read_jsonl


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "configs/benchmarks/track_a_numeric_cells_e54.json"


def normalize(text):
    return " ".join(text.split()).replace("–", "-").replace("−", "-")


def values(rows, label, offset):
    label = normalize(label)
    return [row[c + offset] for row in rows for c, text in enumerate(row)
            if normalize(text) == label and c + offset < len(row)]


def score(release, qa, original, input_pdf, spec):
    with_pages = spec.get("source_pages")
    if with_pages is None:
        import pymupdf

        with pymupdf.open(original) as source:
            with_pages = list(range(1, len(source) + 1))
    verify_input(original, input_pdf, spec, with_pages)
    tables, _ = read_release(release, input_pdf, with_pages)
    table_ids = {table["table_id"] for table in tables}
    view = load_view(qa / "retrieval_chunks.jsonl", release)
    paired = list(view.values())
    counts = {}
    for source_page, probes in spec["rows"].items():
        page = with_pages.index(int(source_page)) + 1
        grid = [row for table in tables if table["pages"] == [page] for row in table["grid"][table["header_rows"]:]]
        projected = [row for chunk in paired if chunk["table_id"] in table_ids and chunk["pages"] == [page]
                     for row in parse_table_chunk(chunk["text"])["rows"]]
        for label, offset, expected in probes:
            key = (int(source_page), label, offset)
            k1 = values(grid, label, offset)
            retrieved = values(projected, label, offset)
            counts[key] = dict(page=int(source_page), label=label, column_offset=offset, expected=expected, k1=k1,
                               retrieval=retrieved, k1_exact=k1 == [expected], retrieval_exact=retrieved == [expected])
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("myrtle", "zerogen"), required=True)
    parser.add_argument("--pdf", type=Path, required=True, help="Pinned original source")
    parser.add_argument("--input-pdf", type=Path, help="Lossless page window actually processed")
    for stage in ("baseline", "candidate"):
        parser.add_argument(f"--{stage}", type=Path, required=True)
        parser.add_argument(f"--{stage}-qa", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(REFERENCE.read_text(encoding="utf-8"))[args.case]
    result = {stage: score(getattr(args, stage), getattr(args, stage + "_qa"),
                           args.pdf.resolve(), (args.input_pdf or args.pdf).resolve(), spec)
              for stage in ("baseline", "candidate")}
    def totals(rows):
        return dict(probes=len(rows), k1_exact=sum(row["k1_exact"] for row in rows.values()),
                    retrieval_exact=sum(row["retrieval_exact"] for row in rows.values()))

    before, after = result["baseline"], result["candidate"]
    regressions = [dict(key=key, before=row, after=after[key]) for key, row in before.items()
                   if any(row[field] and not after[key][field] for field in ("k1_exact", "retrieval_exact"))]
    summary = {stage: totals(rows) for stage, rows in result.items()}
    atomic_write_json(args.out, {"source_sha256": digest(args.pdf), "summary": summary, "regressions": regressions,
                                 "rows": {stage: list(rows.values()) for stage, rows in result.items()}})
    print(summary)
    return int(bool(regressions) or (args.case == "myrtle"
                                    and not all(row["retrieval_exact"] and row["k1_exact"] for row in after.values())))


if __name__ == "__main__":
    raise SystemExit(main())
