"""Download, verify and normalize BSEE Data Center well files into typed JSONL records with row provenance."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import shutil
from typing import Any, Iterator
import zipfile

from .bsee_layouts import LAYOUTS, field_names, parse_row
from .sources import DOC_ID, check_url, open_https, project_root, sha256, write_json, write_text

HOST = "www.data.bsee.gov"
MAX_MEMBER_BYTES = 200 * 1024 * 1024
DATUMS = {"NAD27", "NAD83"}
OUTPUTS = {"borehole": "boreholes.jsonl", "api_change": "api_changes.jsonl", "well": "wells.jsonl"}
EXAMPLES = 5


def load_dataset(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or {"dataset_id", "title", "landing_page", "license", "files"} - config.keys():
        raise ValueError("Dataset config needs dataset_id, title, landing_page, license and files")
    if not isinstance(config["dataset_id"], str) or not DOC_ID.fullmatch(config["dataset_id"]):
        raise ValueError(f"Invalid dataset_id: {config['dataset_id']!r}")
    check_url(config["landing_page"], HOST)
    if not isinstance(config["license"], dict) or set(config["license"]) != {"id", "url"}:
        raise ValueError("License must have an id and URL")
    if not isinstance(config["files"], list) or not config["files"]:
        raise ValueError("Dataset config must list at least one file")
    seen = set()
    for file in config["files"]:
        if not isinstance(file, dict) or {"file_id", "table", "region", "url", "member"} - file.keys():
            raise ValueError("Dataset file entry has missing fields")
        if not isinstance(file["file_id"], str) or not DOC_ID.fullmatch(file["file_id"]) or file["file_id"] in seen:
            raise ValueError(f"Invalid or duplicate file_id: {file['file_id']!r}")
        seen.add(file["file_id"])
        if file["table"] not in LAYOUTS:
            raise ValueError(f"{file['file_id']}: table must be one of {sorted(LAYOUTS)}")
        if file["table"] == "borehole" and file.get("datum") not in DATUMS:
            raise ValueError(f"{file['file_id']}: borehole files need a coordinate datum in {sorted(DATUMS)}")
        check_url(file["url"], HOST)
        if not isinstance(file["member"], str) or not file["member"] or "/" in file["member"] or "\\" in file["member"]:
            raise ValueError(f"{file['file_id']}: member must be a plain file name inside the ZIP")
    return config


def raw_directory(root: Path, config: dict[str, Any]) -> Path:
    return root / "data" / "raw" / config["dataset_id"]


def read_snapshot(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    path = raw_directory(root, config) / "snapshot.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"files": {}}


def check_download(path: Path, file: dict[str, Any], expected: dict[str, Any] | None) -> tuple[int, str]:
    """Verify size, digest, optional pin and the expected ZIP member; return size and digest."""
    size, digest = path.stat().st_size, sha256(path)
    if expected and (size != expected["bytes"] or digest != expected["sha256"]):
        raise ValueError(f"{file['file_id']}: size or SHA256 differs from the recorded snapshot")
    if "sha256" in file and (digest != file["sha256"] or size != file.get("bytes", size)):
        raise ValueError(f"{file['file_id']}: download differs from the pinned SHA256; BSEE may have published a new "
                         "version, so review it and update the pin deliberately")
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo(file["member"]) if file["member"] in archive.namelist() else None
        if info is None or info.file_size > MAX_MEMBER_BYTES:
            raise ValueError(f"{file['file_id']}: ZIP must contain {file['member']} below {MAX_MEMBER_BYTES} bytes")
    return size, digest


def fetch_dataset(config: dict[str, Any], root: Path, refresh: bool = False) -> list[dict[str, Any]]:
    """Download each file once, record a snapshot, and verify cached copies against it."""
    directory = raw_directory(root, config)
    directory.mkdir(parents=True, exist_ok=True)
    snapshot = read_snapshot(root, config)
    results = []
    for file in config["files"]:
        path = directory / f"{file['file_id']}.zip"
        known = snapshot["files"].get(file["file_id"])
        if path.exists() and known and known["url"] == file["url"] and not refresh:
            check_download(path, file, known)
            results.append({"file_id": file["file_id"], **known, "cached": True})
            continue
        partial = path.with_suffix(".zip.part")
        try:
            with open_https(file["url"], HOST) as response, partial.open("wb") as stream:
                last_modified = response.headers.get("Last-Modified")
                for block in iter(lambda: response.read(1024 * 1024), b""):
                    stream.write(block)
            size, digest = check_download(partial, file, None)
            partial.replace(path)
        except zipfile.BadZipFile:
            raise ValueError(f"{file['file_id']}: download is not a ZIP archive") from None
        finally:
            partial.unlink(missing_ok=True)
        snapshot["files"][file["file_id"]] = known = {
            "url": file["url"], "bytes": size, "sha256": digest, "last_modified": last_modified,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        write_json(directory / "snapshot.json", snapshot)
        results.append({"file_id": file["file_id"], **known, "cached": False})
    return results


def read_rows(path: Path, member: str) -> Iterator[list[str]]:
    with zipfile.ZipFile(path) as archive, archive.open(member) as stream:
        yield from csv.reader(io.TextIOWrapper(stream, encoding="utf-8", newline=""), strict=True)


class Examples:
    """Count findings by kind and keep a few examples of each for the summary."""

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.examples: dict[str, list[str]] = defaultdict(list)

    def add(self, kind: str, example: str) -> None:
        self.counts[kind] += 1
        if len(self.examples[kind]) < EXAMPLES:
            self.examples[kind].append(example)

    def report(self) -> dict[str, Any]:
        return {kind: {"count": self.counts[kind], "examples": self.examples[kind]} for kind in sorted(self.counts)}


def parse_dataset(config: dict[str, Any], root: Path) -> tuple[dict[str, list[dict[str, Any]]], Examples, Examples]:
    """Parse every snapshot file into typed records, then apply cross-record checks."""
    snapshot = read_snapshot(root, config)
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    errors, warnings = Examples(), Examples()
    for file in config["files"]:
        known = snapshot["files"].get(file["file_id"])
        if not known:
            raise ValueError(f"{file['file_id']}: not fetched; run the fetch command first")
        path = raw_directory(root, config) / f"{file['file_id']}.zip"
        check_download(path, file, known)
        table = file["table"]
        for row_number, row in enumerate(read_rows(path, file["member"]), 1):
            try:
                values, withheld = parse_row(LAYOUTS[table], row)
            except ValueError as error:
                errors.add("malformed_row", f"{file['file_id']} row {row_number}: {error}")
                continue
            api = values["api_well_number"]
            record = {"record_id": f"bsee:borehole:{api}" if table == "borehole" else f"bsee:{file['file_id']}:{row_number}",
                      "table": table, "region": file["region"], **values}
            if table == "borehole":
                record["well_api10"] = api[:10]
                record["coordinate_datum"] = file["datum"]
            record["withheld"] = withheld
            record["source"] = {"dataset_id": config["dataset_id"], "file_id": file["file_id"], "url": file["url"],
                                "sha256": known["sha256"], "member": file["member"], "row": row_number}
            records[table].append(record)
    check_records(records, errors, warnings)
    records["well"] = derive_wells(records["borehole"], records["api_change"], warnings)
    return records, errors, warnings


def check_records(records: dict[str, list[dict[str, Any]]], errors: Examples, warnings: Examples) -> None:
    seen: dict[str, str] = {}
    for record in records["borehole"]:
        where = f"{record['source']['file_id']} row {record['source']['row']} ({record['api_well_number']})"
        if record["api_well_number"] in seen:
            errors.add("duplicate_api_well_number", f"{where} repeats {seen[record['api_well_number']]}")
        seen.setdefault(record["api_well_number"], where)
        for prefix in ("surface", "bottom"):
            latitude, longitude = record[f"{prefix}_latitude"], record[f"{prefix}_longitude"]
            if (latitude is not None and not -90 <= latitude <= 90) or (longitude is not None and not -180 <= longitude <= 180):
                errors.add("coordinate_out_of_range", f"{where}: {prefix} {latitude}, {longitude}")
        if record["bh_total_md_ft"] is not None and record["tvd_ft"] is not None and record["tvd_ft"] > record["bh_total_md_ft"]:
            warnings.add("tvd_exceeds_md", where)
        if record["spud_date"] and record["total_depth_date"] and record["spud_date"] > record["total_depth_date"]:
            warnings.add("spud_after_total_depth_date", where)
        if record["withheld"]:
            warnings.add("withheld_fields", f"{where}: {', '.join(record['withheld'])}")
    for record in records["api_change"]:
        if record["api_well_number"] not in seen:
            warnings.add("api_change_unknown_borehole", f"{record['record_id']} ({record['api_well_number']})")


def derive_wells(boreholes: list[dict[str, Any]], changes: list[dict[str, Any]], warnings: Examples) -> list[dict[str, Any]]:
    """Group boreholes (12-digit API) into surface wells (first 10 digits) as a reference list for entity resolution."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for borehole in boreholes:
        groups[borehole["well_api10"]].append(borehole)
    previous: dict[str, set[str]] = defaultdict(set)
    for change in changes:
        if change["previous_api_number"]:
            previous[change["api_well_number"]].add(change["previous_api_number"])
    wells = []
    for api10 in sorted(groups):
        members = sorted(groups[api10], key=lambda record: record["api_well_number"])
        regions = sorted({record["region"] for record in members})
        locations = sorted({(record["surface_area_code"], record["surface_block_number"]) for record in members},
                           key=lambda location: tuple(part or "" for part in location))
        if len(regions) > 1 or len(locations) > 1:
            warnings.add("well_with_several_surface_locations", f"{api10}: {regions} {locations}")
        wells.append({
            "record_id": f"bsee:well:{api10}", "table": "well", "well_api10": api10, "regions": regions,
            "surface_locations": [{"area_code": area, "block_number": block} for area, block in locations],
            "boreholes": [{key: record[key] for key in ("api_well_number", "well_name", "well_name_suffix",
                                                         "surface_lease_number", "status_code")} for record in members],
            "previous_api_numbers": sorted(set().union(*(previous[record["api_well_number"]] for record in members))),
            "source_record_ids": [record["record_id"] for record in members]})
    return wells


def write_outputs(config: dict[str, Any], root: Path, output: Path, records: dict[str, list[dict[str, Any]]],
                  warnings: Examples) -> dict[str, Any]:
    """Stage the complete bundle, then replace a previous bundle of this command only."""
    if output.exists() and not (output / "summary.json").exists():
        raise ValueError(f"Refusing to replace {output}: it is not a BSEE bundle")
    staging = output.with_name(output.name + ".partial")
    shutil.rmtree(staging, ignore_errors=True)
    for table, name in OUTPUTS.items():
        write_text(staging / name, "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records[table]))
    boreholes = records["borehole"]
    summary = {
        "dataset_id": config["dataset_id"], "title": config["title"], "landing_page": config["landing_page"],
        "catalog_page": config.get("catalog_page"), "license": config["license"],
        "snapshot": read_snapshot(root, config)["files"],
        "counts": {table: dict(sorted(Counter(record["region"] for record in records[table]).items()))
                   for table in ("borehole", "api_change")} | {"well": len(records["well"])},
        "codes": {key: dict(Counter(record[key] for record in boreholes).most_common())
                  for key in ("status_code", "type_code", "well_class_code", "district_code")},
        "withheld_fields": dict(Counter(name for record in boreholes for name in record["withheld"]).most_common()),
        "warnings": warnings.report(),
        "outputs": {name: sha256(staging / name) for name in OUTPUTS.values()},
    }
    write_json(staging / "summary.json", summary)
    names = sorted([*OUTPUTS.values(), "summary.json"])
    write_text(staging / "SHA256SUMS", "".join(f"{sha256(staging / name)}  {name}\n" for name in names))
    if output.exists():
        shutil.rmtree(output)
    staging.replace(output)
    return summary


def validate_outputs(output: Path) -> list[str]:
    """Check manifest digests, JSON schemas, unique record IDs and references between the three files."""
    from jsonschema import Draft202012Validator
    schemas = Path(__file__).resolve().parents[3] / "schemas"
    errors = []
    for line in (output / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if sha256(output / name) != digest:
            errors.append(f"{name}: SHA256 differs from SHA256SUMS")
    ids: dict[str, set[str]] = {}
    for table, name in OUTPUTS.items():
        validator = Draft202012Validator(json.loads((schemas / f"bsee_{table}.schema.json").read_text(encoding="utf-8")))
        ids[table] = set()
        for number, line in enumerate((output / name).read_text(encoding="utf-8").splitlines(), 1):
            record = json.loads(line)
            for error in validator.iter_errors(record):
                errors.append(f"{name} line {number}: {error.json_path}: {error.message}")
            if record.get("record_id") in ids[table]:
                errors.append(f"{name} line {number}: duplicate record_id {record.get('record_id')}")
            ids[table].add(record.get("record_id"))
            if table == "well" and not set(record.get("source_record_ids", [])) <= ids["borehole"]:
                errors.append(f"{name} line {number}: unknown borehole in source_record_ids")
    if sum(len(json.loads(line)["source_record_ids"]) for line in (output / OUTPUTS["well"]).read_text(encoding="utf-8").splitlines()) != len(ids["borehole"]):
        errors.append("wells.jsonl does not account for every borehole exactly once")
    return errors


def show(output: Path, api: str) -> list[dict[str, Any]]:
    digits = "".join(character for character in api if character.isdigit())
    if len(digits) < 10:
        raise ValueError("Give at least the first 10 digits of an API well number")
    matches = []
    for table in ("well", "borehole", "api_change"):
        for line in (output / OUTPUTS[table]).read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            key = record["well_api10"] if table == "well" else record["api_well_number"]
            if key.startswith(digits[:12]) or digits.startswith(key):
                matches.append(record)
    return matches


def report(summary: dict[str, Any], errors: Examples) -> None:
    for table, counts in summary["counts"].items():
        print(f"{table}: {counts}")
    for kind, finding in summary["warnings"].items():
        print(f"WARNING {kind}: {finding['count']} (e.g. {finding['examples'][0]})")
    for kind, finding in errors.report().items():
        for example in finding["examples"]:
            print(f"ERROR {kind}: {example}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fetch", "parse", "validate", "run", "show"))
    parser.add_argument("--config", type=Path, default=Path("configs/datasets/bsee_wells.json"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--refresh", action="store_true", help="download again even when a verified snapshot exists")
    parser.add_argument("--api", help="API well number (10 or 12 digits) for the show command")
    args = parser.parse_args()
    try:
        config = load_dataset(args.config)
        root = project_root(args.config)
        output = args.output or root / "data" / "processed" / "local" / config["dataset_id"]
        if args.command == "show":
            print(json.dumps(show(output, args.api or ""), ensure_ascii=False, indent=2))
            return 0
        if args.command in {"fetch", "run"}:
            for result in fetch_dataset(config, root, args.refresh):
                state = "verified cached" if result["cached"] else "downloaded"
                print(f"{result['file_id']}: {state}; bytes={result['bytes']}; sha256={result['sha256']}; "
                      f"last_modified={result['last_modified']}", flush=True)
        if args.command in {"parse", "run"}:
            records, errors, warnings = parse_dataset(config, root)
            if errors.counts:
                report({"counts": {}, "warnings": warnings.report()}, errors)
                print(f"FAIL: {sum(errors.counts.values())} malformed or inconsistent records; no output written")
                return 1
            report(write_outputs(config, root, output, records, warnings), errors)
        if args.command in {"validate", "run"}:
            problems = validate_outputs(output)
            for problem in problems[:20]:
                print(f"ERROR {problem}")
            print(f"{'FAIL' if problems else 'PASS'}: {output}; {len(problems)} errors")
            return 1 if problems else 0
        return 0
    except (OSError, ValueError, KeyError, csv.Error, zipfile.BadZipFile) as error:
        print(f"FAIL: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
