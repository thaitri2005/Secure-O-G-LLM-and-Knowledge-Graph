"""Map the chunk ids of the main bundle (``gdr_chunks_full.jsonl``) to K1 chunk ids by text.

Chunk ids change with the id scheme, so citations written against the old ids (for example the prototype gold
facts) need a migration path. Pass 1 matches whitespace-normalized text exactly, pass 2 matches the rest by token
Jaccard similarity. The map is a migration aid: chunks the new parser split or merged stay unmapped.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LEGACY_DOCUMENT = "gdr882_ak3_eowr"
NEAR_THRESHOLD = 0.9


def normalize(text: str) -> str:
    return " ".join(text.split())


def jaccard(left: str, right: str) -> float:
    a, b = set(left.split()), set(right.split())
    return len(a & b) / len(a | b) if a | b else 0.0


def load_legacy_rows(path: Path, doc_id: str = LEGACY_DOCUMENT) -> list[dict]:
    rows = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return [row for row in rows if row["doc_id"] == doc_id]


def map_legacy_chunks(old_rows: list[dict], new_rows: list[dict], near: float = NEAR_THRESHOLD) -> list[dict]:
    """One record per old chunk, sorted by old id; every new chunk is used at most once.

    ``method`` is ``exact``, ``near`` or ``unmapped``; an unmapped record has ``new_chunk_id`` and ``jaccard`` null.
    """
    old = sorted(old_rows, key=lambda row: row["chunk_id"])
    new_text = {row["chunk_id"]: normalize(row["text"]) for row in new_rows}
    old_text = {row["chunk_id"]: normalize(row["text"]) for row in old}
    assigned: dict[str, tuple[str, str, float]] = {}
    used: set[str] = set()
    for row in old:
        match = next((cid for cid, text in new_text.items() if cid not in used and text == old_text[row["chunk_id"]]), None)
        if match:
            assigned[row["chunk_id"]] = (match, "exact", 1.0)
            used.add(match)
    candidates = sorted(((jaccard(old_text[o["chunk_id"]], text), o["chunk_id"], cid)
                         for o in old if o["chunk_id"] not in assigned
                         for cid, text in new_text.items() if cid not in used), key=lambda c: (-c[0], c[1], c[2]))
    for score, old_id, new_id in candidates:
        if score >= near and old_id not in assigned and new_id not in used:
            assigned[old_id] = (new_id, "near", round(score, 4))
            used.add(new_id)
    pages = {row["chunk_id"]: row["page"] for row in new_rows}
    records = []
    for row in old:
        new_id, method, score = assigned.get(row["chunk_id"], (None, "unmapped", None))
        records.append({"old_chunk_id": row["chunk_id"], "new_chunk_id": new_id, "method": method, "jaccard": score,
                        "old_page": row["page"], "new_page": pages.get(new_id)})
    return records


def cited_chunk_ids(facts: dict) -> list[str]:
    """Full old ids of the chunks the gold facts cite, sorted."""
    return sorted({f"{facts['document']}#{chunk}" for fact in facts["facts"] for chunk in fact["chunks"]})


def summarize_legacy_map(records: list[dict], facts: dict | None = None) -> dict[str, Any]:
    """Counts per method and, given gold facts, how many cited chunks map and which do not."""
    summary: dict[str, Any] = {"old_chunks": len(records)}
    for method in ("exact", "near", "unmapped"):
        summary[method] = sum(record["method"] == method for record in records)
    if facts is not None:
        mapped = {record["old_chunk_id"]: record["new_chunk_id"] for record in records}
        cited = cited_chunk_ids(facts)
        summary["cited"] = len(cited)
        summary["cited_mapped"] = sum(bool(mapped.get(cid)) for cid in cited)
        summary["cited_unmapped"] = [cid for cid in cited if not mapped.get(cid)]
    return summary
