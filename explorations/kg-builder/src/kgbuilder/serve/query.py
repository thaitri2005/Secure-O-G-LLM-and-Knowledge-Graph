"""Read graph.json and answer alias, temporal, provenance and path queries."""
from __future__ import annotations

from pathlib import Path

import networkx as nx

from kgbuilder.core.config import ConfigError
from kgbuilder.core.contracts import Entity, GraphRecord
from kgbuilder.core.text import TIME_ISO, holds_at, match_key


def load_graph(run_dir: Path) -> GraphRecord:
    """Load the source of truth without consulting a run manifest."""
    try:
        return GraphRecord.model_validate_json((run_dir / "graph.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"graph.json: {exc}") from exc


def entity_keys(entity: Entity) -> set[str]:
    """Return matching keys for the canonical name and all aliases."""
    return {match_key(entity.name)} | {match_key(a) for a in entity.aliases}


def alias(record: GraphRecord, text: str) -> list[Entity]:
    """Find entities by a normalized name or alias in stable id order."""
    return sorted((e for e in record.entities if match_key(text) in entity_keys(e)),
                  key=lambda e: e.entity_id)


def at(record: GraphRecord, subject: str, predicate: str, at: str | None) -> list[dict]:
    """Return accepted facts whose half-open validity interval includes at."""
    if at is not None and not TIME_ISO.fullmatch(at):
        raise ConfigError("at: expected YYYY, YYYY-MM or YYYY-MM-DD")
    subjects = {e.entity_id for e in alias(record, subject)}
    names = {e.entity_id: e.name for e in record.entities}
    rows = [{"statement_id": s.statement_id, "object": names[s.object_id],
             "valid_from": s.valid_from, "valid_to": s.valid_to, "evidence": s.evidence_span.text}
            for s in record.statements if s.status == "accepted" and s.subject_id in subjects
            and s.predicate == predicate and (at is None or holds_at(s.valid_from, s.valid_to, at))]
    return sorted(rows, key=lambda row: (row["valid_from"] or "", row["statement_id"]))


def evidence(record: GraphRecord, statement_id: str | None = None, s: str | None = None,
             p: str | None = None, o: str | None = None) -> list[dict]:
    """Find statement provenance by id or by an alias-aware triple."""
    if statement_id is None and (s is None or p is None or o is None):
        raise ConfigError("evidence: supply a statement id or subject, predicate and object")
    subjects = {e.entity_id for e in alias(record, s)} if s is not None else set()
    objects = {e.entity_id for e in alias(record, o)} if o is not None else set()
    names = {e.entity_id: e.name for e in record.entities}
    rows = []
    for st in sorted(record.statements, key=lambda st: st.statement_id):
        if (st.statement_id == statement_id if statement_id is not None else
                st.subject_id in subjects and st.predicate == p and st.object_id in objects):
            rows.append({"statement_id": st.statement_id, "subject": names[st.subject_id],
                         "predicate": st.predicate, "object": names[st.object_id],
                         "extractor_version": st.extractor_version, "confidence": st.confidence,
                         "support_count": st.support_count,
                         "evidence": [{"doc_id": e.doc_id, "span": e.span, "text": e.text,
                                       "grounding": e.grounding} for e in st.evidence]})
    return rows


def path(record: GraphRecord, src: str, dst: str, max_hops: int = 3) -> list[dict] | None:
    """Find an undirected shortest path with stable parallel-edge selection."""
    sources, targets = alias(record, src), alias(record, dst)
    if not sources or not targets:
        return None
    graph = nx.Graph()
    graph.add_nodes_from(e.entity_id for e in sorted(record.entities, key=lambda e: e.entity_id))
    for st in sorted(record.statements, key=lambda st: st.statement_id):
        if st.status == "accepted" and not graph.has_edge(st.subject_id, st.object_id):
            graph.add_edge(st.subject_id, st.object_id, statement=st)
    try:
        hops = nx.shortest_path(graph, sources[0].entity_id, targets[0].entity_id)
    except nx.NetworkXNoPath:
        return None
    if len(hops) - 1 > max_hops:
        return None
    names = {e.entity_id: e.name for e in record.entities}
    return [{"from": names[a], "predicate": graph[a][b]["statement"].predicate,
             "to": names[b], "statement_id": graph[a][b]["statement"].statement_id}
            for a, b in zip(hops, hops[1:])]
