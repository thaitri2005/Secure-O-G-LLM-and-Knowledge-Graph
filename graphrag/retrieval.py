"""Plain retrieval baselines (B-D03): BM25, dense embeddings, and their fusion; well routing (B-C11)."""
from __future__ import annotations

import math
import re
import time
from collections import Counter
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

    def __init__(self, chunks: list[Chunk], client, batch: int = 16):
        self.client, self.name = client, f"dense:{client.model}"
        self.qwen = "qwen3-embedding" in client.model.lower()
        self.ids = [c.id for c in chunks]
        started = time.perf_counter()
        texts = [passage_text(c) for c in chunks]
        self.matrix = np.vstack([self._embed(texts[i:i + batch]) for i in range(0, len(texts), batch)])
        self.index_seconds = time.perf_counter() - started
        self.embedded_tokens = client.ledger.prompt_tokens

    def _embed(self, texts: list[str]) -> np.ndarray:
        vectors = np.array(self.client.embed(texts), dtype=np.float32)
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

    def search(self, question: str, k: int, allowed: set[str] | None = None) -> list[tuple[str, float]]:
        query = QUERY_INSTRUCTION + question if self.qwen else question
        return top(self.ids, self.matrix @ self._embed([query])[0], k, allowed)


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
WELL_NAME = re.compile(r"(?<![\w/.-])(?:[A-Z]{1,4}-\d{1,3}[A-Z]?|\d{1,3}-\d{1,3})(?![\w/.-])")


def well_names(text: str) -> set[str]:
    return {m.upper() for m in WELL_NAME.findall(text)}


REPORT_DATE = re.compile(r"Report For\s+(\d{2}-[A-Z][a-z]{2}-\d{2})")
REPORT_NUMBER = re.compile(r"Report No:\s*(\d+)")
QUESTION_DATE = re.compile(r"\b\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|"
                           r"December) \d{4}\b")


def question_dates(question: str) -> set[str]:
    return {normalize(m) for m in QUESTION_DATE.findall(question)}


def page_dates(chunks: list[Chunk]) -> dict[tuple[str, int], str]:
    """The report date of each page of each document, as YYYY-MM-DD. Daily reports print it once, in the header of
    their first page, so continuation pages inherit it. Parsing loses some headers (E24), so a page that keeps only
    its report number takes the date another attachment gives that number; this assumes one well's reports in the
    pool. A stand-in until K1 version 1 carries a report date."""
    stated: dict[tuple[str, int], str] = {}
    numbers: dict[tuple[str, int], str] = {}
    for c in chunks:
        text = f"{c.section or ''} {c.text}"
        found, number = REPORT_DATE.search(text), REPORT_NUMBER.search(text)
        if found:
            stated.setdefault((c.doc_id, c.page), normalize(found.group(1)))
        if number:
            numbers.setdefault((c.doc_id, c.page), number.group(1))
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
