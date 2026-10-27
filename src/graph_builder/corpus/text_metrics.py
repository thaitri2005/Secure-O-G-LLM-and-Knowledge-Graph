"""Compare extracted text with reference text: character and word error rates, and order-insensitive word scores."""
from __future__ import annotations

from collections import Counter
import re
import unicodedata

from rapidfuzz.distance import Levenshtein

from .vietnamese import is_vietnamese_marked


def normalize(text: str) -> str:
    """NFC, unified quotes and dashes, collapsed whitespace; case, digits and diacritics are kept."""
    text = unicodedata.normalize("NFC", text)
    text = text.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                                         "–": "-", "—": "-", " ": " "}))
    return " ".join(text.split())


def words(text: str) -> list[str]:
    return re.findall(r"\w+", normalize(text), re.UNICODE)


def compare(reference: str, hypothesis: str) -> dict[str, float | int | None]:
    """Character/word error rates (order-sensitive) and multiset word precision/recall (order-insensitive)."""
    ref, hyp = normalize(reference), normalize(hypothesis)
    ref_words, hyp_words = words(ref), words(hyp)
    char_edits = Levenshtein.distance(ref, hyp)
    word_edits = Levenshtein.distance(ref_words, hyp_words)
    ref_bag, hyp_bag = Counter(ref_words), Counter(hyp_words)
    overlap = sum((ref_bag & hyp_bag).values())
    marked = Counter({word: count for word, count in ref_bag.items() if is_vietnamese_marked(word)})
    marked_found = sum((marked & hyp_bag).values())
    return {"reference_characters": len(ref), "reference_words": len(ref_words),
            "cer": round(char_edits / len(ref), 4) if ref else None,
            "wer": round(word_edits / len(ref_words), 4) if ref_words else None,
            "word_recall": round(overlap / len(ref_words), 4) if ref_words else None,
            "word_precision": round(overlap / len(hyp_words), 4) if hyp_words else None,
            "vietnamese_word_recall": round(marked_found / sum(marked.values()), 4) if marked else None}
