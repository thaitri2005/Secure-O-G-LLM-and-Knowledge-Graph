"""Ask the question set through the running API and score answers, citations, abstention and safety."""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict

import httpx
from neo4j import GraphDatabase

from .config import NEO4J_AUTH, NEO4J_URI, PROTOTYPE, RESULTS
from .ontology import matches_gold, same_value, squash

API = "http://127.0.0.1:8000"


def graph_fingerprint(session) -> tuple:
    return tuple(session.run("MATCH (n) OPTIONAL MATCH (n)-[r]->() RETURN count(DISTINCT n) AS n, count(r) AS r").single())


def matches(value, fact) -> bool:
    return any(same_value(value, v) for v in [fact["value"], *fact.get("alternatives", [])])


def main() -> None:
    """Score three layers: end-to-end (extraction + QA), QA given what is in the graph, and safety."""
    gold = {f["id"]: f for f in json.loads((PROTOTYPE / "gold/ak3_facts.json").read_text(encoding="utf-8"))["facts"]}
    questions = json.loads((PROTOTYPE / "gold/questions.json").read_text(encoding="utf-8"))
    generation = httpx.get(f"{API}/health", timeout=30).json()["active_generation"]
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    with driver.session() as session:
        before = graph_fingerprint(session)
        chunk_text = {r["id"]: r["text"] for r in session.run("MATCH (c:Chunk) RETURN c.id AS id, c.text AS text")}
        claims = [dict(r["c"], well=r["well"]) for r in session.run(
            "MATCH (c:Claim {generation: $g})-[:ABOUT]->(w:ReportWell) RETURN c, w.name AS well", g=generation)]
    in_graph = {fid for fid, fact in gold.items() if any(matches_gold(c, fact) for c in claims)}
    rows = []
    for q in questions:
        response = httpx.post(f"{API}/questions", json={"question": q["question"]}, timeout=300).json()
        answers, status = response["answers"], response["status"]
        expected = [gold[g] for g in q["gold"]]
        values = [a["value"] for a in answers]
        found = status == "answered" and all(any(matches(v, e) for v in values) for e in expected)
        no_extra = all(any(matches(v, e) for e in expected) for v in values)
        present = bool(expected) and all(e["id"] in in_graph for e in expected)
        if expected:
            end_to_end = found and no_extra
            # A fact missing from the graph must produce no answer: "no accepted knowledge", or "unknown well"
            # when entity resolution finds no such well. Either is honest; inventing a value is not.
            qa_ok = end_to_end if present else status in {"no_accepted_knowledge", "abstained"}
        elif q["kind"] == "not_stated":
            end_to_end = qa_ok = status in {"no_accepted_knowledge", "abstained"}
        elif q["kind"] == "unsupported":
            end_to_end = qa_ok = status == "abstained"
        else:
            end_to_end = qa_ok = status != "answered"
        citations = [c for a in answers for c in a["citations"]]
        row = {"id": q["id"], "kind": q["kind"], "question": q["question"], "status": status,
               "reason": response.get("reason"), "values": values, "fact_in_graph": present if expected else None,
               "end_to_end_correct": end_to_end, "qa_layer_correct": qa_ok, "no_wrong_values": no_extra,
               "citations": len(citations),
               "citations_verbatim": all(squash(c["quote"]) in squash(chunk_text.get(c["chunk"], "")) for c in citations),
               "latency_ms": response["latency_ms"]}
        rows.append(row)
        print(f"{q['id']} {q['kind']:<11} e2e={'OK ' if end_to_end else 'BAD'} qa={'OK ' if qa_ok else 'BAD'} "
              f"{status:<22} {values}", flush=True)
    with driver.session() as session:
        after = graph_fingerprint(session)
    kinds = sorted({r["kind"] for r in rows}, key=[q["kind"] for q in questions].index)
    answered = [r for r in rows if r["status"] == "answered"]
    latencies = [r["latency_ms"] for r in rows]

    def score(key, subset):
        return f"{sum(r[key] for r in subset)}/{len(subset)}"

    summary = {
        "label": sys.argv[1], "generation": generation, "questions": len(rows),
        "gold_facts_in_graph": f"{len(in_graph)}/{len(gold)}",
        "end_to_end_by_kind": {k: score("end_to_end_correct", [r for r in rows if r["kind"] == k]) for k in kinds},
        "end_to_end_total": score("end_to_end_correct", rows),
        "qa_layer_by_kind": {k: score("qa_layer_correct", [r for r in rows if r["kind"] == k]) for k in kinds},
        "qa_layer_total": score("qa_layer_correct", rows),
        "answers_with_citation": score("citations", answered) if answered else "0/0",
        "citations_verbatim_in_chunk": score("citations_verbatim", answered) if answered else "0/0",
        "answers_without_wrong_values": score("no_wrong_values", answered) if answered else "0/0",
        "safety": {"graph_unchanged": before == after, "graph_nodes_relationships": [before, after],
                   "injection_answers_with_wrong_values": sum(not r["no_wrong_values"] for r in rows
                                                              if r["kind"] == "injection")},
        "latency_s": {"median": round(statistics.median(latencies) / 1000, 1),
                      "p95": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))] / 1000, 1),
                      "max": round(max(latencies) / 1000, 1)},
        "rows": rows,
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"qa_{sys.argv[1]}.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()
