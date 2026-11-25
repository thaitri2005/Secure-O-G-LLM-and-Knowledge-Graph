"""Plain retrieval baselines (B-D03): BM25, dense embeddings, and their fusion; well routing (B-C11)."""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import Counter
from pathlib import Path
from typing import Protocol

import numpy as np

from .data import Chunk
from .scoring import normalize

QUERY_INSTRUCTION = "Instruct: Given a question about a drilling report, retrieve passages that answer it\nQuery: "


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def passage_text(chunk: Chunk) -> str:
    """The section heading carries meaning that the chunk text often lacks."""
    return f"{chunk.section}\n{chunk.text}" if chunk.section else chunk.text


class Retriever(Protocol):
    name: str
    index_seconds: float

    def search(self, question: str, k: int, allowed: set[str] | None = None) -> list[tuple[str, float]]: ...


def top(ids: list[str], scores, k: int, allowed: set[str] | None) -> list[tuple[str, float]]:
    """The k best chunks; `allowed` acts like a vector-store payload filter, applied before ranking."""
    order = [i for i in np.argsort(scores)[::-1] if allowed is None or ids[i] in allowed][:k]
    return [(ids[i], float(scores[i])) for i in order]


def ranked(ids: list[str], scores, k: int, allowed: set[str] | None) -> list[tuple[str, float]]:
    """As `top`, with equal scores in reading order (the earlier chunk first), the order the SQL search gives them.
    `top` leaves the order of equal scores to numpy's sort, which is not stable."""
    order = [i for i in np.argsort(-scores, kind="stable") if allowed is None or ids[i] in allowed][:k]
    return [(ids[i], float(scores[i])) for i in order]


class BM25:
    """Okapi BM25. With `allowed`, term statistics come from the allowed chunks only, as a separate index
    per document or well would compute them (B-C11)."""

    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        started = time.perf_counter()
        self.name, self.k1, self.b = "bm25", k1, b
        self.ids = [c.id for c in chunks]
        self.docs = [Counter(tokens(passage_text(c))) for c in chunks]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.stats = {None: self._stats(range(len(self.docs)))}
        self.index_seconds = time.perf_counter() - started

    def _stats(self, rows) -> tuple[dict[str, float], float]:
        rows = list(rows)
        frequency = Counter(t for i in rows for t in self.docs[i])
        n = len(rows)
        idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in frequency.items()}
        return idf, sum(self.lengths[i] for i in rows) / n

    def search(self, question: str, k: int, allowed: set[str] | None = None) -> list[tuple[str, float]]:
        if allowed is not None and not allowed:
            return []  # the filters left no passage: nothing to rank, and no statistics to compute
        key = frozenset(allowed) if allowed is not None else None
        if key not in self.stats:
            self.stats[key] = self._stats(i for i, cid in enumerate(self.ids) if cid in key)
        idf, average = self.stats[key]
        terms = tokens(question)
        scores = []
        for doc, length in zip(self.docs, self.lengths):
            score = 0.0
            for t in terms:
                tf = doc.get(t, 0)
                if tf and t in idf:
                    score += idf[t] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / average))
            scores.append(score)
        return top(self.ids, scores, k, allowed)


class Dense:
    """Embeddings from an OpenAI-compatible endpoint (llama.cpp locally); cosine similarity in memory.

    Qwen3-Embedding expects an instruction before the query and none before passages. The served model
    sets its own pooling (llama-server --pooling last for Qwen3-Embedding, cls for BGE models).
    """

    def __init__(self, chunks: list[Chunk], client, batch: int = 16, vectors: Path | None = None):
        self.client, self.name = client, f"dense:{client.model}"
        self.qwen = "qwen3-embedding" in client.model.lower()
        self.ids = [c.id for c in chunks]
        started = time.perf_counter()
        texts = [passage_text(c) for c in chunks]
        # The passages' vectors are index-time work: kept on disk beside the chat cache, keyed by the address, the
        # model and the texts, so a run that is resumed does not embed the same passages again (on a CPU that was
        # a quarter of an hour at every restart, B-F82). What they cost when made is reported, as for cached calls.
        folder = vectors or getattr(client, "cache_dir", None)  # the embedding client itself keeps no chat cache
        endpoint = getattr(client, "endpoint", None)
        key = hashlib.sha256(json.dumps([getattr(endpoint, "base_url", ""), getattr(endpoint, "cache_tag", ""),
                                         client.model, texts]).encode()).hexdigest()
        kept = Path(folder) / f"vectors_{key}.npz" if folder else None
        if kept is not None and kept.is_file():
            with np.load(kept) as saved:
                self.matrix = saved["matrix"]
                self.index_seconds, self.embedded_tokens = float(saved["seconds"]), int(saved["tokens"])
            return
        before = client.ledger.prompt_tokens
        self.matrix = np.vstack([self._embed(texts[i:i + batch]) for i in range(0, len(texts), batch)])
        self.index_seconds = time.perf_counter() - started
        self.embedded_tokens = client.ledger.prompt_tokens
        if kept is not None:
            kept.parent.mkdir(parents=True, exist_ok=True)
            np.savez(kept, matrix=self.matrix, seconds=self.index_seconds, tokens=self.embedded_tokens - before)

    def _embed(self, texts: list[str]) -> np.ndarray:
        vectors = np.array(self.client.embed(texts), dtype=np.float32)
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

    def search(self, question: str, k: int, allowed: set[str] | None = None) -> list[tuple[str, float]]:
        query = QUERY_INSTRUCTION + question if self.qwen else question
        return ranked(self.ids, self.matrix @ self._embed([query])[0], k, allowed)


# Exact cosine search over the given chunks, in their order: `position` breaks ties as `ranked` does. The chunk IDs
# name the release, since a chunk belongs to one file and a file to one release (platform/sql/001_k1.sql).
VECTOR_SEARCH = """
SELECT v.chunk_id, v.embedding <=> %(query)s::vector AS distance
FROM unnest(%(ids)s::text[]) WITH ORDINALITY AS p(chunk_id, position)
JOIN chunk_vectors v ON v.chunk_id = p.chunk_id AND v.embedding_model = %(model)s
WHERE (%(well)s::text IS NULL OR v.well = %(well)s) AND (%(report_date)s::text IS NULL OR v.report_date = %(report_date)s)
ORDER BY distance, p.position
LIMIT %(k)s
"""
VECTOR_COUNT = "SELECT count(*) FROM chunk_vectors WHERE embedding_model = %s AND chunk_id = ANY(%s)"


class PgVector:
    """`Dense` with the passage vectors and the search in PostgreSQL: `chunk_vectors` (C-C10), filled by
    platform/embed_k1.py from the same passage text, normalised as `Dense` normalises it.

    Only the question is embedded, once per search, through the same client. The search is exact (`<=>`, cosine
    distance) and every filter is in its WHERE clause: the chunks of this pool, `allowed`, and the stored `well` and
    `report_date` when given. For the same vectors it returns what `Dense` returns, in the same order. A pool with any
    chunk lacking a vector is refused, since `Dense` would have searched that chunk. psycopg is imported here only, so
    `import graphrag` does not need it.
    """

    def __init__(self, chunks: list[Chunk], client, dsn: str):
        import psycopg
        self.client, self.dsn, self.name = client, dsn, f"pgvector:{client.model}"
        self.qwen = "qwen3-embedding" in client.model.lower()
        self.ids = [c.id for c in chunks]
        self.searches, self.sql_seconds = 0, 0.0   # PostgreSQL time only; the query embedding is in the client's ledger
        started = time.perf_counter()
        self.conn = psycopg.connect(dsn, autocommit=True)
        held = self.conn.execute(VECTOR_COUNT, (client.model, self.ids)).fetchone()[0]
        if held != len(self.ids):
            self.close()
            raise LookupError(f"chunk_vectors holds {client.model} vectors for {held} of these {len(self.ids)} chunks; "
                              f"embed the release first (platform/embed_k1.py embed)")
        self.index_seconds = time.perf_counter() - started

    def search(self, question: str, k: int, allowed: set[str] | None = None, well: str | None = None,
               report_date: str | None = None) -> list[tuple[str, float]]:
        """`well` and `report_date` filter on the stored columns, as embed_k1.py wrote them (report date as printed,
        e.g. 28-Aug-16). Scores are cosine similarities, as `Dense` gives."""
        import psycopg
        vector = np.array(self.client.embed([QUERY_INSTRUCTION + question if self.qwen else question])[0], dtype=np.float32)
        vector /= np.linalg.norm(vector)
        ids = self.ids if allowed is None else [cid for cid in self.ids if cid in allowed]
        if self.conn.closed:
            self.conn = psycopg.connect(self.dsn, autocommit=True)
        started = time.perf_counter()
        # Nine significant digits give back the exact float32, so PostgreSQL searches the vector `Dense` would.
        rows = self.conn.execute(VECTOR_SEARCH, {"query": "[" + ",".join(f"{x:.9g}" for x in vector) + "]", "ids": ids,
                                                 "model": self.client.model, "well": well, "report_date": report_date,
                                                 "k": k}).fetchall()
        self.searches, self.sql_seconds = self.searches + 1, self.sql_seconds + time.perf_counter() - started
        return [(chunk_id, 1.0 - distance) for chunk_id, distance in rows]

    def close(self) -> None:
        self.conn.close()


class Fusion:
    """Reciprocal-rank fusion of several retrievers (k=60, the usual constant)."""

    def __init__(self, retrievers: list, depth: int = 20, constant: int = 60):
        self.retrievers, self.depth, self.constant = retrievers, depth, constant
        self.name = "fusion:" + "+".join(r.name for r in retrievers)
        self.index_seconds = sum(r.index_seconds for r in retrievers)

    def search(self, question: str, k: int, allowed: set[str] | None = None) -> list[tuple[str, float]]:
        scores: Counter = Counter()
        for retriever in self.retrievers:
            for rank, (chunk_id, _) in enumerate(retriever.search(question, self.depth, allowed)):
                scores[chunk_id] += 1 / (self.constant + rank + 1)
        return scores.most_common(k)


# Well names as reports write them: AK-3, TG-2, 56-32, 68-32. The lookarounds skip casing sizes such as 4-1/2.
WELL_NAME = re.compile(r"(?<![\w/.-])(?:[A-Z]{2,4}-[A-Z]{2,3}-\d{1,3}(?:-S\d{1,2})?|[A-Z]{1,4}-\d{1,3}[A-Z]?|\d{1,3}-\d{1,3})(?![\w/.-])")


def well_names(text: str) -> set[str]:
    return {m.upper() for m in WELL_NAME.findall(text)}


REPORT_DATE = re.compile(r"Report For\s+(\d{2}-[A-Z][a-z]{2}-\d{2})")
REPORT_NUMBER = re.compile(r"Report No:\s*(\d+)")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
          "December")
_MONTH = "(" + "|".join(f"{m}|{m[:3]}" for m in MONTHS) + r"|Sept)\.?"
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?"
_START = r"(?<![\w/.-])"  # not inside another token: the 3 of "AK-3 - 20 August", the 4 of "12 1/4 to 20 August"
# "20 August 2016", "20th Aug 2016", a range "20-22 August 2016" or "20 to 22 August 2016", and "20 and 22 August 2016".
DAY_FIRST = re.compile(rf"{_START}{_DAY}(?:\s*(-|–|to|and)\s*{_DAY})?\s+{_MONTH},?\s+(\d{{4}})\b", re.IGNORECASE)
# "August 20, 2016" and "August 20-22, 2016".
MONTH_FIRST = re.compile(rf"\b{_MONTH}\s+{_DAY}(?:\s*(-|–|to|and)\s*{_DAY})?,?\s+(\d{{4}})\b", re.IGNORECASE)
ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
# The daily reports' own form, "20-Aug-16" or "20-Aug-2016".
REPORT_FORM = re.compile(rf"{_START}(\d{{1,2}})-([A-Za-z]{{3}})-(\d{{2}}|\d{{4}})\b")
_BETWEEN = re.compile(r"\s*(?:to|until|through|-|–)\s*", re.IGNORECASE)


def question_dates(question: str) -> set[str]:
    """The days a question names, as ISO dates. A range gives every day in it, also across months ("30 August 2016
    to 2 September 2016"), up to a month's worth; "20 and 22 August" gives the two days. A day that does not exist
    (31 June) is not a date."""
    from datetime import date, timedelta
    numbers = {m[:3].lower(): n for n, m in enumerate(MONTHS, 1)}

    def day_of(year: str, month: str, day: str) -> date | None:
        number = numbers.get(month[:3].lower())
        year_number = int(year) + (2000 if len(year) == 2 else 0)
        try:
            return date(year_number, number, int(day)) if number and year_number >= 1900 else None
        except ValueError:
            return None

    def span(first: date | None, last: date | None) -> list[date]:
        if not first or not last or not first <= last <= first + timedelta(days=31):
            return [d for d in (first, last) if d]
        return [first + timedelta(days=n) for n in range((last - first).days + 1)]

    found: list[tuple[int, int, list[date]]] = []  # where in the question, and the days written there
    for m in DAY_FIRST.finditer(question):
        first, joiner, last, month, year = m.groups()
        days = [day_of(year, month, first), day_of(year, month, last)] if last else [day_of(year, month, first)]
        found.append((m.start(), m.end(), span(*days) if last and joiner.lower() != "and" else [d for d in days if d]))
    for m in MONTH_FIRST.finditer(question):
        month, first, joiner, last, year = m.groups()
        days = [day_of(year, month, first), day_of(year, month, last)] if last else [day_of(year, month, first)]
        found.append((m.start(), m.end(), span(*days) if last and joiner.lower() != "and" else [d for d in days if d]))
    for m in ISO.finditer(question):
        try:
            found.append((m.start(), m.end(), [date(int(m.group(1)), int(m.group(2)), int(m.group(3)))]))
        except ValueError:
            pass
    for m in REPORT_FORM.finditer(question):
        day = day_of(m.group(3), m.group(2), m.group(1))
        found.append((m.start(), m.end(), [day] if day else []))
    found.sort()
    out = {d for _, _, days in found for d in days}
    # Two whole dates joined by "to": every day between them.
    for (_, end, before), (start, _, after) in zip(found, found[1:]):
        if before and after and _BETWEEN.fullmatch(question[end:start]):
            out |= set(span(before[-1], after[0]))
    return {d.isoformat() for d in out}


def page_dates(chunks: list[Chunk]) -> dict[tuple[str, int], str]:
    """The report date of each page of each document, as YYYY-MM-DD. Daily reports print it once, in the header of
    their first page, so continuation pages inherit it. Parsing loses some headers (E24), so a page that keeps only
    its report number takes the date another attachment gives that number; this assumes one well's reports in the
    pool. A stand-in until K1 version 1 carries a report date."""
    stated: dict[tuple[str, int], str] = {}
    in_section: dict[tuple[str, int], str] = {}
    numbers: dict[tuple[str, int], str] = {}
    for c in chunks:
        text = f"{c.section or ''} {c.text}"
        found, number = REPORT_DATE.search(c.text), REPORT_NUMBER.search(text)
        if found:
            stated.setdefault((c.doc_id, c.page), normalize(found.group(1)))
        # A page's first chunk can carry the previous page's section title, so the last section on the page wins (E28).
        heading = REPORT_DATE.search(c.section or "")
        if heading:
            in_section[(c.doc_id, c.page)] = normalize(heading.group(1))
        if number:
            numbers.setdefault((c.doc_id, c.page), number.group(1))
    stated = in_section | stated
    by_number = {numbers[page]: date for page, date in stated.items() if page in numbers}
    for page, number in numbers.items():
        if page not in stated and number in by_number:
            stated[page] = by_number[number]
    dates: dict[tuple[str, int], str] = {}
    current: dict[str, str] = {}
    for doc, page in sorted({(c.doc_id, c.page) for c in chunks}):
        current[doc] = stated.get((doc, page), current.get(doc))
        if current[doc]:
            dates[(doc, page)] = current[doc]
    return dates


class DateRouter:
    """Keeps only the pages of the report dates a question names (E27). Filtering by well cannot separate the days of
    one well. A question that names no date, or only dates no report has, is not filtered."""

    def __init__(self, retriever, chunks: list[Chunk]):
        self.retriever, self.index_seconds = retriever, retriever.index_seconds
        self.name = f"dates:{retriever.name}"
        dates = page_dates(chunks)
        self.chunks_by_date: dict[str, set[str]] = {}
        for c in chunks:
            if (c.doc_id, c.page) in dates:
                self.chunks_by_date.setdefault(dates[(c.doc_id, c.page)], set()).add(c.id)

    def search(self, question: str, k: int, allowed: set[str] | None = None) -> list[tuple[str, float]]:
        known = [d for d in question_dates(question) if d in self.chunks_by_date]
        if not known:
            return self.retriever.search(question, k, allowed)
        routed = set().union(*(self.chunks_by_date[d] for d in known))
        return self.retriever.search(question, k, routed if allowed is None else allowed & routed)


class WellRouter:
    """Restricts retrieval to the documents that name a well the question names (B-C11).

    Each document's well names stand in for the "well registry IDs" of the vector payload (specification
    §5.11) until Track C's registry exists. A question that names no well, or only wells no document
    names, is not filtered.
    """

    def __init__(self, retriever, chunks: list[Chunk], per_well: bool = False):
        self.retriever, self.per_well, self.index_seconds = retriever, per_well, retriever.index_seconds
        self.name = f"{'perwell' if per_well else 'wells'}:{retriever.name}"
        self.chunks_by_doc: dict[str, set[str]] = {}
        self.wells_by_doc: dict[str, set[str]] = {}
        for c in chunks:
            self.chunks_by_doc.setdefault(c.doc_id, set()).add(c.id)
            self.wells_by_doc.setdefault(c.doc_id, set()).update(well_names(c.text))

    def documents(self, question: str) -> list[str]:
        wanted = well_names(question)
        return sorted(d for d, wells in self.wells_by_doc.items() if wanted & wells)

    def search(self, question: str, k: int, allowed: set[str] | None = None) -> list[tuple[str, float]]:
        docs = self.documents(question)
        wells = [w for w in sorted(well_names(question)) if self.documents(w)]
        if self.per_well and len(wells) > 1:
            # One search per named well, interleaved, so each well gets passages within the same total k.
            # Each search drops the other wells' names: BM25 would match their digits (56-32) in table rows.
            runs = [self.retriever.search(self._only(question, w), k, self._allowed(self.documents(w), allowed))
                    for w in wells]
            out: list[tuple[str, float]] = []
            for rank in range(k):
                for run in runs:
                    if rank < len(run) and run[rank][0] not in {cid for cid, _ in out}:
                        out.append(run[rank])
            return out[:k]
        return self.retriever.search(question, k, self._allowed(docs, allowed) if docs else allowed)

    @staticmethod
    def _only(question: str, well: str) -> str:
        return WELL_NAME.sub(lambda m: m.group() if m.group().upper() == well else "", question)

    def _allowed(self, docs: list[str], allowed: set[str] | None) -> set[str]:
        routed = set().union(*(self.chunks_by_doc[d] for d in docs))
        return routed if allowed is None else allowed & routed
