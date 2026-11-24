"""The vector search in PostgreSQL (graphrag.retrieval.PgVector) returns what the in-memory search (`Dense`) returns.

No embedding server runs here, so a stand-in embedder gives every text a fixed vector from a hash of the text:
the two searches see the same passage vectors and the same query vector, and the tests compare their top k, order
included. Nothing here measures retrieval quality.

Tests needing PostgreSQL skip when it does not answer. They write only into a temporary schema, dropped afterwards
(tests/test_graphrag_stores.py), under a test-only release and test-only embedding model names, so the real release
and its vectors are never touched. The engine test also reads Neo4j, for a well no data has.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
from pathlib import Path
import statistics
import sys
import unittest
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graphrag import baseline, lanes, stores  # noqa: E402
from graphrag.client import Ledger  # noqa: E402
from graphrag.retrieval import Dense, PgVector, passage_text, ranked, top  # noqa: E402
from tests.test_graphrag_stores import NEO4J, NO_NEO4J, NO_POSTGRES, chunk_record, temporary_schema  # noqa: E402

RELEASE = "wtwo-vectors"
# "qwen3-embedding" in the name makes both searches put Qwen3-Embedding's instruction before the question.
MODEL, PARTIAL = "wtwo-qwen3-embedding-stand-in", "wtwo-partial-stand-in"
DIMENSIONS, USED = 1024, 16   # chunk_vectors holds 1,024 dimensions; the stand-in fills 16, so scores spread widely

AK3, TG2, DAILY = "f" + "a" * 16, "f" + "b" * 16, "f" + "c" * 16
FILES = {AK3: ("wtwo_ak3_eowr", "eowr", "AK-3"), TG2: ("wtwo_tg2_eowr", "eowr", "TG-2"),
         DAILY: ("wtwo-appx-30-6-dailyreportsummaryrpt-0a1b2c3d", "daily_report", "AK-3")}
TOPICS = ["total depth", "casing set", "mud weight", "cementing", "bit record", "lost circulation", "logging run",
          "well test", "rig move", "survey", "coring", "kick", "stuck pipe"]
REPEATED = "Mud weight was kept at 9.2 ppg throughout."   # the same passage at three places: exact ties
QUESTIONS = ["What total depth did AK-3 reach?", "Compare the mud weight of AK-3 and TG-2?", "Which casing was set?",
             "What happened on 20 August 2016?", "Was there a kick in TG-2?", "How long did the rig move take?",
             "Compare cementing on AK-3 and TG-2: which took longer?"] + [f"Stand-in question {n}" for n in range(12)]


def vector(text: str) -> list[float]:
    """A fixed vector for a text: equal texts get equal vectors."""
    rng = np.random.default_rng(int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "little"))
    out = np.zeros(DIMENSIONS)
    out[:USED] = rng.standard_normal(USED)
    return out.tolist()


class StandInEmbedder:
    """A `ModelClient` for embeddings only, with fixed vectors; built as `baseline.build` builds the real one."""

    def __init__(self, endpoint=None, model: str = MODEL, cache_dir=None):
        self.model, self.ledger, self.calls = model, Ledger(), 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [vector(t) for t in texts]


def package() -> dict:
    """Two end-of-well reports of 13 chunks, one per well, and a daily report of 6 over two days, in the shape
    platform/load_k1.py loads."""
    chunks = []
    for file_id, (doc_id, kind, well) in FILES.items():
        if kind == "eowr":
            texts = [f"Well {well}: {topic} section, item {n}." for n, topic in enumerate(TOPICS)]
            texts[4] = texts[9] = REPEATED
            chunks += [chunk_record(f"{file_id}:s1:c{n}", doc_id, n // 4 + 1, t) for n, t in enumerate(texts)]
        else:
            chunks += [chunk_record(f"{file_id}:s1:c{n}", doc_id, n // 3 + 1, f"Report For {day}-Aug-16 Well ID: AK-3, "
                                    f"{TOPICS[n]} on the day.", context={"report_date": f"{day}-Aug-16", "well": well})
                       for n, day in enumerate([20, 20, 20, 21, 21, 21])]
    chunks.insert(20, chunks.pop(4))   # one repeated passage later in reading order than the TG-2 report's start
    files = [{"file_id": f, "doc_id": d, "document_type": t, "sha256": f[1:] + "0" * 48, "page_count": 4}
             for f, (d, t, _) in FILES.items()]
    parents = [{"parent_id": f"{f}:s1", "file_id": f, "type": "section", "pages": [1, 2, 3, 4], "document_type": t}
               for f, (_, t, _) in FILES.items()]
    return {"manifest": {"schema_version": "test"}, "sums_sha256": "0" * 64, "files": files, "pages": [],
            "parents": parents, "tables": [], "forms": [], "chunks": chunks, "legacy": []}


def store_vectors(dsn: str, records: list[dict], model: str) -> None:
    """One vector per chunk, as platform/embed_k1.py writes them: the passage text's vector normalised to unit length,
    the file's well and the chunk's report date. Written with nine significant digits, the exact float32 values."""
    import psycopg
    rows = []
    for r in records:
        chunk = stores.to_chunks([r])[0]
        v = np.array(vector(passage_text(chunk)), dtype=np.float32)
        v /= np.linalg.norm(v)
        _, kind, well = FILES[r["file_id"]]
        rows.append((r["chunk_id"], model, "[" + ",".join(f"{x:.9g}" for x in v) + "]", r["file_id"], kind, well,
                     r["context"].get("report_date")))
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.executemany("INSERT INTO chunk_vectors (chunk_id, embedding_model, embedding, file_id, document_type, well, "
                        "report_date) VALUES (%s, %s, %s::vector, %s, %s, %s, %s)", rows)


def stand_in():
    return mock.patch.object(baseline, "ModelClient", StandInEmbedder)


def close(retriever) -> None:
    """Closes the PostgreSQL connections of a retriever and of the retrievers inside it (Fusion, the routers)."""
    if isinstance(retriever, PgVector):
        retriever.close()
    for inner in [*getattr(retriever, "retrievers", []), getattr(retriever, "retriever", None)]:
        if inner is not None:
            close(inner)


# ---- unit tests ----------------------------------------------------------------------------------------------------

class InMemoryTests(unittest.TestCase):
    def setUp(self):
        self.chunks = stores.to_chunks(package()["chunks"])

    def test_dense_breaks_ties_in_reading_order(self):
        dense = Dense(self.chunks, StandInEmbedder())
        hits = [cid for cid, _ in dense.search("How heavy was the mud?", len(self.chunks))]
        repeated = [c.id for c in self.chunks if c.text == REPEATED]
        positions = sorted(hits.index(cid) for cid in repeated)
        self.assertEqual(positions, list(range(positions[0], positions[0] + 4)))   # four equal scores, together
        self.assertEqual([hits[i] for i in positions], repeated)                    # in reading order

    def test_ranked_equals_top_where_no_scores_are_equal(self):
        scores = np.array([0.3, 0.9, 0.1, 0.5, 0.7], dtype=np.float32)
        ids = list("abcde")
        for allowed in (None, {"a", "c", "e"}):
            self.assertEqual(ranked(ids, scores, 3, allowed), top(ids, scores, 3, allowed))

    def test_a_pgvector_spec_needs_a_store(self):
        with mock.patch.dict(os.environ), self.assertRaisesRegex(SystemExit, "BACKEND_DSN"):
            os.environ.pop("BACKEND_DSN", None)
            baseline.build("perwell:fusion:bm25+pgvector:m", self.chunks)

    def test_other_specs_ignore_the_store(self):
        with stand_in():
            for spec in ("wells:bm25", "perwell:fusion:bm25+dense:m", "dates:wells:bm25"):
                plain, given = baseline.build(spec, self.chunks), baseline.build(spec, self.chunks, "postgresql://unused")
                self.assertEqual((given.name, given.search(QUESTIONS[1], 10)), (plain.name, plain.search(QUESTIONS[1], 10)))


# ---- PostgreSQL ----------------------------------------------------------------------------------------------------

@unittest.skipIf(NO_POSTGRES, NO_POSTGRES or "")
class PgVectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = contextlib.ExitStack()
        cls.records = package()["chunks"]
        try:
            cls.dsn = cls.stack.enter_context(temporary_schema(package(), RELEASE))
            store_vectors(cls.dsn, cls.records, MODEL)
            store_vectors(cls.dsn, cls.records[:-1], PARTIAL)   # the last chunk has no vector of this model
            cls.chunks = stores.to_chunks(cls.records)
            cls.eow = [c for c in cls.chunks if not stores.is_daily(c.doc_id)]
        except BaseException:
            cls.stack.close()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def pair(self, chunks, spec: str = "{}:" + MODEL):
        """The spec with the in-memory and the SQL vector search, built on the same chunks."""
        with stand_in():
            memory = baseline.build(spec.format("dense"), chunks)
            sql = baseline.build(spec.format("pgvector"), chunks, self.dsn)
        self.addCleanup(close, sql)
        return memory, sql

    def test_the_sql_search_gives_the_same_top_k_in_the_same_order(self):
        dense, sql = self.pair(self.chunks)
        by_doc = {}
        for c in self.chunks:
            by_doc.setdefault(c.doc_id, set()).add(c.id)
        subsets = [None, by_doc["wtwo_ak3_eowr"], by_doc["wtwo_ak3_eowr"] | by_doc["wtwo_tg2_eowr"],
                   {c.id for c in self.chunks[::3]}, set()]
        compared, timings = 0, []
        for question in QUESTIONS:
            for k in (1, 3, 5, 10, len(self.chunks)):
                for allowed in subsets:
                    expected = dense.search(question, k, allowed)
                    before = sql.sql_seconds
                    got = sql.search(question, k, allowed)
                    timings.append(sql.sql_seconds - before)
                    self.assertEqual([cid for cid, _ in got], [cid for cid, _ in expected], (question, k))
                    for (_, a), (_, b) in zip(got, expected):
                        self.assertAlmostEqual(a, b, places=5)
                    compared += 1
        print(f"\n  pgvector: {compared} searches equal to the in-memory search; SQL time per search over "
              f"{len(self.chunks)} vectors: median {statistics.median(timings) * 1000:.2f} ms, "
              f"max {max(timings) * 1000:.2f} ms (not asserted)")

    def test_equal_scores_come_in_reading_order_from_sql_too(self):
        _, sql = self.pair(self.chunks)
        hits = [cid for cid, _ in sql.search("How heavy was the mud?", len(self.chunks))]
        repeated = [c.id for c in self.chunks if c.text == REPEATED]
        self.assertEqual([cid for cid in hits if cid in repeated], repeated)
        start = hits.index(repeated[0])
        self.assertEqual(hits[start:start + 4], repeated)

    def test_well_and_report_date_filter_in_sql(self):
        dense, sql = self.pair(self.chunks)
        wells = {r["chunk_id"]: FILES[r["file_id"]][2] for r in self.records}
        dates = {r["chunk_id"]: r["context"].get("report_date") for r in self.records}
        for question in QUESTIONS[:6]:
            for well, date in (("TG-2", None), ("AK-3", None), (None, "20-Aug-16"), ("AK-3", "21-Aug-16"),
                               ("TG-2", "20-Aug-16"), ("NO-1", None)):
                keep = {cid for cid in wells if (well is None or wells[cid] == well) and (date is None or dates[cid] == date)}
                got = sql.search(question, 5, well=well, report_date=date)
                self.assertEqual([c for c, _ in got], [c for c, _ in dense.search(question, 5, keep)], (question, well, date))
                self.assertEqual(bool(got), bool(keep))

    def test_per_well_and_fusion_give_what_the_in_memory_specs_give(self):
        for spec in ("wells:{}:" + MODEL, "fusion:bm25+{}:" + MODEL, "perwell:fusion:bm25+{}:" + MODEL):
            memory, sql = self.pair(self.eow, spec)
            self.assertEqual(sql.name, memory.name.replace("dense:", "pgvector:"))
            for question in QUESTIONS:
                got, expected = sql.search(question, 10), memory.search(question, 10)
                self.assertEqual([c for c, _ in got], [c for c, _ in expected], (spec, question))
                # Fusion scores come from ranks, so they are equal; cosine scores agree to float32 precision.
                for (_, a), (_, b) in zip(got, expected):
                    self.assertAlmostEqual(a, b, places=6 if "fusion" in spec else 5)

    def test_the_passages_lane_gives_the_same_passages(self):
        question = "Compare the mud weight of AK-3 and TG-2?"
        found = {}
        with stand_in():
            for kind in ("dense", "pgvector"):
                engine = lanes.Engine(self.eow, [], [], [], multi_well_retriever=f"perwell:fusion:bm25+{kind}:{MODEL}",
                                      vector_store=self.dsn)
                found[kind] = lanes.passages(question, {"report_type": "end_of_well"}, engine)
                for retriever in engine._retrievers.values():
                    self.addCleanup(close, retriever)
        self.assertEqual(found["pgvector"], found["dense"])
        self.assertEqual(len(found["pgvector"].passages), 10)

    def test_a_pool_with_a_chunk_lacking_its_vector_is_refused(self):
        with self.assertRaisesRegex(LookupError, f"{PARTIAL} vectors for {len(self.chunks) - 1} of these "
                                                 f"{len(self.chunks)} chunks"):
            PgVector(self.chunks, StandInEmbedder(model=PARTIAL), self.dsn)
        PgVector(self.chunks[:-1], StandInEmbedder(model=PARTIAL), self.dsn).close()

    def test_the_choice_needs_every_vector_and_an_embedding_endpoint(self):
        n = len(self.records)
        choose = stores.choose_multi_well_retriever
        self.assertEqual(choose(self.dsn, RELEASE, MODEL, True), (f"perwell:fusion:bm25+pgvector:{MODEL}", n))
        self.assertEqual(choose(self.dsn, None, MODEL, False), ("perwell:bm25", n))
        with self.assertNoLogs("graphrag.stores", "WARNING"):
            self.assertEqual(choose(self.dsn, RELEASE, "wtwo-no-vectors", True), ("perwell:bm25", 0))
        with self.assertLogs("graphrag.stores", "WARNING") as logged:
            self.assertEqual(choose(self.dsn, RELEASE, PARTIAL, True), ("perwell:bm25", n - 1))
        self.assertIn(f"{PARTIAL} vectors for {n - 1} of the {n} chunks", logged.output[0])
        with self.assertRaisesRegex(LookupError, "not in the store"):
            choose(self.dsn, "wtwo-no-such-release", MODEL, True)


@unittest.skipIf(NO_POSTGRES or NO_NEO4J, NO_POSTGRES or NO_NEO4J or "")
class EngineFromStoresTests(unittest.TestCase):
    """The choice as engine_from_stores makes it, once, at start. The well `WTWO-404` has no events, so Neo4j is
    only read."""

    def engine(self, dsn: str, **kwargs) -> lanes.Engine:
        # The real fact region cites chunks this release lacks; that warning is tests/test_graphrag_stores.py's.
        with stand_in(), mock.patch.object(stores.log, "disabled", True):
            engine = stores.engine_from_stores(dsn, *NEO4J, release=RELEASE, well="WTWO-404", **kwargs)
        for retriever in engine._retrievers.values():
            self.connections.callback(close, retriever)
        return engine

    def test_vectors_for_the_whole_release_and_an_endpoint_give_the_sql_search(self):
        records = package()["chunks"]
        # The retrievers' connections close before the schema is dropped.
        with temporary_schema(package(), RELEASE) as dsn, contextlib.ExitStack() as self.connections:
            store_vectors(dsn, records, MODEL)
            store_vectors(dsn, records[1:], PARTIAL)
            engine = self.engine(dsn, embed_model=MODEL, embedding_answers=True)
            spec = f"perwell:fusion:bm25+pgvector:{MODEL}"
            self.assertEqual(engine.retrieval, {"multi_well_retriever": spec, "stored_vectors": len(records)})
            self.assertIn((spec, "end_of_well"), engine._retrievers)   # built at start, not at the first question
            hits = lanes.passages("Compare the mud weight of AK-3 and TG-2?", {"report_type": "end_of_well"}, engine)
            self.assertEqual(len(hits.passages), 10)

            self.assertEqual(self.engine(dsn, embed_model=MODEL, embedding_answers=False).retrieval,
                             {"multi_well_retriever": "perwell:bm25", "stored_vectors": len(records)})
            self.assertEqual(self.engine(dsn, embed_model=PARTIAL, embedding_answers=True).retrieval,
                             {"multi_well_retriever": "perwell:bm25", "stored_vectors": len(records) - 1})
            # An explicit setting is kept as given.
            given = self.engine(dsn, embed_model=MODEL, embedding_answers=True, multi_well_retriever="perwell:bm25")
            self.assertEqual(given.retrieval, {"multi_well_retriever": "perwell:bm25", "stored_vectors": len(records)})


if __name__ == "__main__":
    unittest.main()
