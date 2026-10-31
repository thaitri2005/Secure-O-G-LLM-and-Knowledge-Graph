"""Inputs for this stint: K1 version 0 chunks and the prototype's questions and gold facts (B-D01)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "data/processed/gdr_chunks_full.jsonl"
QUESTIONS = ROOT / "prototype/gold/questions.json"
FACTS = ROOT / "prototype/gold/ak3_facts.json"
PROBE = ROOT / "graphrag/gold/cross_report_probe.json"
QUESTION_SETS = ("prototype", "probe")
AK3 = "gdr882_ak3_eowr"
# The 15 chunks the prototype extracted from (prototype/kgproto/extract.py SLICE).
PROTOTYPE_SLICE = ["c0002", "c0010", "c0012", "c0013", "c0029", "c0037", "c0054", "c0055",
                   "c0004", "c0005", "c0008", "c0022", "c0026", "c0028", "c0031"]


@dataclass(frozen=True)
class Chunk:
    id: str
    doc_id: str
    page: int
    kind: str
    section: str | None
    text: str


def load_chunks(docs: list[str] | None = None, path: Path = CHUNKS) -> list[Chunk]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if docs is None or row["doc_id"] in docs:
            out.append(Chunk(row["chunk_id"], row["doc_id"], row["page"], row["type"], row.get("section"),
                             row["text"]))
    return out


def prototype_slice(chunks: list[Chunk]) -> list[Chunk]:
    wanted = {f"{AK3}#{c}" for c in PROTOTYPE_SLICE}
    return [c for c in chunks if c.id in wanted]


def load_questions(name: str = "prototype") -> tuple[list[dict], dict[str, dict]]:
    """Questions, and gold facts keyed by ID with chunk IDs expanded to full chunk IDs.

    "prototype": the prototype's 31 questions on AK-3. "probe": Track B's cross-report probe (not an
    evaluation set, D-49), whose facts already carry full chunk IDs."""
    if name == "probe":
        probe = json.loads(PROBE.read_text(encoding="utf-8"))
        return probe["questions"], {f["id"]: f for f in probe["facts"]}
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    gold = {}
    for fact in facts["facts"]:
        gold[fact["id"]] = dict(fact, chunks=[f"{facts['document']}#{c}" for c in fact["chunks"]])
    return json.loads(QUESTIONS.read_text(encoding="utf-8")), gold
