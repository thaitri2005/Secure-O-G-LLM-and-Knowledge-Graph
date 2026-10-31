"""Facts from table rows by K2's deterministic mappings, with no model call (§6.2 stage 4; risk R-01; E22).

    python -m graphrag.tables --pool three --name E22_tables_three

Writes facts in the same shape as `graphrag.neo4j_kg` (chunk, well, property, qualifier, context, value), so
`baseline.py --fact-sheet ... --validate` can use them alone or together with extracted facts.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter

from .baseline import POOLS, RESULTS, pool
from .data import AK3, ROOT, load_questions
from .ontology import TABLES, load as load_k2, table_rows
from .retrieval import well_names
from .scoring import matches

NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
SIZE = re.compile(r"\d+(?:-\d+/\d+)?")
MAX_HEADER = 50
BARE_NUMBER = re.compile(r"\W?\s*\d[\d.,/ -]*")  # 40, 1,955.0, 10-3/4, ~ 220 (with any leading symbol)


def first(pattern: re.Pattern, text: str) -> str | None:
    found = pattern.search(text or "")
    return found.group().replace(",", "") if found else None


def header_count(rows: list[list[str]]) -> int:
    """Leading rows that are headers: few of their cells are bare numbers. The parser's own counts disagree with
    the tables (56-32: one rendered header row over a two-row header; two header rows over a data row)."""
    count = 0
    for row in rows[:3]:
        cells = [c for c in row if c.strip()]
        if not cells or sum(bool(BARE_NUMBER.fullmatch(c.strip())) for c in cells) >= len(cells) / 4:
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


def extract(chunks, k2: dict) -> list[dict]:
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
    for line in TABLES.read_text(encoding="utf-8").splitlines():
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

        def fact(r, prop, qualifier, value, context=None):
            qualifier = "planned" if "planned" in caption and qualifier == "actual" else qualifier
            facts.append({"chunk": chunk_for(r), "well": main_well[table["doc_id"]], "property": prop,
                          "qualifier": qualifier, "context": context, "value": value, "source": table["table_id"]})

        for m in mappings["series"]:
            if not all(column(heads, w) is not None for w in m["when"]):
                continue
            vcol = column(heads, m["value"])
            ccols = {k: column(heads, w) for k, w in m["context"].items()}
            for r in range(start, len(rows)):
                row = rows[r]
                value = first(NUMBER, row[vcol]) if vcol < len(row) else None
                context = {k: (first(SIZE if k == "casing_size_in" else NUMBER, row[i]) if i is not None and i < len(row)
                               else None) for k, i in ccols.items()}
                if value is not None and all(context.values()):
                    fact(r, m["property"], m["qualifier"], value, context)
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
    parser.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    facts = extract(pool(args.pool), load_k2())
    result = {"pool": args.pool, "method": "K2 table mappings, no model call", "llm_calls": 0,
              "facts_by_property": dict(Counter(f["property"] for f in facts)),
              "extraction": recall([f for f in facts if f["chunk"].startswith(AK3)]), "facts": facts}
    path = RESULTS / f"{args.name}.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "facts"}, indent=2))
    print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
