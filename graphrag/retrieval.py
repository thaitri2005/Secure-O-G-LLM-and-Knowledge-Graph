"""Plain retrieval baselines (B-D03): BM25, dense embeddings, and their fusion."""
from __future__ import annotations

import math
import re
import time
from collections import Counter
from typing import Protocol

import numpy as np

from .data import Chunk

QUERY_INSTRUCTION = "Instruct: Given a question about a drilling report, retrieve passages that answer it\nQuery: "


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def passage_text(chunk: Chunk) -> str:
    """The section heading carries meaning that the chunk text often lacks."""
    return f"{chunk.section}\n{chunk.text}" if chunk.section else chunk.text


class Retriever(Protocol):
    name: str
    index_seconds: float

    def search(self, question: str, k: int) -> list[tuple[str, float]]: ...


class BM25:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        started = time.perf_counter()
        self.name, self.k1, self.b = "bm25", k1, b
        self.ids = [c.id for c in chunks]
        self.docs = [Counter(tokens(passage_text(c))) for c in chunks]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.average = sum(self.lengths) / len(self.lengths)
        frequency = Counter(t for d in self.docs for t in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in frequency.items()}
        self.index_seconds = time.perf_counter() - started

    def search(self, question: str, k: int) -> list[tuple[str, float]]:
        terms = tokens(question)
        scores = []
        for doc, length in zip(self.docs, self.lengths):
            score = 0.0
            for t in terms:
                tf = doc.get(t, 0)
                if tf:
                    score += self.idf[t] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / self.average))
            scores.append(score)
        order = np.argsort(scores)[::-1][:k]
        return [(self.ids[i], float(scores[i])) for i in order]


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

    def search(self, question: str, k: int) -> list[tuple[str, float]]:
        query = QUERY_INSTRUCTION + question if self.qwen else question
        scores = self.matrix @ self._embed([query])[0]
        order = np.argsort(scores)[::-1][:k]
        return [(self.ids[i], float(scores[i])) for i in order]


class Fusion:
    """Reciprocal-rank fusion of several retrievers (k=60, the usual constant)."""

    def __init__(self, retrievers: list, depth: int = 20, constant: int = 60):
        self.retrievers, self.depth, self.constant = retrievers, depth, constant
        self.name = "fusion:" + "+".join(r.name for r in retrievers)
        self.index_seconds = sum(r.index_seconds for r in retrievers)

    def search(self, question: str, k: int) -> list[tuple[str, float]]:
        scores: Counter = Counter()
        for retriever in self.retrievers:
            for rank, (chunk_id, _) in enumerate(retriever.search(question, self.depth)):
                scores[chunk_id] += 1 / (self.constant + rank + 1)
        return scores.most_common(k)
