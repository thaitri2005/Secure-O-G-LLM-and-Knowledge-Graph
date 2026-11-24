"""Expose uncertainty in retained numeric cells in the retrieval text and its metadata."""
from collections import defaultdict

from ..numeric_cells import RULE, chunk_edits
from ..store import read_jsonl


def project(rows, release, manifest, annotations):
    by_table = defaultdict(dict)
    for findings in manifest.get("table_findings", {}).values():
        for finding in findings:
            if finding.get("rule") == RULE:
                by_table[finding["table_id"]][finding["r"], finding["c"]] = finding["reason"]
    if not by_table:
        yield from rows
        return

    plans = {}
    for table in read_jsonl(release / "tables.jsonl"):
        table_id = table["table_id"]
        if table_id not in by_table or len(table["parts"]) != 1:
            continue
        changes = {}
        for (r, c), reason in by_table[table_id].items():
            if not table["header_rows"] <= r < len(table["grid"]) or not 0 <= c < table["num_cols"]:
                continue
            text = table["grid"][r][c]
            changes[r, c] = dict(previous=text, value=f"[unverified: {text}]", reason=reason)
        plans[table_id] = table["num_cols"], changes

    for chunk in rows:
        plan = plans.get(chunk.get("table_id"))
        if plan is None or chunk["type"] != "table":
            yield chunk
            continue
        width, changes = plan
        edits = chunk_edits(chunk, changes, width)
        if not edits:
            yield chunk
            continue
        text = chunk["text"]
        for begin, end, value in sorted(edits.values(), reverse=True):
            text = text[:begin] + value + text[end:]
        cells = [{"r": r, "c": c, "reason": changes[r, c]["reason"]} for r, c in sorted(edits)]
        annotations.append({"chunk_id": chunk["chunk_id"], "table_id": chunk["table_id"], "cells": cells})
        yield dict(chunk, text=text, numeric_review=cells)
