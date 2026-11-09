"""Checks built into the quality ledger. They read metadata the pipeline already stored; none reads the PDF.

Every check takes (context, entity) and returns a list of signal objects. Entities carry their own ``ids``."""
from __future__ import annotations

from .signals import CheckContext, Registry


def _threshold(context: CheckContext, name: str) -> float:
    return context.config["thresholds"][name]["value"]


def _sig(context: CheckContext, code: str, scope: str, entity: dict, evidence: dict | None = None, message: str | None = None) -> dict:
    return context.registry.signal(code, scope, entity["ids"], message=message, evidence=evidence)


def check_k1_validator(context: CheckContext, entity: dict) -> list[dict]:
    validator = entity["validator"]
    if validator["status"] == "pass":
        return []
    return [_sig(context, "K1_VALIDATOR_FAIL", "release", entity,
                 {"error_count": validator["error_count"], "errors": validator["errors"]})]


def check_a107_release(context: CheckContext, entity: dict) -> list[dict]:
    if entity["sidecar"]["found"] is False:
        return [_sig(context, "A107_SIDECAR_MISSING", "release", entity, {"searched": entity["sidecar"]["searched"]})]
    return [_sig(context, "A107_RECORD_UNMATCHED", "release", entity, {"table_id": table_id})
            for table_id in entity["sidecar"]["unmatched"]]


def check_work_folder(context: CheckContext, entity: dict) -> list[dict]:
    out = []
    work = entity["work"]
    if not work["present"]:
        return [_sig(context, "WORK_FOLDER_MISSING", "document", entity, {"reason": work["reason"]})]
    if work["fingerprint_matches_release"] is False:
        out.append(_sig(context, "WORK_FINGERPRINT_MISMATCH", "document", entity, {"work": work["fingerprint"]}))
    for segment in work["segments"]:
        if segment["status"] != "success":
            out.append(_sig(context, "SEGMENT_FAILED", "document", entity, {"pages": segment["pages"], "status": segment["status"]}))
        if segment["errors"]:
            out.append(_sig(context, "SEGMENT_ERRORS", "document", entity, {"pages": segment["pages"], "errors": segment["errors"][:5]}))
    if work["dropped"]:
        out.append(_sig(context, "DROPPED_ITEMS_RECORDED", "document", entity, {"dropped": work["dropped"]}))
    return out


def check_chunk_quality(context: CheckContext, entity: dict) -> list[dict]:
    bad = {key: count for key, count in entity["chunks"]["by_quality"].items() if key != "ok"}
    return [_sig(context, "CHUNK_QUALITY_NOT_OK", "document", entity, {"by_quality": bad})] if bad else []


def check_page_status(context: CheckContext, entity: dict) -> list[dict]:
    status = entity["status"]
    code = {"ok": None, "review": "PAGE_STATUS_REVIEW", "missing": "PAGE_STATUS_MISSING"}.get(status, "PAGE_STATUS_OTHER")
    out = [_sig(context, code, "page", entity, {"status": status})] if code else []
    if entity["work_present"] is False and entity["document_has_work"]:
        out.append(_sig(context, "PAGE_NOT_IN_WORK_DATA", "page", entity))
    return out


def check_char_ratio(context: CheckContext, entity: dict) -> list[dict]:
    """Ratio of extracted to PDF text characters, text-mode pages only (hybrid/OCR pages add OCR text outside the text layer)."""
    pdf, extracted = entity["pdf_text_chars"], entity["extracted_characters"]
    if entity["release_mode"] != "text" or pdf is None or extracted is None or pdf < _threshold(context, "min_pdf_text_chars"):
        return []
    evidence = {"pdf_text_chars": pdf, "extracted_characters": extracted, "ratio": entity["char_ratio"]}
    if extracted == 0:
        exclusion = entity.get("page_exclusion")
        if exclusion and exclusion["explained"]:  # table of contents removed on purpose and recorded; not a verification of the exclusion
            return [_sig(context, "PAGE_EMPTY_EXPLAINED_BY_EXCLUSION", "page", entity, {**evidence, "exclusion": exclusion})]
        return [_sig(context, "PAGE_EMPTY_EXTRACTION", "page", entity, {**evidence, **({"exclusion_partial": exclusion} if exclusion else {})})]
    if entity["char_ratio"] < _threshold(context, "char_ratio_low"):
        return [_sig(context, "CHAR_RATIO_LOW", "page", entity, {**evidence, "threshold": _threshold(context, "char_ratio_low")})]
    if entity["char_ratio"] > _threshold(context, "char_ratio_high"):
        return [_sig(context, "CHAR_RATIO_HIGH", "page", entity, {**evidence, "threshold": _threshold(context, "char_ratio_high")})]
    return []


def check_confidence(context: CheckContext, entity: dict) -> list[dict]:
    confidence = entity["confidence"]
    if not confidence or confidence.get("mean_score") is None:
        return [_sig(context, "CONFIDENCE_MISSING", "page", entity)]
    if confidence["mean_score"] < _threshold(context, "confidence_low"):
        return [_sig(context, "CONFIDENCE_LOW", "page", entity, {"confidence": confidence, "threshold": _threshold(context, "confidence_low")})]
    return []


def check_ocr_flags(context: CheckContext, entity: dict) -> list[dict]:
    if entity["release_mode"] in ("ocr", "hybrid") or entity["ocr"]:
        return [_sig(context, "OCR_PAGE_NO_REFERENCE", "page", entity, {"mode": entity["release_mode"], "ocr": entity["ocr"]})]
    return []


def check_table_origin(context: CheckContext, entity: dict) -> list[dict]:
    if entity["origin"] == "unknown":
        return [_sig(context, "TABLE_ORIGIN_UNKNOWN", "table", entity)]
    if entity["origin"] in ("textlayer_rebuild", "mixed"):
        return [_sig(context, "TABLE_ORIGIN_TEXTLAYER_REBUILD", "table", entity, {"source_refs": entity["source_refs"]})]
    return []


def check_a107_table(context: CheckContext, entity: dict) -> list[dict]:
    record = entity["a107"]
    if record is None:
        return []
    out = []
    if record["state"] != "SUPPORTED_AND_VALIDATED":
        out.append(_sig(context, "A107_STATE_NOT_VALIDATED", "table", entity, {"state": record["state"], "reason": record["reason"]}))
    if entity["completeness"] == "PARTIAL_IN_SOURCE":
        out.append(_sig(context, "A107_PARTIAL_IN_SOURCE", "table", entity, {"completeness": record["completeness"]}))
    return out


def register_builtin(registry: Registry) -> Registry:
    version = "1"
    registry.register_check("k1_validator", check_k1_validator, "release", version,
                            limitations=("Runs k1_validate.inspect read-only; it checks schema, references, checksums and page rebuild, not content.",))
    registry.register_check("a107_sidecar_release", check_a107_release, "release", version,
                            limitations=("Sidecar is found by file-name convention; a different export with the same name would be matched.",))
    registry.register_check("work_folder", check_work_folder, "document", version,
                            limitations=("Reads statistics stored by the pipeline; items dropped without being counted are invisible.",))
    registry.register_check("chunk_quality", check_chunk_quality, "document", version,
                            limitations=("quality 'ok' is only counted, never treated as evidence of correct content.",))
    registry.register_check("page_status", check_page_status, "page", version)
    registry.register_check("char_ratio", check_char_ratio, "page", version,
                            limitations=("Compares the pipeline's own extracted-char count with its own PDF text-char count; furniture removal lowers the ratio legitimately.",))
    registry.register_check("docling_confidence", check_confidence, "page", version,
                            limitations=("Docling scores are model heuristics, not measured accuracy.",))
    registry.register_check("ocr_flags", check_ocr_flags, "page", version)
    registry.register_check("table_origin", check_table_origin, "table", version)
    registry.register_check("a107_sidecar_table", check_a107_table, "table", version,
                            limitations=("States come from the A-107 rule's own validation, not from an independent reference.",))
    return registry
