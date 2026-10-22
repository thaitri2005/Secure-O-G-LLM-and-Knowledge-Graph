"""Pack sentences into bounded text spans while preserving source characters and offsets."""
from __future__ import annotations

import re

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])|\n+")


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def split_sentences(text: str, base: int = 0) -> list[tuple[int, int]]:
    """Return nonempty, trimmed sentence offsets relative to a document."""
    spans, start = [], 0
    for match in SENT_SPLIT.finditer(text):
        left, right = _trim(text, start, match.start())
        if left < right:
            spans.append((base + left, base + right))
        start = match.end()
    left, right = _trim(text, start, len(text))
    if left < right:
        spans.append((base + left, base + right))
    return spans


def chunk_spans(text: str, max_chars: int) -> list[tuple[int, int]]:
    """Pack whole sentences and split oversized sentences at whitespace."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    pieces = []
    for start, end in split_sentences(text):
        while end - start > max_chars:
            limit = start + max_chars
            cut = next((i for i in range(limit, start, -1) if text[i].isspace()), limit)
            left, right = _trim(text, start, cut)
            if left < right:
                pieces.append((left, right))
            start, _ = _trim(text, cut, end)
        if start < end:
            pieces.append((start, end))
    packed = []
    for start, end in pieces:
        if packed and end - packed[-1][0] <= max_chars:
            packed[-1] = (packed[-1][0], end)
        else:
            packed.append((start, end))
    return packed
