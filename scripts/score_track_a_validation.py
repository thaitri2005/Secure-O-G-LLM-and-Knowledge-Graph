"""Score a Track A release independently against the frozen validation reference."""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
import json
from pathlib import Path
import re
import unicodedata

from graph_builder.corpus.qa.handoff import read_verified_view
from graph_builder.corpus.store import file_sha256, read_jsonl


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "configs/benchmarks/track_a_validation_sources.json"
REFERENCE = ROOT / "configs/benchmarks/track_a_validation_reference.json"
UNIT = re.compile(r"\((m/hr|klbf|ppg|m|hr)\)|\b(mmd)\b", re.I)
PRINTED_MARKS = str.maketrans({
    "–": "-", "—": "-", "−": "-", "‘": "'", "’": "'", "“": '"', "”": '"',
})


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).casefold().translate(PRINTED_MARKS)
    value = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", value)
    value = re.sub(r"\s*([-/])\s*", r"\1", value)
    return " ".join(value.split())


def normalize_cell(text: str) -> str:
    value = normalize(text)
    if re.fullmatch(r"\d{1,2}:\d\d", value):
        hours, minutes = value.split(":")
        return f"{int(hours)}:{minutes}"
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
        return str(Decimal(value).normalize())
    return value


def normalize_prose(text: str) -> str:
    return " ".join(re.findall(r"\w+(?:[./:+-](?=\w)\w+)*", normalize(text)))


def score_probes(reference: list[dict], files: dict, published: list[dict], retrieval: list[dict]) -> list[dict]:
    layers = {}
    for name, chunks in (("published", published), ("retrieval", retrieval)):
        by_page = defaultdict(list)
        for chunk in chunks:
            text = f" {normalize_prose(chunk['text'])} "
            for page in chunk["pages"]:
                by_page[chunk["doc_id"], page].append(text)
        layers[name] = by_page

    results = []
    for probe in reference:
        doc_id, page = probe["doc_id"], probe["page"]
        if doc_id in files:
            expected = f" {normalize_prose(probe['label'] + ' ' + probe['value'])} "
            matches = {name: any(expected in text for text in by_page[doc_id, page])
                       for name, by_page in layers.items()}
            results.append(dict(probe, **matches))
    return results


def overlaps_reference(box, expected) -> bool:
    width = max(0, min(box[2], expected[2]) - max(box[0], expected[0]))
    height = max(0, min(box[3], expected[3]) - max(box[1], expected[1]))
    return (width >= .60 * (box[2] - box[0]) and height >= .60 * (box[3] - box[1])
            and height >= .20 * (expected[3] - expected[1]))


def score_table(reference: dict, tables: list[dict]) -> dict:
    table_ids, observed_rows, headers = [], [], []
    for table in tables:
        if table["doc_id"] != reference["doc_id"] or reference["page"] not in table["pages"]:
            continue
        parts = [part for part in table["parts"] if part["page"] == reference["page"]
                 and overlaps_reference(part["bbox"], reference["bbox"])]
        if not parts:
            continue
        table_ids.append(table["table_id"])
        header_count = table["header_rows"]
        headers.append(table["grid"][:header_count])
        indices = sorted({i for part in parts for i in range(max(header_count, part["row_start"]), part["row_end"])})
        observed_rows.extend(table["grid"][i] for i in indices if any(map(normalize_cell, table["grid"][i])))

    key_column = reference["key_col"]
    positions = reference["positions"]
    key_position = positions[key_column][0]
    expected_rows = {normalize_cell(row[key_column]): row for row in reference["rows"]}
    if len(expected_rows) != len(reference["rows"]):
        raise ValueError(f"Duplicate reference row key: {reference['doc_id']}/{reference['name']}")
    by_key = defaultdict(list)
    for row in observed_rows:
        if len(row) > key_position:
            by_key[normalize_cell(row[key_position])].append(row)

    counts = Counter(expected_rows=len(expected_rows), expected_cells=len(expected_rows) * len(positions),
                     table_found=int(bool(table_ids)))
    discrepancies, matched_keys = [], set()
    for key, expected in expected_rows.items():
        matches = by_key.get(key, ())
        counts["ambiguous_keys"] += len(matches) > 1
        actual = matches[0] if len(matches) == 1 else []
        if actual:
            counts["matched_rows"] += 1
            matched_keys.add(key)
        exact = bool(actual)
        for value, (position, label) in zip(expected, positions, strict=True):
            received = actual[position] if position < len(actual) else ""
            if actual and normalize_cell(value) == normalize_cell(received):
                counts["correct_cells"] += 1
                continue
            exact = False
            status = "wrong" if normalize_cell(received) else "missing"
            counts[f"{status}_cells"] += 1
            discrepancies.append(dict(row_key=key, column=position, label=label,
                                      expected=value, actual=received, status=status))
        counts["exact_rows"] += exact

    counts["extra_or_unkeyed_rows"] = sum(key not in expected_rows or len(matches) > 1
                                          for key, matches in by_key.items())
    observed_order = [normalize_cell(row[key_position]) for row in observed_rows
                      if len(row) > key_position and normalize_cell(row[key_position]) in matched_keys]
    expected_order = [key for key in expected_rows if key in matched_keys]
    counts["order_reproduced"] = bool(observed_order) and observed_order == expected_order
    for position, label in positions:
        match = UNIT.search(label)
        if match is None:
            continue
        counts["expected_units"] += 1
        unit = (match[1] or match[2]).lower()
        pattern = re.compile(r"(?<![a-z])" + re.escape(unit) + r"(?![a-z])")
        if len(headers) == 1 and any(pattern.search(normalize(row[position]))
                                     for row in headers[0] if position < len(row)):
            counts["correct_units"] += 1
    return dict(reference, counts=dict(counts), table_ids=table_ids, discrepancies=discrepancies,
                observed_headers=headers)


def score_release(release: Path, qa: Path, sources: list[dict], input_hashes: dict[str, str], reference: dict) -> dict:
    checksums = {name: digest for digest, name in
                 (line.split("  ", 1) for line in (release / "SHA256SUMS").read_text(encoding="utf-8").splitlines())}
    for name in ("files.jsonl", "pages.jsonl", "tables.jsonl", "chunks.jsonl", "forms.jsonl"):
        if file_sha256(release / name) != checksums.get(name):
            raise ValueError(f"K1 checksum differs: {name}")
    files = {row["doc_id"]: row for row in read_jsonl(release / "files.jsonl")}
    if set(files) != set(input_hashes) or any(
            input_hashes[source["id"]] != files[source["id"]]["sha256"]
            or source["pages"] != files[source["id"]]["page_count"] for source in sources):
        raise ValueError("K1 source files or page counts differ from the selected benchmark inputs")
    chunks = list(read_jsonl(release / "chunks.jsonl"))
    verified = read_verified_view(release / "chunks.jsonl", qa / "retrieval_chunks.jsonl")
    retrieval = [json.loads(line) for line in verified.splitlines()]
    tables = list(read_jsonl(release / "tables.jsonl"))
    pages = list(read_jsonl(release / "pages.jsonl"))
    source_qa = list(read_jsonl(qa / "cell_evidence.jsonl"))
    file_to_doc = {row["file_id"]: doc_id for doc_id, row in files.items()}
    families = {source["id"]: source["family"] for source in sources}

    probes = score_probes(reference["probes"], files, chunks, retrieval)
    results = [score_table(case, tables) for case in reference["tables"] if case["doc_id"] in files]
    by_family, by_document = defaultdict(Counter), defaultdict(Counter)
    for result in results:
        by_family[result["family"]].update(result["counts"])
        by_document[result["doc_id"]].update(result["counts"])
    for probe in probes:
        kind = probe["kind"]
        for counts in (by_family[probe["family"]], by_document[probe["doc_id"]]):
            counts.update({f"{kind}_total": 1, f"{kind}_retrieval_total": 1,
                           f"{kind}_published_correct": int(probe["published"]),
                           f"{kind}_retrieval_correct": int(probe["retrieval"])})
    for page in pages:
        doc_id = file_to_doc[page["file_id"]]
        for counts in (by_family[families[doc_id]], by_document[doc_id]):
            counts[f"pages_{page['mode']}"] += 1
    for table in tables:
        doc_id = table["doc_id"]
        for counts in (by_family[families[doc_id]], by_document[doc_id]):
            counts["k1_tables"] += 1
    for row in source_qa:
        doc_id = row.get("doc_id") or file_to_doc.get(row.get("file_id"))
        if doc_id:
            by_family[families[doc_id]][f"qa_cell_{row['status']}"] += 1
    qa_summary = json.loads((qa / "qa-summary.json").read_text(encoding="utf-8"))
    return dict(summary=by_family, docs=by_document, expected_cases=len(results), by_case=results, probes=probes,
                release_counts=dict(files=len(files), tables=len(tables), pages=len(pages), chunks=len(chunks),
                                    retrieval_chunks=len(retrieval), forms=sum(1 for _ in read_jsonl(release / "forms.jsonl"))),
                qa_cell_status=dict(Counter(row["status"] for row in source_qa)),
                qa_validator=qa_summary["k1_validator"])
