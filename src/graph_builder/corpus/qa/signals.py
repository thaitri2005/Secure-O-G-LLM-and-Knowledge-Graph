"""QA signals, reason-code registry, verification levels and the check-registration API.

The QA sidecar describes a K1 release without changing it. Nothing in this module can label content as verified:
the allowed verification levels only say which independent consistency checks were run and passed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

SCHEMA_VERSION = "1"
SEVERITIES = ("INFO", "WARN", "ERROR")
SCOPES = ("release", "document", "page", "table")

# Allowed verification levels (spec 0.12). Order is the rank used when a check grants a higher level.
LEVELS = ("UNVERIFIED", "STRUCTURAL_ONLY", "TEXT_LAYER_CONSISTENT", "CROSS_REPRESENTATION_CONSISTENT")
NOT_APPLICABLE = "NOT_APPLICABLE"
ALL_LEVELS = LEVELS + (NOT_APPLICABLE,)
GRANTABLE = ("TEXT_LAYER_CONSISTENT", "CROSS_REPRESENTATION_CONSISTENT", NOT_APPLICABLE)
COMPLETENESS_VALUES = ("UNKNOWN", "PARTIAL_IN_SOURCE")  # a "complete" value is deliberately not available

LIMITATIONS = (
    "The ledger records signals produced by pipeline metadata and registered checks; the absence of a signal is not evidence of correct content.",
    "STRUCTURAL_ONLY means the release passed schema and consistency rules of K1; it says nothing about whether text, numbers or table cells match the source document.",
    "The quality field of K1 chunks ('ok') is copied as a counter only and is never treated as evidence of correct content.",
    "Docling confidence scores, extracted/pdf character ratios and A-107 states are heuristics of the pipeline that produced the data, not independent references.",
    "The extracted/pdf character ratio is computed by the pipeline against its own text-layer count; furniture removal (footers, running lines) lowers it legitimately.",
    "OCR and hybrid pages have no independent reference in this ledger.",
    "Thresholds in configs/qa/ledger.json are proposals evaluated on five documents of one document family only; generalisation is NOT EVALUATED.",
)

KNOWN_BLIND_SPOTS = (
    "swapped cells or rows inside a table",
    "reordered text or reordered sentences",
    "wrong label-value pairing in forms and key-value tables",
    "OCR substitution errors without an independent reference",
    "errors already present in the PDF text layer",
    "wrong table structure that keeps the same words",
    "numbers changed consistently in every representation",
    "content dropped by the pipeline that is not recorded in its dropped-item statistics",
)


@dataclass(frozen=True)
class Reason:
    code: str
    severity: str
    meaning: str
    emitted_by: str


def _reasons(*items: tuple[str, str, str, str]) -> dict[str, Reason]:
    return {code: Reason(code, severity, meaning, emitter) for code, severity, meaning, emitter in items}


BUILTIN_REASONS = _reasons(
    ("QA_ERROR", "ERROR", "A check or the processing of one entity raised an exception; the entity is left UNVERIFIED and QA continues.", "ledger, registry"),
    ("K1_VALIDATOR_FAIL", "ERROR", "k1_validate.inspect reported errors for the release (the first errors are listed in evidence).", "k1_validator"),
    ("WORK_FOLDER_MISSING", "WARN", "No corpus work folder data for this document; the ledger is built from the release only (degraded).", "work_folder"),
    ("WORK_FINGERPRINT_MISMATCH", "WARN", "Fingerprint of the corpus work data differs from the corpus fingerprint of the release manifest.", "work_folder"),
    ("SEGMENT_FAILED", "ERROR", "A Docling segment did not finish with status success.", "work_folder"),
    ("SEGMENT_ERRORS", "WARN", "A Docling segment finished but recorded error strings.", "work_folder"),
    ("DROPPED_ITEMS_RECORDED", "INFO", "The pipeline removed items (running lines, footers, pictures, index) and recorded their counts.", "work_folder"),
    ("PAGE_STATUS_REVIEW", "WARN", "Page status is 'review' in the release.", "page_status"),
    ("PAGE_STATUS_MISSING", "ERROR", "Page status is 'missing' in the release.", "page_status"),
    ("PAGE_STATUS_OTHER", "WARN", "Page status has a value other than ok, review or missing.", "page_status"),
    ("PAGE_NOT_IN_WORK_DATA", "WARN", "The page exists in the release but not in the corpus work document.", "work_folder"),
    ("PAGE_EMPTY_EXTRACTION", "WARN", "A text-mode page has PDF text characters but zero extracted characters.", "char_ratio"),
    ("CHAR_RATIO_LOW", "WARN", "Extracted/pdf text-char ratio of a text-mode page is below the proposed threshold.", "char_ratio"),
    ("CHAR_RATIO_HIGH", "WARN", "Extracted/pdf text-char ratio of a text-mode page is above the proposed threshold (text not in the text layer).", "char_ratio"),
    ("CONFIDENCE_LOW", "WARN", "Docling mean_score of the page is below the proposed threshold.", "docling_confidence"),
    ("CONFIDENCE_MISSING", "INFO", "No Docling confidence value is available for a page (work data missing or OCR page).", "docling_confidence"),
    ("OCR_PAGE_NO_REFERENCE", "INFO", "Page text came from OCR or hybrid conversion; no independent reference exists in this ledger.", "ocr_flags"),
    ("TABLE_ORIGIN_TEXTLAYER_REBUILD", "INFO", "Table (or part) was rebuilt from the PDF text layer by a rule, not produced by Docling.", "table_origin"),
    ("TABLE_ORIGIN_UNKNOWN", "WARN", "The release table has no source_ref in its parts, origin cannot be determined.", "table_origin"),
    ("A107_SIDECAR_MISSING", "INFO", "No A-107 table repair sidecar was found for this release; table repair states are unknown.", "a107_sidecar"),
    ("A107_STATE_NOT_VALIDATED", "WARN", "A-107 sidecar state of the table is not SUPPORTED_AND_VALIDATED.", "a107_sidecar"),
    ("A107_PARTIAL_IN_SOURCE", "INFO", "The PDF itself indicates that records were not printed (A-107 completeness partial_in_source).", "a107_sidecar"),
    ("A107_RECORD_UNMATCHED", "WARN", "An A-107 sidecar record refers to a table_id that is not in the release.", "a107_sidecar"),
    ("CHUNK_QUALITY_NOT_OK", "WARN", "Chunks of this document carry a quality value other than 'ok'.", "chunk_quality"),
)


@dataclass
class Registry:
    """Reason codes plus registered checks. A-402 and A-403 add their own codes and checks here."""

    reasons: dict[str, Reason] = field(default_factory=lambda: dict(BUILTIN_REASONS))
    checks: list["Check"] = field(default_factory=list)

    def register_reason(self, code: str, severity: str, meaning: str, emitted_by: str) -> None:
        if severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}")
        if code in self.reasons:
            raise ValueError(f"reason code already registered: {code}")
        self.reasons[code] = Reason(code, severity, meaning, emitted_by)

    def register_check(self, name: str, function: Callable[["CheckContext", dict], list[dict]], scope: str,
                       version: str, grants: str | None = None, limitations: tuple[str, ...] = ()) -> None:
        """Register ``function(context, entity) -> list[signal]`` for entities of ``scope``.

        ``grants`` is a verification level given to an entity when the check ran and produced no WARN/ERROR
        signal. Only the levels in GRANTABLE are accepted; a check cannot claim content verification."""
        if scope not in SCOPES:
            raise ValueError(f"scope must be one of {SCOPES}")
        if grants is not None and grants not in GRANTABLE:
            raise ValueError(f"grants must be None or one of {GRANTABLE}")
        if any(check.name == name for check in self.checks):
            raise ValueError(f"check already registered: {name}")
        self.checks.append(Check(name, function, scope, version, grants, tuple(limitations)))

    def signal(self, code: str, scope: str, ids: dict[str, Any], message: str | None = None,
               evidence: dict[str, Any] | None = None) -> dict:
        reason = self.reasons[code]
        return {"code": code, "severity": reason.severity, "scope": {"kind": scope, "ids": dict(sorted(ids.items()))},
                "evidence": evidence or {}, "message": message or reason.meaning}

    def run(self, scope: str, context: "CheckContext", entity: dict, ids: dict[str, Any]) -> tuple[list[dict], list[str], str | None]:
        """Run the checks of ``scope``: returns (signals, 'name@version' list, highest granted level)."""
        signals, ran, granted = [], [], None
        for check in sorted((c for c in self.checks if c.scope == scope), key=lambda c: c.name):
            ran.append(f"{check.name}@{check.version}")
            try:
                produced = check.function(context, entity)
            except Exception as error:  # noqa: BLE001 - failure isolation: one broken check never stops QA
                signals.append(self.signal("QA_ERROR", scope, ids, evidence={"check": check.name, "error": type(error).__name__,
                                                                              "detail": str(error)[:300]}))
                continue
            signals += produced
            # A check that could not examine the entity (no reference, OCR page, too little text) marks one of its
            # INFO signals with evidence {"grant_withheld": true}; the level it grants is then not given.
            withheld = any((s.get("evidence") or {}).get("grant_withheld") for s in produced)
            if check.grants and not withheld and not any(s["severity"] in ("WARN", "ERROR") for s in produced):
                granted = merge_level(granted, check.grants)
        return signals, ran, granted


@dataclass(frozen=True)
class Check:
    name: str
    function: Callable[["CheckContext", dict], list[dict]]
    scope: str
    version: str
    grants: str | None
    limitations: tuple[str, ...]


@dataclass
class CheckContext:
    """Read-only inputs given to checks."""

    registry: Registry
    config: dict
    release_dir: Any
    manifest: dict
    document: dict | None = None
    validator: dict | None = None
    sidecar: dict | None = None  # table_id -> A-107 sidecar record, None when no sidecar was found


def merge_level(current: str | None, granted: str) -> str:
    """Keep the higher of two levels; NOT_APPLICABLE ranks below every real level."""
    rank = {NOT_APPLICABLE: -1, **{level: index for index, level in enumerate(LEVELS)}}
    if current is None:
        return granted
    return granted if rank[granted] > rank[current] else current


def initial_level(signals: list[dict]) -> str:
    return "UNVERIFIED" if any(s["severity"] == "ERROR" for s in signals) else "STRUCTURAL_ONLY"


def final_level(base: str, granted: str | None, signals: list[dict]) -> str:
    """Level after plugin checks. Any ERROR signal forces UNVERIFIED; NOT_APPLICABLE only replaces STRUCTURAL_ONLY."""
    if any(s["severity"] == "ERROR" for s in signals):
        return "UNVERIFIED"
    if granted is None:
        return base
    if granted == NOT_APPLICABLE:
        return NOT_APPLICABLE if base == "STRUCTURAL_ONLY" else base
    return merge_level(base, granted)
