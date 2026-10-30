"""Collect intrinsic, gold, QA, induction, and incremental LLM cost tables."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from kgbuilder.core import config, text
from kgbuilder.core.config import AblationInduce
from kgbuilder.core.project import PROJECT_ROOT

FORMAT = "kgb.ablation/1"
CHECKS = ["G1", "G2", "G3", "G4.q1", "G4.q2", "G4.q3", "G4.q4", "G5", "G6"]
# Fixed fragments from EDC prompt_templates/sd_template.txt and sc_template.txt.
SD_MARK = "write a description to express the meaning of the relation"
VERIFY_MARK = "is there any relation appropriate to replace it?"


def request_kind(row: dict) -> str:
    stage = row.get("stage", "")
    if stage == "extract":
        return "extract"
    for prefix, kind in (("judge", "judge"), ("induce", "concept"), ("qa.", "qa")):
        if stage.startswith(prefix):
            return kind
    if stage == "canon":
        body = "\n".join(str(m.get("content") or "") for m in row.get("messages", []))
        if SD_MARK in body:
            return "sd"
        if VERIFY_MARK in body:
            return "verify"
        return "canon_other"
    return "other"


def modules(flags: dict) -> str:
    return " ".join(letter if flags.get(key) else "-" for key, letter in
                    zip(("resolve", "canon", "temporal", "validate", "judge"), "RCTVJ"))


def new_calls(rows: list[dict], seen: set[str], index: dict) -> dict:
    first = {}
    for row in rows:
        first.setdefault(row["key"], row)
    fresh = [row for key, row in first.items() if key not in seen]
    seen.update(first)
    seconds = sum(row.get("seconds", 0) if row.get("seconds", 0) > 0 else index.get(row["key"], {}).get("seconds", 0) for row in fresh)
    return {"calls": len(rows), "new_calls": len(fresh), "new_seconds": round(seconds, 1),
            "new_by_stage": dict(sorted(Counter(row.get("stage", "unknown") for row in fresh).items()))}


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(path):
    return text.read_jsonl(path) if path.is_file() else []


def level_row(run: str, level: str, level_dir: Path, result_code: int | None, seen: set[str], index: dict) -> dict:
    row = {"run": run, "level": level, "modules": None,
           "status": "skipped" if result_code is None else "ok" if result_code == 0 else "failed", "exit_code": result_code}
    row.update(dict.fromkeys(("entities", "entities_literal", "statements", "rejected", "rejected_by_reason", "er_reduction",
                              "predicate_types", "predicate_redundancy", "grounding", "temporal_statements",
                              "showcase", "webnlg", "judge", "llm", "replay_wall_seconds",
                              "ground_rules", "flagged", "flagged_by_reason", "webnlg_strict")))
    if row["status"] != "ok":
        if result_code is not None:
            new_calls(_rows(level_dir / "llm_calls.jsonl"), seen, index)
        return row
    metrics = _json(level_dir / "metrics.json")
    predicates = {s["predicate"] for s in _json(level_dir / "graph.json")["statements"]}
    row.update({key: metrics[key] for key in ("entities", "entities_literal", "rejected_by_reason", "er_reduction", "temporal_statements")})
    row.update(statements=metrics["statements_accepted"], rejected=metrics["statements_rejected"],
               ground_rules=metrics.get("ground_rules"), flagged=metrics.get("statements_flagged"),
               flagged_by_reason=metrics.get("flagged_by_reason"),
               predicate_types=len(predicates), predicate_redundancy=text.predicate_redundancy(predicates),
               grounding={key: round(metrics["grounding"].get(key, 0) / metrics["candidates"], 3) if metrics["candidates"] else 0.0
                          for key in ("exact", "partial", "none")},
               llm=new_calls(_rows(level_dir / "llm_calls.jsonl"), seen, index),
               replay_wall_seconds=round(sum(metrics["stage_seconds"].values()), 1))
    if (level_dir / "eval/showcase_checks.json").is_file():
        status = _json(level_dir / "eval/showcase_checks.json")["status"]
        failed = [check for check in CHECKS if (status.get("G4", {}).get(check[3:]) if check.startswith("G4.") else status.get(check)) != "PASS"]
        row["showcase"] = {"passed": len(CHECKS) - len(failed), "total": len(CHECKS), "failed": failed, "gold_recall": status["gold_recall"]}
    if (level_dir / "eval/scores.json").is_file():
        scores = _json(level_dir / "eval/scores.json")
        row["webnlg"] = {**{k: scores["strict"][k] for k in ("P", "R", "F1")},
                         **{name + "_F1": scores["per_tag"][tag]["strict"]["F1"] for name, tag in
                            (("subject", "subjects"), ("predicate", "predicates"), ("object", "objects"))},
                         "full_triple_F1": scores["full_triple"]["F1"]}
    if (level_dir / "eval/strict/scores.json").is_file():
        scores = _json(level_dir / "eval/strict/scores.json")
        row["webnlg_strict"] = {**{k: scores["strict"][k] for k in ("P", "R", "F1")},
                                **{name + "_F1": scores["per_tag"][tag]["strict"]["F1"] for name, tag in
                                   (("subject", "subjects"), ("predicate", "predicates"), ("object", "objects"))},
                                "full_triple_F1": scores["full_triple"]["F1"]}
    if (level_dir / "judge.jsonl").is_file():
        judges = _rows(level_dir / "judge.jsonl")
        row["judge"] = {"judged": len(judges), "yes": sum(r["verdict"] == "yes" for r in judges),
                        "no": sum(r["verdict"] == "no" for r in judges),
                        "unparsed": sum(r["verdict"] is None and r["error"] is None for r in judges),
                        "errors": sum(r["error"] is not None for r in judges)}
    return row


def qa_block(qa_dir: Path, run: str, levels: list[str], index: dict) -> dict | None:
    if not (qa_dir / "qa.json").is_file():
        return None
    report = _json(qa_dir / "qa.json")
    calls, seen, rows = _rows(qa_dir / "llm_calls.jsonl"), set(), []
    for row in report["rows"]:
        cost = new_calls([r for r in calls if r.get("stage") == "qa." + row["row"]], seen, index)
        rows.append({**{k: row[k] for k in ("row", "graph", "em", "f1", "no_context", "seeded")},
                     **{k: v for k, v in row.items() if k.startswith("recall@")},
                     "llm_calls": row["llm"]["calls"], "new_calls": cost["new_calls"]})
    return {"run": run, "levels": levels, "qa_json": (qa_dir / "qa.json").relative_to(PROJECT_ROOT).as_posix(),
            "recall_k": report["recall_k"], "rows": rows, "graphs": {label: {key: value[key] for key in
             ("statements", "evidence_pair_recall", "evidence_entity_recall")} for label, value in report["graphs"].items()},
            "pairwise": report["pairwise"]}


def induce_block(entry: AblationInduce) -> dict:
    row = {"label": entry.label, "status": "not run"}
    row.update(dict.fromkeys(("open_types", "canonical_types", "induced_types", "open_redundancy", "induced_redundancy",
                              "statement_coverage", "entities_asked", "entities_typed", "top_types", "induce_llm_calls",
                              "pass2_statements", "pass2_predicate_types", "pass2_redundancy", "pass2_unmapped",
                              "pass2_calls", "pass2_new_calls", "pass2_new_by_kind", "pass2_new_verify_calls",
                              "pass2_fresh_calls", "pass1_log_missing")))
    pass1 = None
    if (entry.induce_dir / "summary.json").is_file():
        summary = _json(entry.induce_dir / "summary.json")
        pass1 = PROJECT_ROOT / summary["source_run"] / "llm_calls.jsonl"
        row["pass1_log_missing"] = not pass1.is_file()
        row.update(status="ok", **{key: summary["relations"][key] for key in
                                   ("open_types", "canonical_types", "induced_types", "open_redundancy", "induced_redundancy")})
        row.update(statement_coverage=summary["coverage"]["statements"], entities_asked=summary["coverage"]["entities_asked"],
                   entities_typed=summary["coverage"]["entities_typed"],
                   top_types=[list(item) for item in sorted(summary["entity_types"].items(), key=lambda x: (-x[1], x[0]))[:5]],
                   induce_llm_calls=summary["llm"]["llm_calls"])
    path = entry.pass2_run
    if path is not None and (path / "metrics.json").is_file() and (path / "graph.json").is_file():
        metrics = _json(path / "metrics.json")
        predicates = {s["predicate"] for s in _json(path / "graph.json")["statements"]}
        calls = _rows(path / "llm_calls.jsonl")
        row.update(pass2_statements=metrics["statements_accepted"], pass2_predicate_types=len(predicates),
                   pass2_redundancy=text.predicate_redundancy(predicates), pass2_unmapped=metrics["canon"]["unmapped"],
                   pass2_calls=len(calls),
                   pass2_fresh_calls=sum(not r.get("cache_hit", False) and not r.get("miss", False) for r in calls),
                   pass1_log_missing=pass1 is None or not pass1.is_file())
        if not row["pass1_log_missing"]:
            seen = {r["key"] for r in _rows(pass1)}
            first = {}
            for call in calls:
                first.setdefault(call["key"], call)
            kinds = Counter(request_kind(call) for key, call in first.items() if key not in seen)
            row.update(pass2_new_calls=new_calls(calls, seen, {})["new_calls"],
                       pass2_new_by_kind=dict(sorted(kinds.items())),
                       pass2_new_verify_calls=kinds.get("verify", 0))
    return row


def collect(abl, root: Path, built: dict, qa: dict | None, index: dict, mock: bool, baselines: dict, plan: bool = False) -> dict:
    rows = []
    for entry in abl.runs:
        cfg = config.load_config(entry.config, sets=entry.sets, mock=mock)
        if cfg.run.name not in built:
            continue
        seen = set()
        for level in entry.levels or abl.levels:
            result = built[cfg.run.name][level]
            row = level_row(cfg.run.name, level, root / cfg.run.name / level,
                            None if result is None else result.exit_code, seen, index)
            flags = config.effective_flags(config.from_resolved({**cfg.model_dump(mode="json"), "ablation": level}))
            row["modules"] = modules(flags)
            rows.append(row)
    return {"format": FORMAT, "name": abl.name, "levels": abl.levels, "mock": mock, "plan": plan, "rows": rows,
            "baselines": baselines, "qa": qa, "induce": [induce_block(entry) for entry in abl.induce]}


def render_md(table: dict) -> str:
    """Render the five evaluation tables without hiding failed cells."""
    dash = "\u2013"
    def fmt(value):
        if value is None:
            return dash
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value).replace("|", "\\|").replace("\n", " ")
    lines = [f'# Ablation {table["name"]} ({FORMAT})',
             f'mock: {str(table["mock"]).lower()}; levels: {", ".join(table["levels"])}. H1: rows webnlg10 / webnlg10_kggen / webnlg10_auto. H2: cumulative module changes A0 -> A5 within each run (not entity-resolution-only). H3: section 4 vs the graph columns (not measured when section 4 reads "QA: not run").']
    if table.get("plan"):
        lines[1] += "; plan: true (counts only; judge/reader answers are empty)"
    def heading(title, columns, note=None):
        lines.extend(["", title, ""])
        if note:
            lines.extend([note, ""])
        lines.extend(["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"])
    def cells(values):
        lines.append("| " + " | ".join(fmt(v) for v in values) + " |")
    def metrics(row, values):
        if row["status"] != "ok":
            message = f'FAILED (exit {row["exit_code"]})' if row["status"] == "failed" else "skipped (--exclude)"
            return [message] * len(values)
        return values
    heading("## 1. Intrinsic graph metrics", ["run", "level", "modules", "build-stage entities", "build-stage literals", "accepted statements", "rejected", "ER reduction (build-stage)", "graph predicate types", "graph predicate redundancy", "grounding e/p/n (candidates)", "temporal (accepted)"],
            "Populations: build-stage entities, build-stage literals and ER reduction are pre-validation counts (metrics.json, before validate/judge); accepted statements and graph predicate types are the exported graph.json.")
    for row in table["rows"]:
        grounding = row.get("grounding")
        values = [row.get(k) for k in ("entities", "entities_literal", "statements", "rejected", "er_reduction", "predicate_types", "predicate_redundancy")]
        values += ["/".join(fmt(grounding[k]) for k in ("exact", "partial", "none")) if grounding else None, row.get("temporal_statements")]
        cells([row["run"], row["level"], row["modules"], *metrics(row, values)])
    heading("## 2. Gold", ["run", "level", "showcase checks", "gold_recall", "strict P", "strict R", "strict F1", "subject F1", "predicate F1", "object F1", "judge yes/no/unparsed"])
    for row in table["rows"]:
        showcase, web, judge = row.get("showcase"), row.get("webnlg") or {}, row.get("judge")
        checks = None if showcase is None else f'{showcase["passed"]}/{showcase["total"]}' + (" (FAIL: " + ", ".join(showcase["failed"]) + ")" if showcase["failed"] else "")
        values = [checks, showcase["gold_recall"] if showcase else None, *[web.get(k) for k in ("P", "R", "F1", "subject_F1", "predicate_F1", "object_F1")],
                  "/".join(str(judge[k]) for k in ("yes", "no", "unparsed")) if judge else None]
        cells([row["run"], row["level"], *metrics(row, values)])
    for name, baseline in table["baselines"].items():
        scores = baseline["webnlg"]
        cells([name, baseline["label"], None, None, *[scores["strict"][k] for k in ("P", "R", "F1")],
               *[scores["per_tag"][k]["strict"]["F1"] for k in ("subjects", "predicates", "objects")], None])
    heading("## 3. LLM cost (new calls = keys not seen at an earlier level of the same run; seconds as recorded live)",
            ["run", "level", "exit", "LLM calls", "new calls", "new LLM s (recorded)", "new calls by stage", "replay wall s"])
    for row in table["rows"]:
        cost = row.get("llm") or {}
        values = [cost.get(k) for k in ("calls", "new_calls", "new_seconds")]
        values += [", ".join(f"{key}: {value}" for key, value in cost.get("new_by_stage", {}).items()) or None, row.get("replay_wall_seconds")]
        cells([row["run"], row["level"], row["exit_code"], *metrics(row, values)])
    qa = table["qa"]
    lines.extend(["", "## 4. QA on 2Wiki (H3)", ""])
    if qa is None or "error" in qa:
        lines.append("QA: not run (" + (f'exit {qa["error"]}' if qa else "no qa block") + ")")
    else:
        recalls = [f"recall@{k}" for k in qa["recall_k"]]
        heading("", ["row", "EM", "F1", *["R@" + str(k) for k in qa["recall_k"]], "no_context", "seeded", "LLM calls", "new calls"])
        for row in qa["rows"]:
            cells([row[k] for k in ("row", "em", "f1", *recalls, "no_context", "seeded", "llm_calls", "new_calls")])
        heading("", ["graph", "statements", "evidence_pair_recall", "evidence_entity_recall"])
        for label, graph in qa["graphs"].items():
            cells([label, *[graph[k] for k in ("statements", "evidence_pair_recall", "evidence_entity_recall")]])
    lines.extend(["", "## 5. Schema induction", ""])
    if not table["induce"]:
        lines.append("Schema induction: not configured")
    else:
        heading("", ["label", "open types", "canonical types", "induced types", "redundancy open \u2192 induced", "statement coverage", "entities typed / asked", "top entity types", "pass-2 statements", "pass-2 predicate types", "pass-2 redundancy", "pass-2 edc_unmapped", "pass-2 calls total / new vs pass 1 / new verify / fresh", "induce LLM calls"])
        for row in table["induce"]:
            if row["status"] != "ok":
                cells([row["label"], *["not run"] * 13])
                continue
            cells([row["label"], row["open_types"], row["canonical_types"], row["induced_types"],
                   fmt(row["open_redundancy"]) + " -> " + fmt(row["induced_redundancy"]), row["statement_coverage"],
                   f'{row["entities_typed"]} / {row["entities_asked"]}', ", ".join(f"{k}: {v}" for k, v in row["top_types"]),
                   *[row[k] for k in ("pass2_statements", "pass2_predicate_types", "pass2_redundancy", "pass2_unmapped")],
                   None if row["pass2_calls"] is None else " / ".join(fmt(row[k]) for k in
                       ("pass2_calls", "pass2_new_calls", "pass2_new_verify_calls", "pass2_fresh_calls")),
                   row["induce_llm_calls"]])
    heading("## 6. WINDOW_GROUNDING seams", ["run", "level", "flagged", "flagged by reason", "grounding rules e/w/c/o/ch/n", "strict-level F1"])
    for row in table["rows"]:
        if row["status"] != "ok":
            continue
        rules = row.get("ground_rules")
        cells([row["run"], row["level"], row.get("flagged"), row.get("flagged_by_reason"),
               "/".join(str(rules.get(k, 0)) for k in ("exact", "window", "coref", "overlap", "chunk", "none")) if rules is not None else None,
               (row.get("webnlg_strict") or {}).get("F1")])
    return "\n".join(lines) + "\n"


def write(table: dict, root: Path) -> None:
    text.write_json(root / "ablation.json", table)
    (root / "ablation.md").write_text(render_md(table), encoding="utf-8", newline="\n")
