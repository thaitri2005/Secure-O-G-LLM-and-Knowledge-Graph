"""Deterministic artifact-only error analysis and paired statistics."""
from __future__ import annotations

import ast
import json
import math
import random
import re
from collections import Counter
from pathlib import Path

from kgbuilder.core import text
from kgbuilder.core.config import ConfigError
from kgbuilder.core.project import PROJECT_ROOT

FORMAT = "kgb.analysis/1"
LEVELS = ("A0", "A1", "A2", "A3", "A4", "A5")
REFERENCE_RUNS = ("runs/reference/ablation_sentence_grounding", "runs/reference/twowiki10_sentence_grounding")


def fit_token_cost(rows: list[dict]) -> dict:
    """Fit nonnegative prompt/completion coefficients without an intercept."""
    rows = [r for r in rows if not r.get("cache_hit") and r.get("content") is not None
            and not r.get("miss") and r.get("stage", "").startswith("qa.") and r.get("usage", {}).get("prompt_tokens")]
    xx = sum(r["usage"]["prompt_tokens"] ** 2 for r in rows)
    yy = sum(r["usage"].get("completion_tokens", 0) ** 2 for r in rows)
    xy = sum(r["usage"]["prompt_tokens"] * r["usage"].get("completion_tokens", 0) for r in rows)
    xs = sum(r["usage"]["prompt_tokens"] * r["seconds"] for r in rows)
    ys = sum(r["usage"].get("completion_tokens", 0) * r["seconds"] for r in rows)
    det = xx * yy - xy * xy
    if len(rows) < 2 or det == 0:
        raise ConfigError("analyze --plan: no reference reader rows")
    chars = sum(len("".join(m["content"] for m in r["messages"])) for r in rows)
    return {"a": round(max(0, (xs * yy - ys * xy) / det), 4),
            "b": round(max(0, (ys * xx - xs * xy) / det), 4),
            "chars_per_token": round(chars / sum(r["usage"]["prompt_tokens"] for r in rows), 4), "n_rows": len(rows)}


def plan_cost(root: Path, kind, reference: list[Path]) -> dict:
    """Estimate sequential wall cost from distinct planned requests and local rows."""
    planned = {}
    for path in sorted(root.rglob("llm_calls.jsonl")):
        for row in _rows(path):
            if row.get("planned"):
                planned.setdefault(row["key"], row)
    references = [p for p in reference if p.is_dir()]
    fresh = [r for directory in references for path in sorted(directory.rglob("llm_calls.jsonl")) for r in _rows(path)
             if not r.get("cache_hit") and r.get("content") is not None and not r.get("miss") and r.get("usage", {}).get("prompt_tokens")]
    model = fit_token_cost(fresh)
    pooled = sum(r["usage"].get("completion_tokens", 0) for r in fresh) / len(fresh)
    means = {}
    for name in sorted({kind(r) for r in fresh}):
        values = [r["usage"].get("completion_tokens", 0) for r in fresh if kind(r) == name]
        means[name] = sum(values) / len(values)
    groups = {}
    for row in planned.values():
        name = kind(row)
        pt = len("".join(m["content"] for m in row["messages"])) / model["chars_per_token"]
        group = groups.setdefault(name, {"new_calls": 0, "tokens": 0., "low": 0., "high": 0.})
        group["new_calls"] += 1
        group["tokens"] += pt
        group["low"] += model["a"] * pt + model["b"] * means.get(name, pooled)
        group["high"] += model["a"] * pt + model["b"] * row["asked_max_tokens"]
    kinds = {name: {"new_calls": g["new_calls"], "mean_prompt_tokens_est": round(g["tokens"] / g["new_calls"], 1),
                    "minutes_low": round(g["low"] / 60, 1), "minutes_high": round(g["high"] / 60, 1)}
             for name, g in sorted(groups.items())}
    return {"format": "kgb.plan/2", "root": root.relative_to(PROJECT_ROOT).as_posix(),
            "reference": [p.relative_to(PROJECT_ROOT).as_posix() for p in references], "model": model, "kinds": kinds,
            "total": {"new_calls": len(planned), "minutes_low": round(sum(g["low"] for g in groups.values()) / 60, 1),
                      "minutes_high": round(sum(g["high"] for g in groups.values()) / 60, 1)}}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _rows(path: Path) -> list[dict]:
    return text.read_jsonl(path) if path.is_file() else []


def _triples(path: Path) -> list[set]:
    return [set(tuple(t) for t in ast.literal_eval(line))
            for line in path.read_text(encoding="utf-8").splitlines()]


def same_triple(a: tuple[str, str, str], b: tuple[str, str, str]) -> bool:
    return (bool(text.literal_forms(a[0]) & text.literal_forms(b[0]))
            and text.norm_surface(a[1]) == text.norm_surface(b[1])
            and bool(text.literal_forms(a[2]) & text.literal_forms(b[2])))


def classify(extra: tuple, missing: tuple) -> str:
    if same_triple(extra, missing):
        literal = any(text.match_key(extra[i]) != text.match_key(missing[i]) and
                      (text.NUMBER_UNIT.fullmatch(text._base_form(extra[i])) or
                       text.NUMBER_UNIT.fullmatch(text._base_form(missing[i])) or
                       len(text.literal_forms(extra[i]) | text.literal_forms(missing[i])) > 1)
                      for i in (0, 2))
        return "literal" if literal else "surface"
    if same_triple(extra, (missing[2], missing[1], missing[0])):
        return "direction"
    sides = [bool(text.literal_forms(extra[i]) & text.literal_forms(missing[i])) for i in (0, 2)]
    pred = text.norm_surface(extra[1]) == text.norm_surface(missing[1])
    if all(sides) and not pred:
        return "predicate"
    return "partial_entity" if pred and any(sides) else "other"


def sign_test(wins: int, losses: int) -> float:
    n = wins + losses
    return round(min(1.0, 2 * sum(math.comb(n, k) for k in range(min(wins, losses) + 1)) / 2 ** n), 4) if n else 1.0


def paired_bootstrap(diffs: list[float], n: int = 1000, seed: int = 0) -> dict:
    if not diffs:
        return {"n": 0, "mean": None, "lo": None, "hi": None}
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(diffs, k=len(diffs))) / len(diffs) for _ in range(n))
    return {"n": len(diffs), "mean": round(sum(diffs) / len(diffs), 4),
            "lo": round(means[int(.025 * n)], 4), "hi": round(means[int(.975 * n) - 1], 4)}


def _statement_rows(level: Path) -> list[dict]:
    return [r["record"] for r in _rows(level / "rejected.jsonl") if r.get("kind") == "statement"]


def _named(stmt: dict, entities: dict) -> tuple:
    return (entities[stmt["subject_id"]]["name"], stmt["predicate"], entities[stmt["object_id"]]["name"])


def webnlg_report(run_dir: Path) -> dict:
    levels = [level for level in LEVELS if (run_dir / level / "eval/pred.txt").is_file()]
    predictions = {level: _triples(run_dir / level / "eval/pred.txt") for level in levels}
    refs = {level: _triples(run_dir / level / "eval/ref.txt") for level in levels}
    residual, scores = {}, {}
    classes = ("literal", "surface", "direction", "predicate", "partial_entity", "other")
    for level in levels:
        items, f1s, extra_n, missing_n = [], [], 0, 0
        for doc, (pred, ref) in enumerate(zip(predictions[level], refs[level])):
            extra, missing = sorted(pred - ref), sorted(ref - pred)
            extra_n += len(extra)
            missing_n += len(missing)
            f1s.append(2 * len(pred & ref) / (len(pred) + len(ref)) if pred or ref else 1.0)
            for triple in extra:
                pairs = [(classes.index(classify(triple, other)), other) for other in missing]
                if pairs:
                    rank, other = min(pairs)
                    missing.remove(other)
                    items.append({"doc": doc, "class": classes[rank], "extra": triple, "missing": other})
                else:
                    items.append({"doc": doc, "class": "extra_only", "extra": triple, "missing": None})
            items.extend({"doc": doc, "class": "missing_only", "extra": None, "missing": t} for t in missing)
        scores[level] = f1s
        residual[level] = {"extra": extra_n, "missing": missing_n,
                           "counts": dict(sorted(Counter(i["class"] for i in items).items())), "items": items}
    transitions = []
    pairs = list(zip(levels, levels[1:]))
    # The pinned audit also compares A2 directly with A4 across temporal A3.
    if "A2" in levels and "A4" in levels and ("A2", "A4") not in pairs:
        pairs.append(("A2", "A4"))
    for earlier, later in pairs:
        target = run_dir / later
        entities = {r["entity_id"]: r for r in _rows(target / "entities.jsonl")}
        causes = {}
        for stmt in _statement_rows(target):
            s, p, o = _named(stmt, entities)
            causes[(stmt["source_doc_id"], (re.sub(r"\s+", "_", s), p, re.sub(r"\s+", "_", o)))] = ",".join(sorted(stmt["reasons"]))
        docs = _json(target / "graph.json").get("documents", [])
        old_flags = _json(run_dir / earlier / "manifest.json").get("flags", {})
        new_flags = _json(target / "manifest.json").get("flags", {})
        changes = {"from": earlier, "to": later, "lost": [], "gained": []}
        for doc, (old, new) in enumerate(zip(predictions[earlier], predictions[later])):
            doc_id = docs[doc]["doc_id"] if doc < len(docs) else str(doc)
            for key, triples in (("lost", old - new), ("gained", new - old)):
                for triple in sorted(triples):
                    cause = causes.get((doc_id, triple), "canon" if new_flags.get("canon") and not old_flags.get("canon") else "other")
                    changes[key].append({"doc": doc, "triple": triple, "cause": cause,
                                         "gold_correct": any(same_triple(triple, gold) for gold in refs[later][doc])})
        changes["bootstrap"] = paired_bootstrap([b - a for a, b in zip(scores[earlier], scores[later])])
        transitions.append(changes)
    return {"levels": levels, "transitions": transitions, "residual": residual,
            "per_doc_f1": scores, "f1_label": "harness exact-string F1, not EDC strict"}


def rejected_report(level_dir: Path) -> dict:
    rows = _statement_rows(level_dir)
    entities = {r["entity_id"]: r for r in _rows(level_dir / "entities.jsonl")}
    docs = {r["doc_id"]: r for r in _rows(level_dir / "documents.jsonl")}
    chunks = {r["chunk_id"]: r for r in _rows(level_dir / "chunks.jsonl")}
    items = []
    for row in rows:
        if "weak_evidence" not in row["reasons"]:
            continue
        ev = row["evidence_span"]
        chunk, doc = chunks[ev["chunk_id"]], docs[ev["doc_id"]]
        sentences = [text.surface_key(doc["text"][a:b]) for a, b in text.split_sentences(chunk["text"], chunk["char_start"])]
        sk, ok = [{text.match_key(n) for n in [entities[row[k]]["name"], *entities[row[k]]["aliases"]]}
                  for k in ("subject_id", "object_id")]
        subject_tokens = {t for name in sk for t in text.tokens(name) if len(t) >= 4 and t not in text.GROUND_STOPWORDS}
        si = [i for i, sentence in enumerate(sentences) if any(k in sentence for k in sk) or subject_tokens & set(text.tokens(sentence))]
        oi = [i for i, sentence in enumerate(sentences) if any(k in sentence for k in ok)]
        distance = min(abs(i - j) for i in si for j in oi) if si and oi else None
        items.append({"statement_id": row["statement_id"], "distance": distance,
                      "object_in_chunk": any(k in text.surface_key(chunk["text"]) for k in ok)})
    return {"rejected": len(rows), "by_reason": dict(sorted(Counter(r for row in rows for r in row["reasons"]).items())),
            "weak": {"n": len(items), "object_in_chunk": sum(i["object_in_chunk"] for i in items),
                     "distance": dict(sorted(Counter(str(i["distance"]) for i in items if i["distance"] is not None).items())),
                     "unlocated": sum(i["distance"] is None for i in items), "items": items}}


def judge_report(level_dir: Path) -> dict:
    rows = _rows(level_dir / "judge.jsonl")
    metrics = _json(level_dir / "metrics.json")
    counts = {kind: dict.fromkeys(("yes", "no", "unparsed", "errors"), 0) for kind in ("recorded", "reparsed")}
    verdicts = {"recorded": [], "reparsed": []}
    for row in rows:
        verdicts["recorded"].append("errors" if row.get("error") else row.get("verdict") or "unparsed")
        verdicts["reparsed"].append("errors" if row.get("content") is None else text.parse_yes_no(row["content"]) or "unparsed")
    for kind in counts:
        counts[kind].update(Counter(verdicts[kind]))
    gold_path = level_dir / "eval/ref.txt"
    gold_dir = _json(level_dir / "manifest.json").get("config", {}).get("eval", {}).get("showcase_gold_dir")
    no_vs_gold = None
    if gold_path.is_file() or gold_dir:
        statements = {r["statement_id"]: r for r in [*_rows(level_dir / "statements.jsonl"), *_statement_rows(level_dir)]}
        if gold_path.is_file():
            refs = _triples(gold_path)
            documents = _json(level_dir / "graph.json")["documents"]
            gold = {d["doc_id"]: refs[i] for i, d in enumerate(documents)}
            matches = same_triple
        else:
            gold = {}
            for r in _rows(Path(gold_dir) / "gold_triples.jsonl"):
                gold.setdefault(r["doc_id"], []).append((r["subject"], r["predicate"], r["object"]))
            matches = lambda a, b: tuple(map(text.surface_key, a)) == tuple(map(text.surface_key, b))
        no_vs_gold = {}
        for kind, values in verdicts.items():
            negatives = [r for r, value in zip(rows, values) if value == "no"]
            correct = sum(any(matches((r["subject"], r["predicate"], r["object"]), g)
                              for g in gold.get(statements[r["statement_id"]]["source_doc_id"], [])) for r in negatives)
            no_vs_gold[kind] = {"n_no": len(negatives), "gold_correct": correct,
                                "precision": (len(negatives) - correct) / len(negatives) if negatives else None}
    result = {**counts, "finish_length": metrics.get("llm", {}).get("finish_length", 0), "no_vs_gold": no_vs_gold}
    if any("risk" in r for r in rows):
        result.update(judged=len(rows), skipped=metrics["statements_accepted"] - len(rows))
    return result


def qa_report(qa_dirs: list[Path]) -> dict:
    answers, duplicates, expected = {}, [], None
    for directory in qa_dirs:
        rows = _rows(directory / "answers.jsonl")
        ids = {r["qid"] for r in rows}
        if expected is not None and ids != expected:
            raise ConfigError("analyze: QA question ids differ")
        expected = ids
        grouped = {}
        for r in rows:
            grouped.setdefault(r["row"], {})[r["qid"]] = r
        for name, values in grouped.items():
            if name in answers:
                duplicates.append(name)
            else:
                answers[name] = values
    labels = sorted({name.split("@", 1)[1] for name in answers if "@" in name},
                    key=lambda label: (0, LEVELS.index(label)) if label in LEVELS else (1, label))
    pairs = [(row, "text") for row in sorted(answers) if row != "text" and "text" in answers]
    for mode in sorted({name.split("@", 1)[0] for name in answers if "@" in name}):
        names = [f"{mode}@{label}" for label in labels if f"{mode}@{label}" in answers]
        pairs.extend((later, earlier) for i, later in enumerate(names) for earlier in names[:i])
    results, changes = [], []
    for row, vs in pairs:
        if set(answers[row]) != set(answers[vs]):
            raise ConfigError("analyze: QA question ids differ")
        diffs = []
        for qid in sorted(answers[row]):
            a, b = answers[row][qid], answers[vs][qid]
            delta = a["f1"] - b["f1"]
            diffs.append(delta)
            if delta:
                changes.append({"row": row, "vs": vs, "qid": qid, "f1_row": a["f1"], "f1_vs": b["f1"],
                                "facts_only_row": sorted(set(a["facts"]) - set(b["facts"])),
                                "facts_only_vs": sorted(set(b["facts"]) - set(a["facts"])),
                                "passages_only_row": sorted(set(a["retrieved"]) - set(b["retrieved"])),
                                "passages_only_vs": sorted(set(b["retrieved"]) - set(a["retrieved"])),
                                "seeds_row": a["seeds"], "seeds_vs": b["seeds"]})
        wins, losses = sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)
        results.append({"row": row, "vs": vs, "wins": wins, "losses": losses, "ties": len(diffs) - wins - losses,
                        "sign_p": sign_test(wins, losses), "bootstrap": paired_bootstrap(diffs)})
    return {"duplicate_rows": sorted(set(duplicates)), "pairs": results, "diffs": changes}


def alias_report(level_dir: Path) -> dict:
    items = []
    for entity in _rows(level_dir / "entities.jsonl"):
        if not entity["aliases"]:
            continue
        numbers = [sorted(text.number_tokens(n)) for n in [entity["name"], *entity["aliases"]]]
        items.append({"entity_id": entity["entity_id"], "name": entity["name"], "aliases": entity["aliases"],
                      "number_sets": numbers, "conflict": len({tuple(n) for n in numbers}) > 1})
    return {"groups": len(items), "number_conflicts": sum(r["conflict"] for r in items), "items": items}


def analyze(root: Path, qa_dirs: list[Path]) -> dict:
    runs = sorted(p for p in root.iterdir() if p.is_dir() and any((p / level / "metrics.json").is_file() for level in LEVELS))
    dirs = ([root / "qa"] if (root / "qa/answers.jsonl").is_file() else []) + qa_dirs
    report = {"format": FORMAT, "root": root.relative_to(PROJECT_ROOT).as_posix(),
              "qa_dirs": [p.relative_to(PROJECT_ROOT).as_posix() for p in dirs],
              "webnlg": {}, "rejected": {}, "judge": {}, "alias": {}, "qa": qa_report(dirs) if dirs else None}
    for run in runs:
        if any((run / level / "eval/pred.txt").is_file() for level in LEVELS):
            report["webnlg"][run.name] = webnlg_report(run)
        for level in LEVELS:
            path = run / level
            if not (path / "metrics.json").is_file():
                continue
            key = f"{run.name}/{level}"
            report["rejected"][key] = rejected_report(path)
            report["alias"][key] = alias_report(path)
            if (path / "judge.jsonl").is_file():
                report["judge"][key] = judge_report(path)
    return report


def render_md(report: dict) -> str:
    lines = ["# Artifact error analysis", "", "Rule-based residual classes; not the hand classification.",
             "Harness exact-string F1, not EDC strict."]
    def table(headers, rows):
        def cell(value):
            raw = text.cj(value) if isinstance(value, (dict, list, tuple)) else str(value)
            return raw.replace("|", "\\|").replace("\n", " ")
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join("---" for _ in headers) + "|")
        lines.extend("| " + " | ".join(cell(v) for v in row) + " |" for row in rows)
        lines.append("")
    lines += ["", "## 1. WebNLG diff + residual", ""]
    for run, data in report["webnlg"].items():
        lines += ["### " + run, ""]
        table(["Transition", "Lost", "Gained", "Paired bootstrap"],
              [(f'{r["from"]} -> {r["to"]}', len(r["lost"]), len(r["gained"]), r["bootstrap"]) for r in data["transitions"]])
        table(["Transition", "Change", "Doc", "Triple", "Cause", "Gold correct"],
              [(f'{r["from"]} -> {r["to"]}', kind, item["doc"], item["triple"], item["cause"], item["gold_correct"])
               for r in data["transitions"] for kind in ("lost", "gained") for item in r[kind]])
        table(["Level", "Extra", "Missing", "Rule classes", "Per-document F1"],
              [(level, r["extra"], r["missing"], r["counts"], data["per_doc_f1"][level]) for level, r in data["residual"].items()])
        table(["Level", "Doc", "Class", "Extra", "Missing"],
              [(level, item["doc"], item["class"], item["extra"], item["missing"])
               for level, r in data["residual"].items() for item in r["items"]])
    lines += ["## 2. Rejected distance", ""]
    table(["Run/level", "Rejected", "Reasons", "Weak", "Object in chunk", "Distance", "Unlocated"],
          [(key, r["rejected"], r["by_reason"], r["weak"]["n"], r["weak"]["object_in_chunk"],
            r["weak"]["distance"], r["weak"]["unlocated"]) for key, r in report["rejected"].items()])
    lines += ["## 3. Judge vs gold", ""]
    table(["Run/level", "Recorded", "Reparsed", "Finish length", "No vs gold", "Judged", "Skipped"],
          [(key, r["recorded"], r["reparsed"], r["finish_length"], r["no_vs_gold"], r.get("judged", "-"), r.get("skipped", "-"))
           for key, r in report["judge"].items()])
    lines += ["## 4. QA per question + pairs", ""]
    if report["qa"]:
        table(["Row", "Vs", "Wins", "Losses", "Ties", "Sign p", "Bootstrap"],
              [(r["row"], r["vs"], r["wins"], r["losses"], r["ties"], r["sign_p"], r["bootstrap"]) for r in report["qa"]["pairs"]])
        table(["Row", "Vs", "Question", "F1 row/vs", "Facts row only", "Facts vs only", "Passages row only", "Passages vs only", "Seeds row/vs"],
              [(r["row"], r["vs"], r["qid"], [r["f1_row"], r["f1_vs"]], r["facts_only_row"], r["facts_only_vs"],
                r["passages_only_row"], r["passages_only_vs"], [r["seeds_row"], r["seeds_vs"]]) for r in report["qa"]["diffs"]])
        lines += ["Duplicate rows (first directory wins): " + text.cj(report["qa"]["duplicate_rows"]), ""]
    lines += ["## 5. Alias groups", ""]
    table(["Run/level", "Groups", "Number conflicts"], [(key, r["groups"], r["number_conflicts"]) for key, r in report["alias"].items()])
    table(["Run/level", "Entity", "Name", "Aliases", "Number sets", "Conflict"],
          [(key, i["entity_id"], i["name"], i["aliases"], i["number_sets"], i["conflict"])
           for key, r in report["alias"].items() for i in r["items"]])
    return "\n".join(lines) + "\n"


def write(report: dict, out: Path) -> None:
    text.write_json(out / "analysis.json", report)
    (out / "analysis.md").write_text(render_md(report), encoding="utf-8", newline="\n")
