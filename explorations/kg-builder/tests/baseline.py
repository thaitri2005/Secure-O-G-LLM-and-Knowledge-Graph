"""Capture and compare the immutable pre-extractor routing mock demonstration baseline."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT_ROOT / "tests/fixtures/baselines/sentence_grounding"
FIXTURE_V1 = PROJECT_ROOT / "tests/fixtures/baselines/sentence_grounding_copy"
FIXTURE_V2 = PROJECT_ROOT / "tests/fixtures/baselines/window_grounding"
RUN_LEVELS = ("showcase/A0", "showcase/A4", "webnlg10/A0", "webnlg10/A4")
GRAPH_FILES = ("graph.json", "graph.graphml", "statements.jsonl", "entities.jsonl")
DROP_TOP = ("stage_seconds",)
DROP_LLM = ("seconds", "cache_hits", "cache_misses")
WINDOW_GROUNDING_METRIC_KEYS = ("ground_rules", "statements_flagged", "flagged_by_reason")


def normalize_metrics(metrics: dict, legacy: bool = True) -> dict:
    result = copy.deepcopy(metrics)
    for key in (*DROP_TOP, *(WINDOW_GROUNDING_METRIC_KEYS if legacy else ())):
        result.pop(key, None)
    for key in DROP_LLM:
        result.get("llm", {}).pop(key, None)
    return result


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


def capture(run_root: Path, dst: Path, overwrite: bool) -> dict:
    dst = dst.resolve()
    if not dst.is_relative_to(PROJECT_ROOT) or dst == PROJECT_ROOT:
        raise ValueError("baseline destination must stay within the project")
    if dst.exists() and any(dst.iterdir()) and not overwrite:
        raise ValueError("baseline destination is not empty; --overwrite is required")
    recorded = json.loads((FIXTURE / "baseline.json").read_text(encoding="utf-8"))["files"]
    expected = {f"{level}/{name}" for level in RUN_LEVELS for name in GRAPH_FILES}
    if not expected.issubset(recorded):
        raise ValueError("baseline manifest does not contain all 16 graph hashes")
    differences = [f"DIFF {rel}" for rel in sorted(expected)
                   if not (run_root / rel).is_file() or _sha(run_root / rel) != recorded[rel]]
    if differences:
        raise ValueError("\n".join(differences))
    # Read every input before creating or replacing the destination.
    metrics = {level: normalize_metrics(json.loads((run_root / level / "metrics.json").read_text(encoding="utf-8")))
               for level in RUN_LEVELS}
    if dst.exists() and overwrite:
        shutil.rmtree(dst)
    files = {}
    for level in RUN_LEVELS:
        metric_path = dst / level / "metrics.json"
        _write(metric_path, metrics[level])
        files[f"{level}/metrics.json"] = _sha(metric_path)
        for name in GRAPH_FILES:
            rel = f"{level}/{name}"
            shutil.copyfile(run_root / rel, dst / rel)
            files[rel] = _sha(dst / rel)
    manifest = {"format": "kgb.baseline/1",
                "command": "./kgb.ps1 run --config configs/experiments/demo.yaml --mock --out runs/_baseline_capture --overwrite",
                "normalize": {"drop": ["stage_seconds", "llm.seconds", "llm.cache_hits", "llm.cache_misses"]},
                "files": files}
    _write(dst / "baseline.json", manifest)
    return manifest


def compare(run_root: Path, fixture: Path = FIXTURE) -> list[str]:
    manifest = json.loads((fixture / "baseline.json").read_text(encoding="utf-8"))
    differences = []
    for rel, digest in sorted(manifest["files"].items()):
        stored, fresh = fixture / rel, run_root / rel
        if not stored.is_file() or _sha(stored) != digest:
            differences.append(f"CORRUPT {rel}")
            continue
        if not fresh.is_file():
            differences.append(f"MISSING {rel}")
            continue
        if rel.endswith("/metrics.json"):
            equal = normalize_metrics(json.loads(fresh.read_text(encoding="utf-8")), manifest["format"] == "kgb.baseline/1") == json.loads(stored.read_text(encoding="utf-8"))
        else:
            equal = _sha(fresh) == digest
        if not equal:
            differences.append(f"DIFF {rel}")
    return differences


def preserve_v1() -> list[str]:
    """Copy once, then verify without ever repairing the historical copy."""
    if not FIXTURE_V1.exists():
        shutil.copytree(FIXTURE, FIXTURE_V1)
    manifest = json.loads((FIXTURE / "baseline.json").read_text(encoding="utf-8"))
    expected = {**manifest["files"], "baseline.json": _sha(FIXTURE / "baseline.json")}
    return [f"MISMATCH {rel}" for rel, digest in sorted(expected.items())
            if not (FIXTURE_V1 / rel).is_file() or _sha(FIXTURE_V1 / rel) != digest]


def diff(run_root: Path, fixture: Path) -> list[str]:
    """Report exact row/field changes before a deliberate v2 capture."""
    manifest = json.loads((fixture / "baseline.json").read_text(encoding="utf-8"))
    files = set(manifest["files"]) | {f"{level}/graph_strict.json" for level in RUN_LEVELS
                                     if (run_root / level / "graph_strict.json").is_file()}
    lines = []
    for rel in sorted(files):
        old, new = fixture / rel, run_root / rel
        if not new.is_file():
            lines.append(f"missing {rel}")
            continue
        if not old.is_file():
            lines.append(f"added {rel}")
            continue
        if rel.endswith("metrics.json"):
            before = json.loads(old.read_text(encoding="utf-8"))
            raw = json.loads(new.read_text(encoding="utf-8"))
            after = normalize_metrics(raw)
            lines.append(f'{"same" if before == after else "changed"} {rel}')
            for key in sorted(before.keys() | after.keys()):
                if before.get(key) != after.get(key):
                    lines.append(f'  field {key}: {json.dumps(before.get(key), sort_keys=True)} -> {json.dumps(after.get(key), sort_keys=True)}')
            lines.append('  WINDOW_GROUNDING metrics ' + json.dumps({k: raw.get(k) for k in WINDOW_GROUNDING_METRIC_KEYS}, sort_keys=True))
            continue
        equal = old.read_bytes() == new.read_bytes()
        lines.append(f'{"same" if equal else "changed"} {rel}')
        if not equal and rel.endswith(("statements.jsonl", "entities.jsonl")):
            key = "statement_id" if rel.endswith("statements.jsonl") else "entity_id"
            before = {r[key]: r for r in map(json.loads, old.read_text(encoding="utf-8").splitlines())}
            after = {r[key]: r for r in map(json.loads, new.read_text(encoding="utf-8").splitlines())}
            for rid in sorted(before.keys() | after.keys()):
                if rid not in before:
                    lines.append(f'  added {rid}: {json.dumps(after[rid], sort_keys=True)}')
                elif rid not in after:
                    lines.append(f'  removed {rid}: {json.dumps(before[rid], sort_keys=True)}')
                elif before[rid] != after[rid]:
                    for field in sorted(before[rid].keys() | after[rid].keys()):
                        if before[rid].get(field) != after[rid].get(field):
                            lines.append(f'  changed {rid}.{field}: {json.dumps(before[rid].get(field), sort_keys=True)} -> {json.dumps(after[rid].get(field), sort_keys=True)}')
    return lines


def capture_v2(run_root: Path, dst: Path, overwrite: bool) -> dict:
    """Capture only the approved v2 destination, retaining every WINDOW_GROUNDING metric."""
    dst = dst.resolve()
    if dst != FIXTURE_V2.resolve():
        raise ValueError("capture-v2 target must be tests/fixtures/baselines/window_grounding")
    if overwrite and (dst / "baseline.json").exists():
        raise ValueError("capture-v2 cannot overwrite the published baseline")
    if dst.exists() and any(dst.iterdir()) and not overwrite:
        raise ValueError("mock_demo_v2 exists; pass --overwrite")
    content = {}
    for level in RUN_LEVELS:
        metrics = normalize_metrics(json.loads((run_root / level / "metrics.json").read_text(encoding="utf-8")), False)
        content[f"{level}/metrics.json"] = (json.dumps(metrics, sort_keys=True, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        for name in (*GRAPH_FILES, "graph_strict.json"):
            source = run_root / level / name
            if name != "graph_strict.json" or source.is_file():
                content[f"{level}/{name}"] = source.read_bytes()
    if dst.exists() and overwrite:
        shutil.rmtree(dst)
    for rel, raw in content.items():
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    manifest = {"format": "kgb.baseline/2", "command": "./kgb.ps1 run --config configs/experiments/demo.yaml --mock --out runs/_baseline_v2 --overwrite --set extract.backend=kggen --set llm.cache_path=.cache/tmp/baseline_v2/no_cache.jsonl",
                "defaults": "window grounding", "supersedes": "sentence_grounding_copy",
                "normalize": {"drop": ["stage_seconds", "llm.seconds", "llm.cache_hits", "llm.cache_misses"]},
                "files": {rel: _sha(dst / rel) for rel in sorted(content)}}
    _write(dst / "baseline.json", manifest)
    return manifest


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("--run", type=Path, required=True)
    cap.add_argument("--to", type=Path, required=True)
    cap.add_argument("--overwrite", action="store_true")
    sub.add_parser("preserve-v1")
    cap2 = sub.add_parser("capture-v2")
    cap2.add_argument("--run", type=Path, required=True)
    cap2.add_argument("--to", type=Path, required=True)
    cap2.add_argument("--overwrite", action="store_true")
    differences = sub.add_parser("diff")
    differences.add_argument("--run", type=Path, required=True)
    differences.add_argument("--fixture", type=Path, required=True)
    check = sub.add_parser("check")
    check.add_argument("--run", type=Path, required=True)
    check.add_argument("--fixture", type=Path, default=FIXTURE)
    args = parser.parse_args(argv)
    try:
        if args.command == "preserve-v1":
            errors = preserve_v1()
            print("\n".join(errors) if errors else "mock_demo_v1: every file hash matches mock_demo")
            return int(bool(errors))
        if args.command == "diff":
            print("\n".join(diff(args.run, args.fixture)))
            return 0
        if args.command == "capture-v2":
            manifest = capture_v2(args.run, args.to, args.overwrite)
            print(f'captured mock_demo_v2: {len(manifest["files"]) + 1} files')
            return 0
        if args.command == "capture":
            capture(args.run, args.to, args.overwrite)
            print("16/16 graph files match the published baseline manifest; wrote 21 files")
            return 0
        differences = compare(args.run, args.fixture)
        for line in differences:
            print(line)
        return int(bool(differences))
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
