"""Form-versus-text-chunk conflict check (A-435, OPTIONAL, release only): does a text chunk pair a label with another value than the form record?

K1 holds the same page twice: the form record (``forms.jsonl``: label-value pairs read by geometry and vertical rulings from the PDF,
``verified`` when the page matched the template) and the text chunks that Docling wrote in its own reading order. When the text layer
lists labels first and values later, a text chunk can contain "Days On Location: 1700" while the form record says "Days On Location: 1".
This check reads only the release. For every page that has a VERIFIED form record, it finds the "Label: value" pairs of the text chunks
(label = a label of that page's form record, value = the text after the colon on the same line, or the next line when the label stands alone
is NOT a pair) and flags a pair whose first value token is not the first token of any value that the form record holds for that label.
What it is not: it does not say which side is right (the form record is the better-grounded one, but neither is content-verified), it does
not look at table chunks or at unverified forms, it compares the first token only, and a label without a same-line value is not judged.
WARN signal only, never a publish gate. Opt-in (CLI flag --form-conflict).
"""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from typing import Any

from .labelvalue import fold_label, k1_pairs, first_token
from .ledger import iter_jsonl
from .signals import CheckContext, Registry

DEFAULT_CONFIG = Path("configs/qa/form_conflict.json")
CHECK_NAME = "form_text_conflict"
CHECK_VERSION = "1"
LIMITATIONS = (
    "Compares the text chunks of a page with the form record of the same page of the SAME release; both come from the same PDF text layer, so an error present in the text layer itself is invisible, and the form record can be wrong too (it is not content-verified).",
    "Only pages with a verified form record (template page) are examined; table chunks, form chunks and unverified forms are not.",
    "Only 'Label: value' on one line counts as a pairing; a label that stands alone on its line (value on another line) is not judged, so a wrong pairing that Docling expresses by line order only is NOT detected.",
    "Only the first token of the value is compared; later words of a value can still be wrong. A label that occurs several times in the form record accepts any of its values.",
    "Whether the layouts other than the development documents behave the same is NOT EVALUATED.",
)
REASONS = (
    ("FORM_TEXT_PAIR_CONFLICT", "WARN", "A text chunk gives a label a value that differs from the value of the same label in the verified form record of the page.", CHECK_NAME),
)


def load_config(path: Path | None = None) -> dict:
    return json.loads((path or DEFAULT_CONFIG).read_text(encoding="utf-8"))


def _value(config: dict, section: str, name: str) -> Any:
    return config[section][name]["value"]


def conflicts_of(form_fields: list[dict], text: str) -> tuple[list[dict], int]:
    """(conflicting pairs, compared pairs) of one text against the fields of a form record. Pure function."""
    held: dict[str, list[str]] = defaultdict(list)
    for field in form_fields:
        held[fold_label(field["key"])].append(first_token(field["value"]))
    labels = set(held)
    pairs = [pair for line in text.splitlines() for pair in k1_pairs(line, labels)]  # one line at a time: a value on the next line is not a pairing
    found, compared = [], 0
    for label, token in pairs:
        if not token:
            continue
        compared += 1
        accepted = {value for value in held[label] if value}
        if token not in accepted:
            found.append({"label": label, "text_value": token, "form_values": sorted(accepted) if accepted else [], "form_blank": not accepted})
    return found, compared


class FormConflictState:
    """Index of the verified forms and the text chunks of one release (read once)."""

    def __init__(self, release_dir: Path) -> None:
        self.release_dir = release_dir
        self.forms: dict[tuple[str, int], list[dict]] = defaultdict(list)
        for form in iter_jsonl(release_dir / "forms.jsonl"):
            if form.get("verified"):
                self.forms[(form["file_id"], form["page"])].extend(form["fields"])
        self.chunks: dict[tuple[str, int], list[dict]] = defaultdict(list)
        for chunk in iter_jsonl(release_dir / "chunks.jsonl"):
            if chunk.get("type") == "text" and not chunk.get("table_id") and not chunk.get("form_id"):
                for page in chunk.get("pages") or [chunk.get("page")]:
                    if (chunk["file_id"], page) in self.forms:
                        self.chunks[(chunk["file_id"], page)].append(chunk)

    def analyse(self, file_id: str, page: int) -> dict | None:
        fields = self.forms.get((file_id, page))
        if not fields:
            return None
        conflicts, compared = [], 0
        for chunk in sorted(self.chunks.get((file_id, page), []), key=lambda c: c["chunk_id"]):
            found, count = conflicts_of(fields, chunk["text"])
            compared += count
            conflicts += [{"chunk_id": chunk["chunk_id"], **item} for item in found]
        return {"compared_pairs": compared, "conflicts": conflicts}


def register_form_conflict(registry: Registry, config_path: Path | None = None) -> Registry:
    config = load_config(config_path)
    holder: dict[str, FormConflictState] = {}
    for code, severity, meaning, emitter in REASONS:
        registry.register_reason(code, severity, meaning, emitter)

    def check(context: CheckContext, entity: dict) -> list[dict]:
        state = holder.get("state")
        if state is None or state.release_dir != Path(context.release_dir):
            state = holder["state"] = FormConflictState(Path(context.release_dir))
        ids = entity["ids"]
        result = state.analyse(ids["file_id"], ids["page"])
        if result is None or len(result["conflicts"]) < _value(config, "comparison", "min_conflicts_for_page_signal"):
            return []
        limit = _value(config, "comparison", "max_listed_pairs")
        return [registry.signal("FORM_TEXT_PAIR_CONFLICT", "page", ids, evidence={
            "compared_pairs": result["compared_pairs"], "conflict_pairs": len(result["conflicts"]), "conflicts": result["conflicts"][:limit]})]

    registry.register_check(CHECK_NAME, check, "page", CHECK_VERSION, limitations=LIMITATIONS)
    return registry
