"""Fetch, parse, check and link a mapped dataset into a versioned bundle of typed records and a property graph.

Rows stream from disk to disk; keys, nodes and cross-table references live in a temporary SQLite database,
so memory use does not grow with the number of rows. The bundle is staged and swapped in only when the
import stays within its error budget.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import operator
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any, Iterator
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..corpus.store import atomic_write_json, atomic_write_text, file_sha256
from .mapping import column_names
from .readers import iter_rows
from .values import ValueProblem, derive, parse_value, render

COMPARE = {"<": operator.lt, "<=": operator.le, "==": operator.eq, "!=": operator.ne, ">=": operator.ge, ">": operator.gt}
EXAMPLES = 5
JSON_TYPES = {"string": "string", "integer": "integer", "decimal": "number", "date": "string", "datetime": "string",
              "boolean": "boolean"}


class Findings:
    """Count findings by kind and keep a few examples of each."""

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.examples: dict[str, list[str]] = defaultdict(list)

    def add(self, kind: str, example: str) -> None:
        self.counts[kind] += 1
        if len(self.examples[kind]) < EXAMPLES:
            self.examples[kind].append(example)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def report(self) -> dict[str, Any]:
        return {kind: {"count": self.counts[kind], "examples": self.examples[kind]} for kind in sorted(self.counts)}


# --- sources ---------------------------------------------------------------------------------------------------

def raw_directory(mapping: dict[str, Any], root: Path) -> Path:
    return root / "data" / "raw" / mapping["dataset_id"]


def fetch(mapping: dict[str, Any], root: Path, refresh: bool = False) -> dict[str, dict[str, Any]]:
    """Resolve every source to a verified local file and record the snapshot (URL, bytes, SHA256, time)."""
    directory = raw_directory(mapping, root)
    directory.mkdir(parents=True, exist_ok=True)
    snapshot_path = directory / "snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8")) if snapshot_path.exists() else {"files": {}}
    allowed = set(mapping.get("allowed_hosts", []))
    resolved = {}
    for source in mapping["sources"]:
        source_id = source["source_id"]
        if "path" in source:
            path = (Path(mapping["_base"]) / source["path"]).resolve()
            if not path.is_file():
                raise ValueError(f"{source_id}: no such file {path}")
            entry = {"path": path.as_posix(), "bytes": path.stat().st_size, "sha256": file_sha256(path)}
        else:
            url = source["url"]
            suffix = Path(urlparse(url).path).suffix or ".bin"
            path = directory / f"{source_id}{suffix}"
            known = snapshot["files"].get(source_id)
            if not (path.is_file() and known and known.get("url") == url and not refresh
                    and file_sha256(path) == known["sha256"]):
                known = download(url, path, allowed)
            entry = known
        if "sha256" in source and entry["sha256"] != source["sha256"]:
            raise ValueError(f"{source_id}: SHA256 {entry['sha256']} differs from the pinned value; the publisher may "
                             "have released a new version, so review it and update the pin deliberately")
        snapshot["files"][source_id] = entry
        resolved[source_id] = {**entry, "local": path}
    atomic_write_json(snapshot_path, snapshot)
    return resolved


def download(url: str, target: Path, allowed: set[str]) -> dict[str, Any]:
    if urlparse(url).scheme != "https" or urlparse(url).hostname not in allowed:
        raise ValueError(f"Download host not in allowed_hosts {sorted(allowed)}: {url}")
    partial = target.with_name(target.name + ".partial")
    try:
        request = Request(url, headers={"User-Agent": "graph-builder-datasets/1"})
        with urlopen(request, timeout=600) as response, partial.open("wb") as stream:
            if urlparse(response.geturl()).hostname not in allowed:
                raise ValueError(f"Redirect left the allowed hosts: {response.geturl()}")
            last_modified = response.headers.get("Last-Modified")
            shutil.copyfileobj(response, stream, 1024 * 1024)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return {"url": url, "bytes": target.stat().st_size, "sha256": file_sha256(target), "last_modified": last_modified,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


# --- parsing ---------------------------------------------------------------------------------------------------

def is_withheld(value: Any, characters: list[str]) -> bool:
    return isinstance(value, str) and bool(value) and bool(characters) and set(value) <= set(characters)


def parse_row(table: dict[str, Any], row: dict[str, Any] | list[Any]) -> tuple[dict[str, Any], list[str]]:
    """Typed values in column order plus the names of withheld fields; raises ValueProblem when malformed."""
    columns = table["columns"]
    withheld_chars = table.get("withheld_chars", [])
    if isinstance(row, list) and len(row) != len(columns):
        raise ValueProblem(f"expected {len(columns)} columns, found {len(row)}")
    values: dict[str, Any] = {}
    withheld: list[str] = []
    for index, column in enumerate(columns):
        if isinstance(row, list):
            raw = row[index]
        else:
            name = column.get("source", column.get("name"))
            if name not in row:
                raise ValueProblem(f"missing column {name!r}")
            raw = row[name]
        parts = column["split"] if "split" in column else [column]
        stripped = raw.strip() if isinstance(raw, str) else raw
        if is_withheld(stripped, withheld_chars):
            for part in parts:
                values[part["name"]] = None
                withheld.append(part["name"])
            continue
        if "split" in column:
            if stripped and len(raw) != sum(part["width"] for part in parts):
                raise ValueProblem(f"{parts[0]['name']}: combined column has width {len(raw)}: {raw!r}")
            position = 0
            for part in parts:
                piece = raw[position:position + part["width"]] if stripped else ""
                position += part["width"]
                values[part["name"]] = typed(part, piece.strip())
        else:
            values[column["name"]] = typed(column, stripped)
        for part in parts:
            if part.get("required") and values[part["name"]] is None:
                raise ValueProblem(f"{part['name']}: required value is empty")
    return values, withheld


def typed(spec: dict[str, Any], raw: Any) -> Any:
    try:
        return parse_value(spec, raw)
    except ValueProblem as problem:
        raise ValueProblem(f"{spec['name']}: {problem}") from None


def row_checks(table_name: str, table: dict[str, Any], record: dict[str, Any], where: str) -> list[tuple[str, str, str]]:
    """Return (severity, name, message) for every failed range or compare check."""
    failures = []
    for check in table.get("checks", []):
        if check["check"] == "range":
            for field in check["fields"]:
                value = record.get(field)
                if value is not None and not check.get("min", value) <= value <= check.get("max", value):
                    failures.append((check["severity"], check["name"], f"{where}: {field}={value}"))
        elif check["check"] == "compare":
            left, right = record.get(check["left"]), record.get(check["right"])
            if left is not None and right is not None and not COMPARE[check["op"]](left, right):
                failures.append((check["severity"], check["name"],
                                 f"{where}: {check['left']}={left} {check['op']} {check['right']}={right} fails"))
    return failures


def skipped(spec: dict[str, Any], record: dict[str, Any]) -> bool:
    return any(record.get(field) in values for field, values in spec.get("skip_values", {}).items())


def node_properties(spec: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    properties = spec.get("properties", {})
    if isinstance(properties, list):
        properties = {name: name for name in properties}
    return {name: record.get(field) for name, field in properties.items()}


def evidence(record: dict[str, Any]) -> dict[str, Any]:
    source = record["source"]
    return {"record_id": record["record_id"], "source_id": source["source_id"], "sha256": source["sha256"],
            "member": source.get("member"), "row": source["row"]}


def run_import(mapping: dict[str, Any], root: Path, output: Path, refresh: bool = False) -> dict[str, Any]:
    """Run the whole import. Returns the summary; raises ValueError when errors exceed the budget."""
    files = fetch(mapping, root, refresh)
    max_errors = mapping.get("error_policy", {}).get("max_errors", 0)
    graph = mapping.get("graph", {"nodes": [], "edges": []})
    errors, warnings, skips = Findings(), Findings(), Counter()
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    database = None
    try:
        database = sqlite3.connect(staging / "work.sqlite")
        database.execute("CREATE TABLE keys (tbl TEXT, key TEXT, record_id TEXT, PRIMARY KEY (tbl, key))")
        database.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, label TEXT, body TEXT)")
        counts: Counter[str] = Counter()
        field_stats: dict[str, dict[str, Counter]] = defaultdict(lambda: {"null": Counter(), "withheld": Counter()})
        (staging / "records").mkdir()
        outputs = {name: (staging / "records" / f"{name}.jsonl").open("w", encoding="utf-8", newline="\n")
                   for name in mapping["tables"]}
        rejects = (staging / "rejects.jsonl").open("w", encoding="utf-8", newline="\n")
        nodes_by_table = defaultdict(list)
        for spec in graph.get("nodes", []):
            nodes_by_table[spec["table"]].append(spec)
        try:
            for source in mapping["sources"]:
                table_name = source["table"]
                table = mapping["tables"][table_name]
                local = files[source["source_id"]]
                for row_number, row in iter_rows(local["local"], source.get("member"), table["layout"]):
                    where = f"{source['source_id']} row {row_number}"
                    try:
                        values, withheld = parse_row(table, row)
                    except ValueProblem as problem:
                        errors.add("malformed_row", f"{where}: {problem}")
                        rejects.write(json.dumps({"source_id": source["source_id"], "row": row_number,
                                                  "problem": str(problem)}, ensure_ascii=False) + "\n")
                        continue
                    record = {**source.get("constants", {}), **values}
                    for field, spec in table.get("derived", {}).items():
                        record[field] = derive(spec, record)
                    record["withheld"] = withheld
                    record["source"] = {"dataset_id": mapping["dataset_id"], "source_id": source["source_id"],
                                        "sha256": local["sha256"], "member": source.get("member"), "row": row_number}
                    record_id = render(table["id"], {**record, "_source_id": source["source_id"], "_row": row_number})
                    if record_id is None:
                        errors.add("missing_record_id", where)
                        continue
                    record = {"record_id": record_id, "table": table_name, **record}
                    failures = row_checks(table_name, table, record, where)
                    if table.get("key"):
                        key = "|".join(str(record[field]) for field in table["key"])
                        try:
                            database.execute("INSERT INTO keys VALUES (?, ?, ?)", (table_name, key, record_id))
                        except sqlite3.IntegrityError:
                            failures.append(("error", "duplicate_key", f"{where}: {table['key']}={key}"))
                    if table.get("warn_withheld") and withheld:
                        failures.append(("warning", "withheld_fields", f"{where}: {', '.join(withheld)}"))
                    hard = [failure for failure in failures if failure[0] == "error"]
                    for severity, name, message in failures:
                        (errors if severity == "error" else warnings).add(name, message)
                    if hard:
                        rejects.write(json.dumps({"source_id": source["source_id"], "row": row_number,
                                                  "problem": "; ".join(m for _, _, m in hard)}, ensure_ascii=False) + "\n")
                        continue
                    for name in column_names(table):
                        if record.get(name) is None:
                            field_stats[table_name]["withheld" if name in withheld else "null"][name] += 1
                    outputs[table_name].write(json.dumps(record, ensure_ascii=False) + "\n")
                    counts[table_name] += 1
                    for spec in nodes_by_table[table_name]:
                        node_id = None if skipped(spec, record) else render(spec["id"], record)
                        if node_id is None:
                            skips[f"{spec['label']} node: missing or placeholder value"] += 1
                            continue
                        body = {"id": node_id, "label": spec["label"], **node_properties(spec, record),
                                "evidence": evidence(record)}
                        database.execute("INSERT OR IGNORE INTO nodes VALUES (?, ?, ?)",
                                         (node_id, spec["label"], json.dumps(body, ensure_ascii=False)))
                    if errors.total > max_errors:
                        raise ValueError(f"more than {max_errors} errors; first: {errors.report()}")
                database.commit()
        finally:
            for stream in outputs.values():
                stream.close()
            rejects.close()
        # Phase 2: cross-table references and edges, streaming the staged records again.
        edge_count: Counter[str] = Counter()
        with (staging / "edges.jsonl").open("w", encoding="utf-8", newline="\n") as edge_stream:
            for table_name, table in mapping["tables"].items():
                references = [check for check in table.get("checks", []) if check["check"] == "reference"]
                edges = [spec for spec in graph.get("edges", []) if spec["table"] == table_name]
                if not references and not edges:
                    continue
                for record in read_records(staging / "records" / f"{table_name}.jsonl"):
                    where = f"{record['source']['source_id']} row {record['source']['row']}"
                    for check in references:
                        value = record.get(check["field"])
                        if value is not None and not database.execute(
                                "SELECT 1 FROM keys WHERE tbl = ? AND key = ?", (check["table"], str(value))).fetchone():
                            (errors if check["severity"] == "error" else warnings).add(
                                check["name"], f"{where}: {check['field']}={value}")
                    for spec in edges:
                        if skipped(spec, record):
                            skips[f"{spec['type']} edge: placeholder value"] += 1
                            continue
                        source_id, target_id = render(spec["from"], record), render(spec["to"], record)
                        if source_id is None or target_id is None:
                            skips[f"{spec['type']} edge: missing value"] += 1
                            continue
                        if spec.get("not_self") and source_id == target_id:
                            skips[f"{spec['type']} edge: self link"] += 1
                            continue
                        missing = [node for node in (source_id, target_id) if not database.execute(
                            "SELECT 1 FROM nodes WHERE id = ?", (node,)).fetchone()]
                        if missing:
                            if spec.get("require_existing"):
                                skips[f"{spec['type']} edge: endpoint not in dataset"] += 1
                            else:
                                errors.add("edge_endpoint_missing", f"{where}: {spec['type']} {missing}")
                            continue
                        edge_stream.write(json.dumps({"source": source_id, "relation": spec["type"], "target": target_id,
                                                      "evidence": evidence(record)}, ensure_ascii=False) + "\n")
                        edge_count[spec["type"]] += 1
        if errors.total > max_errors:
            raise ValueError(f"{errors.total} errors exceed the budget of {max_errors}: {json.dumps(errors.report())[:2000]}")
        node_count: Counter[str] = Counter()
        with (staging / "nodes.jsonl").open("w", encoding="utf-8", newline="\n") as node_stream:
            for label, body in database.execute("SELECT label, body FROM nodes ORDER BY rowid"):
                node_stream.write(body + "\n")
                node_count[label] += 1
        database.close()
        database = None
        (staging / "work.sqlite").unlink()
        write_schemas(mapping, staging / "schemas")
        names = sorted(path.relative_to(staging).as_posix() for path in staging.rglob("*") if path.is_file())
        summary = {"dataset_id": mapping["dataset_id"], "title": mapping["title"], "license": mapping["license"],
                   "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "sources": {key: {k: v for k, v in value.items() if k != "local"} for key, value in files.items()},
                   "records": dict(sorted(counts.items())), "nodes": dict(sorted(node_count.items())),
                   "edges": dict(sorted(edge_count.items())), "skipped_links": dict(sorted(skips.items())),
                   "errors": errors.report(), "warnings": warnings.report(),
                   "null_fields": {table: {kind: dict(sorted(counter.items())) for kind, counter in stats.items()}
                                   for table, stats in sorted(field_stats.items())},
                   "outputs": {name: file_sha256(staging / name) for name in names}}
        atomic_write_json(staging / "summary.json", summary)
        atomic_write_text(staging / "SHA256SUMS", "".join(f"{file_sha256(staging / name)}  {name}\n"
                                                          for name in sorted([*names, "summary.json"])))
        if output.exists():
            if not (output / "summary.json").exists():
                raise ValueError(f"Refusing to replace {output}: it is not a dataset bundle")
            old = output.with_name(output.name + ".old")
            shutil.rmtree(old, ignore_errors=True)
            output.rename(old)
            staging.rename(output)
            shutil.rmtree(old, ignore_errors=True)
        else:
            staging.rename(output)
        return summary
    except BaseException:
        if database is not None:
            database.close()
        shutil.rmtree(staging, ignore_errors=True)
        raise


def read_records(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def write_schemas(mapping: dict[str, Any], directory: Path) -> None:
    """Write a JSON Schema per table describing the records this mapping produces."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, table in mapping["tables"].items():
        properties: dict[str, Any] = {"record_id": {"type": "string"}, "table": {"const": name},
                                      "withheld": {"type": "array", "items": {"type": "string"}},
                                      "source": {"type": "object"}}
        for column in table["columns"]:
            for part in column["split"] if "split" in column else [column]:
                properties[part["name"]] = {"type": [JSON_TYPES[part["type"]], "null"]}
        for field in table.get("derived", {}):
            properties[field] = {"type": ["string", "null"]}
        constants = {key for source in mapping["sources"] if source["table"] == name for key in source.get("constants", {})}
        for key in constants:
            properties.setdefault(key, {})
        atomic_write_json(directory / f"{name}.schema.json", {
            "$schema": "https://json-schema.org/draft/2020-12/schema", "title": f"{mapping['dataset_id']} {name} record",
            "type": "object", "additionalProperties": False, "required": sorted(properties), "properties": properties})


def validate_bundle(output: Path) -> list[str]:
    """Check digests, record schemas, unique record IDs and that every edge endpoint is a node."""
    from jsonschema import Draft202012Validator
    problems = []
    for line in (output / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if file_sha256(output / name) != digest:
            problems.append(f"{name}: SHA256 differs")
    for path in sorted((output / "records").glob("*.jsonl")):
        schema = json.loads((output / "schemas" / f"{path.stem}.schema.json").read_text(encoding="utf-8"))
        validator, seen = Draft202012Validator(schema), set()
        for number, record in enumerate(read_records(path), 1):
            for error in validator.iter_errors(record):
                problems.append(f"{path.name} line {number}: {error.json_path}: {error.message}")
            if record["record_id"] in seen:
                problems.append(f"{path.name} line {number}: duplicate record_id")
            seen.add(record["record_id"])
            if len(problems) > 50:
                return problems
    with sqlite3.connect(":memory:") as database:
        database.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY)")
        for node in read_records(output / "nodes.jsonl"):
            database.execute("INSERT INTO nodes VALUES (?)", (node["id"],))
        for number, edge in enumerate(read_records(output / "edges.jsonl"), 1):
            for end in (edge["source"], edge["target"]):
                if not database.execute("SELECT 1 FROM nodes WHERE id = ?", (end,)).fetchone():
                    problems.append(f"edges.jsonl line {number}: unknown node {end}")
    return problems
