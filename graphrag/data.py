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
SIMULATED = ROOT / "graphrag/gold/simulated_expert_v0.json"
AK3_DAILY = ROOT / "graphrag/gold/ak3_daily_v0.json"
# Ignored by git; regenerate with scripts/run_ak3_appendices.py.
AK3_APPENDIX_EXPORT = ROOT / "data/corpora/ak3_appendices/exports/v1"
HELDOUT = ROOT / "graphrag/gold/simulated_heldout_v0.json"
AK3_DAILY_HELDOUT = ROOT / "graphrag/gold/ak3_daily_heldout_v0.json"
AK3_EVENTS = ROOT / "graphrag/gold/ak3_events_v0.json"
AK3_EVENTS_HELDOUT = ROOT / "graphrag/gold/ak3_events_heldout_v0.json"
QUESTION_SETS = ("prototype", "probe", "simulated", "heldout", "ak3_daily", "ak3_daily_heldout", "ak3_events",
                 "ak3_events_heldout")
AK3 = "gdr882_ak3_eowr"
# The 15 chunks the prototype extracted from (prototype/kgproto/extract.py SLICE).
PROTOTYPE_SLICE = ["c0002", "c0010", "c0012", "c0013", "c0029", "c0037", "c0054", "c0055",
                   "c0004", "c0005", "c0008", "c0022", "c0026", "c0028", "c0031"]


def document_key(chunk_id: str) -> str:
    """The part of a chunk ID that names its document: `<doc_id>` of `<doc_id>#c0005` (K1 version 0), or the file
    ID `f<hex>` of `f<hex>:s6:c0` (Track A's K1 version 1 candidate, E30). Chunks of one document share it."""
    return chunk_id.split("#", 1)[0] if "#" in chunk_id else chunk_id.split(":", 1)[0]


def short_id(chunk_id: str) -> str:
    """A chunk ID without its document part, unique within one document: `c0005`, or `s6:c0` for K1 version 1."""
    return chunk_id.split("#", 1)[1] if "#" in chunk_id else chunk_id.split(":", 1)[-1]


def cited_id(raw: str, hits: list[str], doc_id: str) -> str:
    """The chunk ID a model's citation names, in either ID format. A full ID or a short one that matches a retrieved
    chunk resolves to it; anything else becomes `<doc_id>#<label>`, as before K1 version 1 (B-C07)."""
    label = raw.strip("[] ")
    if label in hits:
        return label
    # Version 0 short labels always meant `<doc_id>#<label>`; keeping that leaves earlier runs unchanged.
    found = [h for h in hits if short_id(h) == label and ("#" not in h or document_key(h) == doc_id)]
    if len(found) == 1:
        return found[0]
    return raw if "#" in raw else f"{doc_id}#{label}"


@dataclass(frozen=True)
class Chunk:
    id: str
    doc_id: str
    page: int
    kind: str
    section: str | None
    text: str
    table_id: str | None = None
    row_start: int | None = None
    row_end: int | None = None


def load_chunks(docs: list[str] | None = None, path: Path = CHUNKS) -> list[Chunk]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if docs is None or row["doc_id"] in docs:
            out.append(Chunk(row["chunk_id"], row["doc_id"], row["page"], row["type"], row.get("section"),
                             row["text"], row.get("table_id"), row.get("row_start"), row.get("row_end")))
    return out


def appendix_chunks_path(export: Path = AK3_APPENDIX_EXPORT) -> Path:
    """The chunk file of the export's current release (CURRENT.json names it)."""
    release = json.loads((export / "CURRENT.json").read_text(encoding="utf-8"))["release"]
    return export / "releases" / release / "chunks.jsonl"


def daily_rows(path: Path | None = None) -> list[dict]:
    """The chunk rows of the four AK-3 daily-report attachments, in the corpus chunk format (E24)."""
    path = path or appendix_chunks_path()
    rows = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return [row for row in rows if "dailyreport" in row["doc_id"]]


def load_daily_chunks(path: Path | None = None) -> list[Chunk]:
    path = path or appendix_chunks_path()
    return load_chunks(sorted({row["doc_id"] for row in daily_rows(path)}), path)


def chunks_on_pages(sources: list[dict], rows: list[dict]) -> list[str]:
    """Chunks on the given attachment pages. E24's gold names pages, not chunks, so that it does not inherit
    parsing errors; a source is {"appx": "30", "page": 17}, matched against doc IDs like gdr882-ak3-appx-30-..."""
    wanted = {(s["appx"], s["page"]) for s in sources}
    return [row["chunk_id"] for row in rows
            if any((row["doc_id"].split("-appx-")[1][:2], page) in wanted for page in row["pages"])]


def prototype_slice(chunks: list[Chunk]) -> list[Chunk]:
    wanted = {f"{AK3}#{c}" for c in PROTOTYPE_SLICE}
    return [c for c in chunks if c.id in wanted]


def load_questions(name: str = "prototype") -> tuple[list[dict], dict[str, dict]]:
    """Questions, and gold facts keyed by ID with chunk IDs expanded to full chunk IDs.

    "prototype": the prototype's 31 questions on AK-3. "probe": Track B's cross-report probe (not an
    evaluation set, D-49), whose facts already carry full chunk IDs. "ak3_daily": E24's questions on the AK-3
    daily reports, whose facts name pages."""
    if name in ("ak3_daily", "ak3_daily_heldout", "ak3_events", "ak3_events_heldout"):
        files = {"ak3_daily": AK3_DAILY, "ak3_daily_heldout": AK3_DAILY_HELDOUT, "ak3_events": AK3_EVENTS,
                 "ak3_events_heldout": AK3_EVENTS_HELDOUT}
        daily = json.loads(files[name].read_text(encoding="utf-8"))
        rows = daily_rows()
        return daily["questions"], {f["id"]: dict(f, chunks=chunks_on_pages(f["sources"], rows)) for f in daily["facts"]}
    if name in ("probe", "simulated", "heldout"):
        probe = json.loads({"probe": PROBE, "simulated": SIMULATED, "heldout": HELDOUT}[name].read_text(encoding="utf-8"))
        return probe["questions"], {f["id"]: f for f in probe["facts"]}
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    gold = {}
    for fact in facts["facts"]:
        gold[fact["id"]] = dict(fact, chunks=[f"{facts['document']}#{c}" for c in fact["chunks"]])
    return json.loads(QUESTIONS.read_text(encoding="utf-8")), gold
