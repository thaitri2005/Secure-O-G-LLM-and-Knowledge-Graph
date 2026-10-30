"""Load the closed YAML schema or EDC two-column CSV and emit EDC CSV."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from kgbuilder.core.config import KgbError
from kgbuilder.core.text import norm_pred


@dataclass(frozen=True)
class Relation:
    name: str
    definition: str
    inverse_of: str | None = None
    start: tuple[str, ...] = ()
    end: tuple[str, ...] = ()


@dataclass(frozen=True)
class SchemaSpec:
    relations: dict[str, Relation]
    kind: Literal["yaml", "csv"]
    source: Path

    def temporal_relations(self) -> set[str]:
        return {name for name, relation in self.relations.items() if relation.start or relation.end}

    def trigger_index(self) -> dict[str, tuple[str, str]]:
        result = {}
        for name, relation in self.relations.items():
            for trigger in relation.start:
                key = norm_pred(trigger)
                if key in result: raise KgbError(2, f"duplicate temporal trigger: {trigger}")
                result[key] = (name, "start")
            for trigger in relation.end:
                key = norm_pred(trigger)
                if key in result: raise KgbError(2, f"duplicate temporal trigger: {trigger}")
                result[key] = (name, "end")
        return result


def _bad(msg: str):
    raise KgbError(2, msg)


def load_schema(path: Path) -> SchemaSpec:
    """Validate and load a YAML or EDC CSV schema."""
    path = Path(path)
    if not path.exists(): _bad(f"schema: file does not exist: {path}")
    if path.suffix.lower() == ".csv":
        relations = {}
        try:
            with path.open("r", encoding="utf-8", newline="") as fh:
                for number, row in enumerate(csv.reader(fh), 1):
                    if len(row) != 2 or not row[0].strip() or not row[1].strip(): _bad(f"schema CSV row {number}: expected two non-empty columns")
                    if row[0] in relations: _bad(f"schema CSV duplicate relation: {row[0]}")
                    relations[row[0]] = Relation(row[0], row[1])
        except OSError as exc: _bad(f"schema: {exc}")
        return SchemaSpec(relations, "csv", path)
    try: data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc: _bad(f"schema YAML: {exc}")
    if data.get("version") != 1 or not isinstance(data.get("relations"), dict): _bad("schema YAML requires version: 1 and relations")
    relations = {}
    for name, value in data["relations"].items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name): _bad(f"invalid relation name: {name}")
        if not isinstance(value, dict): _bad(f"relation {name}: expected mapping")
        definition = value.get("definition")
        if not isinstance(definition, str) or not 10 <= len(definition) <= 500: _bad(f"relation {name}: definition must be 10..500 characters")
        inverse = value.get("inverse_of")
        temporal = value.get("temporal") or {}
        start, end = tuple(temporal.get("start", ())), tuple(temporal.get("end", ()))
        if not all(isinstance(x, str) and 1 <= len(x) <= 60 for x in (*start, *end)): _bad(f"relation {name}: invalid trigger")
        relations[name] = Relation(name, definition, inverse, start, end)
    for name, relation in relations.items():
        if relation.inverse_of is not None and (relation.inverse_of not in relations or relation.inverse_of == name): _bad(f"relation {name}: bad inverse_of")
    for name, relation in relations.items():
        if relation.inverse_of is not None and relations[relation.inverse_of].inverse_of is not None:
            _bad(f"relation {name}: inverse_of must point to a non-inverse relation")
    spec = SchemaSpec(relations, "yaml", path)
    spec.trigger_index()
    return spec


def write_edc_csv(schema: SchemaSpec, path: Path) -> None:
    """Write every schema relation to EDC's headerless CSV format."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        for relation in schema.relations.values(): writer.writerow([relation.name, relation.definition])
