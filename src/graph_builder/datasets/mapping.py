"""Load and validate a dataset mapping: sources, table layouts, typed columns, checks and graph rules."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .values import TYPES

ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
FILE_TYPES = {"csv", "xlsx", "jsonl"}
DERIVATIONS = {"slice", "strip_leading_zeros", "digits", "upper", "lower", "template"}
CHECKS = {"range", "compare", "reference"}
OPERATORS = {"<", "<=", "==", "!=", ">=", ">"}


def load_mapping(path: Path) -> dict[str, Any]:
    mapping = json.loads(path.read_text(encoding="utf-8"))
    validate_mapping(mapping)
    mapping["_base"] = str(path.resolve().parent)
    return mapping


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"Invalid mapping: {message}")


def column_names(table: dict[str, Any]) -> list[str]:
    names = []
    for column in table["columns"]:
        names.extend(part["name"] for part in column["split"]) if "split" in column else names.append(column["name"])
    return names


def validate_column(spec: dict[str, Any], where: str) -> None:
    require(isinstance(spec, dict) and isinstance(spec.get("name"), str) and ID.fullmatch(spec["name"]) is not None,
            f"{where}: column needs a lowercase name")
    require(spec.get("type") in TYPES, f"{where}.{spec['name']}: type must be one of {sorted(TYPES)}")
    if spec["type"] in ("date", "datetime"):
        require(isinstance(spec.get("formats"), list) and spec["formats"], f"{where}.{spec['name']}: dates need formats")


def validate_mapping(mapping: Any) -> None:
    require(isinstance(mapping, dict), "top level must be an object")
    for key in ("dataset_id", "title", "license", "sources", "tables"):
        require(key in mapping, f"missing {key}")
    require(isinstance(mapping["dataset_id"], str) and ID.fullmatch(mapping["dataset_id"]) is not None,
            "dataset_id must be lowercase letters, digits, _ or -")
    require(isinstance(mapping["license"], dict) and set(mapping["license"]) == {"id", "url"}, "license needs id and url")
    tables = mapping["tables"]
    require(isinstance(tables, dict) and tables, "tables must be a nonempty object")
    for name, table in tables.items():
        require(ID.fullmatch(name) is not None, f"table name {name!r}")
        layout = table.get("layout", {})
        require(isinstance(layout, dict) and layout.get("type") in FILE_TYPES, f"{name}: layout.type in {sorted(FILE_TYPES)}")
        require(isinstance(table.get("columns"), list) and table["columns"], f"{name}: columns must be a nonempty list")
        for column in table["columns"]:
            if "split" in column:
                require(isinstance(column["split"], list) and column["split"], f"{name}: split needs parts")
                for part in column["split"]:
                    validate_column(part, name)
                    require(type(part.get("width")) is int and part["width"] > 0, f"{name}.{part['name']}: split width")
            else:
                validate_column(column, name)
        names = column_names(table) + list(table.get("derived", {}))
        require(len(names) == len(set(names)), f"{name}: duplicate field names")
        require(isinstance(table.get("id"), str) and "{" in table["id"], f"{name}: id must be a template such as 'x:{{field}}'")
        for field, spec in table.get("derived", {}).items():
            require(ID.fullmatch(field) is not None and spec.get("op") in DERIVATIONS, f"{name}.{field}: derivation")
        for field in table.get("key", []):
            require(field in names, f"{name}: key field {field} is not a column")
        for check in table.get("checks", []):
            require(check.get("check") in CHECKS and check.get("severity") in ("error", "warning")
                    and isinstance(check.get("name"), str), f"{name}: checks need check, severity and name")
            if check["check"] == "compare":
                require(check.get("op") in OPERATORS, f"{name}: compare op")
            if check["check"] == "reference":
                require(check.get("table") in tables and len(tables[check["table"]].get("key", [])) == 1,
                        f"{name}: reference needs a table with a one-field key")
    sources = mapping["sources"]
    require(isinstance(sources, list) and sources, "sources must be a nonempty list")
    seen = set()
    for source in sources:
        require(isinstance(source, dict) and ID.fullmatch(source.get("source_id", "")) is not None
                and source["source_id"] not in seen, "source_id must be unique and lowercase")
        seen.add(source["source_id"])
        require(source.get("table") in tables, f"{source['source_id']}: unknown table")
        require(("url" in source) != ("path" in source), f"{source['source_id']}: give exactly one of url or path")
        if "sha256" in source:
            require(re.fullmatch(r"[a-f0-9]{64}", source["sha256"]) is not None, f"{source['source_id']}: sha256")
    for node in mapping.get("graph", {}).get("nodes", []):
        require(node.get("table") in tables and isinstance(node.get("label"), str) and "{" in node.get("id", ""),
                "graph nodes need label, table and an id template")
    for edge in mapping.get("graph", {}).get("edges", []):
        require(edge.get("table") in tables and isinstance(edge.get("type"), str)
                and "{" in edge.get("from", "") and "{" in edge.get("to", ""), "graph edges need type, table, from, to")
    policy = mapping.get("error_policy", {"max_errors": 0})
    require(type(policy.get("max_errors")) is int and policy["max_errors"] >= 0, "error_policy.max_errors")
