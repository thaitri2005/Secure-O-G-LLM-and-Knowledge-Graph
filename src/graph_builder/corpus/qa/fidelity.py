"""Source fidelity check (A-402): compare the text of a K1 page with the PDF text layer read by another library.

What it is: a second reader (pypdfium2) over the same text layer that Docling and the pipeline already used. It compares
multisets of word tokens and numeric tokens per page. It emits WARN/INFO signals only; it is never a publish gate.
What it is not: it does not verify content. A page that passes may be granted TEXT_LAYER_CONSISTENT at most, and only
for text-mode pages that had enough tokens. See KNOWN_BLIND_SPOTS in signals.py (swapped cells, reordered text, wrong
pairings, OCR errors, errors inside the text layer and wrong table structure with the same words stay invisible).
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterator

from .signals import CheckContext, Registry

DEFAULT_CONFIG = Path("configs/qa/source_fidelity.json")
CHECK_NAME = "source_fidelity"
CHECK_VERSION = "1"
WORD = re.compile(r"[^\W\d_]\w*")
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
PAGE_NUMBER = re.compile(r"^#{1,4}$")  # line_key of a bare number of up to four digits

FIDELITY_LIMITATIONS = (
    "Second reader over the SAME PDF text layer: errors present in the text layer itself are invisible.",
    "Compares multisets of tokens per page: swapped cells, reordered text or sentences, wrong label-value pairing and wrong table structure that keeps the same words are NOT detected.",
    "A digit changed in K1 is only seen when the new token does not occur on the PDF page; a consistent change of every occurrence of a number is not seen.",
    "OCR pages have no independent reference (NOT_APPLICABLE); hybrid pages are checked for PDF-word recall only and receive no level.",
    "Furniture exclusion uses repeated top/bottom margin lines (digits masked) found in the PDF itself; furniture the pipeline removed from other places is reported as content candidate. A bare number as first/last line of a page counts as page number, which can hide one genuinely missing number.",
    "Section titles kept in chunk metadata credit recall only (a title can be inherited from an earlier page).",
    "Page rotation and multi-column order are not modelled; thresholds are proposals from one document family.",
)

REASONS = (
    ("FIDELITY_NUMERIC_NOVEL", "WARN", "K1 page text has numeric tokens that do not occur on the PDF page text layer.", CHECK_NAME),
    ("FIDELITY_NUMERIC_RECALL_LOW", "WARN", "Numeric-token recall of the PDF page in K1 (after furniture exclusion) is below the proposed threshold.", CHECK_NAME),
    ("FIDELITY_WORD_RECALL_LOW", "WARN", "Word-token recall of the PDF page in K1 (after furniture exclusion) is below the proposed threshold.", CHECK_NAME),
    ("FIDELITY_PAGE_EMPTY", "WARN", "K1 has no text for a page whose PDF text layer has words.", CHECK_NAME),
    ("FIDELITY_NOT_APPLICABLE", "INFO", "OCR page: no independent text reference exists; the level stays STRUCTURAL_ONLY.", CHECK_NAME),
    ("FIDELITY_PARTIAL_REFERENCE", "INFO", "Hybrid page: only PDF-word recall was compared; OCR text has no reference; no level granted.", CHECK_NAME),
    ("FIDELITY_NO_REFERENCE", "INFO", "The source PDF was not found or its SHA-256 differs from the release; nothing was compared.", CHECK_NAME),
    ("FIDELITY_INSUFFICIENT_TOKENS", "INFO", "The PDF page has too few word tokens to judge recall; numeric checks still ran.", CHECK_NAME),
)


def load_config(path: Path | None = None) -> dict:
    return json.loads((path or DEFAULT_CONFIG).read_text(encoding="utf-8"))


def _value(config: dict, section: str, name: str) -> Any:
    return config[section][name]["value"]


def normalise(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def tokens(text: str) -> tuple[Counter, Counter]:
    """(word multiset, numeric multiset) of a text. Words start with a letter; numbers keep inner . and ,."""
    folded = normalise(text)
    return Counter(WORD.findall(folded)), Counter(NUMBER.findall(folded))


def line_key(line: str) -> str:
    """Margin line identity for furniture detection: digits masked, case and spaces folded."""
    return " ".join(re.sub(r"\d", "#", normalise(line)).split())


def furniture_keys(band_lines: list[list[str]], frequency: float, min_pages: int) -> set[str]:
    """Margin lines that repeat on at least ``frequency`` of the pages of a document (needs ``min_pages`` pages)."""
    if len(band_lines) < min_pages:
        return set()
    seen: Counter = Counter()
    for lines in band_lines:
        seen.update({line_key(line) for line in lines if line_key(line)})
    return {key for key, count in seen.items() if count / len(band_lines) >= frequency}


def _missing(reference: Counter, other: Counter) -> Counter:
    return Counter({token: count - other[token] for token, count in reference.items() if count > other[token]})


def _take(missing: Counter, pool: Counter) -> Counter:
    """Part of ``missing`` that a furniture pool can explain (never more than the pool holds)."""
    return Counter({token: min(count, pool[token]) for token, count in missing.items() if pool[token] > 0})


def compare_page(pdf_text: str, k1_text: str, margin_text: str, repeated_text: str, config: dict, credit_text: str = "") -> dict:
    """Pure comparison of one page.

    Furniture explains only tokens that are actually missing from K1: missing tokens are first attributed to repeated
    margin lines, then to other lines repeated on most pages of the document, the rest is 'content candidate'.
    Recall is reported raw and after removing the furniture-explained tokens from numerator and denominator.\n    ``credit_text`` (section titles kept in chunk metadata) counts toward recall only: a title can be inherited from an\n    earlier page, so it must never create or hide a novel token."""
    p_words, p_nums = tokens(pdf_text)
    k_words, k_nums = tokens(k1_text)
    c_words, c_nums = tokens(k1_text + "\n" + credit_text)
    result: dict[str, Any] = {}
    for kind, pdf, k1, margin, repeated in (("word", p_words, c_words, tokens(margin_text)[0], tokens(repeated_text)[0]),
                                            ("numeric", p_nums, c_nums, tokens(margin_text)[1], tokens(repeated_text)[1])):
        total = sum(pdf.values())
        raw_missing = _missing(pdf, k1)
        by_margin = _take(raw_missing, margin)
        by_repeated = _take(_missing(raw_missing, by_margin), repeated)
        content_missing = _missing(_missing(raw_missing, by_margin), by_repeated)
        explained = sum(by_margin.values()) + sum(by_repeated.values())
        ref_total = total - explained
        result[kind] = {
            "pdf_tokens": total, "reference_tokens": ref_total, "k1_tokens": sum(k1.values()),
            "missing_raw": sum(raw_missing.values()), "missing_content": sum(content_missing.values()),
            "missing_furniture_margin": sum(by_margin.values()), "missing_furniture_repeated_line": sum(by_repeated.values()),
            "recall_raw": round(1 - sum(raw_missing.values()) / total, 4) if total else None,
            "recall_after_exclusion": round(1 - sum(content_missing.values()) / ref_total, 4) if ref_total else None,
            "_content_missing": content_missing, "_margin": by_margin, "_repeated": by_repeated}
    novel_numeric = sorted(set(k_nums) - set(p_nums))
    result["novel_numeric"] = novel_numeric
    result["novel_numeric_occurrences"] = sum(k_nums[token] for token in novel_numeric)
    result["novel_word_types"] = len(set(k_words) - set(p_words))
    return result

def _listed(counter: Counter, limit: int) -> list[str]:
    return [f"{token}x{count}" if count > 1 else token for token, count in sorted(counter.items())[:limit]]


def public_metrics(raw: dict, limit: int) -> dict:
    """Metrics without the internal counters, plus bounded sorted token samples for the evidence."""
    out = {kind: {k: v for k, v in raw[kind].items() if not k.startswith("_")} for kind in ("word", "numeric")}
    out.update({"novel_numeric": raw["novel_numeric"][:limit], "novel_numeric_types": len(raw["novel_numeric"]),
                "novel_numeric_occurrences": raw["novel_numeric_occurrences"], "novel_word_types": raw["novel_word_types"]})
    for name, key in (("missing_content_candidate", "_content_missing"), ("missing_furniture_margin", "_margin"),
                      ("missing_furniture_repeated_line", "_repeated")):
        out[name] = {kind: _listed(raw[kind][key], limit) for kind in ("word", "numeric")}
    return out

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def k1_page_texts(release_dir: Path, file_id: str) -> tuple[dict[int, str], dict[int, str]]:
    """(page text, section titles) per page. Text is rebuilt from chunks the way the K1 validator does (source spans,
    else the whole chunk text). Section titles come from chunk metadata: K1 keeps headings there, not in chunk text."""
    pages: dict[int, list[str]] = {}
    sections: dict[int, set[str]] = {}
    for chunk in iter_jsonl(release_dir / "chunks.jsonl"):
        if chunk["file_id"] != file_id:
            continue
        if chunk.get("source_spans"):
            numbers = set()
            for span in chunk["source_spans"]:
                numbers.add(span["page"])
                pages.setdefault(span["page"], []).append(chunk["text"][span["start"]:span["end"]])
        elif chunk.get("page") is not None:
            numbers = {chunk["page"]}
            pages.setdefault(chunk["page"], []).append(chunk["text"])
        else:
            numbers = set()
        for number in numbers:
            sections.setdefault(number, set()).update(str(item) for item in (chunk.get("section_path") or []))
    return ({page: "\n".join(parts) for page, parts in pages.items()},
            {page: "\n".join(sorted(items)) for page, items in sections.items()})


class PdfReference:
    """Open PDF with per-page text and the document-level repeated-line keys. Only one document is held at a time."""

    def __init__(self, path: Path, config: dict) -> None:
        import pypdfium2 as pdfium
        self.document = pdfium.PdfDocument(str(path))
        self.config = config
        self.page_count = len(self.document)
        self._keys: set[str] | None = None
        self._margin_keys: list[set[str]] = []

    def close(self) -> None:
        self.document.close()

    def _read(self, index: int, band: float | None) -> tuple[str, str]:
        """(full page text, text of the top and bottom margin bands or '' when band is None)."""
        page = self.document[index]
        try:
            textpage = page.get_textpage()
            try:
                full = textpage.get_text_range()
                margins = ""
                if band is not None:
                    width, height = page.get_size()
                    margins = (textpage.get_text_bounded(0, height * (1 - band), width, height) + "\n"
                               + textpage.get_text_bounded(0, 0, width, height * band))
            finally:
                textpage.close()
        finally:
            page.close()
        return full, margins

    def _scan(self) -> set[str]:
        """One pass over the document: keys of lines that repeat on at least ``frequency`` of the pages (digits masked)."""
        if self._keys is None:
            band = _value(self.config, "furniture", "margin_band")
            seen: Counter = Counter()
            for index in range(self.page_count):
                full, margins = self._read(index, band)
                keys = {line_key(line) for line in full.splitlines()} - {""}
                seen.update(keys)
                self._margin_keys.append({line_key(line) for line in margins.splitlines()} - {""})
            frequency, min_pages = _value(self.config, "furniture", "frequency"), _value(self.config, "furniture", "min_pages")
            self._keys = set() if self.page_count < min_pages else {key for key, n in seen.items() if n / self.page_count >= frequency}
        return self._keys

    def page_text(self, page_number: int) -> tuple[str, str, str]:
        """(full page text, repeated margin lines, other repeated lines) for a 1-based page number."""
        index = page_number - 1
        keys = self._scan()
        full, _ = self._read(index, None)
        lines = [line for line in full.splitlines() if line_key(line)]
        margin, repeated = [], []
        for position, line in enumerate(lines):
            key = line_key(line)
            if PAGE_NUMBER.match(key) and (position in (0, len(lines) - 1) or key in self._margin_keys[index]):
                margin.append(line)  # a bare number as first/last line or in a margin band: page number
            elif key in keys:
                (margin if key in self._margin_keys[index] else repeated).append(line)
        return full, "\n".join(margin), "\n".join(repeated)


class FidelityState:
    """Per-release state: file rows, PDF lookup (SHA-256 verified), one open PDF and one rebuilt K1 text at a time."""

    def __init__(self, release_dir: Path, corpus_dir: Path | None, config: dict) -> None:
        self.release_dir, self.corpus_dir, self.config = release_dir, corpus_dir, config
        self.files = {row["file_id"]: row for row in iter_jsonl(release_dir / "files.jsonl")}
        self._current: str | None = None
        self._reference: PdfReference | None = None
        self._reference_error: str | None = None
        self._k1: dict[int, str] = {}
        self._sections: dict[int, str] = {}

    def close(self) -> None:
        if self._reference is not None:
            self._reference.close()
        self._reference, self._current = None, None

    def locate_pdf(self, file_row: dict) -> tuple[Path | None, str]:
        sha = str(file_row.get("sha256") or "")
        if len(sha) < 8:
            return None, "release file row has no sha256"
        values = {"corpus": str(self.corpus_dir) if self.corpus_dir else "", "sha": sha, "sha2": sha[:2], "sha4": sha[2:4],
                  "original_name": file_row.get("original_name", "")}
        tried = []
        for template in self.config.get("pdf_search", []):
            if "{corpus}" in template and not self.corpus_dir:
                continue
            candidate = Path(template.format(**values))
            tried.append(str(candidate.name))
            if candidate.is_file() and sha256_file(candidate) == sha:
                return candidate, ""
        return None, "no PDF with matching sha256 among: " + ", ".join(tried)

    def select(self, file_id: str) -> None:
        if file_id == self._current:
            return
        self.close()
        self._current, self._reference_error = file_id, None
        self._k1, self._sections = k1_page_texts(self.release_dir, file_id)
        path, reason = self.locate_pdf(self.files[file_id])
        if path is None:
            self._reference_error = reason
            return
        try:
            self._reference = PdfReference(path, self.config)
        except Exception as error:  # noqa: BLE001 - unreadable PDF is a missing reference, not a crash
            self._reference_error = f"PDF unreadable: {type(error).__name__}"

    def analyse(self, file_id: str, page: int) -> tuple[dict | None, str | None]:
        """(raw comparison or None, reference error or None) for one page."""
        self.select(file_id)
        if self._reference is None:
            return None, self._reference_error
        if not 1 <= page <= self._reference.page_count:
            return None, f"page {page} outside the PDF ({self._reference.page_count} pages)"
        pdf_text, margin, repeated = self._reference.page_text(page)
        return compare_page(pdf_text, self._k1.get(page, ""), margin, repeated, self.config, self._sections.get(page, "")), None

    def k1_text(self, file_id: str, page: int) -> str:
        self.select(file_id)
        return self._k1.get(page, "")

    def pdf_page(self, file_id: str, page: int) -> tuple[str, str, str]:
        self.select(file_id)
        if self._reference is None:
            raise LookupError(self._reference_error)
        return self._reference.page_text(page)

def judge(raw: dict, mode: str, k1_empty: bool, config: dict) -> list[tuple[str, dict]]:
    """Pure decision: (reason code, evidence) pairs for one compared page. Mode is the release conversion mode."""
    metrics = public_metrics(raw, config["max_listed_tokens"]["value"])
    words, numbers = metrics["word"], metrics["numeric"]
    enough = words["reference_tokens"] >= _value(config, "thresholds", "min_page_words")
    if k1_empty and words["pdf_tokens"] >= _value(config, "thresholds", "empty_page_min_words"):
        return [("FIDELITY_PAGE_EMPTY", metrics)]
    out: list[tuple[str, dict]] = []
    if mode == "hybrid":
        out.append(("FIDELITY_PARTIAL_REFERENCE", {"mode": mode, "grant_withheld": True}))
    elif not enough:
        out.append(("FIDELITY_INSUFFICIENT_TOKENS", {"pdf_word_tokens": words["pdf_tokens"], "grant_withheld": True}))
    if mode != "hybrid" and metrics["novel_numeric_types"] > _value(config, "thresholds", "numeric_novel_max"):
        out.append(("FIDELITY_NUMERIC_NOVEL", metrics))
    recall = numbers["recall_after_exclusion"]
    if recall is not None and recall < _value(config, "thresholds", "numeric_recall_min"):
        out.append(("FIDELITY_NUMERIC_RECALL_LOW", metrics))
    recall = words["recall_after_exclusion"]
    if enough and recall is not None and recall < _value(config, "thresholds", "word_recall_min"):
        out.append(("FIDELITY_WORD_RECALL_LOW", metrics))
    return out


def evaluate_page(state: FidelityState, registry: Registry, ids: dict, entity: dict) -> list[dict]:
    """Signals for one page entity (needs ids file_id/page and entity release_mode)."""
    mode = entity.get("release_mode")
    if mode == "ocr":
        return [registry.signal("FIDELITY_NOT_APPLICABLE", "page", ids, evidence={"mode": mode, "grant_withheld": True})]
    raw, error = state.analyse(ids["file_id"], ids["page"])
    if raw is None:
        return [registry.signal("FIDELITY_NO_REFERENCE", "page", ids, evidence={"reason": error, "grant_withheld": True})]
    k1_empty = state.k1_text(ids["file_id"], ids["page"]).strip() == ""
    return [registry.signal(code, "page", ids, evidence=evidence) for code, evidence in judge(raw, str(mode), k1_empty, state.config)]

def register_fidelity(registry: Registry, corpus_dir: Path | None = None, config_path: Path | None = None) -> Registry:
    """Add the reason codes and the page-scope check to a quality-ledger registry.

    The per-release state is created lazily by the first page the check sees; call ``close_fidelity`` after the run."""
    config = load_config(config_path)
    holder: dict[str, FidelityState] = {}
    for code, severity, meaning, emitter in REASONS:
        registry.register_reason(code, severity, meaning, emitter)

    def check(context: CheckContext, entity: dict) -> list[dict]:
        state = holder.get("state")
        if state is None or state.release_dir != context.release_dir:
            if state is not None:
                state.close()
            state = holder["state"] = FidelityState(Path(context.release_dir), corpus_dir, config)
        return evaluate_page(state, registry, entity["ids"], entity)

    registry.register_check(CHECK_NAME, check, "page", CHECK_VERSION, grants="TEXT_LAYER_CONSISTENT", limitations=FIDELITY_LIMITATIONS)
    registry.fidelity_holder = holder  # type: ignore[attr-defined]
    return registry


def close_fidelity(registry: Registry) -> None:
    holder = getattr(registry, "fidelity_holder", {})
    if "state" in holder:
        holder["state"].close()
