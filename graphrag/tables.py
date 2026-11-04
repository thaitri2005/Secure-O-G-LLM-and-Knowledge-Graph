"""Facts from table rows by K2's deterministic mappings, with no model call (§6.2 stage 4; risk R-01; E22).

    python -m graphrag.tables --pool three --name E22_tables_three
    python -m graphrag.tables --run e25_78-32 --name E25_tables_78-32   # a named ingestion run, kept apart from the pools

Writes facts in the same shape as `graphrag.neo4j_kg` (chunk, well, property, qualifier, context, value), so
`baseline.py --fact-sheet ... --validate` can use them alone or together with extracted facts.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter

from .baseline import POOLS, RESULTS, pool
from .data import AK3, ROOT, load_chunks, load_questions
from .ontology import TABLES, load as load_k2, table_rows
from .retrieval import well_names
from .scoring import matches

NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
SIZE = re.compile(r"\d+(?:[- ]\d+/\d+|\.\d+)?")  # 5-1/2, 5 1/2 and 5.5 (78-32 writes decimals, E25)
FRACTIONS = {"¼": "1/4", "½": "1/2", "¾": "3/4", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8"}
METRES = re.compile(r"(?:^|[\s(])(?:m|metres?|meters?)(?:$|[\s)])")
PLAIN_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
MAX_HEADER = 50
BARE_NUMBER = re.compile(r"\W?\s*\d[\d.,/ -]*")  # 40, 1,955.0, 10-3/4, ~ 220 (with any leading symbol)


def first(pattern: re.Pattern, text: str) -> str | None:
    found = pattern.search(text or "")
    return found.group().replace(",", "") if found else None


def casing_size_text(text: str) -> str | None:
    """A size in one form: 13 ⅜" and 13 3/8 become 13-3/8."""
    for symbol, fraction in FRACTIONS.items():
        text = re.sub(rf"\s*-?{symbol}", f"-{fraction}", text or "")
    size = first(SIZE, text)
    return size.replace(" ", "-") if size else None


def paired_numbers(*cells: str) -> list[tuple[str, ...]]:
    """Rows from cells holding only numbers. The parser merges neighbouring rows ("114.20 125.50" over "0.20 0.10");
    they can be split when every cell holds the same count. Anything else is skipped, not guessed (E29)."""
    tokens = [c.replace("°", " ").split() for c in cells]
    if not tokens[0] or any(len(t) != len(tokens[0]) for t in tokens):
        return []
    if not all(PLAIN_NUMBER.fullmatch(x) for t in tokens for x in t):
        return []
    return [tuple(x.replace(",", "") for x in row) for row in zip(*tokens)]


def header_count(rows: list[list[str]]) -> int:
    """Leading rows that are headers: few of their cells are bare numbers. The parser's own counts disagree with
    the tables (56-32: one rendered header row over a two-row header; two header rows over a data row)."""
    count = 0
    for row in rows[:3]:
        cells = [c for c in row if c.strip()]
        if not cells or sum(bool(BARE_NUMBER.fullmatch(c.strip())) for c in cells) >= len(cells) / 4:
            break
        # "Wellbore: Original Wellbore" under a survey's headers is a section row, not a header (E25).
        if count and cells[0].endswith(":"):
            break
        count += 1
    return max(1, count)


def headers(rows: list[list[str]], count: int) -> list[str]:
    """Column headers, joining multi-row headers (Measured / Depth)."""
    width = max(len(r) for r in rows)
    return [" ".join(r[c] for r in rows[:count] if c < len(r)).lower() for c in range(width)]


def column(heads: list[str], words: str) -> int | None:
    """The first column whose header has one of the `|`-separated words as a whole word ("inc" is not "inches")."""
    pattern = re.compile(rf"\b({words})\b")
    # Real headers are short labels; garbled daily-report grids put whole paragraphs in the first row.
    return next((i for i, h in enumerate(heads) if len(h) <= MAX_HEADER and pattern.search(h)), None)


def steady_readings(readings: list[tuple], max_step: float) -> list[tuple]:
    """Drops readings a shifted column produced: a value far from its neighbours' median, or a depth far above the
    deepest reading so far. A survey changes gradually and goes down, so such a reading is a parsing error (E29)."""
    if len(readings) < 5:
        return readings
    kept, deepest = [], 0.0
    for i, reading in enumerate(readings):
        values = sorted(float(x[2]) for x in readings[max(0, i - 3):i + 4])
        depth = float(reading[1])
        if abs(float(reading[2]) - values[len(values) // 2]) <= max_step and depth >= deepest * 0.5:
            kept.append(reading)
            deepest = max(deepest, depth)
    return kept


def extract(chunks, k2: dict, tables=None) -> list[dict]:
    by_table: dict[str, list] = {}
    for c in chunks:
        if c.table_id:
            by_table.setdefault(c.table_id, []).append(c)
    main_well = {}
    for doc in {c.doc_id for c in chunks}:
        counts = Counter(w for c in chunks if c.doc_id == doc for w in well_names(c.text))
        main_well[doc] = counts.most_common(1)[0][0] if counts else None
    mappings = k2["table_mappings"]
    facts = []
    for line in (tables or TABLES).read_text(encoding="utf-8").splitlines():
        table = json.loads(line)
        parts = by_table.get(table["table_id"])
        if not parts or not main_well.get(table["doc_id"]):
            continue
        rows = table_rows(table)
        if len(rows) < 2:
            continue
        start = header_count(rows)
        heads = headers(rows, start)
        caption = parts[0].text.split("|")[0].lower()

        def chunk_for(r: int) -> str:
            return next((c.id for c in parts if c.row_start is not None and c.row_start <= r <= c.row_end), parts[0].id)

        def fact(r, prop, qualifier, value, context=None, unit=None):
            qualifier = "planned" if "planned" in caption and qualifier == "actual" else qualifier
            facts.append({"chunk": chunk_for(r), "well": main_well[table["doc_id"]], "property": prop,
                          "qualifier": qualifier, "context": context, "value": value, "source": table["table_id"],
                          **({"unit": unit} if unit else {})})

        for m in mappings["series"]:
            if not all(column(heads, w) is not None for w in m["when"]):
                continue
            vcol = column(heads, m["value"])
            ccols = {k: column(heads, w) for k, w in m["context"].items()}
            if m.get("number_cells"):
                # Surveys: every cell must be a number; a metre depth is labelled as such (E29).
                dcol = ccols["depth_ft"]
                if dcol is None:
                    break
                # The parser can merge the unit row into the data, so the unit is looked for there too.
                probe = heads[dcol] + " " + (rows[1][dcol] if len(rows) > 1 and dcol < len(rows[1]) else "")
                key = "depth_m" if METRES.search(probe) else "depth_ft"
                readings = [(r, depth, value) for r in range(start, len(rows)) if max(dcol, vcol) < len(rows[r])
                            for depth, value in paired_numbers(rows[r][dcol], rows[r][vcol])
                            if 0 <= float(value) <= m["max_value"]]
                for r, depth, value in steady_readings(readings, m["max_step"]):
                    fact(r, m["property"], m["qualifier"], value, {key: depth})
                break
            for r in range(start, len(rows)):
                row = rows[r]
                value = first(NUMBER, row[vcol]) if vcol < len(row) else None
                context = {k: ((casing_size_text(row[i]) if k == "casing_size_in" else first(NUMBER, row[i])) if i is not None and i < len(row)
                               else None) for k, i in ccols.items()}
                if value is not None and all(context.values()):
                    fact(r, m["property"], m["qualifier"], value, context, "m" if METRES.search(heads[vcol]) else None)
            break  # one series mapping per table
        for m in mappings["rows"]:
            vcol = column(heads, m["value"])
            if vcol is None or not all(column(heads, w) is not None for w in m["when"]):
                continue
            for r in range(start, len(rows)):
                prop = m["labels"].get(rows[r][0].strip().lower())
                value = first(NUMBER, rows[r][vcol]) if prop and vcol < len(rows[r]) else None
                if value is not None:
                    fact(r, prop, "actual", value)
        # Casing strings named in an item column: `13 ⅜" Casing` with a bottom depth. Rows that continue a mixed string
        # have no item, so their cells sit one to the left; the string's deepest bottom is its depth (E29).
        items = mappings.get("casing_items")
        if items and column(heads, items["item"]) == 0:
            depth_col = next((c for c in (column(heads, w) for w in items["depth"]) if c is not None), None)
            # A cement table has the same layout, with the top of cement where the depth would be.
            depth_col = None if column(heads, items["not_depth"]) is not None else depth_col
            deepest: dict[str, tuple[float, int]] = {}
            current = None
            for r in range(start, len(rows)):
                row = rows[r]
                name = row[0].lower()
                shift = 0
                if re.search(items["strings"], name) and not re.search(items["exclude"], name):
                    current = casing_size_text(row[0])
                elif current and PLAIN_NUMBER.fullmatch(row[0].strip()) and len(row) < len(heads):
                    shift = 1
                else:
                    current = None
                    continue
                cell = depth_col - shift if depth_col is not None else None
                depth = first(NUMBER, row[cell]) if current and cell is not None and 0 <= cell < len(row) else None
                if depth is not None and float(depth) > deepest.get(current, (-1, 0))[0]:
                    deepest[current] = (float(depth), r)
            for size, (depth, r) in deepest.items():
                fact(r, "casing_depth", "actual", f"{depth:g}", {"casing_size_in": size}, "m" if METRES.search(heads[depth_col]) else None)
        # Casing weight and grade, in their own columns or inside a "17 ppf, L-80, BTC" column (E27).
        spec = mappings.get("casing_specs")
        size_col = column(heads, spec["size"]) if spec else None
        if size_col is not None and column(heads, spec["when"]) is not None:
            for r in range(start, len(rows)):
                row = rows[r]
                size = first(SIZE, row[size_col]) if size_col < len(row) else None
                if not size:
                    continue
                for prop, source in spec["properties"].items():
                    col = next((column(heads, words) for words in source["columns"] if column(heads, words) is not None), None)
                    found = re.search(source["pattern"], row[col]) if col is not None and col < len(row) else None
                    if found:
                        fact(r, prop, "actual", found.group(1), {"casing_size_in": size})
        # Forms read as two-column tables: "Drilling Rig: | Rig-16" (E27).
        labels = mappings.get("key_value", {})
        for r, row in enumerate(rows):
            prop = labels.get(row[0].strip().lower().rstrip(":")) if len(row) >= 2 else None
            if prop and row[1].strip():
                fact(r, prop, "actual", row[1].strip())
    return facts


def recall(facts: list[dict]) -> dict:
    """Share of the 41 AK-3 gold facts found with the same key, value and context (as in neo4j_kg)."""
    _, gold = load_questions()
    found = []
    for g in gold.values():
        ctx = {k: g[k] for k in ("depth_ft", "casing_size_in") if k in g}
        if any(f["property"] == g["property"] and f["qualifier"] == g["qualifier"] and "AK-3" in well_names(f["well"])
               and matches(f["value"], g) and all(str((f["context"] or {}).get(k)) == str(v) for k, v in ctx.items())
               for f in facts):
            found.append(g["id"])
    return {"gold_facts": len(gold), "gold_found": len(found), "recall": round(len(found) / len(gold), 3)}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pool", choices=POOLS, default="three")
    parser.add_argument("--run", help="a named run under data/interim/runs/ instead of a pool (E25)")
    parser.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    if args.run:
        run = ROOT / "data/interim/runs" / args.run
        facts = extract(load_chunks(path=run / "gdr_chunks_full.jsonl"), load_k2(), run / "gdr_tables.jsonl")
    else:
        facts = extract(pool(args.pool), load_k2())
    result = {"pool": args.pool, "run": args.run, "method": "K2 table mappings, no model call", "llm_calls": 0,
              "facts_by_property": dict(Counter(f["property"] for f in facts)),
              **({} if args.run else {"extraction": recall([f for f in facts if f["chunk"].startswith(AK3)])}),
              "facts": facts}
    path = RESULTS / f"{args.name}.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "facts"}, indent=2))
    print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
