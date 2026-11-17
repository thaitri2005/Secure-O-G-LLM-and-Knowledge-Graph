"""Label-value geometry check (A-432, OPTIONAL): does a 'Label: value' pair in the K1 text chunks of a page agree with the position of the value in the PDF?

What it is: it re-reads the PDF text layer with character boxes (pypdfium2) and finds, for each 'Label:' on the page, the value by GEOMETRY:
on the same text run after the colon, else the nearest phrase to the right on the same line, else the phrase directly below. Then it looks for
the same label in the K1 page text and compares the first token of the K1 value with the first token of the PDF value. A mismatch means
'the number next to this label in K1 is not the number that stands next to it on the page' (example: a text layer whose stream order lists
labels first and values later, so a serialiser pairs a label with the wrong number).
What it is not: it does not verify content. A page without a signal was only not contradicted. Not seen: labels without a colon, labels
whose value is in a table cell of K1 split from the label, rotated pages (skipped), two-column layouts where a value sits under another
label, K1 pairs whose label text differs from the PDF label text. Opt-in (CLI flag --label-value); WARN signal only, never a publish gate.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from typing import Any

from .fidelity import FidelityState, load_config as load_fidelity_config, normalise
from .signals import CheckContext, Registry

DEFAULT_CONFIG = Path("configs/qa/label_value.json")
CHECK_NAME = "label_value_geometry"
CHECK_VERSION = "2"  # A-445: a URL scheme or a bracket index before the colon is not a label
LIMITATIONS = (
    "Second reader over the SAME PDF text layer (character boxes): errors inside the text layer are invisible.",
    "Only 'Label:' pairs with a colon are examined; the label text in K1 must equal the PDF label text (case and spaces folded).",
    "The PDF value is the same run after the colon, else the nearest phrase to the right on the line, else the phrase below; a form that puts a value elsewhere (two-column grids, a value under another label) is not modelled.",
    "A blank PDF value (the next phrase is another label) and a K1 label without a value are skipped, not judged. Rotated pages are skipped.",
    "Only the first token of the value is compared; later words of a value can still be wrong.",
    "The mismatch rate on layouts other than the development documents is NOT EVALUATED.",
)
REASONS = (
    ("LABEL_VALUE_GEOMETRY_MISMATCH", "WARN", "A 'Label: value' pair in the K1 page text has a value that differs from the value standing next to that label in the PDF (by geometry).", CHECK_NAME),
    ("LABEL_VALUE_NOT_APPLICABLE", "INFO", "Page skipped by the label-value check (rotated page or no PDF reference); nothing was compared.", CHECK_NAME),
)
LABEL_PHRASE = re.compile(r"^(?P<label>[^:]*[^\W\d_][^:]*):(?!\d)\s*(?P<value>.*)$")


def load_config(path: Path | None = None) -> dict:
    return json.loads((path or DEFAULT_CONFIG).read_text(encoding="utf-8"))


def _value(config: dict, section: str, name: str) -> Any:
    return config[section][name]["value"]


def _matches_any(text: str, config: dict, section: str, name: str) -> bool:
    """True when the text matches one of the regular expressions of config[section][name] (case-insensitive). A config without the key
    matches nothing, i.e. behaves as before A-445."""
    patterns = (config.get(section) or {}).get(name, {}).get("value") or []
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def fold_label(label: str) -> str:
    return " ".join(normalise(label).replace("|", " ").split()).strip(" :")


def first_token(text: str) -> str:
    """First whitespace token of a value, folded, without table pipes and trailing punctuation; numbers lose thousands commas."""
    for part in normalise(text).replace("|", " ").split():
        token = part.strip(".,;:()[]\"'")
        if token:
            return token.replace(",", "") if re.fullmatch(r"[\d,]+(?:\.\d+)?", token) else token
    return ""


def words_of_page(page: Any) -> list[dict]:
    """Words of a pypdfium2 page with boxes (left, bottom, right, top; PDF points, y up), in text-layer order."""
    textpage = page.get_textpage()
    try:
        count = textpage.count_chars()
        if not count:
            return []
        text = textpage.get_text_range(0, count)
        boxes = [textpage.get_charbox(index) for index in range(min(count, len(text)))]
    finally:
        textpage.close()
    words, start = [], None
    for index, char in enumerate(list(text[:len(boxes)]) + [" "]):
        if char.isspace():
            if start is not None:
                part = boxes[start:index]
                words.append({"text": text[start:index], "l": min(b[0] for b in part), "b": min(b[1] for b in part),
                              "r": max(b[2] for b in part), "t": max(b[3] for b in part)})
                start = None
        elif start is None:
            start = index
    return [word for word in words if word["r"] > word["l"] and word["t"] > word["b"]]


def phrases_of(words: list[dict], config: dict) -> list[dict]:
    """Group words into lines (vertical centres within same_line_fraction) and lines into phrases (gap below phrase_gap_em)."""
    same_line, gap_em = _value(config, "geometry", "same_line_fraction"), _value(config, "geometry", "phrase_gap_em")
    lines: list[list[dict]] = []
    for word in sorted(words, key=lambda w: (-(w["b"] + w["t"]) / 2, w["l"])):
        centre, height = (word["b"] + word["t"]) / 2, word["t"] - word["b"]
        for line in lines:
            ref = line[0]
            if abs((ref["b"] + ref["t"]) / 2 - centre) <= same_line * min(height, ref["t"] - ref["b"]):
                line.append(word)
                break
        else:
            lines.append([word])
    phrases = []
    for line in lines:
        line.sort(key=lambda w: w["l"])
        current = [line[0]]
        for word in line[1:]:
            height = max(word["t"] - word["b"], current[-1]["t"] - current[-1]["b"])
            if word["l"] - current[-1]["r"] <= gap_em * height:
                current.append(word)
            else:
                phrases.append(current)
                current = [word]
        phrases.append(current)
    return [{"text": " ".join(w["text"] for w in p), "l": min(w["l"] for w in p), "b": min(w["b"] for w in p),
             "r": max(w["r"] for w in p), "t": max(w["t"] for w in p)} for p in phrases]


def label_of(phrase: dict, config: dict) -> tuple[str, str] | None:
    """(folded label, inline value) when the phrase is 'Label:' or 'Label: value'; None otherwise."""
    match = LABEL_PHRASE.match(phrase["text"])
    if not match or _matches_any(phrase["text"], config, "labels", "not_a_label_patterns"):
        return None
    label = fold_label(match.group("label"))
    letters = sum(char.isalpha() for char in label)
    if letters < _value(config, "labels", "min_label_letters") or len(label.split()) > _value(config, "labels", "max_label_words"):
        return None
    return label, match.group("value").strip()


def pdf_pairs(phrases: list[dict], config: dict) -> list[dict]:
    """[{label, value, source: inline|right|below|blank, box}] for every label phrase of the page."""
    max_gap, below_gap = _value(config, "geometry", "max_value_gap_em"), _value(config, "geometry", "below_max_gap_lines")
    below_left = _value(config, "geometry", "below_left_tolerance_em")
    same_line = _value(config, "geometry", "same_line_fraction")
    out = []
    for phrase in phrases:
        found = label_of(phrase, config)
        if found is None:
            continue
        label, inline = found
        height = phrase["t"] - phrase["b"]
        pair = {"label": label, "box": [round(phrase["l"], 1), round(phrase["b"], 1), round(phrase["r"], 1), round(phrase["t"], 1)]}
        if inline:
            out.append({**pair, "value": inline, "source": "inline"})
            continue
        centre = (phrase["b"] + phrase["t"]) / 2
        right = [p for p in phrases if p is not phrase and p["l"] >= phrase["r"] - 0.1 * height
                 and abs((p["b"] + p["t"]) / 2 - centre) <= same_line * min(height, p["t"] - p["b"])
                 and p["l"] - phrase["r"] <= max_gap * height]
        if right:
            nearest = min(right, key=lambda p: p["l"])
            out.append({**pair, "value": "" if label_of(nearest, config) else nearest["text"], "source": "right" if not label_of(nearest, config) else "blank"})
            continue
        under = [p for p in phrases if p is not phrase and p["t"] <= phrase["b"] + 0.1 * height and phrase["b"] - p["t"] <= below_gap * height
                 and p["l"] <= phrase["r"] and p["r"] >= phrase["l"] - below_left * height and abs(p["l"] - phrase["l"]) <= max(below_left * height, phrase["r"] - phrase["l"])]
        if under:
            nearest = max(under, key=lambda p: p["t"])
            out.append({**pair, "value": "" if label_of(nearest, config) else nearest["text"], "source": "below" if not label_of(nearest, config) else "blank"})
        else:
            out.append({**pair, "value": "", "source": "blank"})
    return out


def k1_pairs(text: str, labels: set[str]) -> list[tuple[str, str]]:
    """[(label, first token of the value)] for every occurrence of a KNOWN label (a label found in the PDF page) followed by a colon in
    the K1 page text. Longer labels claim their text first, so 'depth (ft):' inside 'measured depth (ft):' is not a second pair. A value that
    starts with another known label means the first label has no value in K1 (empty token). Table pipes are separators."""
    if not labels:
        return []
    stream = " ".join(normalise(text).replace("|", " | ").split())
    ordered = sorted(labels, key=lambda label: (-len(label), label))
    pattern = {label: re.compile(r"(?<![^\W_])" + r"\s+".join(re.escape(word) for word in label.split()) + r"\s*:(?!\d)") for label in ordered}
    starts = re.compile("^(?:\\|\\s*)*(?:" + "|".join(r"\s+".join(re.escape(w) for w in label.split()) + r"\s*:" for label in ordered) + ")")
    claimed: list[tuple[int, int]] = []
    found: list[tuple[int, str, str]] = []
    for label in ordered:
        for match in pattern[label].finditer(stream):
            if any(start <= match.start() < end for start, end in claimed):
                continue
            claimed.append((match.start(), match.end()))
            rest = stream[match.end():].lstrip(" |")
            token = "" if starts.match(stream[match.end():].lstrip()) else first_token(rest)
            found.append((match.start(), label, token))
    return [(label, token) for _, label, token in sorted(found)]


def compare_page(pdf: list[dict], k1: list[tuple[str, str]], config: dict) -> dict:
    """Pure comparison. Returns counts and the mismatching pairs.

    For a label the PDF values of all its occurrences are collected; a K1 pair of that label agrees when its first value token is the
    first token of one of them. K1 pairs whose label is a suffix/prefix of PDF text only partially are matched by equality of the folded label."""
    expected: dict[str, list[dict]] = {}
    for pair in pdf:
        expected.setdefault(pair["label"], []).append(pair)
    counts: Counter = Counter()
    mismatches = []
    for label, token in k1:
        pairs = expected.get(label)
        if not pairs:
            counts["k1_label_not_in_pdf"] += 1
            continue
        values = [first_token(p["value"]) for p in pairs]
        if not token:
            counts["k1_value_empty"] += 1
            continue
        if all(not value for value in values):
            counts["pdf_value_blank"] += 1
            continue
        counts["compared"] += 1
        if token in values:
            counts["agree"] += 1
        else:
            counts["mismatch"] += 1
            mismatches.append({"label": label, "k1_value": token, "pdf_values": sorted({v for v in values if v}), "pdf_source": sorted({p["source"] for p in pairs}),
                               "box": pairs[0]["box"]})
    return {"counts": dict(counts), "mismatches": mismatches, "pdf_labels": len(expected)}


class LabelValueState:
    """Reuses the fidelity state for the SHA-verified PDF lookup and the K1 page text; adds the geometry read."""

    def __init__(self, release_dir: Path, corpus_dir: Path | None, fidelity_config: dict, config: dict) -> None:
        self.base = FidelityState(release_dir, corpus_dir, fidelity_config)
        self.release_dir, self.config = release_dir, config

    def close(self) -> None:
        self.base.close()

    def analyse(self, file_id: str, page_number: int) -> tuple[dict | None, str | None]:
        self.base.select(file_id)
        reference = self.base._reference  # noqa: SLF001 - same module family; the PDF is opened once for both checks
        if reference is None:
            return None, self.base._reference_error  # noqa: SLF001
        if not 1 <= page_number <= reference.page_count:
            return None, f"page {page_number} outside the PDF"
        page = reference.document[page_number - 1]
        try:
            if page.get_rotation() % 180:
                return None, "rotated page"
            words = words_of_page(page)
        finally:
            page.close()
        pairs = pdf_pairs(phrases_of(words, self.config), self.config)
        return compare_page(pairs, k1_pairs(self.base.k1_text(file_id, page_number), {pair["label"] for pair in pairs}), self.config), None


def evaluate_page(state: LabelValueState, registry: Registry, ids: dict, entity: dict) -> list[dict]:
    if entity.get("release_mode") == "ocr":
        return [registry.signal("LABEL_VALUE_NOT_APPLICABLE", "page", ids, evidence={"reason": "OCR page: no text-layer geometry"})]
    result, reason = state.analyse(ids["file_id"], ids["page"])
    if result is None:
        return [registry.signal("LABEL_VALUE_NOT_APPLICABLE", "page", ids, evidence={"reason": reason})]
    if len(result["mismatches"]) < _value(state.config, "comparison", "min_pairs_for_page_signal"):
        return []
    limit = _value(state.config, "comparison", "max_listed_pairs")
    return [registry.signal("LABEL_VALUE_GEOMETRY_MISMATCH", "page", ids, evidence={"counts": result["counts"], "mismatches": result["mismatches"][:limit],
                                                                                     "mismatch_pairs": len(result["mismatches"])})]


def register_label_value(registry: Registry, corpus_dir: Path | None = None, config_path: Path | None = None, fidelity_config_path: Path | None = None) -> Registry:
    """Add the reason codes and the page-scope check; call ``close_label_value`` after the run."""
    config = load_config(config_path)
    fidelity_config = load_fidelity_config(fidelity_config_path)
    holder: dict[str, LabelValueState] = {}
    for code, severity, meaning, emitter in REASONS:
        registry.register_reason(code, severity, meaning, emitter)

    def check(context: CheckContext, entity: dict) -> list[dict]:
        state = holder.get("state")
        if state is None or state.release_dir != context.release_dir:
            if state is not None:
                state.close()
            state = holder["state"] = LabelValueState(Path(context.release_dir), corpus_dir, fidelity_config, config)
        return evaluate_page(state, registry, entity["ids"], entity)

    registry.register_check(CHECK_NAME, check, "page", CHECK_VERSION, limitations=LIMITATIONS)
    registry.label_value_holder = holder  # type: ignore[attr-defined]
    return registry


def close_label_value(registry: Registry) -> None:
    holder = getattr(registry, "label_value_holder", {})
    if "state" in holder:
        holder["state"].close()
