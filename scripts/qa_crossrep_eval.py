"""A-403 evaluation of the cross-representation checks. One command, deterministic:

    PYTHONPATH=src python scripts/qa_crossrep_eval.py --out data/interim/overnight/a403/eval.json

(1) clean releases: signals per code with denominators; (2) the former table-vs-chunk residue: a naive token-multiset
comparison (what the earlier 192/204 measurement did, REPORTED) versus the row-wise comparison, with a cause for every
naive mismatch; (3) synthetic corruptions with denominators, in memory for tables/forms and on disk (scratch copy, with
SHA256SUMS rewritten) for release-level cases, together with the K1 validator verdict; (4) determinism, time, memory.
Writes only under the --out folder / its scratch folder; the releases are never modified.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import time

import psutil

from graph_builder.corpus.qa import crossrep as xr
from graph_builder.corpus.k1_validate import inspect

RELEASES = {
    "ops-rebuild-r3-e2": "data/interim/k1-run/corpus/exports/ops-rebuild-r3-e2/releases/20261108T174020Z-e34a87c780d8",
    "k1-legacy": "data/interim/k1-run/corpus/exports/k1-legacy/releases/20261106T181142Z-67e8a9a1c73b",
}
CONFIG = xr.load_config()
BAD = ("WARN", "ERROR")


def rows(path: Path) -> list[dict]:
    return list(xr._read(path))


def severity(code: str) -> str:
    return {r[0]: r[1] for r in xr.REASONS}[code]


def flagged(findings: list[tuple[str, dict]]) -> list[str]:
    return sorted({code for code, _ in findings if severity(code) in BAD})


def load(release: Path) -> dict:
    chunks = rows(release / "chunks.jsonl")
    by_table: dict[str, list[dict]] = {}
    by_form: dict[str, list[dict]] = {}
    for chunk in chunks:
        if chunk.get("table_id"):
            by_table.setdefault(chunk["table_id"], []).append(chunk)
        if chunk.get("form_id"):
            by_form.setdefault(chunk["form_id"], []).append(chunk)
    for group in (by_table, by_form):
        for items in group.values():
            items.sort(key=lambda c: c["child_index"])
    return {"tables": rows(release / "tables.jsonl"), "forms": rows(release / "forms.jsonl"), "by_table": by_table, "by_form": by_form}


def clean_run(release: Path) -> dict:
    process = psutil.Process()
    start, rss0 = time.perf_counter(), process.memory_info().rss
    findings = xr.analyse_release(release, CONFIG)
    seconds = time.perf_counter() - start
    codes = findings.all_codes()
    pages = findings.stats["pages"]
    return {"stats": dict(sorted(findings.stats.items())), "signals_by_code": dict(sorted(codes.items())),
            "warn_or_error_signals": sum(n for c, n in codes.items() if severity(c) in BAD),
            "seconds": round(seconds, 3), "ms_per_page": round(1000 * seconds / max(pages, 1), 2),
            "rss_delta_mb": round((process.memory_info().rss - rss0) / 1e6, 1)}


def naive_residue(data: dict) -> dict:
    """Table-level token multiset of the grid against all table chunks, as in the earlier 192/204 measurement (REPORTED)."""
    tok = lambda text: Counter(re.findall(r"\w+", text.casefold()))
    mismatched, causes = [], Counter()
    for table in data["tables"]:
        chunks = data["by_table"].get(table["table_id"], [])
        grid, chunk_tokens = Counter(), Counter()
        for row in table["grid"]:
            for cell in row:
                grid.update(tok(cell))
        for chunk in chunks:
            chunk_tokens.update(tok(chunk["text"]))
        if grid == chunk_tokens:
            continue
        reasons = []
        parsed = [xr.parse_table_chunk(c["text"]) for c in chunks]
        if len(chunks) > 1:
            reasons.append("header repeated in continuation chunks")
        if any(p["caption"] for p in parsed):
            reasons.append("caption line before the Markdown header (not in tables.jsonl)")
        if chunks and parsed[0]["header"] is not None and chunks[0].get("row_start") != (table.get("header_rows") or 0):
            reasons.append("rendered header rows differ from header_rows (row_start counts rendered header)")
        # a mismatch with a recognised cause must disappear when the three causes are removed explicitly
        rendered = chunks[0]["row_start"] if chunks else 0
        remaining = Counter()
        for p in parsed:
            for row in p["rows"]:
                for cell in row:
                    remaining.update(tok(cell))
        body = Counter()
        for row in table["grid"][rendered:]:
            for cell in row:
                body.update(tok(cell))
        explained = body == remaining
        mismatched.append({"table_id": table["table_id"], "causes": reasons, "explained_by_causes": explained})
        causes.update(reasons)
    return {"tables": len(data["tables"]), "naive_mismatching_tables": len(mismatched), "unexplained": sum(not m["explained_by_causes"] for m in mismatched),
            "cause_counts": dict(sorted(causes.items())), "examples": mismatched[:5]}


def digit_cell(table: dict, start: int):
    for r in range(start, len(table["grid"])):
        for c, cell in enumerate(table["grid"][r]):
            if re.search(r"\d", cell):
                return r, c
    return None


def bump(text: str) -> str:
    match = re.search(r"\d", text)
    return text[:match.start()] + str((int(match.group()) + 1) % 10) + text[match.end():] if match else text


def chunk_for_row(chunks: list[dict], row: int):
    return next((c for c in chunks if c["row_start"] <= row < c["row_end"]), None)


def mutate_chunk_row(chunk: dict, row: int, new_cells: list[str] | None = None, swap_with: int | None = None) -> None:
    lines = chunk["text"].split("\n")
    table_idx = [i for i, line in enumerate(lines) if line.strip().startswith("|")]
    pos = table_idx[2 + row - chunk["row_start"]]
    if new_cells is not None:
        lines[pos] = "| " + " | ".join(cell.replace("|", "\\|") for cell in new_cells) + " |"
    if swap_with is not None:
        other = table_idx[2 + swap_with - chunk["row_start"]]
        lines[pos], lines[other] = lines[other], lines[pos]
    chunk["text"] = "\n".join(lines)


def table_cases(data: dict, limit: int) -> dict:
    """Return per-case {tried, flagged_by_crossrep, expected} for in-memory table mutations."""
    results = {name: {"tried": 0, "flagged": 0} for name in (
        "cell_digit_changed_only_in_tables_jsonl", "cell_digit_changed_only_in_chunk", "cell_digit_changed_in_both_representations",
        "two_rows_swapped_only_in_tables_jsonl", "two_rows_swapped_in_both_representations", "row_end_beyond_row_count",
        "table_chunk_deleted_single_chunk_table", "table_chunk_deleted_last_of_several", "unchanged_control")}
    tables = [t for t in data["tables"] if data["by_table"].get(t["table_id"])]
    for table in tables[:: max(1, len(tables) // limit)][:limit]:
        chunks = data["by_table"][table["table_id"]]
        rendered = chunks[0]["row_start"]
        results["unchanged_control"]["tried"] += 1
        results["unchanged_control"]["flagged"] += bool(flagged(xr.analyse_table(table, chunks, CONFIG)))
        spot = digit_cell(table, rendered)
        if spot:
            r, c = spot
            changed = copy.deepcopy(table)
            changed["grid"][r][c] = bump(changed["grid"][r][c])
            results["cell_digit_changed_only_in_tables_jsonl"]["tried"] += 1
            results["cell_digit_changed_only_in_tables_jsonl"]["flagged"] += bool(flagged(xr.analyse_table(changed, chunks, CONFIG)))
            mutated = copy.deepcopy(chunks)
            cell = list(table["grid"][r])
            cell[c] = bump(cell[c])
            mutate_chunk_row(chunk_for_row(mutated, r), r, new_cells=[xr.collapse(x) for x in cell])
            results["cell_digit_changed_only_in_chunk"]["tried"] += 1
            results["cell_digit_changed_only_in_chunk"]["flagged"] += bool(flagged(xr.analyse_table(table, mutated, CONFIG)))
            results["cell_digit_changed_in_both_representations"]["tried"] += 1
            results["cell_digit_changed_in_both_representations"]["flagged"] += bool(flagged(xr.analyse_table(changed, mutated, CONFIG)))
        body = list(range(rendered, len(table["grid"])))
        pair = next(((a, b) for a in body for b in body if a < b and xr.collapse(" ".join(table["grid"][a])) != xr.collapse(" ".join(table["grid"][b]))
                     and chunk_for_row(chunks, a) is chunk_for_row(chunks, b)), None)
        if pair:
            a, b = pair
            changed = copy.deepcopy(table)
            changed["grid"][a], changed["grid"][b] = changed["grid"][b], changed["grid"][a]
            results["two_rows_swapped_only_in_tables_jsonl"]["tried"] += 1
            results["two_rows_swapped_only_in_tables_jsonl"]["flagged"] += bool(flagged(xr.analyse_table(changed, chunks, CONFIG)))
            mutated = copy.deepcopy(chunks)
            mutate_chunk_row(chunk_for_row(mutated, a), a, swap_with=b)
            results["two_rows_swapped_in_both_representations"]["tried"] += 1
            results["two_rows_swapped_in_both_representations"]["flagged"] += bool(flagged(xr.analyse_table(changed, mutated, CONFIG)))
        mutated = copy.deepcopy(chunks)
        mutated[-1]["row_end"] = table["num_rows"] + 3
        results["row_end_beyond_row_count"]["tried"] += 1
        results["row_end_beyond_row_count"]["flagged"] += bool(flagged(xr.analyse_table(table, mutated, CONFIG)))
        if len(chunks) == 1:
            results["table_chunk_deleted_single_chunk_table"]["tried"] += 1
            results["table_chunk_deleted_single_chunk_table"]["flagged"] += bool(flagged(xr.analyse_table(table, [], CONFIG)))
        else:
            results["table_chunk_deleted_last_of_several"]["tried"] += 1
            results["table_chunk_deleted_last_of_several"]["flagged"] += bool(flagged(xr.analyse_table(table, chunks[:-1], CONFIG)))
    return results


def form_cases(data: dict, limit: int) -> dict:
    results = {name: {"tried": 0, "flagged": 0} for name in ("form_value_changed_only_in_forms_jsonl", "form_value_changed_only_in_chunk",
                                                             "form_value_changed_in_both_representations", "form_chunk_deleted", "unchanged_control")}
    forms = [f for f in data["forms"] if data["by_form"].get(f["form_id"])]
    for form in forms[:: max(1, len(forms) // limit)][:limit]:
        chunks = data["by_form"][form["form_id"]]
        index = next((i for i, f in enumerate(form["fields"]) if re.search(r"\d", f["value"])), None)
        results["unchanged_control"]["tried"] += 1
        results["unchanged_control"]["flagged"] += bool(flagged(xr.analyse_form(form, chunks, CONFIG)))
        results["form_chunk_deleted"]["tried"] += 1
        results["form_chunk_deleted"]["flagged"] += bool(flagged(xr.analyse_form(form, [], CONFIG)))
        if index is None:
            continue
        changed = copy.deepcopy(form)
        changed["fields"][index]["value"] = bump(changed["fields"][index]["value"])
        mutated = copy.deepcopy(chunks)
        lines = mutated[0]["text"].split("\n")
        lines[index] = changed["fields"][index]["key"].rstrip(":") + ": " + changed["fields"][index]["value"]
        mutated[0]["text"] = "\n".join(lines)
        for name, record, chunk_list in (("form_value_changed_only_in_forms_jsonl", changed, chunks),
                                         ("form_value_changed_only_in_chunk", form, mutated),
                                         ("form_value_changed_in_both_representations", changed, mutated)):
            results[name]["tried"] += 1
            results[name]["flagged"] += bool(flagged(xr.analyse_form(record, chunk_list, CONFIG)))
    return results


def write_sums(directory: Path) -> None:
    lines = []
    for path in sorted(p for p in directory.rglob("*") if p.is_file() and p.name != "SHA256SUMS"):
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(directory).as_posix()}")
    (directory / "SHA256SUMS").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def disk_cases(release: Path, scratch: Path) -> list[dict]:
    """Release-level corruptions on a scratch copy (SHA256SUMS rewritten so the validator sees a consistent package)."""
    outcomes = []

    def run(name: str, edit, expect: str) -> None:
        target = scratch / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(release, target)
        edit(target)
        write_sums(target)
        verdict = inspect(target)
        findings = xr.analyse_release(target, CONFIG)
        codes = sorted(c for c in findings.all_codes() if severity(c) in BAD)
        outcomes.append({"case": name, "k1_validator": verdict["status"], "k1_validator_errors": len(verdict["errors"]),
                         "validator_first_error": (verdict["errors"] or [""])[0][:120], "crossrep_codes": codes, "expected": expect, "flagged_as_expected": expect in codes})

    def rewrite(path: Path, fn) -> None:
        items = rows(path)
        fn(items)
        path.write_bytes(("\n".join(json.dumps(i, sort_keys=True, ensure_ascii=False, separators=(",", ":")) for i in items) + "\n").encode("utf-8"))

    def grid_digit(target: Path) -> None:
        def go(items):
            for t in items:
                spot = digit_cell(t, 1)
                if spot:
                    t["grid"][spot[0]][spot[1]] = bump(t["grid"][spot[0]][spot[1]])
                    return
        rewrite(target / "tables.jsonl", go)

    def form_value(target: Path) -> None:
        def go(items):
            for f in items:
                for field in f["fields"]:
                    if re.search(r"\d", field["value"]):
                        field["value"] = bump(field["value"])
                        return
        rewrite(target / "forms.jsonl", go)

    def row_end(target: Path) -> None:
        def go(items):
            for c in items:
                if c.get("row_end"):
                    c["row_end"] += 5
                    return
        rewrite(target / "chunks.jsonl", go)

    def drop_table_chunk(target: Path) -> None:
        tables = {t["table_id"] for t in rows(target / "tables.jsonl")}
        counts = Counter(c["table_id"] for c in rows(target / "chunks.jsonl") if c.get("table_id"))
        victim = next(t for t in sorted(tables) if counts[t] == 1)
        rewrite(target / "chunks.jsonl", lambda items: items.__setitem__(slice(None), [c for c in items if c.get("table_id") != victim]))

    def page_count(target: Path) -> None:
        rewrite(target / "files.jsonl", lambda items: items[0].__setitem__("page_count", items[0]["page_count"] + 1))

    for name, edit, expect in (("tables_jsonl_digit_only", grid_digit, "XREP_TABLE_CHUNK_MISMATCH"), ("forms_jsonl_value_only", form_value, "XREP_FORM_CHUNK_MISMATCH"),
                               ("row_end_beyond_rows", row_end, "XREP_ROW_RANGE_INVALID"), ("table_chunk_deleted", drop_table_chunk, "XREP_TABLE_NO_CHUNK"),
                               ("file_page_count_changed", page_count, "XREP_PAGE_COUNT_MISMATCH")):
        run(name, edit, expect)
    shutil.rmtree(scratch, ignore_errors=True)
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("data/interim/overnight/a403/eval.json"))
    parser.add_argument("--samples", type=int, default=60)
    parser.add_argument("--release", action="append", default=[], metavar="NAME=PATH", help="release to evaluate; repeatable (default: the two K1 run releases)")
    args = parser.parse_args()
    releases = dict(item.split("=", 1) for item in args.release) or RELEASES
    report: dict = {"check": f"{xr.CHECK_NAME}@{xr.CHECK_VERSION}", "releases": {}}
    for name, relative in releases.items():
        release = Path(relative)
        if not release.is_dir():
            report["releases"][name] = {"status": "release directory missing", "path": relative}
            continue
        data = load(release)
        first, second = xr.run_standalone(release), xr.run_standalone(release)
        digest = lambda r: hashlib.sha256(json.dumps(r, sort_keys=True).encode()).hexdigest()
        report["releases"][name] = {
            "clean_run": clean_run(release),
            "deterministic_two_runs_identical": digest(first) == digest(second),
            "former_residue_naive_vs_rowwise": naive_residue(data),
            "synthetic_tables_in_memory": table_cases(data, args.samples),
            "synthetic_forms_in_memory": form_cases(data, args.samples),
            "synthetic_on_disk_with_k1_validator": disk_cases(release, args.out.parent / "mut" / name),
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({name: {"clean": r.get("clean_run", {}).get("signals_by_code"), "naive": r.get("former_residue_naive_vs_rowwise", {}).get("naive_mismatching_tables")}
                      for name, r in report["releases"].items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
