"""Shared application records: evidence, claim revisions and registry entities (design §7.1; plan backlog 7).

These join the three paths that exist today. A corpus chunk and a dataset record both become ``Evidence`` pinned
to the published release they came from; extraction and dataset mappings both produce ``Claim`` revisions that
cite evidence IDs; subjects resolve to registry ``Entity`` IDs. IDs are content digests, so rebuilding from the
same inputs gives the same IDs and any change in source, release, locator or value gives new ones.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .corpus.store import file_sha256
from .publication import current_release

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"
CLAIM_KINDS = ("observation", "plan", "derived", "interpretation")


class ContractError(ValueError):
    pass


def _digest(prefix: str, value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"{prefix}:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:24]}"


@lru_cache(maxsize=None)
def _validator(name: str):
    from jsonschema import Draft202012Validator
    return Draft202012Validator(json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8")))


def check(name: str, record: dict[str, Any], validate: bool = True) -> dict[str, Any]:
    """Validate a record against schemas/<name>.schema.json; raise ContractError listing every problem.

    Bulk builders may pass ``validate=False`` after validating a sample: schema checks cost about 2.5 ms each.
    """
    if not validate:
        return record
    problems = [f"{error.json_path}: {error.message}" for error in _validator(name).iter_errors(record)]
    if problems:
        raise ContractError(f"invalid {name}: {problems}")
    return record


def bundle_ref(root: Path, kind: str) -> dict[str, str]:
    """Pin the current release of a corpus export or dataset bundle: its name and the digest of its SHA256SUMS."""
    release = current_release(root)
    return {"kind": kind, "release": release.name if release != root else "flat",
            "sums_sha256": file_sha256(release / "SHA256SUMS")}


def evidence_from_chunk(chunk: dict[str, Any], document: dict[str, Any], bundle: dict[str, str],
                        quote: str | None = None) -> dict[str, Any]:
    """Evidence for a span of a corpus chunk. Without ``quote`` the whole chunk is the evidence.

    The quote must occur verbatim in the chunk; its offsets are recorded so a viewer can highlight it.
    """
    if chunk["doc_id"] != document["doc_id"]:
        raise ContractError(f"chunk {chunk['chunk_id']} does not belong to {document['doc_id']}")
    text = chunk["text"]
    quote = text if quote is None else quote
    start = text.find(quote) if quote else -1
    if start < 0:
        raise ContractError(f"quote not found verbatim in {chunk['chunk_id']}")
    locator = {"chunk_id": chunk["chunk_id"], "chunk_sha256": chunk["sha256"], "page": chunk["page"],
               "pages": chunk["pages"], "regions": chunk["regions"], "table_id": chunk.get("table_id"),
               "quote": quote, "quote_start": start, "quote_end": start + len(quote)}
    source = {"source_id": document["doc_id"], "sha256": document["sha256"]}
    return check("evidence", {"evidence_id": _digest("ev", [source, bundle, locator]), "kind": "document_span",
                              "source": source, "bundle": bundle, "locator": locator})


def evidence_from_record(record: dict[str, Any], bundle: dict[str, str], fields: list[str],
                         validate: bool = True) -> dict[str, Any]:
    """Evidence for named fields of one dataset record; every field must exist on the record."""
    missing = [field for field in fields if field not in record]
    if missing:
        raise ContractError(f"record {record['record_id']} has no fields {missing}")
    origin = record["source"]
    source = {"source_id": f"{origin['dataset_id']}/{origin['source_id']}", "sha256": origin["sha256"]}
    locator = {"record_id": record["record_id"], "file": origin["source_id"], "member": origin.get("member"),
               "row": origin["row"], "fields": sorted(fields)}
    return check("evidence", {"evidence_id": _digest("ev", [source, bundle, locator]), "kind": "dataset_row",
                              "source": source, "bundle": bundle, "locator": locator}, validate)


def claim_revision(profile: str, subject: dict[str, Any], property_name: str, qualifier: str, value: dict[str, Any],
                   context: dict[str, Any], evidence: list[str], origin: dict[str, str],
                   kind: str = "observation") -> dict[str, Any]:
    """A claim revision. ``subject`` needs entity_type, mention and key; entity_id may be None until resolved."""
    if kind not in CLAIM_KINDS:
        raise ContractError(f"unknown claim kind {kind!r}")
    subject = {"entity_id": None, **subject}
    logical = [profile, subject["entity_type"], subject["key"], property_name, qualifier, context]
    claim_id = _digest("cl", logical)
    revision = {"claim_id": claim_id, "profile": profile, "subject": subject, "property": property_name,
                "qualifier": qualifier, "value": value, "context": context, "kind": kind,
                "evidence": sorted(set(evidence)), "origin": origin}
    # Resolving the subject to a registry entity is a separate, reversible decision: it does not make a new revision.
    content = {k: v for k, v in revision.items() if k not in ("claim_id", "subject")}
    content["subject"] = {k: v for k, v in subject.items() if k != "entity_id"}
    revision["revision_id"] = _digest("cr", content)
    return check("claim", revision)


def entity(profile: str, entity_type: str, names: list[dict[str, Any]],
           identifiers: list[dict[str, str]] | None = None, key: str | None = None,
           evidence: list[str] | None = None, former_identifiers: list[dict[str, str]] | None = None,
           validate: bool = True) -> dict[str, Any]:
    """A registry entity. Its ID comes from its first identifier, or else from its type, scope and name key."""
    identifiers = identifiers or []
    if identifiers:
        basis: list[Any] = [entity_type, identifiers[0]["scheme"], identifiers[0]["value"]]
    elif key:
        basis = [entity_type, names[0].get("scope") if names else None, key]
    else:
        raise ContractError("an entity needs an identifier or a name key")
    record = {"entity_id": _digest("ent", basis), "entity_type": entity_type, "profile": profile,
              "identifiers": identifiers, "names": names}
    if evidence:
        record["evidence"] = sorted(set(evidence))
    if former_identifiers:
        record["former_identifiers"] = former_identifiers
    return check("entity", record, validate)
