"""Score immutable grid, form-field and reading-order annotations."""
import csv
import json
from pathlib import Path

from .attribution import page_texts


def whitespace(text):
    return " ".join(text.split())


def score_values(values, text):
    text = whitespace(text)
    values = [value for value in values if value.strip()]
    matches = sum(whitespace(value) in text for value in values)
    return {"value_matches": matches, "value_count": len(values),
            "value_recall": matches / len(values) if values else None}


def bbox_iou(left, right):
    area = max(0, min(left[2], right[2]) - max(left[0], right[0])) * max(0, min(left[3], right[3]) - max(left[1], right[1]))
    union = (left[2] - left[0]) * (left[3] - left[1]) + (right[2] - right[0]) * (right[3] - right[1]) - area
    return area / union if union > 0 else 0.0


def match_table(annotation, tables):
    candidates = [(bbox_iou(annotation["bbox"], region["bbox"]), table)
                  for table in tables if table["doc_id"] == annotation["doc_id"]
                  for region in table["regions"] if region["page"] == annotation["page"]]
    if not candidates:
        return None, 0.0
    overlap, table = max(candidates, key=lambda pair: pair[0])
    return (table if overlap > 0 else None), overlap


def cell_grid(table):
    grid = [[""] * table["num_cols"] for _ in range(table["num_rows"])]
    for cell in table["cells"]:
        grid[cell["r"]][cell["c"]] = cell["text"]
    return grid


def score_grid(expected, predicted, header_rows):
    def count(start, end):
        total = matches = 0
        for row in range(start, end):
            for column, value in enumerate(expected[row]):
                total += 1
                if row < len(predicted) and column < len(predicted[row]):
                    matches += whitespace(value) == whitespace(predicted[row][column])
        return matches, total
    matches, total = count(header_rows, len(expected))
    headers, header_total = count(0, min(header_rows, len(expected)))
    return {"cell_matches": matches, "cell_count": total, "cell_accuracy": matches / total if total else None,
            "header_matches": headers, "header_count": header_total,
            "header_accuracy": headers / header_total if header_total else None,
            "row_count_correct": len(expected) == len(predicted),
            "column_count_correct": max(map(len, expected), default=0) == max(map(len, predicted), default=0),
            "expected_rows": len(expected), "predicted_rows": len(predicted),
            "expected_columns": max(map(len, expected), default=0), "predicted_columns": max(map(len, predicted), default=0)}


def score_order(annotation, predicted):
    unique = {}
    for item in predicted:
        unique.setdefault(item["id"], item)
    predicted = list(unique.values())
    # Preserve the first occurrence when an item has several provenance boxes.
    order = list(dict.fromkeys(item["id"] for item in predicted))
    reference = annotation["reading_order"]
    common = [identifier for identifier in reference if identifier in order]
    ranks = {identifier: index for index, identifier in enumerate(order)}
    discordant = sum(ranks[left] > ranks[right] for index, left in enumerate(common) for right in common[index + 1:])
    pairs = len(common) * (len(common) - 1) // 2
    sections = {item["id"]: item["section"] for item in predicted}
    expected = {item["id"]: item["section"] for item in annotation["items"]}
    matches = sum(sections[identifier] == expected[identifier] for identifier in common)
    return {"kendall_tau": 1 - 2 * discordant / pairs if pairs else None,
            "common_items": len(common), "missing_items": len(set(reference) - set(order)),
            "extra_items": len(set(order) - set(reference)), "section_matches": matches,
            "section_accuracy": matches / len(common) if common else None}


def predicted_page(document, page, options):
    from docling_core.types.doc import ContentLayer, TableItem
    from .filters import clean_text, dropped_item_reasons, filter_running_lines
    document, _ = filter_running_lines(document, options["margin_band"], options["frequency"],
                                       options["running_block_max_gap_lines"], options["running_block_alignment_lines"],
                                       options["running_line_fragment_gap_lines"])
    excluded = dropped_item_reasons(document)
    section, result, seen = None, [], set()
    for item, _ in document.iterate_items(included_content_layers=set(ContentLayer), traverse_pictures=True):
        if item.self_ref in excluded or item.self_ref in seen:
            continue
        text = " ".join(cell.text for cell in item.data.table_cells) if isinstance(item, TableItem) else getattr(item, "text", "")
        if not text.strip():
            continue
        if item.label.value in {"section_header", "title"}:
            section = clean_text(text) or None
        if any(prov.page_no == page for prov in item.prov):
            result.append({"id": item.self_ref, "section": section})
            seen.add(item.self_ref)
    return result


def scoring_document(root, doc_id, document, options):
    """Apply optional table transformations before scoring item reading order."""
    from .runs import conversion_cache
    if options["tables"]["rotation_retry"]:
        from .rotation import retry_rotated_tables
        document, _ = retry_rotated_tables(document, root / "data/raw" / f"{doc_id}.pdf",
                                            conversion_cache(root, options) / "rotated" / doc_id, options)
    if options["tables"]["merge_pages"]:
        from .filters import filter_running_lines
        from .tables import merge_adjacent_tables
        document, _ = filter_running_lines(document, options["margin_band"], options["frequency"],
                                            options["running_block_max_gap_lines"], options["running_block_alignment_lines"],
                                            options["running_line_fragment_gap_lines"])
        document, _ = merge_adjacent_tables(document)
    return document


def score_gold(root: Path, tables, chunks, documents, options):
    gold = root / "data/gold/ingestion"
    results = []
    for annotation in json.loads((gold / "tables.json").read_text(encoding="utf-8")):
        if annotation["doc_id"] not in documents:
            continue
        if annotation["status"] != "corrected":
            raise ValueError("Gold must be corrected before scoring")
        with (root / annotation["csv"]).open(encoding="utf-8", newline="") as stream:
            rows = list(csv.reader(stream))
        record = {"id": annotation["id"], "format": annotation["format"]}
        if annotation["format"] == "form_fields":
            text = whitespace("\n".join(page_texts(c).get(annotation["page"], "") for c in chunks
                                       if c["doc_id"] == annotation["doc_id"]))
            values = [row[2] for row in rows[1:] if row[2].strip()]
            record.update(score_values(values, text))
        else:
            table, overlap = match_table(annotation, tables)
            record.update(iou=overlap, matched_table_id=table["table_id"] if table else None,
                          **score_grid(rows, cell_grid(table) if table else [], annotation["header_rows"]))
        results.append(record)
    pages = []
    for path in sorted((gold / "pages").glob("*.json")):
        annotation = json.loads(path.read_text(encoding="utf-8"))
        if annotation["doc_id"] not in documents:
            continue
        if annotation["status"] != "corrected":
            raise ValueError("Gold must be corrected before scoring")
        predicted = (predicted_page(scoring_document(root, annotation["doc_id"], documents[annotation["doc_id"]], options), annotation["page"], options)
                     if options["chunking"]["strategy"] != "pypdf" else [])
        pages.append({"doc_id": annotation["doc_id"], "page": annotation["page"], **score_order(annotation, predicted)})
    count = sum(r.get("cell_count", 0) for r in results)
    return {"tables": results, "pages": pages,
            "cell_accuracy": sum(r.get("cell_matches", 0) for r in results) / count if count else None}


def supplement_gold(root, tables, chunks, documents, options):
    """Use the same parser and chunking options for cached appendix gold sources."""
    from docling_core.types.doc import DoclingDocument
    from .runs import conversion_cache
    from .chunking import chunks_from_document
    annotations = json.loads((root / "data/gold/ingestion/tables.json").read_text(encoding="utf-8"))
    missing = sorted({a["doc_id"] for a in annotations} - documents.keys())
    for doc_id in missing:
        path = conversion_cache(root, options) / f"{doc_id}.json"
        if not path.exists():
            continue
        document = DoclingDocument.model_validate_json(path.read_text(encoding="utf-8"))
        documents[doc_id] = document.model_copy(deep=True)
        if options["tables"]["rotation_retry"]:
            from .rotation import retry_rotated_tables
            document, _ = retry_rotated_tables(document, root / "data/raw" / f"{doc_id}.pdf",
                                                conversion_cache(root, options) / "rotated" / doc_id, options)
        metadata, records = [], []
        parts, _ = chunks_from_document(document, doc_id, options["max_chars"], options["margin_band"], options["frequency"],
                                        options["running_block_max_gap_lines"], options["running_block_alignment_lines"],
                                        options["running_line_fragment_gap_lines"], metadata, options["chunking"]["strategy"],
                                        options["tables"], records)
        if options["chunking"]["strategy"] == "hybrid":
            from .strategies import hybrid_chunks
            parts, metadata = hybrid_chunks(document, doc_id, options)
        if options["chunking"]["strategy"] != "pypdf":
            tables.extend(records)
            chunks.extend({**part, **extra} for part, extra in zip(parts, metadata))
    return score_gold(root, tables, chunks, documents, options)
