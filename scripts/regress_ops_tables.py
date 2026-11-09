"""Regression of a K1 release with rebuilt Operations Summary tables against a baseline release (AC7 and AC8).

Usage (repository root, any interpreter with the project installed; PYTHONPATH=src):
    python scripts/regress_ops_tables.py BASELINE_RELEASE AFTER_RELEASE [--events] [--repairs table_repairs.NAME.json]
                                         [--repairs-baseline table_repairs.OTHER.json]

Checks: table ids and order of the existing tables, new table ids, non-operations tables and every chunk that is not
an operations table chunk (identical in every field except the character offsets, which may differ only for chunks that
come after a rebuilt or added table of the same document; both counts are reported), parents, forms, files, changed
pages, the shape of the rebuilt tables and their chunks. ``--repairs-baseline`` compares the Round 1 fields of the
records of two sidecars (page, index, status, reason, action, table_id, docling_table; the fields added in Round 2 are
left out). ``--events`` runs ``graphrag.events`` (read only, Track B code is not
changed) on both releases and compares it with graphrag/results/E28_events.json.

Output is aggregate counts. Table and event details are printed only for the DEVELOPMENT dates of
scripts/evaluate_ops_tables.py, never for held-out dates.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEV = {"2016-08-12", "2016-08-13", "2016-08-15", "2016-08-16", "2016-08-18", "2016-08-19", "2016-08-21", "2016-08-22",
       "2016-08-24", "2016-08-25", "2016-08-27", "2016-08-28", "2016-08-30", "2016-08-31", "2016-09-02", "2016-09-03",
       "2016-09-05", "2016-09-06"}
GROUPS = ("files", "pages", "tables", "forms", "parents", "chunks")
OFFSETS = ("char_start", "char_end")


def read(directory: Path, name: str) -> list[dict]:
    return [json.loads(line) for line in (directory / f"{name}.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def is_ops(table: dict) -> bool:
    head = " ".join(" ".join(row) for row in table["grid"][:2])
    return "Operations Description" in head or "Non-Prod" in head or "Operations Summary" in head


def dump(value) -> str:
    return json.dumps(value, sort_keys=True)


def strip(chunk: dict) -> dict:
    return {key: value for key, value in chunk.items() if key not in OFFSETS}


def chunks_after_changed_table(chunks: list[dict], changed_tables: set[str]) -> set[str]:
    """Ids of the chunks that follow, in the same document, a chunk of a table that is new or different from the baseline.

    ``chunks`` is a release's chunk list in order; the character offsets of a chunk depend on the length of every chunk
    before it in its file, so only these chunks may differ in ``char_start``/``char_end``.
    """
    seen, result = set(), set()
    for chunk in chunks:
        if chunk["file_id"] in seen:
            result.add(chunk["chunk_id"])
        if chunk["table_id"] in changed_tables:
            seen.add(chunk["file_id"])
    return result


def tables_and_chunks(base: dict, after: dict) -> dict:
    """Ids, non-ops tables and chunks; returns the facts as a dict (also printed)."""
    facts = {}
    b_tables = {t["table_id"]: t for t in base["tables"]}
    a_tables = {t["table_id"]: t for t in after["tables"]}
    new = sorted(i for i in a_tables if i not in b_tables)
    facts["baseline_table_ids_missing"] = sum(i not in a_tables for i in b_tables)
    facts["new_table_ids"] = new
    facts["existing_order_unchanged"] = [t["table_id"] for t in base["tables"]] == [
        t["table_id"] for t in after["tables"] if t["table_id"] in b_tables]
    contiguous = {}
    for file_id in sorted({i.split(":")[0] for i in new}):
        top = max(int(i.split(":t")[1]) for i in b_tables if i.startswith(file_id))
        got = sorted(int(i.split(":t")[1]) for i in new if i.startswith(file_id))
        contiguous[file_id] = {"baseline_max": top, "new": got, "contiguous_after_max": got == list(range(top + 1, top + 1 + len(got)))}
    facts["new_ids_per_file"] = contiguous
    ops_ids = {t["table_id"] for t in base["tables"] if is_ops(t)}
    non_ops = [t for t in base["tables"] if t["table_id"] not in ops_ids]
    facts["baseline_ops_tables"] = len(ops_ids)
    facts["baseline_non_ops_tables"] = len(non_ops)
    facts["non_ops_tables_identical"] = sum(dump(t) == dump(a_tables.get(t["table_id"])) for t in non_ops)
    a_chunks = {c["chunk_id"]: c for c in after["chunks"]}
    changed_tables = {i for i, t in a_tables.items() if i not in b_tables or dump(t) != dump(b_tables[i])}
    kinds, missing, unexplained = Counter(), [], []
    follows_changed = chunks_after_changed_table(after["chunks"], changed_tables)
    for chunk in base["chunks"]:
        kind = ("form" if chunk["type"] == "form" else "table_ops" if chunk["table_id"] in ops_ids
                else "table_non_ops" if chunk["type"] == "table" else "text")
        other = a_chunks.get(chunk["chunk_id"])
        if other is None:
            kinds[kind + ":missing"] += 1
            missing.append(chunk["chunk_id"])
        elif dump(chunk) == dump(other):
            kinds[kind + ":identical"] += 1
        elif dump(strip(chunk)) == dump(strip(other)):
            # Only the character offsets differ. That is expected exactly when the chunk comes after a table that was
            # rebuilt or added in the same document (the offsets add up the lengths of all chunks before it).
            kinds[kind + ":offset_only"] += 1
            if chunk["chunk_id"] not in follows_changed:
                unexplained.append(chunk["chunk_id"])
        else:
            kinds[kind + ":changed"] += 1
    facts["baseline_chunks_by_kind"] = dict(sorted(kinds.items()))
    facts["chunks_offset_only_changed"] = sum(v for k, v in kinds.items() if k.endswith(":offset_only"))
    facts["offset_changes_not_after_a_rebuilt_table"] = unexplained
    facts["baseline_chunk_ids_missing_in_after"] = missing
    baseline_ids = {c["chunk_id"] for c in base["chunks"]}
    facts["chunks_only_in_after"] = sum(i not in baseline_ids for i in a_chunks)
    kept = [c["chunk_id"] for c in base["chunks"] if c["table_id"] not in ops_ids]
    facts["order_of_non_ops_chunks_preserved"] = kept == [c["chunk_id"] for c in after["chunks"] if c["chunk_id"] in set(kept)]
    return facts


def other_records(base: dict, after: dict) -> dict:
    facts = {}
    b_par = {p["parent_id"]: p for p in base["parents"]}
    a_par = {p["parent_id"]: p for p in after["parents"]}
    facts["parents"] = {"baseline_missing": sum(i not in a_par for i in b_par),
                        "changed": sum(i in a_par and a_par[i] != p for i, p in b_par.items()),
                        "new": sorted(i for i in a_par if i not in b_par)}
    facts["forms_identical"], facts["files_identical"] = base["forms"] == after["forms"], base["files"] == after["files"]
    a_pages = {p["page_id"]: p for p in after["pages"]}
    changed = {p["page_id"]: [k for k in p if p[k] != a_pages[p["page_id"]][k]] for p in base["pages"] if p != a_pages[p["page_id"]]}
    rebuilt = [t for t in after["tables"] if t["parts"][0]["source_ref"].startswith("textlayer:")]
    allowed = {f"{t['file_id']}:p{t['pages'][0]}" for t in rebuilt}
    facts["pages"] = {"changed": len(changed), "changed_fields": dict(Counter(k for v in changed.values() for k in v)),
                      "all_changed_pages_have_a_rebuilt_table": set(changed) <= allowed, "pages_with_rebuilt_table": len(allowed)}
    bad = 0
    for table in rebuilt:
        chunks = [c for c in after["chunks"] if c["table_id"] == table["table_id"]]
        header = "| " + " | ".join(table["grid"][0]) + " |"
        bad += (not chunks or any(not c["text"].startswith(header) for c in chunks))
        bad += sum(c["row_end"] - c["row_start"] for c in chunks) != table["num_rows"] - 1
    facts["rebuilt_tables"] = {"count": len(rebuilt), "seven_columns_one_header_row": sum(
        t["num_cols"] == 7 and t["header_rows"] == 1 and len(t["grid"][0]) == 7 for t in rebuilt),
        "join_single": sum(t["join"] == {"status": "single", "reasons": []} for t in rebuilt), "chunk_problems": bad}
    return facts


def events(base_dir: Path, after_dir: Path, after: dict) -> dict:
    """Track B: graphrag.events on both releases against the frozen E28 result. Details only for DEV dates."""
    sys.path.insert(0, str(ROOT))
    from graphrag import events as E
    from graphrag.data import load_chunks
    wanted = sorted({r["doc_id"] for r in after["chunks"] if "dailyreport" in r["doc_id"]})
    built = {}
    for label, directory in (("baseline", base_dir), ("after", after_dir)):
        chunks = load_chunks(wanted, directory / "chunks.jsonl")
        tables = [t for t in read(directory, "tables") if t["doc_id"] in wanted]
        found, stats = E.build_events(chunks, tables)
        built[label] = ({(e.date, e.start, e.end): e.__dict__ for e in found}, stats, found)
    e28 = {(e["date"], e["start"], e["end"]): e for e in json.loads((ROOT / "graphrag/results/E28_events.json").read_text(encoding="utf-8"))["events"]}
    sig = lambda e: (e["date"], e["start"], e["end"], e["hours"], e["end_md"], e["code"])  # noqa: E731
    new, old, base = built["after"][0], e28, built["baseline"][0]
    common = set(new) & set(old)
    dev_differs = sorted(k for k in common if k[0] in DEV and new[k]["description"] != old[k]["description"])
    return {
        "baseline_events": len(base), "after_events": len(new), "after_stats": built["after"][1],
        "after_hours": round(sum(e.hours for e in built["after"][2]), 2), "e28_events": len(old),
        "common_keys": len(common), "differing_date_start_end_hours_end_md_code": sum(sig(new[k]) != sig(old[k]) for k in common),
        "e28_keys_missing_in_after": len(set(old) - set(new)), "after_keys_not_in_e28": len(set(new) - set(old)),
        "baseline_keys_subset_of_after": set(base) <= set(new),
        "baseline_events_identical_in_after": all(sig(new[k]) == sig(v) for k, v in base.items() if k in new),
        "description_differs_dev_dates_only": {"differs": len(dev_differs), "of": sum(1 for k in common if k[0] in DEV),
                                               "examples": [{"key": list(k), "e28": old[k]["description"],
                                                             "after": new[k]["description"]} for k in dev_differs]},
    }


def record_coverage(base: dict, repairs: list[dict]) -> dict:
    """Every Docling Operations table of the baseline must sit on a page that has a record in the sidecar.

    Aggregate counts only (per file, by status and reason); no table or page is named.
    """
    doc_of = {f["file_id"]: f["doc_id"] for f in base["files"]}
    recorded = {(r["doc_id"], r["page"]) for r in repairs}
    without = Counter(t["file_id"] for t in base["tables"] if is_ops(t)
                      and not any((doc_of[t["file_id"]], page) in recorded for page in t["pages"]))
    return {"records": len(repairs), "by_status_reason": dict(sorted(Counter(
                f"{r['status']}:{r['reason'] or '-'}" for r in repairs).items())),
            "by_action": dict(sorted(Counter(r["action"] for r in repairs).items())),
            "by_state": dict(sorted(Counter(r.get("state") or "-" for r in repairs).items())),
            "baseline_ops_tables_without_a_record": sum(without.values()),
            "baseline_ops_tables_without_a_record_by_file": dict(sorted(without.items()))}
ROUND_ONE_FIELDS = ("doc_id", "page", "index", "status", "reason", "action", "table_id", "docling_table")


def compare_records(baseline: list[dict], after: list[dict]) -> dict:
    """Round 1 fields of the sidecar records of two exports (the fields Round 2 added are not compared).

    Records are matched by (doc_id, page, index); aggregate counts only, with the (status, reason) transitions of the
    records that differ so a reader can see whether they are the expected ones.
    """
    key = lambda r: (r["doc_id"], r["page"], r["index"])  # noqa: E731
    old, new = {key(r): r for r in baseline}, {key(r): r for r in after}
    same = sum(all(old[k].get(f) == new[k].get(f) for f in ROUND_ONE_FIELDS) for k in old if k in new)
    differ = Counter(f"{old[k]['status']}:{old[k]['reason'] or '-'} -> {new[k]['status']}:{new[k]['reason'] or '-'}"
                     for k in old if k in new and any(old[k].get(f) != new[k].get(f) for f in ROUND_ONE_FIELDS))
    return {"baseline_records": len(old), "after_records": len(new), "identical_round_one_fields": same,
            "only_in_baseline": len(set(old) - set(new)), "only_in_after": len(set(new) - set(old)),
            "different_by_transition": dict(sorted(differ.items()))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--events", action="store_true")
    parser.add_argument("--repairs", type=Path, help="table_repairs sidecar of the export: every baseline Operations "
                        "table must sit on a page with a record")
    parser.add_argument("--repairs-baseline", type=Path, help="table_repairs sidecar of the baseline export, to compare "
                        "the Round 1 fields of the records")
    args = parser.parse_args(argv)
    base = {g: read(args.baseline, g) for g in GROUPS}
    after = {g: read(args.after, g) for g in GROUPS}
    result = {"counts_baseline": {g: len(v) for g, v in base.items()}, "counts_after": {g: len(v) for g, v in after.items()},
              **tables_and_chunks(base, after), **other_records(base, after)}
    if args.repairs:
        result["record_coverage"] = record_coverage(base, json.loads(args.repairs.read_text(encoding="utf-8")))
        if args.repairs_baseline:
            result["records_vs_baseline"] = compare_records(json.loads(args.repairs_baseline.read_text(encoding="utf-8")),
                                                            json.loads(args.repairs.read_text(encoding="utf-8")))
    if args.events:
        result["track_b_events"] = events(args.baseline, args.after, after)
    print(json.dumps(result, indent=1, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
