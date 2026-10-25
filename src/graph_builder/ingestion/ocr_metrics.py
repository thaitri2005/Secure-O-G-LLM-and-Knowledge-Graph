"""Diacritic-sensitive OCR error metrics; no accent stripping or case folding."""
import unicodedata


def distance(reference, hypothesis):
    previous = list(range(len(hypothesis) + 1))
    for i, left in enumerate(reference, 1):
        current = [i]
        for j, right in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def score_ocr(reference: str, hypothesis: str) -> dict:
    reference, hypothesis = [" ".join(unicodedata.normalize("NFC", text).split())
                             for text in (reference, hypothesis)]
    chars = distance(reference, hypothesis)
    words = distance(reference.split(), hypothesis.split())
    return {"character_errors": chars, "reference_characters": len(reference),
            "cer": chars / len(reference) if reference else None,
            "word_errors": words, "reference_words": len(reference.split()),
            "wer": words / len(reference.split()) if reference.split() else None}
