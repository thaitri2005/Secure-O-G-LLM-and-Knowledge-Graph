"""Offline packet freeze, strict validation, immutable seals and blinded adjudication."""
from __future__ import annotations

import copy
import json
import math
import os
import re
import shutil
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from kgbuilder.core.config import ConfigError, project_path
from kgbuilder.core.domain import read_object
from kgbuilder.core.project import PROJECT_ROOT
from kgbuilder.core.text import chunk_spans, cj, iter_jsonl, sha256_file, sha256_text, write_json, write_jsonl
from kgbuilder.core.well_facts import AnnotationFacts, WellFact, annotation_message, iaa_score, load_annotations, match, partition, resolve_fact, resolve_span, score


PROTOCOL = ("guideline.md",)


def load_config(path: Path) -> dict:
    """Read only the declared gold settings and resolve contained paths."""
    try:
        cfg = yaml.safe_load(project_path(path, "gold config", True).read_text(encoding="utf-8"))
        keys = {"root", "batch_size", "seed", "annotators", "frozen_inputs", "forbidden_before_seal"}
        if set(cfg) not in (keys, keys | {"converter"}):
            raise ValueError()
        if "converter" in cfg and (cfg["converter"] != "v2" or "configs/domains/bsee/bsee_literals.yaml" not in cfg["frozen_inputs"]):
            raise ValueError()
        if type(cfg["batch_size"]) is not int or cfg["batch_size"] < 1 or type(cfg["seed"]) is not int or cfg["annotators"] != ["annotator_a", "annotator_b"]:
            raise ValueError()
        cfg["root"] = project_path(cfg["root"], "gold root", False)
        boundary = PROJECT_ROOT / "runs/_test"
        v1, v2 = (PROJECT_ROOT / "data/benchmarks/bsee_gold" / version for version in ("v1", "v2"))
        if (cfg["root"] == v1 and "converter" in cfg or cfg["root"] == v2 and "converter" not in cfg
                or cfg["root"] not in (v1, v2) and (cfg["root"] == boundary or not cfg["root"].is_relative_to(boundary))):
            raise ValueError("invalid gold root")
        for key in ("frozen_inputs", "forbidden_before_seal"):
            if not isinstance(cfg[key], list) or not all(isinstance(p, str) for p in cfg[key]): raise ValueError()
            for value in cfg[key]: project_path(value, key, key == "frozen_inputs")
        return cfg
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        raise ConfigError("invalid gold configuration") from exc


def _absent(cfg):
    for name in cfg["forbidden_before_seal"]:
        if project_path(name, "forbidden path", False).exists(): raise ConfigError(f"forbidden before seal: {name}")


def _inside(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve(): raise ConfigError("gold path escapes root")
    return path


def _hashes(root, names):
    return {name: sha256_file(_inside(root, name)) for name in sorted(names)}


def _check_hashes(root, hashes):
    for name, digest in hashes.items():
        path = _inside(root, name)
        if not path.is_file() or sha256_file(path) != digest: raise ConfigError(f"gold hash mismatch: {name}")


def _freeze(cfg, check_inputs: bool = True):
    root = cfg["root"]
    freeze = read_object(root / "freeze.json")
    if freeze.get("converter") != cfg.get("converter"): raise ConfigError("gold freeze settings mismatch")
    if freeze.get("seed") != cfg["seed"] or freeze.get("batch_size") != cfg["batch_size"] or freeze.get("annotators") != cfg["annotators"]:
        raise ConfigError("gold freeze settings mismatch")
    if freeze.get("checked_absent") != cfg["forbidden_before_seal"]: raise ConfigError("gold forbidden inventory changed")
    if set(freeze["frozen_inputs"]) != set(cfg["frozen_inputs"]): raise ConfigError("frozen input inventory changed")
    if check_inputs:
        _check_hashes(PROJECT_ROOT, freeze["frozen_inputs"])
        base = {"protocol/" + n for n in PROTOCOL}
        added = {p for entry in freeze.get("amendments", []) for p in entry["added_protocol"]}
        present = {p.relative_to(root).as_posix() for p in (root / "protocol").glob("*.md")}
        if not base <= set(freeze["protocol"]) <= base | added or present != set(freeze["protocol"]):
            raise ConfigError("protocol inventory mismatch")
        _check_hashes(root, freeze["protocol"])
    _check_hashes(root, freeze["packets"])
    _check_hashes(root, {"split.json": freeze["split_sha256"]})
    if {p.relative_to(root).as_posix() for p in (root / "packets").glob("*.jsonl")} != set(freeze["packets"]):
        raise ConfigError("packet inventory mismatch")
    return freeze


def prepare(cfg, corpus_dir: Path) -> dict:
    """Freeze a hash-checked corpus and blind batches; never consult research files."""
    root = cfg["root"]
    _absent(cfg)
    if (root / "freeze.json").exists(): raise ConfigError("freeze already exists")
    for name in PROTOCOL:
        if not (root / "protocol" / name).is_file(): raise ConfigError(f"missing protocol/{name}")
    for name in ("packets", "annotations", "adjudication", "seals"):
        path = root / name
        if path.exists() and any(path.iterdir()): raise ConfigError(f"gold output is nonempty: {name}")
    selection = read_object(corpus_dir / "selection.json")
    corpus_hash = sha256_file(corpus_dir / "corpus.jsonl")
    if corpus_hash != selection["corpus_sha256"]: raise ConfigError("selection corpus hash mismatch")
    documents = list(iter_jsonl(corpus_dir / "corpus.jsonl"))
    ids = [d["doc_id"] for d in documents]
    dev, test = selection["dev"], selection["test"]
    if not ids or len(set(ids)) != len(ids) or len(dev + test) != len(set(dev + test)) or ids != dev + test:
        raise ConfigError("selection split identity/order mismatch")
    packets = []
    for doc in documents:
        if chunk_spans(doc["text"], 2000) != [(0, len(doc["text"]))]: raise ConfigError("gold requires one whole chunk per document")
        packets.append({"format": "kgb.well_packet/1", "chunk_id": doc["doc_id"] + "#c000", "doc_id": doc["doc_id"], "source_type": "eor", "text": doc["text"]})
    packets.sort(key=lambda p: (sha256_text(f"{cfg['seed']}|{p['chunk_id']}"), p["chunk_id"]))
    names = []
    for i in range(0, len(packets), cfg["batch_size"]):
        name = f"packets/batch_{i // cfg['batch_size'] + 1:02d}.jsonl"
        write_jsonl(root / name, packets[i:i + cfg["batch_size"]]); names.append(name)
    write_json(root / "split.json", {"dev": dev, "test": test, "test_subset": selection.get("test_subset", selection.get("pilot", [])), "seed": cfg["seed"]})
    freeze = {"format": "kgb.well_freeze/1", "corpus_sha256": corpus_hash, "packets": _hashes(root, names),
              "split_sha256": sha256_file(root / "split.json"), "protocol": _hashes(root, ["protocol/" + n for n in PROTOCOL]),
              "frozen_inputs": {name: sha256_file(project_path(name, "frozen input", True)) for name in cfg["frozen_inputs"]},
              "seed": cfg["seed"], "batch_size": cfg["batch_size"], "annotators": cfg["annotators"],
              "created_at": datetime.now(timezone.utc).isoformat(), "statement": "no system, silver or rule output on real data existed at freeze",
              "checked_absent": cfg["forbidden_before_seal"], "n_gold": len(ids), "n_dev": len(dev), "n_test": len(test)}
    if "converter" in cfg: freeze["converter"] = cfg["converter"]
    write_json(root / "freeze.json", freeze)
    return {"freeze": freeze, "freeze_sha256": sha256_file(root / "freeze.json"), "batches": len(names)}


def _packets(cfg, check_inputs: bool = True):
    freeze = _freeze(cfg, check_inputs=check_inputs)
    return {Path(name).name: list(iter_jsonl(cfg["root"] / name)) for name in freeze["packets"]}


def publish(cfg, corpus_dir: Path) -> dict:
    """Seal existing labels for publication without changing their content."""
    root = cfg["root"]
    if cfg["forbidden_before_seal"]:
        raise ConfigError("publication requires an empty prior-output exclusion list")
    if (root / "freeze.json").exists() or ((root / "seals").exists() and any((root / "seals").iterdir())):
        raise ConfigError("publication freeze or seals already exist")
    # Validate the complete seal chain in isolation before publishing it.
    with tempfile.TemporaryDirectory(prefix=".publication-", dir=root.parent) as temporary:
        staged = Path(temporary) / "benchmark"
        shutil.copytree(root, staged)
        result = _publish_existing({**cfg, "root": staged}, corpus_dir)
        seals = root / "seals"
        seals_existed = seals.exists()
        try:
            shutil.copytree(staged / "seals", seals, dirs_exist_ok=True)
            os.replace(staged / "freeze.json", root / "freeze.json")
        except BaseException:
            for path in (staged / "seals").iterdir():
                (seals / path.name).unlink(missing_ok=True)
            if not seals_existed and seals.exists():
                seals.rmdir()
            raise
    return result


def _publish_existing(cfg, corpus_dir: Path) -> dict:
    root = cfg["root"]
    selection = read_object(corpus_dir / "selection.json")
    split = read_object(root / "split.json")
    corpus_hash = sha256_file(corpus_dir / "corpus.jsonl")
    if selection["corpus_sha256"] != corpus_hash:
        raise ConfigError("publication corpus hash mismatch")
    for name in ("dev", "test"):
        if selection.get(name, []) != split.get(name, []):
            raise ConfigError("publication split differs from corpus selection")
    # Historical dataset keys retain their original spelling in publication.
    if selection.get("test_subset", selection.get("pilot", [])) != split.get("test_subset", split.get("pilot", [])):
        raise ConfigError("publication split differs from corpus selection")
    packets = sorted(p.relative_to(root).as_posix() for p in (root / "packets").glob("*.jsonl"))
    documents = {d["doc_id"]: d["text"] for d in iter_jsonl(corpus_dir / "corpus.jsonl")}
    rows = [row for name in packets for row in iter_jsonl(root / name)]
    if len(rows) != len(documents) or {r["doc_id"]: r["text"] for r in rows} != documents:
        raise ConfigError("publication packets differ from corpus")
    freeze = {"format": "kgb.well_freeze/1", "corpus_sha256": corpus_hash,
              "packets": _hashes(root, packets), "split_sha256": sha256_file(root / "split.json"),
              "protocol": _hashes(root, ["protocol/" + name for name in PROTOCOL]),
              "frozen_inputs": {name: sha256_file(project_path(name, "frozen input", True)) for name in cfg["frozen_inputs"]},
              "seed": cfg["seed"], "batch_size": cfg["batch_size"], "annotators": cfg["annotators"],
              "created_at": datetime.now(timezone.utc).isoformat(), "checked_absent": [],
              "statement": "re-sealed for publication; label content identical",
              "n_gold": len(documents), "n_dev": len(split["dev"]), "n_test": len(split["test"])}
    if "converter" in cfg:
        freeze["converter"] = cfg["converter"]
    write_json(root / "freeze.json", freeze)
    for role in cfg["annotators"]:
        seal(cfg, role)
    outputs, key, _ = _build_adjudication(cfg)
    _packet_identity(cfg, outputs, key)
    _write_seal(cfg, "adjudication_packet", [*outputs, "adjudication/key.json"])
    seal(cfg, "adjudicator")
    records, _, _ = _merged_records(cfg)
    if list(iter_jsonl(root / "adjudicated.jsonl")) != records:
        raise ConfigError("publication labels differ from merged decisions")
    corpus = {row["chunk_id"]: row["text"] for row in rows}
    load_annotations(root / "adjudicated.jsonl", corpus)
    _write_seal(cfg, "adjudicated", ["adjudicated.jsonl"])
    return verify(cfg)


def _role_files(cfg, role, check_inputs: bool = True):
    if role not in [*cfg["annotators"], "adjudicator"]: raise ConfigError("unknown annotation role")
    if role == "adjudicator":
        packet = _verify_seal(cfg, "adjudication_packet", check_inputs=check_inputs)
        expected = {Path(name).name.replace("packet_", "decisions_") for name in packet["files"] if Path(name).name.startswith("packet_")}
        folder = cfg["root"] / "adjudication"
        present = {p.name for p in folder.glob("*.jsonl") if not p.name.startswith("packet_")}
    else:
        expected = set(_packets(cfg, check_inputs=check_inputs))
        folder = cfg["root"] / "annotations" / role
        present = {p.name for p in folder.glob("*.jsonl")}
    if present - expected: raise ConfigError("annotation file has no matching packet: " + sorted(present - expected)[0])
    return folder, expected, present


class _ValidationIssues(list):
    """Bound CLI diagnostics while plain issue lists retain the full amend scan."""
    def __init__(self, limit):
        super().__init__()
        self.limit = limit


def validate(cfg, role: str, locations_only: bool = False, check_inputs: bool = True) -> dict:
    """Validate only present batches; sealing additionally requires all batches."""
    packets = _packets(cfg, check_inputs=check_inputs)
    folder, expected, present = _role_files(cfg, role, check_inputs=check_inputs)
    facts, chunks, errors = 0, 0, []
    for name in sorted(present):
        try:
            if role == "adjudicator":
                rows = _decisions(cfg, name, check_inputs=check_inputs)
                facts += len(rows)
                continue
            texts = {r["chunk_id"]: r["text"] for r in packets[name]}
            label = (folder / name).relative_to(cfg["root"]).as_posix()
            issues = _ValidationIssues(50 - len(errors))
            loaded = load_annotations(folder / name, texts, issues=issues, label=label)
            errors.extend(annotation_message(issue, locations_only) for issue in issues[:50 - len(errors)])
            if any(row["annotator"] != role for row in loaded.statuses.values()) or any(f.annotator != role for f in loaded):
                errors.append(label + (":1: record" if locations_only else ":1: record: annotator mismatch"))
            facts += len(loaded); chunks += len(texts)
        except ConfigError as exc:
            message = str(exc)
            if locations_only and role == "adjudicator":
                message = re.sub(r"(:\d+: decision):.*", r"\1", message)
            errors.append(message)
        if len(errors) >= 50: break
    if errors: raise ConfigError("\n".join(errors[:50]))
    return {"role": role, "present": len(present), "total": len(expected), "status": f"present {len(present)}/{len(expected)}", "chunks": chunks, "facts": facts}


def _write_seal(cfg, name, files):
    path = cfg["root"] / "seals" / (name + ".json")
    if path.exists(): raise ConfigError("seal already exists: " + name)
    _absent(cfg)
    seal = {"role": name, "freeze_sha256": sha256_file(cfg["root"] / "freeze.json"), "files": _hashes(cfg["root"], files),
            "forbidden_absent": True, "created_at": datetime.now(timezone.utc).isoformat(),
            "dependencies": {p.relative_to(cfg["root"]).as_posix(): sha256_file(p) for p in sorted((cfg["root"] / "seals").glob("*.json"))}}
    write_json(path, seal)
    return {"role": name, "files": len(files), "seal_sha256": sha256_file(path)}


def seal(cfg, role: str) -> dict:
    """Seal complete role outputs once, after validating and checking ordering."""
    if (cfg["root"] / "seals" / (role + ".json")).exists(): raise ConfigError("seal already exists: " + role)
    result = validate(cfg, role)
    folder, expected, present = _role_files(cfg, role)
    if expected != present: raise ConfigError("missing batches: " + ", ".join(sorted(expected - present)))
    changes = _check_amendments(cfg)
    result.update(_write_seal(cfg, role, [(folder / name).relative_to(cfg["root"]).as_posix() for name in sorted(present)]))
    if role in changes: result["amendment_changes"] = changes[role]
    return result


def _verify_seal(cfg, role, check_inputs: bool = True):
    root = cfg["root"]
    value = read_object(root / "seals" / (role + ".json"))
    if set(value) != {"role", "freeze_sha256", "files", "forbidden_absent", "created_at", "dependencies"}: raise ConfigError("invalid seal fields")
    if value.get("role") != role or value.get("forbidden_absent") is not True or value.get("freeze_sha256") != sha256_file(root / "freeze.json"):
        raise ConfigError("invalid gold seal: " + role)
    _check_hashes(root, value["files"])
    _check_hashes(root, value["dependencies"])
    if role in cfg["annotators"]:
        expected = {f"annotations/{role}/{name}" for name in _packets(cfg, check_inputs=check_inputs)}
        present = {p.relative_to(root).as_posix() for p in (root / "annotations" / role).glob("*.jsonl")}
        if set(value["files"]) != expected or present != expected: raise ConfigError("sealed annotation inventory mismatch")
    return value


def verify(cfg) -> dict:
    """Verify every frozen input and required seal; later outputs may now exist."""
    _freeze(cfg)
    _check_amendments(cfg)
    status = {"freeze": "OK", "amendments": "OK"}
    for role in [*cfg["annotators"], "adjudication_packet", "adjudicator", "adjudicated"]:
        _verify_seal(cfg, role); status[role] = "OK"
    # Require coverage, not just hashes in arbitrarily shortened seal dictionaries.
    root = cfg["root"]
    expected = {"adjudication/key.json", *{f"adjudication/{name.replace('batch_', 'packet_')}" for name in _packets(cfg)}}
    if set(_verify_seal(cfg, "adjudication_packet")["files"]) != expected: raise ConfigError("adjudication packet seal inventory")
    decisions = {name.replace("packet_", "decisions_") for name in expected if "/packet_" in name}
    if set(_verify_seal(cfg, "adjudicator")["files"]) != decisions: raise ConfigError("adjudicator seal inventory")
    if {p.relative_to(root).as_posix() for p in (root / "adjudication").glob("*.jsonl")} != (expected - {"adjudication/key.json"}) | decisions:
        raise ConfigError("adjudication directory inventory mismatch")
    if set(_verify_seal(cfg, "adjudicated")["files"]) != {"adjudicated.jsonl"}: raise ConfigError("adjudicated seal inventory")
    return status


def _annotations(cfg, role, check_inputs: bool = True):
    _verify_seal(cfg, role, check_inputs=check_inputs)
    facts = AnnotationFacts()
    for name, packet in _packets(cfg, check_inputs=check_inputs).items():
        rows = load_annotations(cfg["root"] / "annotations" / role / name, {p["chunk_id"]: p["text"] for p in packet})
        facts.extend(rows); facts.statuses.update(rows.statuses)
    return facts


def _annotation_hashes(root):
    return _hashes(root, [p.relative_to(root).as_posix() for p in (root / "annotations").rglob("*") if p.is_file()])


def _adjudication_hashes(root):
    return _hashes(root, [p.relative_to(root).as_posix() for p in (root / "adjudication").rglob("*") if p.is_file()])


def _archive_hashes(record):
    hashes = {}
    for seal in record["superseded_seals"].values():
        hashes[seal["archived_seal"]] = seal["seal_sha256"]
        hashes.update(seal["archived_files"])
    return hashes


def _amendment_integrity(cfg, record):
    root = cfg["root"]
    unchanged = record["unchanged"]
    try:
        _check_hashes(root, {**unchanged["packets"], "split.json": unchanged["split_sha256"], **_archive_hashes(record)})
        packets = {p.relative_to(root).as_posix() for p in (root / "packets").glob("*.jsonl")}
        if packets != set(unchanged["packets"]) or _annotation_hashes(root) != unchanged["annotations"]:
            raise ConfigError("inventory changed")
        if "adjudication" in unchanged and _adjudication_hashes(root) != unchanged["adjudication"]:
            raise ConfigError("adjudication inventory changed")
    except (ConfigError, OSError) as exc:
        raise ConfigError("amendment integrity") from exc


def _amendment_records(cfg, freeze):
    """Verify the hash chain and archived bytes without exposing their contents."""
    root, records = cfg["root"], []
    entries = freeze.get("amendments", [])
    if freeze.get("amendment", 0) != len(entries): raise ConfigError("amendment chain numbering")
    for number, entry in enumerate(entries, 1):
        folder = f"amendments/{number:03d}"
        if entry["number"] != number or entry["record"] != folder + "/record.json":
            raise ConfigError("amendment chain numbering")
        _check_hashes(root, {entry["record"]: entry["record_sha256"], folder + "/previous_freeze.json": entry["previous_freeze_sha256"]})
        record = read_object(root / entry["record"])
        previous = read_object(root / folder / "previous_freeze.json")
        if record.get("format") != "kgb.well_freeze_amendment/1" or record.get("number") != number:
            raise ConfigError("amendment record identity")
        if previous.get("amendments", []) != entries[:number - 1] or previous.get("amendment", 0) != number - 1:
            raise ConfigError("amendment previous chain")
        for key in ("reason", "previous_freeze_sha256", "changed_frozen_inputs", "changed_protocol", "added_protocol"):
            if record[key] != entry[key]: raise ConfigError("amendment record mismatch: " + key)
        if {role: row["seal_sha256"] for role, row in record["superseded_seals"].items()} != entry["superseded_seals"]:
            raise ConfigError("amendment superseded inventory")
        if record["checked_absent"] != freeze["checked_absent"] or record["forbidden_absent"] is not True:
            raise ConfigError("amendment ordering")
        for key in ("packets", "split_sha256", "corpus_sha256"):
            if previous[key] != freeze[key] or record["unchanged"][key] != freeze[key]:
                raise ConfigError("amendment unchanged mismatch: " + key)
        successor = (read_object(root / f"amendments/{number + 1:03d}/previous_freeze.json")
                     if number < len(entries) else freeze)
        expected = copy.deepcopy(previous)
        for key, changed_key in (("frozen_inputs", "changed_frozen_inputs"), ("protocol", "changed_protocol")):
            for name, hashes in record[changed_key].items():
                if expected[key].get(name) != hashes["old"]: raise ConfigError("amendment old input hash")
                expected[key][name] = hashes["new"]
        for name, digest in record["added_protocol"].items():
            if name in expected["protocol"]: raise ConfigError("amendment added protocol exists")
            expected["protocol"][name] = digest
        expected.update(amendment=number, amendments=entries[:number])
        if successor != expected: raise ConfigError("amendment freeze transition")
        _check_hashes(root, _archive_hashes(record))
        for role, seal in record["superseded_seals"].items():
            if role not in [*cfg["annotators"], "adjudication_packet", "adjudicator"]: raise ConfigError("amendment archive role")
            archived = read_object(_inside(root, seal["archived_seal"]))
            if (archived["role"] != role or archived["freeze_sha256"] != entry["previous_freeze_sha256"]
                    or archived["forbidden_absent"] is not True):
                raise ConfigError("amendment archived seal")
            expected_files = {folder + "/superseded/" + name: digest for name, digest in archived["files"].items()}
            if expected_files != seal["archived_files"]: raise ConfigError("amendment archive inventory")
            for name, digest in archived["files"].items():
                inventory = "annotations" if role in cfg["annotators"] else "adjudication"
                if record["unchanged"].get(inventory, {}).get(name) != digest: raise ConfigError("amendment archived file hash")
            for live in (root / "seals").glob("*"):
                if live.is_file() and sha256_file(live) == seal["seal_sha256"]:
                    raise ConfigError("superseded seal remains: " + live.name)
        records.append(record)
    return records


def _check_amendments(cfg) -> dict:
    """Check correction boundaries and return only counts and closed field names."""
    try:
        freeze = _freeze(cfg, check_inputs=False)
        records = _amendment_records(cfg, freeze)
        root, changes = cfg["root"], {}
        if records and records[-1].get("state") == "post_adjudication":
            for inventory, live in (("annotations", _annotation_hashes(root)), ("adjudication", _adjudication_hashes(root))):
                old = records[-1]["unchanged"][inventory]
                different = sorted(name for name in set(old) | set(live) if old.get(name) != live.get(name))
                if different: raise ConfigError("amendment byte equality: " + ", ".join(different))
        for role in [*cfg["annotators"], "adjudication_packet", "adjudicator"]:
            superseded = [r for r in records if role in r["superseded_seals"]]
            if not superseded: continue
            for index, baseline in enumerate(superseded):
                following = superseded[index + 1] if index + 1 < len(superseded) else None
                limit = following["number"] - 1 if following else len(records)
                allowed = {}
                for record in records[baseline["number"] - 1:limit]:
                    for issue in record["flagged"].get(role, []):
                        allowed.setdefault((issue["file"], issue["line"]), {})[issue["path"]] = issue["reason"]
                count, paths, relations, seen = 0, Counter(), Counter(), set()
                seal = baseline["superseded_seals"][role]
                prefix = f"amendments/{baseline['number']:03d}/superseded/"
                originals = {p.removeprefix(prefix): p for p in seal["archived_files"]}
                if following:
                    next_prefix = f"amendments/{following['number']:03d}/superseded/"
                    targets = {p.removeprefix(next_prefix): p for p in following["superseded_seals"][role]["archived_files"]}
                    present = set(targets)
                else:
                    targets = {name: name for name in originals}
                    if role in cfg["annotators"]:
                        present = {p.relative_to(root).as_posix() for p in (root / "annotations" / role).glob("*.jsonl")}
                    else:
                        pattern = "packet_*.jsonl" if role == "adjudication_packet" else "decisions_*.jsonl"
                        present = {p.relative_to(root).as_posix() for p in (root / "adjudication").glob(pattern)}
                        if role == "adjudication_packet" and (root / "adjudication/key.json").is_file(): present.add("adjudication/key.json")
                if baseline.get("state") == "post_adjudication":
                    different = sorted(name for name in originals if name not in present or
                                       _inside(root, originals[name]).read_bytes() != _inside(root, targets[name]).read_bytes())
                    different += sorted(present - set(originals))
                    if different: raise ConfigError("amendment byte equality: " + ", ".join(different))
                    if role not in cfg["annotators"]: continue
                if present != set(originals): raise ConfigError("amendment annotation inventory: " + role)
                for name, archived in originals.items():
                    old = [line for line in _inside(root, archived).read_text(encoding="utf-8-sig").splitlines() if line.strip()]
                    current = [(n, line) for n, line in enumerate(_inside(root, targets[name]).read_text(encoding="utf-8-sig").splitlines(), 1) if line.strip()]
                    if len(old) != len(current): raise ConfigError(f"{name}:1: amendment line count")
                    for old_line, (line_no, current_line) in zip(old, current):
                        before, after = json.loads(old_line), json.loads(current_line)
                        masked = copy.deepcopy(after)
                        for path, reason in allowed.get((name, line_no), {}).items():
                            seen.add((name, line_no, path))
                            if path not in {"object", "time", "subject", "evidence", "qualifiers"} and not path.startswith("qualifiers."):
                                raise ConfigError(f"{name}:{line_no}: amendment field path")
                            parts = path.split(".")
                            left, right, target = before, after, masked
                            for key in parts[:-1]: left, right, target = left[key], right[key], target[key]
                            key = parts[-1]
                            if left.get(key) != right.get(key):
                                count += 1; paths[path] += 1; relations[before["relation"]] += 1
                            if reason == "date normalization mismatch":
                                for field in ("iso", "precision"):
                                    target[key][field] = left[key][field]
                            elif key in left: target[key] = copy.deepcopy(left[key])
                            else: target.pop(key, None)
                        if before != masked: raise ConfigError(f"{name}:{line_no}: amendment correction outside flagged paths")
                flagged = sum(len(v) for v in allowed.values())
                if len(seen) != flagged: raise ConfigError("amendment flagged location missing: " + role)
                changes.setdefault(role, []).append({"amendment": baseline["number"], "flagged": flagged, "changed": count,
                                 "changed_by_path": dict(sorted(paths.items())), "changed_by_relation": dict(sorted(relations.items())),
                                 "flagged_unchanged": flagged - count})
        return changes
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ConfigError("invalid amendment chain or correction") from exc


def amend(cfg, reason: str) -> dict:
    """Archive a reviewed freeze change, committing only by atomic replacement."""
    try:
        return _amend(cfg, reason)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ConfigError("invalid amendment input or I/O") from exc


def _amend(cfg, reason):
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500 or len(reason.splitlines()) != 1 or "\n" in reason or "\r" in reason:
        raise ConfigError("amendment reason must be nonblank, one line, at most 500 characters")
    root = cfg["root"]
    freeze = _freeze(cfg, check_inputs=False)
    _absent(cfg)
    for name in ("seals/adjudicated.json", "adjudicated.jsonl"):
        path = root / name
        if path.exists(): raise ConfigError("amendment guard: " + name)
    if any(p.is_dir() for p in (root / "adjudication").glob("*")):
        raise ConfigError("amendment guard: adjudication directory inventory")
    protocol = _hashes(root, [p.relative_to(root).as_posix() for p in (root / "protocol").glob("*.md")])
    if not ({"protocol/" + n for n in PROTOCOL} | set(freeze["protocol"])) <= set(protocol):
        raise ConfigError("amendment protocol removal")
    for role in cfg["annotators"]: _role_files(cfg, role, check_inputs=False)
    annotation_hashes = _annotation_hashes(root)
    packet_names = {Path(p).name for p in freeze["packets"]}
    for name in annotation_hashes:
        parts = Path(name).parts
        if len(parts) != 3 or parts[1] not in cfg["annotators"] or parts[2] not in packet_names:
            raise ConfigError("annotation file has no matching packet: " + name)
    unchanged = {key: freeze[key] for key in ("packets", "split_sha256", "corpus_sha256")}
    unchanged["annotations"] = annotation_hashes
    freeze_hash = sha256_file(root / "freeze.json")
    entries = freeze.get("amendments", [])
    previous_hash = entries[-1]["previous_freeze_sha256"] if entries else None
    current, leftovers = {}, []
    last_record = None
    if entries:
        _check_hashes(root, {entries[-1]["record"]: entries[-1]["record_sha256"]})
        last_record = read_object(_inside(root, entries[-1]["record"]))
    for path in sorted((root / "seals").glob("*")):
        if not path.is_file(): raise ConfigError("invalid seal: " + path.name)
        value = read_object(path)
        role = value.get("role")
        if role not in [*cfg["annotators"], "adjudication_packet", "adjudicator"] or path.name != role + ".json":
            raise ConfigError("amendment guard: invalid seal: " + path.name)
        if value.get("freeze_sha256") == freeze_hash:
            current[role] = _verify_seal(cfg, role, check_inputs=False)
        elif previous_hash is not None and value.get("freeze_sha256") == previous_hash:
            archived = last_record["superseded_seals"].get(role)
            if not archived or sha256_file(path) != archived["seal_sha256"]: raise ConfigError("invalid leftover seal: " + path.name)
            leftovers.append(path)
        else: raise ConfigError("invalid seal freeze: " + path.name)
    if leftovers:
        _amendment_integrity(cfg, last_record)
        for path in leftovers: path.unlink()
        return {"status": "cleanup completed", "amendment": freeze["amendment"], "freeze_sha256": freeze_hash}
    adjudication = _adjudication_hashes(root)
    roles = {*cfg["annotators"], "adjudication_packet", "adjudicator"}
    post = set(current) == roles
    pending_reseal = bool(last_record and last_record.get("state") == "post_adjudication" and not post)
    if post:
        packet_files = {"adjudication/key.json", *{"adjudication/" + n.replace("batch_", "packet_") for n in packet_names}}
        decision_files = {"adjudication/" + n.replace("batch_", "decisions_") for n in packet_names}
        sealed_annotations = {name: digest for role in cfg["annotators"] for name, digest in current[role]["files"].items()}
        sealed_adjudication = {name: digest for role in ("adjudication_packet", "adjudicator") for name, digest in current[role]["files"].items()}
        if (set(current["adjudication_packet"]["files"]) != packet_files or set(current["adjudicator"]["files"]) != decision_files
                or adjudication != sealed_adjudication or annotation_hashes != sealed_annotations):
            raise ConfigError("amendment guard: sealed inventory differs")
        unchanged["adjudication"] = adjudication
    elif pending_reseal:
        if adjudication != last_record["unchanged"]["adjudication"]:
            raise ConfigError("amendment guard: adjudication inventory differs")
    elif adjudication or any(role in current for role in ("adjudication_packet", "adjudicator")):
        raise ConfigError("amendment guard: adjudication requires all four seals")
    _check_amendments(cfg)
    inputs = _hashes(PROJECT_ROOT, cfg["frozen_inputs"])
    def changed(old, new):
        return {p: {"old": old[p], "new": new[p]} for p in sorted(old) if old[p] != new[p]}
    changed_inputs, changed_protocol = changed(freeze["frozen_inputs"], inputs), changed(freeze["protocol"], protocol)
    added_protocol = {p: protocol[p] for p in sorted(set(protocol) - set(freeze["protocol"]))}
    if not changed_inputs and not changed_protocol and not added_protocol:
        return {"status": "no change", "amendment": freeze.get("amendment", 0), "freeze_sha256": freeze_hash}
    if pending_reseal: raise ConfigError("amendment guard: re-seal the superseded roles first")
    if post and (changed_protocol or added_protocol or any(p.endswith(".yaml") for p in changed_inputs)):
        raise ConfigError("amendment guard: post-adjudication scope")
    number = freeze.get("amendment", 0) + 1
    base = f"amendments/{number:03d}"
    packets, flagged, unsealed = _packets(cfg, check_inputs=False), {}, {}
    for role in cfg["annotators"]:
        folder, _, present = _role_files(cfg, role, check_inputs=False)
        flagged[role] = []
        for name in sorted(present):
            label, issues = (folder / name).relative_to(root).as_posix(), []
            load_annotations(folder / name, {r["chunk_id"]: r["text"] for r in packets[name]}, issues=issues, label=label)
            flagged[role].extend({k: issue[k] for k in ("file", "line", "path", "reason")} for issue in issues)
        if role not in current: unsealed[role] = [(folder / n).relative_to(root).as_posix() for n in sorted(present)]
    regenerated = None
    if post:
        decision_issues = []
        for name in sorted(current["adjudicator"]["files"]):
            _decisions(cfg, Path(name).name, check_inputs=False, issues=decision_issues)
        issues = [issue for values in flagged.values() for issue in values] + decision_issues
        if issues: raise ConfigError("amendment guard: flagged locations\n" + "\n".join(annotation_message(i, True) for i in issues))
        outputs, key, counts = _build_adjudication(cfg, check_inputs=False)
        _packet_identity(cfg, outputs, key)
        regenerated = {"packets": "identical", "items": counts}
    # All post-adjudication guards precede even crash-staging renames.
    abandoned = []
    for path in sorted((root / "amendments").glob("*")):
        hit = re.fullmatch(r"(\d{3})(?:\.staging)?", path.name)
        if not path.is_dir() or not hit or (path.name == hit[1] and int(hit[1]) < number): continue
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = path.with_name(hit[1] + ".abandoned_" + timestamp)
        suffix = 1
        while target.exists():
            target = path.with_name(hit[1] + ".abandoned_" + timestamp + f"_{suffix}"); suffix += 1
        path.rename(target)
        abandoned.append({"old": path.relative_to(root).as_posix(), "new": target.relative_to(root).as_posix()})
    staging = root / (base + ".staging")
    staging.mkdir(parents=True)
    def archive(source, relative, digest):
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if sha256_file(target) != digest or sha256_file(source) != digest: raise ConfigError("amendment archive copy mismatch")
    archive(root / "freeze.json", "previous_freeze.json", freeze_hash)
    superseded = {}
    for role, value in sorted(current.items()):
        seal_name = f"seals/{role}.json"
        digest = sha256_file(root / seal_name)
        archive(root / seal_name, "superseded/" + seal_name, digest)
        files = {}
        for name, file_hash in value["files"].items():
            archive(_inside(root, name), "superseded/" + name, file_hash)
            files[base + "/superseded/" + name] = file_hash
        superseded[role] = {"seal_sha256": digest, "archived_seal": base + "/superseded/" + seal_name, "archived_files": files}
    record = {"format": "kgb.well_freeze_amendment/1", "number": number, "reason": reason,
              "previous_freeze_sha256": freeze_hash, "changed_frozen_inputs": changed_inputs,
              "changed_protocol": changed_protocol, "added_protocol": added_protocol, "superseded_seals": superseded,
              "unsealed_present": unsealed, "flagged": flagged, "abandoned": abandoned,
              "checked_absent": cfg["forbidden_before_seal"], "forbidden_absent": True, "unchanged": unchanged}
    if post: record.update(state="post_adjudication", regenerated=regenerated)
    write_json(staging / "record.json", record)
    staging.rename(root / base)
    entry = {k: record[k] for k in ("number", "reason", "previous_freeze_sha256", "changed_frozen_inputs", "changed_protocol", "added_protocol")}
    entry.update(created_at=datetime.now(timezone.utc).isoformat(), superseded_seals={r: s["seal_sha256"] for r, s in superseded.items()},
                 record=base + "/record.json", record_sha256=sha256_file(root / base / "record.json"),
                 statement="no system, silver or rule output on real data existed at amendment")
    new = {**freeze, "frozen_inputs": inputs, "protocol": protocol, "amendment": number, "amendments": [*entries, entry]}
    _amendment_integrity(cfg, record)
    if sha256_file(root / "freeze.json") != freeze_hash: raise ConfigError("amendment integrity: freeze changed")
    temporary = root / base / "freeze.tmp"
    write_json(temporary, new)
    os.replace(temporary, root / "freeze.json")
    _amendment_integrity(cfg, record)
    for role, seal in superseded.items():
        live = root / "seals" / (role + ".json")
        if live.read_bytes() != _inside(root, seal["archived_seal"]).read_bytes(): raise ConfigError("amendment integrity: seal changed")
    for role in superseded: (root / "seals" / (role + ".json")).unlink()
    _amendment_integrity(cfg, record)
    return {"status": "amended", "freeze_sha256": sha256_file(root / "freeze.json"), "amendment": number,
            "changed_frozen_inputs": changed_inputs, "changed_protocol": changed_protocol, "added_protocol": added_protocol,
            "superseded_seals": superseded, "abandoned": abandoned,
            **({"state": "post_adjudication", "regenerated": regenerated} if post else {}),
            "flagged": {role: [annotation_message(issue, True) for issue in issues] for role, issues in flagged.items()},
            "counts": {role: {"flagged": len(issues), "by_path": dict(Counter(i["path"] for i in issues))} for role, issues in flagged.items()}}


def _policy(cfg):
    candidates = [p for p in cfg["frozen_inputs"] if p.endswith("bsee_eval.yaml")]
    if len(candidates) != 1: raise ConfigError("missing frozen evaluation policy")
    return yaml.safe_load(project_path(candidates[0], "evaluation policy", True).read_text(encoding="utf-8"))


def _plain(fact):
    row = fact.model_dump(exclude_none=True)
    row["time"] = fact.time
    row.pop("annotator", None)
    return row


def _build_adjudication(cfg, check_inputs: bool = True):
    """Build identical packet rows for initial writing and amendment certification."""
    packets = _packets(cfg, check_inputs=check_inputs)
    annotator_a, annotator_b = (_annotations(cfg, role, check_inputs=check_inputs) for role in cfg["annotators"])
    policy = _policy(cfg)
    key, outputs, counts = {}, {}, Counter()
    for name, packet in packets.items():
        output = []
        for chunk in packet:
            identity = chunk["chunk_id"]
            flip = int(sha256_text(f"{cfg['seed']}|ab|{identity}"), 16) % 2
            role_a, role_b = ("annotator_b", "annotator_a") if flip else ("annotator_a", "annotator_b")
            a, b = ([f for f in source if f.chunk_id == identity] for source in ((annotator_b, annotator_a) if flip else (annotator_a, annotator_b)))
            key[identity] = {"A": role_a, "B": role_b}
            pairs = match(a, b, policy, "L1")
            used_a, used_b = {i for i, _ in pairs}, {j for _, j in pairs}
            full = set(match(a, b, policy, "L3"))
            items = []
            for i, j in pairs:
                same = all(getattr(a[i], field) == getattr(b[j], field) for field in ("polarity", "modality", "uncertainty"))
                kind = "agreed" if (i, j) in full and same else "partial"
                items.append((kind, _plain(a[i]), _plain(b[j])))
            items += [("only_A", _plain(f), None) for i, f in enumerate(a) if i not in used_a]
            items += [("only_B", None, _plain(f)) for j, f in enumerate(b) if j not in used_b]
            if not items:
                output.append({"format": "kgb.well_adjudication_packet/1", "record": "chunk", "chunk_id": identity,
                               "text": chunk["text"], "items": []})
            for kind, left, right in items:
                item_id = sha256_text(f"{cfg['seed']}|item|{identity}|{kind}|{cj(left)}|{cj(right)}")[:16]
                counts[kind] += 1
                output.append({"format": "kgb.well_adjudication_packet/1", "chunk_id": identity, "text": chunk["text"],
                               "item_id": item_id, "kind": kind, "A": left, "B": right})
        target = "adjudication/" + name.replace("batch_", "packet_")
        outputs[target] = output
    return outputs, key, dict(counts)


def _packet_identity(cfg, outputs, key):
    """Refuse differing bytes with only item ids or the key filename in diagnostics."""
    root, differences, missing_ids, changed_ids = cfg["root"], [], set(), set()
    for name, rows in outputs.items():
        data = "".join(cj(row) + "\n" for row in rows).encode("utf-8")
        if (root / name).read_bytes() != data:
            differences.append(name)
            old = {r["item_id"]: r for r in iter_jsonl(root / name) if "item_id" in r}
            new = {r["item_id"]: r for r in rows if "item_id" in r}
            missing_ids.update(set(old) ^ set(new))
            changed_ids.update(k for k in set(old) & set(new) if old[k] != new[k])
    key_differs = (root / "adjudication/key.json").read_bytes() != (json.dumps(key, sort_keys=True, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    if differences or key_differs:
        ids = sorted(missing_ids) + sorted(changed_ids - missing_ids)
        message = f"amendment guard: adjudication packets differ\n{len(ids)} items:"
        if ids: message += "\n" + "\n".join(ids)
        if key_differs: message += "\nadjudication/key.json"
        raise ConfigError(message)


def adjudication_packet(cfg) -> dict:
    """Write initial packets or re-certify byte-identical post-amendment packets."""
    root = cfg["root"]
    _absent(cfg)
    if (root / "seals/adjudication_packet.json").exists(): raise ConfigError("adjudication packet already sealed")
    folder = root / "adjudication"
    recertify = folder.exists() and any(folder.iterdir())
    if recertify:
        records = _amendment_records(cfg, _freeze(cfg))
        if not records or records[-1].get("state") != "post_adjudication" or "adjudication_packet" not in records[-1]["superseded_seals"]:
            raise ConfigError("adjudication directory nonempty")
        _check_amendments(cfg)
    outputs, key, counts = _build_adjudication(cfg)
    names = [*outputs, "adjudication/key.json"]
    if recertify:
        _packet_identity(cfg, outputs, key)
    else:
        for name, rows in outputs.items(): write_jsonl(root / name, rows)
        write_json(root / "adjudication/key.json", key)
    result = {"items": counts, **_write_seal(cfg, "adjudication_packet", names)}
    if recertify: result["recertified"] = True
    return result


def _decisions(cfg, name, check_inputs: bool = True, issues=None):
    root = cfg["root"]
    _verify_seal(cfg, "adjudication_packet", check_inputs=check_inputs)
    packet_name = name.replace("decisions_", "packet_")
    items = {r["item_id"]: r for r in iter_jsonl(root / "adjudication" / packet_name) if "item_id" in r}
    batch = name.replace("decisions_", "batch_")
    texts = {r["chunk_id"]: r["text"] for r in _packets(cfg, check_inputs=check_inputs)[batch]}
    allowed = {"agreed": {"keep", "accept_A", "accept_B", "accept_edited", "reject"},
               "only_A": {"accept_A", "accept_edited", "reject"}, "only_B": {"accept_B", "accept_edited", "reject"},
               "partial": {"accept_A", "accept_B", "accept_both", "accept_edited", "reject"}}
    seen, decisions = set(), []
    path = root / "adjudication" / name
    with path.open(encoding="utf-8-sig") as source:
        for line_no, line in enumerate(source, 1):
            try:
                row = json.loads(line)
                if set(row) != {"record", "format", "chunk_id", "item_id", "decision", "fact", "citation", "rationale"}:
                    raise ValueError("decision fields")
                if row["record"] != "decision" or row["format"] != "kgb.well_adjudication/1" or row["chunk_id"] not in texts:
                    raise ValueError("decision identity")
                if not isinstance(row["rationale"], str) or not row["rationale"].strip(): raise ValueError("rationale required")
                identity, decision = row["item_id"], row["decision"]
                if not isinstance(identity, str) or not identity or identity in seen: raise ValueError("duplicate decision")
                seen.add(identity)
                item = items.get(identity)
                if decision == "add":
                    if item is not None: raise ValueError("add requires a distinct decision id")
                elif item is None or item["chunk_id"] != row["chunk_id"] or decision not in allowed[item["kind"]]:
                    raise ValueError("decision not allowed for item")
                text = texts[row["chunk_id"]]
                chosen = []
                if decision in {"accept_edited", "add"}:
                    if not isinstance(row["fact"], dict) or "annotator" in row["fact"]: raise ValueError("edited fact shape")
                    fact = resolve_fact(WellFact.model_validate({**row["fact"], "annotator": "adjudicated"}), text)
                    if fact.chunk_id != row["chunk_id"]: raise ValueError("edited fact chunk mismatch")
                    chosen = [_plain(fact)]
                else:
                    if row["fact"] is not None: raise ValueError("unexpected edited fact")
                    if decision in {"keep", "accept_A"}: chosen = [item["A"]]
                    elif decision == "accept_B": chosen = [item["B"]]
                    elif decision == "accept_both": chosen = [item["A"], item["B"]]
                if decision != "keep":
                    citation = row["citation"]
                    if not isinstance(citation, dict) or set(citation) != {"text", "occ"} or not citation["text"] or type(citation["occ"]) is not int or citation["occ"] < 0:
                        raise ValueError("citation required")
                    citation = resolve_span(citation, text)
                    evidence = chosen if decision != "reject" else [r for r in (item["A"], item["B"]) if r]
                    if not evidence or any(not (citation["start"] < f["evidence"]["end"] and f["evidence"]["start"] < citation["end"]) for f in evidence):
                        raise ValueError("citation does not overlap evidence")
                elif row["citation"] is not None:
                    resolve_span(row["citation"], text)
                decisions.append({**row, "chosen": chosen})
            except (ValueError, KeyError, TypeError) as exc:
                if issues is not None:
                    issues.append({"file": "adjudication/" + name, "line": line_no, "path": "decision", "reason": "invalid decision"})
                    continue
                reason = "invalid json" if isinstance(exc, json.JSONDecodeError) else str(exc) if type(exc) is ValueError else type(exc).__name__
                raise ConfigError(f"adjudication/{name}:{line_no}: decision: {reason}") from exc
    if not set(items) <= seen:
        if issues is None: raise ConfigError(f"{name}: missing item decisions")
        issues.append({"file": "adjudication/" + name, "line": 1, "path": "decision", "reason": "missing item decisions"})
    return decisions


def merge(cfg) -> dict:
    """Merge sealed decisions mechanically; never choose an annotation on its merits."""
    root = cfg["root"]
    _freeze(cfg)
    _verify_seal(cfg, "adjudicator")
    if (root / "adjudicated.jsonl").exists() or (root / "seals/adjudicated.json").exists(): raise ConfigError("adjudicated output exists")
    records, counts, partitions = _merged_records(cfg)
    write_jsonl(root / "adjudicated.jsonl", records)
    return {"decisions": dict(counts), "partitions": dict(partitions), **_write_seal(cfg, "adjudicated", ["adjudicated.jsonl"])}


def _merged_records(cfg):
    """Build the deterministic adjudicated records without writing output."""
    annotator_a, annotator_b = (_annotations(cfg, role) for role in cfg["annotators"])
    folder, expected, present = _role_files(cfg, "adjudicator")
    if present != expected: raise ConfigError("missing decision files")
    chosen, counts, records = {}, Counter(), []
    for name in sorted(present):
        for decision in _decisions(cfg, name):
            counts[decision["decision"]] += 1
            for value in decision["chosen"]:
                origin = {"keep": "agreed", "accept_A": "A", "accept_B": "B", "accept_edited": "edited", "add": "added"}.get(decision["decision"], "A" if value == decision["chosen"][0] else "B")
                row = {**value, "annotator": "adjudicated", "origin": origin, "decision_id": decision["item_id"]}
                chosen.setdefault(decision["chunk_id"], []).append(row)
    partitions = Counter()
    for packet in _packets(cfg).values():
        for chunk in packet:
            identity = chunk["chunk_id"]
            rows = chosen.get(identity, [])
            unreadable = any(facts.statuses[identity]["status"] == "unreadable" for facts in (annotator_a, annotator_b))
            records.append({"record": "chunk", "format": "kgb.well_annotation/1", "annotator": "adjudicated", "chunk_id": identity,
                            "status": "unreadable" if unreadable else "annotated" if rows else "no_facts", "n_facts": len(rows),
                            "note": "person name present" if unreadable else ""})
            for number, row in enumerate(rows, 1):
                row["fact_no"] = number
                parsed = WellFact.model_validate(row)
                if not unreadable: partitions[partition(parsed)] += 1
                records.append(row)
    return records, counts, partitions


def agreement(cfg, out_dir: Path, rules: Path | None) -> dict:
    """Report sealed annotator agreement separately for dev, test and all chunks."""
    verify(cfg)
    root, policy = cfg["root"], _policy(cfg)
    annotator_a, annotator_b = (_annotations(cfg, role) for role in cfg["annotators"])
    split = read_object(root / "split.json")
    texts = {r["chunk_id"]: r["text"] for packet in _packets(cfg).values() for r in packet}
    adjudicated = load_annotations(root / "adjudicated.jsonl", texts)
    unreadable = {k for k, v in adjudicated.statuses.items() if v["status"] == "unreadable"}
    result = {"label": "AI-gold (agent-annotated, adjudicated; not human gold)", "n_unreadable": len(unreadable),
              "unreadable_chunks": sorted(unreadable), "scopes": {}, "decision_counts": dict(Counter(r["decision"] for path in (root / "adjudication").glob("decisions_*.jsonl") for r in iter_jsonl(path)))}
    items = {r["item_id"]: r for path in (root / "adjudication").glob("packet_*.jsonl") for r in iter_jsonl(path) if "item_id" in r}
    result["keep_time_differs"] = sum(r["decision"] == "keep" and
                                    items[r["item_id"]]["A"].get("time") != items[r["item_id"]]["B"].get("time")
                                    for path in (root / "adjudication").glob("decisions_*.jsonl") for r in iter_jsonl(path))
    for scope, ids in (("dev", set(split["dev"])), ("test", set(split["test"])), ("all", set(split["dev"] + split["test"]))):
        chunk_ids = {k for k in texts if k.rsplit("#", 1)[0] in ids}
        sets = [[f for f in source if f.chunk_id in chunk_ids and f.chunk_id not in unreadable] for source in (annotator_a, annotator_b)]
        positives = [[f for f in source if partition(f) == "G+"] for source in sets]
        iaa = iaa_score(sets[0], sets[1], policy)
        pairs = match(positives[0], positives[1], policy, "L3", symmetric=True)
        exact, iou = 0, []
        for i, j in pairs:
            a, b = positives[0][i], positives[1][j]
            exact += (a.object.get("start"), a.object.get("end")) == (b.object.get("start"), b.object.get("end"))
            inter = max(0, min(a.evidence["end"], b.evidence["end"]) - max(a.evidence["start"], b.evidence["start"]))
            union = max(a.evidence["end"], b.evidence["end"]) - min(a.evidence["start"], b.evidence["start"])
            iou.append(inter / union if union else 0)
        row = {"n": len(chunk_ids), "n_unreadable": len(chunk_ids & unreadable), "iaa": iaa,
               "span_exact": exact / len(pairs) if pairs else None, "evidence_iou": sum(iou) / len(iou) if iou else None,
               "chunk_status_agreement": sum(annotator_a.statuses[k]["status"] == annotator_b.statuses[k]["status"] for k in chunk_ids) / len(chunk_ids) if chunk_ids else None,
               "rates": {role: {category: sum(partition(f) == category for f in values) / len(values) if values else None for category in ("G?", "Gother", "G-")}
                         for role, values in zip(cfg["annotators"], sets)}}
        if rules:
            predicted = [WellFact.model_validate(r) for r in iter_jsonl(rules / "rules.jsonl") if r["record"] == "fact" and r["chunk_id"] in chunk_ids]
            reference = AnnotationFacts([f for f in adjudicated if f.chunk_id in chunk_ids], {k: v for k, v in adjudicated.statuses.items() if k in chunk_ids})
            predicted = [p for p in predicted if p.chunk_id not in unreadable]
            row["rules_vs_ai_gold"] = score(reference, [p for p in predicted if partition(p) == "G+"], policy)
            row["rules_vs_ai_gold"]["excluded_predictions"] = dict(Counter(partition(p) for p in predicted if partition(p) != "G+"))
        result["scopes"][scope] = row
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "agreement.json", result)
    lines = [result["label"], "", "| Scope | n | L1 F1 | L2 F1 | L3 F1 | n_unreadable |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, row in result["scopes"].items(): lines.append(f"| {name} | {row['n']} | {row['iaa']['L1']['f1']} | {row['iaa']['L2']['f1']} | {row['iaa']['L3']['f1']} | {row['n_unreadable']} |")
    lines += ["", "Span agreement, chunk statuses, rates, decision counts and rules per relation:", "", cj(result), "",
              "LLM annotators can share errors; agreement is not correctness. The adjudicator shares the model family of annotator A; A/B anonymisation mitigates this. Blindness is procedural; packet IDs carry report serials. No domain expert reviewed the guideline."]
    (out_dir / "agreement.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result
