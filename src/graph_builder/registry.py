"""Entity registry built from a published dataset bundle, and a conservative resolver (design §5.4, §5.7; FR-05, FR-16).

A registry config says which dataset nodes become which entity types, with which identifier scheme, which names
(scoped by a linked node, for example a lease) and which edges carry former identifiers. Nothing here knows
about wells: BSEE is one config (configs/registry/bsee_wells.registry.json).

Resolution never merges on similarity. An exact identifier or a former identifier resolves; a name resolves only
inside a scope and only when exactly one entity has it there; an unscoped name returns candidates for review.

    python -m graph_builder.registry build --config configs/registry/bsee_wells.registry.json
    python -m graph_builder.registry resolve --config ... "012032016500"
    python -m graph_builder.registry resolve --config ... "001" --type Wellbore --scope G01234
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any

from .contracts import bundle_ref, entity, evidence_from_record
from .corpus.store import atomic_write_json, atomic_write_text, file_sha256
from .publication import current_release, publish

VALIDATE_FIRST = 50  # schema-check the first records of each kind; the builders are deterministic after that


def name_key(text: Any) -> str:
    """Case, spacing and punctuation folded: "OCS-G 1234" and "ocs g1234" share a key."""
    return re.sub(r"[^A-Z0-9]", "", str(text).upper())


def identifier_value(mention: str, rule: dict[str, Any]) -> str | None:
    """Apply a scheme's match rule to a mention; None if it cannot be that kind of identifier."""
    value = re.sub(r"\D", "", mention) if rule.get("strip") == "non_digits" else name_key(mention)
    return value if value and ("length" not in rule or len(value) == rule["length"]) else None


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    for key in ("registry", "profile", "dataset", "output", "entities"):
        if key not in config:
            raise ValueError(f"{path}: missing {key}")
    for spec in config["entities"]:
        for key in ("label", "entity_type", "identifier"):
            if key not in spec:
                raise ValueError(f"{path}: entity spec needs {key}")
    return config


def build(config: dict[str, Any], root: Path = Path(".")) -> dict[str, Any]:
    """Build the registry from the dataset's current release and publish it as a release of its own."""
    dataset = root / config["dataset"]
    release = current_release(dataset)
    bundle = bundle_ref(dataset, "dataset_release")
    dataset_id = json.loads((release / "summary.json").read_text(encoding="utf-8"))["dataset_id"]
    specs = {spec["label"]: spec for spec in config["entities"]}
    scope_edges = {name["scope"]["edge"] for spec in specs.values() for name in spec.get("names", []) if "scope" in name}
    former_edges = {former["edge"]: former["scheme"] for spec in specs.values()
                    for former in spec.get("former_identifiers", [])}
    scope_properties = {name["scope"]["edge"]: name["scope"]["property"] for spec in specs.values()
                        for name in spec.get("names", []) if "scope" in name}

    nodes: dict[str, dict[str, Any]] = {}
    with (release / "nodes.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            node = json.loads(line)
            nodes[node["id"]] = node
    scopes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    formers: dict[str, list[tuple[str, str]]] = defaultdict(list)
    with (release / "edges.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            edge = json.loads(line)
            if edge["relation"] in scope_edges:
                target = nodes.get(edge["target"], {})
                value = target.get(scope_properties[edge["relation"]])
                if value is not None:
                    scopes[edge["source"]].append((edge["relation"], str(value)))
            elif edge["relation"] in former_edges:
                formers[edge["source"]].append((former_edges[edge["relation"]], edge["target"].split(":", 1)[1]))

    staging = Path(tempfile.mkdtemp(prefix=".registry-", dir=_output_parent(root, config)))
    counts: Counter[str] = Counter()
    seen = Counter()
    try:
        with (staging / "entities.jsonl").open("w", encoding="utf-8", newline="\n") as entities, \
                (staging / "evidence.jsonl").open("w", encoding="utf-8", newline="\n") as evidence_out:
            for node in nodes.values():
                spec = specs.get(node["label"])
                if spec is None:
                    continue
                identifier = spec["identifier"]
                value = node.get(identifier["property"])
                if value in (None, ""):
                    counts[f"{spec['entity_type']} skipped: no identifier"] += 1
                    continue
                names = []
                for name_spec in spec.get("names", []):
                    # A name is one property, or several joined by spaces (for example name + sidetrack suffix).
                    parts = [node.get(p) for p in name_spec.get("properties", [name_spec.get("property")])]
                    if any(part in (None, "") for part in parts):
                        continue
                    text = " ".join(str(part) for part in parts)
                    relation = name_spec.get("scope", {}).get("edge")
                    for scope in sorted({s for r, s in scopes.get(node["id"], []) if r == relation}) or [None]:
                        names.append({"text": str(text), "language": spec.get("language", "en"), "scope": scope})
                if not names:
                    names = [{"text": str(value), "language": "und", "scope": None}]
                record = {"record_id": node["evidence"]["record_id"], identifier["property"]: value,
                          "source": {**node["evidence"], "dataset_id": dataset_id}}
                check = seen[spec["entity_type"]] < VALIDATE_FIRST
                seen[spec["entity_type"]] += 1
                proof = evidence_from_record(record, bundle, [identifier["property"]], validate=check)
                former = [{"scheme": scheme, "value": old} for scheme, old in sorted(set(formers.get(node["id"], [])))]
                item = entity(config["profile"], spec["entity_type"], names,
                              [{"scheme": identifier["scheme"], "value": str(value)}],
                              evidence=[proof["evidence_id"]], former_identifiers=former, validate=check)
                entities.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
                evidence_out.write(json.dumps(proof, ensure_ascii=False, sort_keys=True) + "\n")
                counts[spec["entity_type"]] += 1
                counts["former identifiers"] += len(former)
                counts["scoped names"] += sum(1 for n in names if n["scope"])
        summary = {"registry": config["registry"], "profile": config["profile"], "dataset": bundle,
                   "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "counts": dict(sorted(counts.items())),
                   "schemes": {spec["identifier"]["scheme"]: spec["identifier"].get("match", {})
                               for spec in specs.values()}}
        atomic_write_json(staging / "summary.json", summary)
        atomic_write_text(staging / "SHA256SUMS", "".join(f"{file_sha256(staging / name)}  {name}\n"
                                                          for name in ("entities.jsonl", "evidence.jsonl",
                                                                       "summary.json")))
        release_path = publish(staging, root / config["output"], marker="summary.json",
                               digest=file_sha256(staging / "SHA256SUMS"))
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {**summary, "release": str(release_path)}


def _output_parent(root: Path, config: dict[str, Any]) -> Path:
    parent = (root / config["output"]).parent
    parent.mkdir(parents=True, exist_ok=True)
    return parent


class Registry:
    """In-memory indexes over one registry release."""

    def __init__(self, release: Path):
        summary = json.loads((release / "summary.json").read_text(encoding="utf-8"))
        self.schemes: dict[str, dict[str, Any]] = summary["schemes"]
        self.identifiers: dict[tuple[str, str], str] = {}
        self.former: dict[tuple[str, str], str] = {}
        self.names: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.scoped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        self.types: dict[str, str] = {}
        with (release / "entities.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                item = json.loads(line)
                entity_id = item["entity_id"]
                self.types[entity_id] = item["entity_type"]
                for ident in item["identifiers"]:
                    self.identifiers[(ident["scheme"], ident["value"])] = entity_id
                for ident in item.get("former_identifiers", []):
                    self.former.setdefault((ident["scheme"], ident["value"]), entity_id)
                for name in item["names"]:
                    entry = {"entity_id": entity_id, "entity_type": item["entity_type"], "name": name["text"],
                             "scope": name["scope"], "scope_key": name_key(name["scope"]) if name["scope"] else None}
                    self.names[name_key(name["text"])].append(entry)
                    if entry["scope_key"]:
                        self.scoped[(name_key(name["text"]), entry["scope_key"])].append(entry)

    @classmethod
    def load(cls, output: Path) -> "Registry":
        return cls(current_release(output))

    def resolve(self, mention: str, entity_type: str | None = None, scope: str | None = None) -> dict[str, Any]:
        """Resolve a mention: "resolved" (with how), "needs_review" (candidates), "ambiguous" or "unknown"."""
        for scheme, rule in self.schemes.items():
            value = identifier_value(mention, rule)
            if value is None:
                continue
            for table, via in ((self.identifiers, "identifier"), (self.former, "former_identifier")):
                entity_id = table.get((scheme, value))
                if entity_id and (entity_type is None or self.types[entity_id] == entity_type):
                    return {"status": "resolved", "entity_id": entity_id, "via": via, "scheme": scheme}
        if scope is not None:
            scoped = [c for c in self.scoped.get((name_key(mention), name_key(scope)), [])
                      if entity_type is None or c["entity_type"] == entity_type]
            if len({c["entity_id"] for c in scoped}) == 1:
                return {"status": "resolved", "entity_id": scoped[0]["entity_id"], "via": "scoped_name"}
            if scoped:
                return {"status": "ambiguous", "candidates": scoped[:20]}
            return {"status": "unknown", "candidates": []}
        candidates = [c for c in self.names.get(name_key(mention), [])
                      if entity_type is None or c["entity_type"] == entity_type]
        if candidates:
            # A name without a scope is never identity, even when only one entity carries it.
            return {"status": "needs_review", "candidates": candidates[:20]}
        return {"status": "unknown", "candidates": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m graph_builder.registry", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("build", "resolve"))
    parser.add_argument("mention", nargs="?")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--type")
    parser.add_argument("--scope")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "build":
            summary = build(config, args.root)
            print(json.dumps({k: summary[k] for k in ("counts", "release")}, indent=1))
        else:
            if not args.mention:
                raise ValueError("resolve needs a mention")
            registry = Registry.load(args.root / config["output"])
            print(json.dumps(registry.resolve(args.mention, args.type, args.scope), indent=1, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
