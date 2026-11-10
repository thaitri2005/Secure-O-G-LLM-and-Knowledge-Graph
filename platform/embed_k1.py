"""Embed a K1 release into pgvector and check search from the store (C-C10, D-56).

    python platform/embed_k1.py embed      # one vector per chunk into chunk_vectors
    python platform/embed_k1.py check      # pgvector top 5 equals the same search done in memory

Vectors come from Qwen3-Embedding-0.6B served by llama.cpp (endpoint `local-embed`, port 8081), called through
`graphrag/client.py` as Track B does, on the same passage text (`section` + text) and normalised the same way, so
the store holds what `graphrag.retrieval.Dense` computes in memory. Each vector keeps the chunk's well and report
date for filtering. End-of-well chunks carry no well (B-F57), so they take their file's well: the well the file's
daily-report context names, or else the well name its text mentions most.

`embed` replaces one model's vectors for the release in one transaction. `check` searches the stored vectors with
SQL (`<=>`, cosine distance, exact search) and with numpy on the same vectors, unfiltered, by well and by date,
and fails if any top 5 differs.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

import numpy as np
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graphrag.client import ModelClient, load_endpoints  # noqa: E402
from graphrag.retrieval import QUERY_INSTRUCTION, well_names  # noqa: E402

DSN = "postgresql://kg:platform-dev@127.0.0.1:5434/kg"   # platform/docker-compose.yml
MODEL = "qwen3-embedding-0.6b"                            # the alias in graphrag/README.md's llama-server command
DIMENSIONS = 1024
QUESTIONS = ROOT / "prototype/gold/questions.json"


def passage_text(chunk: dict) -> str:
    """As graphrag.retrieval.passage_text: the section heading carries meaning the chunk text often lacks."""
    return f"{chunk['section']}\n{chunk['text']}" if chunk.get("section") else chunk["text"]


def file_wells(chunks: list[dict]) -> dict[str, str | None]:
    """Each file's well: the one its chunks' report context names most, or else the well name its text mentions most."""
    named, mentioned = {}, {}
    for chunk in chunks:
        well = (chunk.get("context") or {}).get("well")
        if well:
            named.setdefault(chunk["file_id"], Counter())[well] += 1
        mentioned.setdefault(chunk["file_id"], Counter()).update(well_names(chunk["text"]))
    return {file_id: (named.get(file_id) or counts).most_common(1)[0][0] if (named.get(file_id) or counts) else None
            for file_id, counts in mentioned.items()}


def literal(vector) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"


def unit(vectors) -> np.ndarray:
    vectors = np.array(vectors, dtype=np.float32)
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def client(endpoint: str, model: str) -> ModelClient:
    return ModelClient(load_endpoints()[endpoint], model, cache_dir=None)


def release_of(cur, release: str | None) -> str:
    cur.execute("SELECT release FROM k1_releases ORDER BY release")
    releases = [row[0] for row in cur.fetchall()]
    if release:
        return release
    if len(releases) != 1:
        raise SystemExit(f"name a release with --release; the store holds {releases or 'none'}")
    return releases[0]


def embed(args) -> int:
    model = client(args.endpoint, args.model)
    with psycopg.connect(args.dsn) as conn:
        with conn.cursor() as cur:
            release = release_of(cur, args.release)
            cur.execute("SELECT c.record, f.document_type FROM chunks c JOIN files f USING (file_id) "
                        "WHERE f.release = %s ORDER BY c.seq", (release,))
            rows = cur.fetchall()
            chunks = [row[0] for row in rows]
            wells = file_wells(chunks)
            started = time.perf_counter()
            vectors = []
            for i in range(0, len(chunks), args.batch):
                vectors.extend(unit(model.embed([passage_text(c) for c in chunks[i:i + args.batch]])))
            seconds = time.perf_counter() - started
            if any(len(v) != DIMENSIONS for v in vectors):
                raise SystemExit(f"the model returned {len(vectors[0])} dimensions; chunk_vectors holds {DIMENSIONS}")
            cur.execute("DELETE FROM chunk_vectors v USING files f WHERE v.file_id = f.file_id AND f.release = %s "
                        "AND v.embedding_model = %s", (release, args.model))
            cur.executemany(
                "INSERT INTO chunk_vectors (chunk_id, embedding_model, embedding, file_id, document_type, well, "
                "report_date) VALUES (%s, %s, %s::vector, %s, %s, %s, %s)",
                [(c["chunk_id"], args.model, literal(v), c["file_id"], document_type,
                  (c.get("context") or {}).get("well") or wells.get(c["file_id"]),
                  (c.get("context") or {}).get("report_date"))
                 for c, v, (_, document_type) in zip(chunks, vectors, rows)])
            cur.execute("SELECT count(*), count(well), count(report_date) FROM chunk_vectors v JOIN files f "
                        "USING (file_id) WHERE f.release = %s AND v.embedding_model = %s", (release, args.model))
            stored, with_well, with_date = cur.fetchone()
            cur.execute("SELECT sum(page_count) FROM files WHERE release = %s", (release,))
            pages = cur.fetchone()[0]
    ledger = model.ledger.summary()
    print(f"release {release}, model {args.model}: {stored} vectors stored ({with_well} with a well, "
          f"{with_date} with a report date); file wells: {sorted(set(wells.values()), key=str)}")
    print(f"cost: {ledger['calls']} embedding calls, {ledger['prompt_tokens']} tokens, {seconds:.1f} s; "
          f"per page {ledger['prompt_tokens'] / pages:.0f} tokens and {seconds / pages:.2f} s over {pages} pages")
    return 0 if stored == len(chunks) else 1


def store_search(cur, model: str, release: str, query: str, k: int, well: str | None = None,
                 report_date: str | None = None) -> list[str]:
    """Exact cosine search in PostgreSQL, filtered by well and report date in the same query."""
    cur.execute(
        "SELECT v.chunk_id FROM chunk_vectors v JOIN files f USING (file_id) "
        "WHERE f.release = %s AND v.embedding_model = %s "
        "AND (%s::text IS NULL OR v.well = %s) AND (%s::text IS NULL OR v.report_date = %s) "
        "ORDER BY v.embedding <=> %s::vector, v.chunk_id LIMIT %s",
        (release, model, well, well, report_date, report_date, query, k))
    return [row[0] for row in cur.fetchall()]


def check(args) -> int:
    model = client(args.endpoint, args.model)
    with psycopg.connect(args.dsn) as conn, conn.cursor() as cur:
        release = release_of(cur, args.release)
        cur.execute("SELECT v.chunk_id, v.embedding::text, v.well, v.report_date FROM chunk_vectors v JOIN files f "
                    "USING (file_id) WHERE f.release = %s AND v.embedding_model = %s ORDER BY v.chunk_id",
                    (release, args.model))
        rows = cur.fetchall()
        if not rows:
            raise SystemExit("no vectors for this release and model: run `embed` first")
        ids = [r[0] for r in rows]
        matrix = unit([json.loads(r[1]) for r in rows])
        wells, dates = [r[2] for r in rows], [r[3] for r in rows]
        gold = json.loads(QUESTIONS.read_text(encoding="utf-8"))
        questions = [q["question"] for q in (gold["questions"] if isinstance(gold, dict) else gold)]
        report_dates = sorted({d for d in dates if d})[:5]
        cases = ([(q, None, None) for q in questions] + [(q, "AK-3", None) for q in questions]
                 + [(f"What operations were carried out on {d}?", None, d) for d in report_dates])
        query_vectors = unit(model.embed([QUERY_INSTRUCTION + q for q, _, _ in cases]))
        problems = 0
        for (question, well, date), vector in zip(cases, query_vectors):
            scores = matrix @ vector
            keep = [i for i in range(len(ids)) if (well is None or wells[i] == well) and (date is None or dates[i] == date)]
            memory = [ids[i] for i in sorted(keep, key=lambda i: (-float(scores[i]), ids[i]))[:args.k]]
            stored = store_search(cur, args.model, release, literal(vector), args.k, well, date)
            # Equal when every rank has the same similarity; near-ties may swap between float32 and PostgreSQL.
            score = dict(zip(ids, scores))
            if len(stored) != len(memory) or any(abs(score[a] - score[b]) > 1e-5 for a, b in zip(stored, memory)):
                problems += 1
                print(f"differs: {question!r} well={well} date={date}\n  store  {stored}\n  memory {memory}")
    print(f"{len(cases) - problems} / {len(cases)} searches give the same top {args.k} from pgvector as in memory "
          f"({len(questions)} unfiltered, {len(questions)} filtered by well AK-3, {len(report_dates)} by report date)")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["embed", "check"])
    parser.add_argument("--dsn", default=DSN)
    parser.add_argument("--release", help="release in the store (default: the only one)")
    parser.add_argument("--endpoint", default="local-embed", help="endpoint in configs/graphrag/endpoints.json")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args(argv)
    return embed(args) if args.command == "embed" else check(args)


if __name__ == "__main__":
    sys.exit(main())
