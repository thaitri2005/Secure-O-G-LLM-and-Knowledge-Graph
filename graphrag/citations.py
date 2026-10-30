"""Citations checked in code (B-C07): the model's chunk ID and quote are claims, not facts.

A citation is kept only when the cited chunk was among the retrieved passages and the quote appears in it.
Otherwise the citation is attached from the retrieved passages: first the one containing the quote, then the
first one containing the value. An answer no retrieved passage supports gets no citation.
"""
from __future__ import annotations

from .scoring import squash


def _contains(text: str, needle: str) -> bool:
    return bool(squash(needle)) and squash(needle).lower() in squash(text).lower()


def resolve(answer: dict, hits: list[str], texts: dict[str, str], doc_id: str) -> tuple[str | None, str]:
    """Return (chunk ID or None, how): "model", "by_quote", "by_value" or "unsupported"."""
    cited = answer["chunk"] if "#" in answer["chunk"] else f"{doc_id}#{answer['chunk'].strip('[] ')}"
    if cited in hits and _contains(texts[cited], answer["quote"]):
        return cited, "model"
    for how, needle in (("by_quote", answer["quote"]), ("by_value", answer["value"])):
        found = next((cid for cid in hits if _contains(texts[cid], needle)), None)
        if found:
            return found, how
    return None, "unsupported"
