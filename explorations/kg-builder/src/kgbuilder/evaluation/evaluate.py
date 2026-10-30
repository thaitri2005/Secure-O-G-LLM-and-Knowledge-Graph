"""Offline golden checks and guarded EDC WebNLG evaluation."""
from __future__ import annotations

import ast
import logging
import math
import os
import re
import subprocess
import time
from pathlib import Path

import yaml

from kgbuilder.core.config import KgbError, PipelineConfig, project_path
from kgbuilder.core.contracts import GraphRecord, flagged
from kgbuilder.build.publish.export import webnlg_prediction_lines
from kgbuilder.runtime.onprem import PROJECT_ROOT, blocked_count
from kgbuilder.core.text import cj, holds_at, read_jsonl, surface_key, write_json, write_jsonl

LOG = logging.getLogger("kgb")
_SCORE = re.compile(r"(Precision|Recall|F1):\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)")


def parse_eval_txt(text: str) -> dict:
    """Parse the four total scores, per-tag strict/exact, and full-triple scores."""
    lines = text.splitlines()
    totals = {"ent_type": {}, "partial": {}, "strict": {}, "exact": {}}
    section_names = {"Ent_type": "ent_type", "Partial": "partial", "Strict": "strict", "Exact": "exact"}
    current = None
    per_tag = {}
    tag = None
    full = {}
    in_tags = False
    for raw in lines:
        title = raw.strip()
        if title == "Scores per tag":
            in_tags = True
            current = None
            continue
        if title == "Full triple scores":
            current = full
            continue
        if title in section_names:
            kind = section_names[title]
            if in_tags:
                if tag is None:
                    continue
                current = per_tag.setdefault(tag, {}).setdefault(kind, {})
            else:
                current = totals[kind]
            continue
        if in_tags and title in {"Subjects", "Predicates", "Objects"}:
            tag = title.lower()
            per_tag.setdefault(tag, {})
            current = None
            continue
        for metric, value in _SCORE.findall(title):
            if current is not None:
                current[{"Precision": "P", "Recall": "R", "F1": "F1"}[metric]] = float(value)
    if any(set(score) != {"P", "R", "F1"} for score in [*totals.values(), full]):
        raise KgbError(6, "incomplete EDC evaluator score output")
    per_tag = {tag: {kind: scores[kind] for kind in ("strict", "exact")} for tag, scores in per_tag.items()}
    return {"ent_type": totals["ent_type"], "partial": totals["partial"], "strict": totals["strict"],
            "exact": totals["exact"], "per_tag": per_tag, "full_triple": full}


def _contained(path: Path, key: str) -> Path:
    path = Path(path).resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise KgbError(2, f"{key}: path outside project") from exc
    return path


def run_webnlg_evaluator(pred: Path, ref: Path, workdir: Path, edc_python: Path,
                         timeout_s: int = 1800) -> dict:
    """Run the upstream scorer through the guarded Python 3.9 worker."""
    pred, ref, workdir = _contained(pred, "prediction"), _contained(ref, "reference"), _contained(workdir, "workdir")
    workdir.mkdir(parents=True, exist_ok=True)
    net_log = workdir / "net_eval.jsonl"
    env = {"PYTHONPATH": str(PROJECT_ROOT / "src"), "PYTHONHASHSEED": "0", "PYTHONUTF8": "1",
           "PYTHONDONTWRITEBYTECODE": "1"}
    inherited = os.environ.copy()
    inherited.update(env)
    command = [str(_contained(edc_python, "edc_python")), "-m", "kgbuilder.build.refine.edc_worker",
               "--evaluate", str(pred), str(ref), "--net-log", str(net_log)]
    try:
        completed = subprocess.run(command, cwd=workdir, env=inherited, capture_output=True,
                                   text=True, encoding="utf-8", timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        (workdir / "eval.txt").write_text(out, encoding="utf-8", newline="\n")
        (workdir / "evaluator.log").write_text(err, encoding="utf-8", newline="\n")
        raise KgbError(6, "EDC evaluator timeout") from exc
    (workdir / "eval.txt").write_text(completed.stdout, encoding="utf-8", newline="\n")
    (workdir / "evaluator.log").write_text(completed.stderr, encoding="utf-8", newline="\n")
    if blocked_count(net_log):
        raise KgbError(4, "EDC evaluator network guard blocked a request")
    if completed.returncode:
        tail = "\n".join(completed.stderr.splitlines()[-40:])
        LOG.error("EDC evaluator exited %s:\n%s", completed.returncode, tail)
        raise KgbError(6, f"EDC evaluator exited {completed.returncode}:\n{tail}")
    return parse_eval_txt(completed.stdout)


def permutation_report(pred_lines: list[str], ref_lines: list[str]) -> list[dict]:
    return [{"doc": index, "n_pred": len(ast.literal_eval(pred)), "n_gold": len(ast.literal_eval(ref)),
             "perm": math.perm(len(ast.literal_eval(pred)), len(ast.literal_eval(ref)))}
            for index, (pred, ref) in enumerate(zip(pred_lines, ref_lines))]


def eval_webnlg(run_dir: Path, cfg: PipelineConfig) -> dict:
    """Write predictions/references and score them with the guarded worker."""
    run_dir = _contained(run_dir, "run")
    if cfg.corpus.format != "webnlg_txt" or cfg.eval.webnlg_reference is None:
        raise KgbError(2, "webnlg evaluation requires webnlg_txt corpus and reference")
    record = GraphRecord.model_validate_json((run_dir / "graph.json").read_text(encoding="utf-8"))
    docs = record.documents[:cfg.corpus.limit] if cfg.corpus.limit else record.documents
    reference = _contained(cfg.eval.webnlg_reference, "eval.webnlg_reference")
    ref_lines = reference.read_text(encoding="utf-8").splitlines()
    if cfg.corpus.limit:
        ref_lines = ref_lines[:cfg.corpus.limit]
    if len(ref_lines) != len(docs):
        raise KgbError(2, f"WebNLG reference has {len(ref_lines)} lines for {len(docs)} documents")
    eval_dir = run_dir / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    pred_lines = webnlg_prediction_lines(record, docs)
    (eval_dir / "pred.txt").write_text("\n".join(pred_lines) + "\n", encoding="utf-8", newline="\n")
    (eval_dir / "ref.txt").write_text("\n".join(ref_lines) + "\n", encoding="utf-8", newline="\n")
    permutations = permutation_report(pred_lines, ref_lines)
    write_json(eval_dir / "scores.json", {"per_doc": permutations})
    for row in permutations:
        if row["perm"] > 5_000_000:
            LOG.warning("WebNLG permutation cost document %s: %s", row["doc"], row["perm"])
    started = time.monotonic()
    parsed = run_webnlg_evaluator(eval_dir / "pred.txt", eval_dir / "ref.txt", eval_dir,
                                   cfg.canon.edc_python, timeout_s=1800)
    elapsed = round(time.monotonic() - started, 1)
    scores = {**parsed, "per_doc": permutations, "evaluator_seconds": elapsed}
    write_json(eval_dir / "scores.json", scores)
    strict_scores = None
    strict_path = run_dir / "graph_strict.json"
    if strict_path.is_file():
        strict = GraphRecord.model_validate_json(strict_path.read_text(encoding="utf-8"))
        if {s.statement_id for s in strict.statements} != {s.statement_id for s in record.statements}:
            strict_dir = eval_dir / "strict"
            strict_dir.mkdir(parents=True, exist_ok=True)
            strict_lines = webnlg_prediction_lines(strict, docs)
            (strict_dir / "pred.txt").write_text("\n".join(strict_lines) + "\n", encoding="utf-8", newline="\n")
            (strict_dir / "ref.txt").write_text("\n".join(ref_lines) + "\n", encoding="utf-8", newline="\n")
            started = time.monotonic()
            strict_scores = run_webnlg_evaluator(strict_dir / "pred.txt", strict_dir / "ref.txt", strict_dir,
                                                  cfg.canon.edc_python, timeout_s=1800)
            strict_scores = {**strict_scores, "evaluator_seconds": round(time.monotonic() - started, 1)}
            write_json(strict_dir / "scores.json", {**strict_scores, "per_doc": permutation_report(strict_lines, ref_lines)})
    logs = [run_dir / "net.jsonl", PROJECT_ROOT / ".cache/kgb/net" / f"core_{os.getpid()}.jsonl",
            eval_dir / "net_eval.jsonl", eval_dir / "strict/net_eval.jsonl"]
    rows = {cj([row.get(key) for key in ("kind", "target", "allowed")]): row
            for path in logs if path.is_file() for row in read_jsonl(path)}
    write_jsonl(run_dir / "net.jsonl", [rows[key] for key in sorted(rows)])
    if any(row.get("allowed") is False for row in rows.values()):
        raise KgbError(4, "network guard blocked a request during evaluation")
    result = {key: value for key, value in scores.items() if key != "per_doc"}
    if strict_scores is not None:
        result["strict_level"] = strict_scores
    return result


def _names(entity_rows):
    names = {}
    for row in entity_rows:
        values = [row["name"], *row.get("aliases", [])]
        for value in values:
            names.setdefault(surface_key(value), set()).add(row["entity_id"])
    return names


def _matches(statement, subject, predicate, object_, names):
    return (statement.predicate == predicate and
            statement.subject_id in names.get(surface_key(subject), set()) and
            statement.object_id in names.get(surface_key(object_), set()))


def eval_showcase(run_dir: Path, cfg: PipelineConfig) -> dict:
    """Run G1–G6 and gold recall against a completed showcase graph."""
    run_dir = _contained(run_dir, "run")
    record = GraphRecord.model_validate_json((run_dir / "graph.json").read_text(encoding="utf-8"))
    entity_rows = read_jsonl(run_dir / "entities.jsonl")
    names = _names(entity_rows)
    statements = [s for s in record.statements if s.status == "accepted"]
    docs = {doc.doc_id: doc for doc in record.documents}
    if cfg.eval.showcase_gold_dir is None:
        raise KgbError(2, "showcase evaluation requires eval.showcase_gold_dir")
    gold_dir = project_path(cfg.eval.showcase_gold_dir, "eval.showcase_gold_dir", True)
    gold_entities = read_jsonl(gold_dir / "gold_entities.jsonl")
    details = {}
    ibm = [row for row in entity_rows if {surface_key(row["name"]), *(surface_key(a) for a in row.get("aliases", []))} >=
           {"ibm", "international business machines", "international business machines corporation"}]
    research = [row for row in entity_rows if row["entity_id"] in names.get("ibm research", set())]
    details["G1"] = {"matches": [row["entity_id"] for row in ibm], "research_entities": [row["entity_id"] for row in research]}
    g1 = len(ibm) == 1 and bool(research) and all(row["entity_id"] != ibm[0]["entity_id"] for row in research)
    turing = [s for s in statements if _matches(s, "Alan Turing", "born_in", "London", names)]
    reverse = [s for s in statements if _matches(s, "London", "born_in", "Alan Turing", names)]
    spans = {e.span for s in turing for e in s.evidence}
    details["G2"] = {"matches": [s.statement_id for s in turing], "support_count": max((s.support_count for s in turing), default=0),
                     "spans": sorted(spans), "reverse": [s.statement_id for s in reverse]}
    g2 = any(s.support_count >= 2 and len({e.span for e in s.evidence}) >= 2 for s in turing) and not reverse
    acme = [s for s in statements if _matches(s, "Alice", "works_at", "Acme Labs", names)]
    nova = [s for s in statements if _matches(s, "Alice", "works_at", "Nova AI", names)]
    g3 = any(s.valid_from == "2021" and s.valid_to == "2024" for s in acme) and any(s.valid_from == "2024" and s.valid_to is None for s in nova)
    details["G3"] = {name: [{"statement_id": s.statement_id, "valid_from": s.valid_from,
                              "valid_to": s.valid_to} for s in values]
                     for name, values in [("acme", acme), ("nova", nova)]}
    queries = yaml.safe_load(project_path(cfg.eval.showcase_queries, "eval.showcase_queries", True).read_text(encoding="utf-8")) if cfg.eval.showcase_queries else []
    g4, qdetails = {}, {}
    for query in queries:
        # Evaluate object matches directly to retain aliases and exact-vs-contains semantics.
        found_ids = {s.object_id for s in statements if s.predicate == query["predicate"]
                     and s.subject_id in names.get(surface_key(query["subject"]), set())
                     and (query.get("at") is None or holds_at(s.valid_from, s.valid_to, query["at"]))}
        expected_sets = [names.get(surface_key(value), set()) for value in query["expect"]]
        covered = all(found_ids & expected for expected in expected_sets)
        expected_ids = set().union(*expected_sets)
        ok = covered and (found_ids <= expected_ids if query.get("at") is not None else True)
        qdetails[query["qid"]] = {"expected": query["expect"], "found": sorted(found_ids), "ok": ok}
        g4[query["qid"]] = "PASS" if ok else "FAIL"
    details["G4"] = qdetails
    g5_bad = []
    for statement in statements:
        for evidence in statement.evidence:
            document = docs.get(evidence.doc_id)
            if document is None or document.text[evidence.char_start:evidence.char_end] != evidence.text:
                g5_bad.append(statement.statement_id + ":" + evidence.span)
    details["G5"] = {"invalid": g5_bad}
    g5 = not g5_bad
    reversed_ids = [s.statement_id for s in statements if not flagged(s) and _matches(s, "IBM", "part_of", "research division", names)]
    details["G6"] = {"reversed": reversed_ids, "flagged": [s.statement_id for s in statements
                      if flagged(s) and _matches(s, "IBM", "part_of", "research division", names)]}
    gold_rows = read_jsonl(gold_dir / "gold_triples.jsonl")
    matched = 0
    for gold in gold_rows:
        if any(_matches(s, gold["subject"], gold["predicate"], gold["object"], names) and
               s.valid_from == gold.get("valid_from") and s.valid_to == gold.get("valid_to") for s in statements):
            matched += 1
    gold_recall = matched / len(gold_rows) if gold_rows else 0.0
    details["gold_recall"] = {"matched": matched, "total": len(gold_rows), "gold_entities": len(gold_entities)}
    result = {"G1": "PASS" if g1 else "FAIL", "G2": "PASS" if g2 else "FAIL", "G3": "PASS" if g3 else "FAIL",
              "G4": g4, "G5": "PASS" if g5 else "FAIL", "G6": "PASS" if not reversed_ids else "FAIL", "gold_recall": gold_recall}
    write_json(run_dir / "eval" / "showcase_checks.json", {"status": result, "details": details})
    return result
