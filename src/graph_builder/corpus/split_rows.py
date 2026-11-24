"""Restore a source-proven narrative cell split across two consecutive pages."""
from __future__ import annotations

from collections import Counter, defaultdict
from functools import cache
import re

from .activity_detail import PageGrid, assemble, native_matches, replace_chunks
from .aligned_grids import QUANTITY
from .column_alignment import comparison
from .complex_grids import independent_words, read_rectangles, word_data
from .ops_tables import chunk_template, grid_table_record
from .qa.crossrep import parse_table_chunk
from .report_fields import source_report_identity
from .table_join import assess_pair, candidate_pairs, running_limits
from .text_layer import source_page

RULE = "split_row"
CLOSED_SENTENCE = re.compile(r"[.!?;:]\s*[\])\"'”’]*$")
CONTINUATION_WORD = re.compile(r"\b(?:continued\b|cont\.)", re.I)


def fragment_column(left, right):
    """Infer a narrative lane from a short fragment and the neighboring complete records."""
    if len(left) < 3 or len(right) < 3:
        return None
    prefix, suffix = left[-1], right[0]
    nonempty = [c for c, text in enumerate(suffix) if text.strip()]
    if len(nonempty) != 1:
        return None
    column, = nonempty
    neighbors = [*left[-3:-1], *right[1:3]]
    first_letter = next((ch for ch in suffix[column] if ch.isalpha()), "")
    if (not prefix[column] or CLOSED_SENTENCE.search(prefix[column]) or not first_letter.islower()
            or any(not any(ch.isalpha() for ch in row[column]) for row in neighbors)
            or QUANTITY.fullmatch(suffix[column])):
        return None
    anchors = [c for c in range(len(prefix)) if c != column
               and all(QUANTITY.fullmatch(row[c]) for row in [*neighbors, prefix])]
    return column if anchors and any(ch.isalpha() for ch in prefix[column]) else None


def read_panel(pdf, page, box):
    if page.rotation:
        return None
    candidates = [table for table in page.find_tables(strategy="lines_strict").tables
                  if all(abs(a - b) <= 3 for a, b in zip(table.bbox, box, strict=True))]
    if len(candidates) != 1:
        return None
    panel = read_rectangles(candidates[0], word_data(page), independent_words(pdf, page.number + 1))
    if not panel or panel["header_rows"] != 1 or any(c["row_span"] != 1 or c["col_span"] != 1 for c in panel["cells"]):
        return None
    grid = panel["grid"]
    edges = [*[box[0] for box in panel["cell_boxes"][0]], panel["bbox"][2]]
    return PageGrid(page.number + 1, (0, 0), grid[0], grid[1:], panel["cell_boxes"], edges, panel["bbox"], {})


def original_text_survives(table, chunks, panel):
    """A source reconstruction must preserve every prior table token and prose remains in its original chunk."""
    def tokens(values):
        return Counter(re.findall(r"\w+|[^\w\s]", comparison(" ".join(values))))

    if not chunks or any(chunk["ocr"] or chunk["pages"] != [panel.page] for chunk in chunks):
        return False
    parsed = [parse_table_chunk(chunk["text"]) for chunk in chunks]
    if any(not part["separator_ok"] or part["caption"] or part["stray"] or part["header"] != parsed[0]["header"] for part in parsed):
        return False
    visible = tokens(value for row in (panel.header, *panel.rows) for value in row)
    prior = [*parsed[0]["header"], *(value for part in parsed for row in part["rows"] for value in row)]
    return not (tokens(cell["text"] for cell in table["cells"]) - visible or tokens(prior) - visible)


def prove_pair(first, second, a, b, context, get_layer, options):
    if (not a or not b or len(a.edges) != len(b.edges)
            or any(abs(x - y) > 2 for x, y in zip(a.edges, b.edges, strict=True))
            or context.get(a.page, {}) != context.get(b.page, {})):
        return None
    layer_a, layer_b = get_layer(a.page), get_layer(b.page)
    identity_a, identity_b = source_report_identity(layer_a), source_report_identity(layer_b)
    if any(set(identity_a[key]).isdisjoint(identity_b[key]) for key in identity_a.keys() & identity_b.keys()):
        return None
    limits = running_limits({a.page: layer_a, b.page: layer_b}, options)
    # Treat the native tables as two physically corroborated grids for the unchanged boundary checker.
    inputs = []
    for original, panel in ((first, a), (second, b)):
        record = grid_table_record(original["table_id"], original["doc_id"], original["source_ref"],
                                   panel.page, panel.bbox, [panel.header, *panel.rows])
        record["parts"] = [{"source_ref": original["source_ref"]}]
        inputs.append(record)
    decision = assess_pair(*inputs, layer_a, layer_b, limits, options)
    if decision["decision"] == "joined" and decision["dropped_header_rows"] == 1 and decision["evidence"].get("continuation_caption"):
        return fragment_column(a.rows, b.rows)
    return None


def repair_document(pdf, pages, chunks, tables, max_chars, context, options, *, stacked_pages=(), source_texts=None):
    import pymupdf

    eligible = {p["page"]: p for p in pages if p.get("mode") == "text" and not p.get("rotation")
                and not (p.get("orientation") or {}).get("normalized") and p["page"] not in stacked_pages}
    candidates = [(a, b) for a, b in candidate_pairs(tables, set())
                  if all(len(t["regions"]) == 1 and t["regions"][0]["page"] in eligible
                         and t["source_ref"].startswith("#/tables/") and t["num_rows"] >= 3 for t in (a, b))
                  and (source_texts is None or CONTINUATION_WORD.search(source_texts.get(b["regions"][0]["page"], "")))]
    if not candidates:
        return chunks, tables, []
    findings, used = [], set()
    children = defaultdict(list)
    for chunk in chunks:
        children[chunk["table_id"]].append(chunk)
    with pymupdf.open(pdf) as source:
        @cache
        def get_layer(number):
            return source_page(pdf, number, displayed_origin=True)

        for first, second in candidates:
            if {first["table_id"], second["table_id"]} & used:
                continue
            left, right = (table["regions"][0] for table in (first, second))
            page_a, page_b = (source[region["page"] - 1] for region in (left, right))
            if left["bbox"][3] < page_a.rect.height * .78 or right["bbox"][1] > page_b.rect.height * .24:
                continue
            try:
                a, b = [read_panel(pdf, page, region["bbox"]) for page, region in ((page_a, left), (page_b, right))]
                column = prove_pair(first, second, a, b, context, get_layer, options)
            except (OSError, RuntimeError, ValueError):
                continue
            if column is None or native_matches(tables, [a, b]) != {first["table_id"], second["table_id"]}:
                continue
            if not all(original_text_survives(table, children[table["table_id"]], panel)
                       for table, panel in ((first, a), (second, b))):
                continue
            template = chunk_template(children[first["table_id"]][0])
            built = assemble([a, b], first["doc_id"], first["table_id"], template, max_chars,
                             rule=RULE, description_column=column)
            if not built:
                continue
            table, pieces = built
            both = {first["table_id"], second["table_id"]}
            position = tables.index(first)
            tables = tables[:position] + [table] + [t for t in tables[position:] if t["table_id"] not in both]
            chunks = replace_chunks(chunks, pieces, both)
            used.update(both)
            findings.append({"page": a.page, "rule": RULE, "action": "joined_fragment",
                             "continuation_page": b.page, "column": column})
    return chunks, tables, findings
