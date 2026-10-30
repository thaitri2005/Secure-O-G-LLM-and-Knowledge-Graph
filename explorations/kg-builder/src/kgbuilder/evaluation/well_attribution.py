"""Artifact-only stage attribution with frozen scoring and checked EDC linkage."""
from __future__ import annotations

import csv
import math
import re
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from kgbuilder.core import choice, well_facts, well_literals
from kgbuilder.core.config import ConfigError, KgbError, project_path
from kgbuilder.core.domain import input_path, read_object, run_path
from kgbuilder.core.project import PROJECT_ROOT
from kgbuilder.core.schema import load_schema
from kgbuilder.core.text import cj, iter_jsonl, match_key, sha256_file, sha256_text, split_sentences_abbrev, write_json, write_jsonl
from kgbuilder.core.well_values import RELATIONS, parse_quantity, parse_us_date


STAGES = ("tp_L3", "tp_L2_only", "tp_L1_only", "match_lost", "convert_mismatch",
          "convert_unparsed", "export_excluded", "validate_rejected", "resolve_changed",
          "canon_dropped", "extract_wrong_slot", "extract_entity_only", "extract_missed")
_PATHS = ("canon_dropped", "resolve_changed", "validate_rejected", "export_excluded",
          "convert_unparsed", "convert_mismatch")
_MECHANISMS = ("relation_accepts_gold_kind", "typed_unique", "verifier_fixable", "fallback_ok", "tubular_head")
_BRANCHES = ("schema_short_circuit", "edc_undefined", "no_call", "verified")
_OUTCOMES = ("schema_short_circuit", "choice", "none_of_above", "unparsed", "no_call", "edc_undefined")
_TYPED = frozenset((*well_literals.QUANTITY_KINDS, "date"))
_EXTRACTION_STAGES = frozenset({"extract_missed", "extract_entity_only", "extract_wrong_slot"})
_RECALL_LABELS = ("relation_absent", "sentence_silent", "multi_sentence", "chunk_abstained")


def recall_triggers(rows, stats) -> dict:
    """Apply the registered mechanism counts, shares and three-chunk minimum."""
    n_fn = stats["n_gplus"] - sum(stats["stages"][s] for s in STAGES[:3])
    result = {"n_fn": n_fn}
    for name, share in (("guided_windows", .25), ("guided_groups", .25), ("guided_recall", .25), ("derived_casing_size", .10)):
        selected = []
        for row in rows:
            extraction = row["stage"] in _EXTRACTION_STAGES
            include = (extraction and row.get("sentence_silent", False) and row.get("multi_sentence", False) if name == "guided_windows" else
                       extraction and row.get("relation_absent", False) if name == "guided_groups" else extraction if name == "guided_recall" else
                       row["relation"] == "casing_size" and row["stage"] in {
                           "extract_wrong_slot", "canon_dropped", "resolve_changed", "validate_rejected"} and row.get("tubular_head", False))
            if include:
                selected.append(row)
        n, chunks, threshold = len(selected), len({r["chunk_id"] for r in selected}), max(3, math.ceil(share * n_fn))
        result[name] = {"n": n, "chunks": chunks, "threshold": threshold, "fired": n >= threshold and chunks >= 3}
    return result


def _recall_labels(fact, chunk, candidates):
    """Compare non-derived evidence to the gold sentence in chunk offsets."""
    spans = split_sentences_abbrev(chunk["text"])
    start, end = fact.evidence["start"], fact.evidence["end"]
    sentence = next((s for s in spans if s[0] <= start < s[1]), None)
    if sentence is None:
        overlaps = [(max(0, min(s[1], end) - max(s[0], start)), s) for s in spans]
        overlap, best = max(overlaps, key=lambda item: item[0], default=(0, None))
        sentence = best if overlap else (0, len(chunk["text"]))
    candidates = [c for c in candidates if c["extractor"] != "derived"]
    base = chunk["char_start"]
    silent = not any(c["evidence"]["char_start"] - base < sentence[1] and
                     sentence[0] < c["evidence"]["char_end"] - base for c in candidates)
    return {"relation_absent": not any(c["predicate"] == fact.relation for c in candidates),
            "sentence_silent": silent, "multi_sentence": len(spans) >= 3, "chunk_abstained": not candidates}


def request_key(candidate: dict) -> tuple:
    """Replicate the running canon request order without importing the build layer."""
    return candidate["chunk_id"], candidate["candidate_id"] if candidate["extractor"] != "edc" else ""


def carries(surface: str, obj: dict, policy: dict) -> bool:
    """Diagnose surface retention without using this lenient rule for scoring."""
    kind = obj["kind"]
    numbers = []
    for token in re.findall(r"\d+[- ]\d+/\d+|(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", surface):
        if "/" in token:
            whole, numerator, denominator = re.split(r"[- /]", token)
            if Decimal(denominator): numbers.append(Decimal(whole) + Decimal(numerator) / Decimal(denominator))
        else:
            numbers.append(Decimal(token.replace(",", "")))
    tolerance = policy.get("tolerance", policy)
    def present(value, absolute=0, relative=0):
        if value is None: return False
        number = Decimal(str(value))
        bound = Decimal(str(absolute)) + abs(number) * Decimal(str(relative))
        return any(abs(n - number) <= bound for n in numbers)
    if kind in {"depth", "pressure", "density", "volume", "size"}:
        absolute = tolerance.get("depth_ft", 1) if kind == "depth" else tolerance.get("density_ppg", .05) if kind == "density" else 0
        relative = tolerance.get(kind + "_relative", .01) if kind in {"pressure", "volume"} else 0
        return present(obj.get("value"), absolute, relative)
    if kind == "interval":
        limit = Decimal(str(tolerance.get("depth_ft", 1)))
        if all(present(obj.get(k), limit) for k in ("lower", "upper")): return True
        parsed = parse_quantity(surface, "interval")
        return parsed.lower is not None and all(abs(Decimal(getattr(parsed, k)) - Decimal(obj[k])) <= limit for k in ("lower", "upper"))
    if kind == "date":
        for pattern in well_literals.DATE_PATTERNS:
            for hit in re.finditer(pattern, surface, re.I):
                if obj["precision"] == "partial":
                    if match_key(hit[0]) == match_key(obj["text"]): return True
                elif parse_us_date(hit[0]) == (obj["iso"], obj["precision"]): return True
        return False
    if kind == "status":
        return any(value and re.search(r"(?<![A-Za-z0-9])" + re.escape(value) + r"(?![A-Za-z0-9])", surface, re.I)
                   for value in (obj.get("text", ""), obj.get("value", "")))
    heads = set(policy.get("generic_heads", ["sand", "zone", "reservoir", "formation", "rig", "well"]))
    tokens = set(match_key(obj.get("text", "")).split()) - heads
    return bool(tokens) and tokens <= set(match_key(surface).split())


def triggers(stats: dict) -> dict:
    """Count only the pre-registered stage/mechanism combinations, by fact/chunk."""
    stages = stats["stages"]
    n_fn = stats["n_gplus"] - sum(stages[s] for s in ("tp_L1_only", "tp_L2_only", "tp_L3"))
    rows = stats["per_fact"]
    checks = {
        "verifier_normalization": lambda r: r["stage"] == "canon_dropped" and r["verifier_fixable"],
        "canon_fallback": lambda r: r["stage"] == "canon_dropped" and r["fallback_ok"],
        "typed_literals": lambda r: r["stage"] == "convert_unparsed" and r["relation_accepts_gold_kind"] and r["typed_unique"],
        "derived_casing_size": lambda r: r["relation"] == "casing_size" and r["stage"] in {"extract_wrong_slot", "canon_dropped", "resolve_changed", "validate_rejected"} and r["tubular_head"],
        "guided_extraction": lambda r: r["stage"] in {"extract_missed", "extract_entity_only", "extract_wrong_slot", "canon_dropped"},
    }
    result = {"n_fn": n_fn}
    for fix, check in checks.items():
        selected = [r for r in rows if check(r)]
        count, chunks = len(selected), len({r["chunk_id"] for r in selected})
        threshold = max(3, math.ceil((.25 if fix == "guided_extraction" else .10) * n_fn))
        result[fix] = {"n": count, "chunks": chunks, "threshold": threshold, "fired": count >= threshold and chunks >= 3}
    return result


def _rows(path):
    return list(iter_jsonl(path)) if path.is_file() else []


def _invariant(condition, name):
    if not condition: raise KgbError(1, "attribution invariant: " + name)


def _link_edc(run, candidates, canonical, manifest, calls):
    verifier_normalization = manifest.get("config", {}).get("canon", {}).get("verifier_normalize") is True
    counts = {"branches": dict.fromkeys(_BRANCHES, 0), "raw": dict.fromkeys(_OUTCOMES, 0),
              "effective": dict.fromkeys(_OUTCOMES, 0), "raw_normalised": {k: dict.fromkeys(("choice", "none_of_above", "unparsed"), 0)
              for k in ("choice", "none_of_above", "unparsed")}, "choice_word": 0, "verifier_normalization_enabled": verifier_normalization}
    canon_counts = dict.fromkeys(("sent", "mapped", "edc_unmapped", "edc_undefined"), 0)
    linked = {}
    request_path = run / "edc/request.json"
    if not request_path.exists(): return linked, canon_counts, counts, set()
    request = read_object(request_path)
    schema_path = run / "edc/schema.csv"
    if request.get("enrich_schema") is not False or not schema_path.is_file():
        raise ConfigError("attribution needs a target-schema run")
    with schema_path.open(encoding="utf-8", newline="") as stream:
        relations = {row[0] for row in csv.reader(stream)}
    inverse = {}
    original_schema = manifest.get("config", {}).get("canon", {}).get("schema_path")
    if original_schema:
        inverse = {k: r.inverse_of for k, r in load_schema(project_path(original_schema, "schema", True)).relations.items() if r.inverse_of}
    groups = defaultdict(list)
    for candidate in sorted((c for c in candidates if c.get("trigger_relation") is None and c["extractor"] != "derived"), key=request_key):
        groups[candidate["chunk_id"]].append(candidate)
    responses = read_object(run / "edc/response.json")["items"]
    requests = request["items"]
    def mapping(ok):
        if not ok: raise KgbError(1, "edc mapping reconstruction failed")
    mapping(len(requests) == len(responses) == len(groups))
    seen = set()
    verify_rows = [r for r in calls if r.get("stage") == "canon" and r.get("asked_max_tokens") == 1]
    for item, response in zip(requests, responses):
        key = item["key"]
        mapping(key not in seen and key in groups and response["key"] == key)
        seen.add(key)
        group = groups[key]
        mapping(len(group) == len(item["triples"]) == len(response["results"]))
        for candidate, triple, result in zip(group, item["triples"], response["results"]):
            mapping(triple == [candidate[k] for k in ("subject", "predicate", "object")])
            cid = candidate["candidate_id"]
            mapped = result.get("canonical")
            retrieved = result.get("candidates", {})
            prompt_key = "Text: " + item["text"] + "\nTriplet: " + repr(triple) + "\n"
            rows = [r for r in verify_rows if r.get("messages") and prompt_key in r["messages"][0].get("content", "")]
            if triple[1] in relations:
                branch = "schema_short_circuit"
                valid = mapped == triple and retrieved == {} and not rows
            elif result.get("reason") == "edc_undefined":
                branch = "edc_undefined"
                valid = mapped is None and retrieved == {}
            elif retrieved == {}:
                branch = "no_call"
                valid = mapped is None
            else:
                branch = "verified"
                valid = bool(rows)
            if not valid: raise KgbError(1, "verifier reconstruction failed: " + branch)
            raw = normalised = effective = branch
            answer = None
            if branch == "verified":
                row = rows[0]
                answer = row.get("content") or ""
                letters, none = choice.parse_choices(row["messages"][0]["content"])
                normalized_answer = choice.normalize_choice(answer)
                raw, normalised = choice.classify(answer, letters, none), choice.classify(normalized_answer, letters, none)
                effective = normalised if verifier_normalization else raw
                effective_answer = normalized_answer if verifier_normalization else answer
                valid = (effective == "choice") == (mapped is not None)
                if effective == "choice": valid = valid and letters[effective_answer[0]] == mapped[1]
                if not valid: raise KgbError(1, "verifier reconstruction failed: verified")
                counts["raw_normalised"][raw][normalised] += 1
                counts["choice_word"] += int(raw == "choice" and len(answer) >= 2 and answer[:2].isalpha())
            if mapped is not None:
                mapping(cid in canonical and canonical[cid]["predicate"] == inverse.get(mapped[1], mapped[1]))
            canon_counts["sent"] += 1
            canon_counts["mapped" if mapped is not None else "edc_undefined" if result.get("reason") == "edc_undefined" else "edc_unmapped"] += 1
            counts["branches"][branch] += 1
            counts["raw"][raw] += 1
            counts["effective"][effective] += 1
            linked[cid] = {"result": result, "branch": branch, "raw": raw, "normalised": normalised,
                           "effective": effective, "answer": answer}
    return linked, canon_counts, counts, relations


def _kinds(relation):
    return well_facts.RELATION_SPEC[relation][1] if relation in well_facts.RELATION_SPEC else frozenset()


def _replacement(surface, relation, lexicon):
    kinds = _kinds(relation)
    if "status" in kinds: return well_literals.status_code(surface, lexicon["status"])
    return well_literals.typed_surface(surface, kinds & _TYPED) if kinds & _TYPED else None


def attribute(run_dir: Path, corpus_dir: Path, gold_root: Path, policy: dict, lexicon: dict,
              split: str, export: str, out_dir: Path) -> dict:
    """Attribute readable G+ facts; TEST outputs contain aggregate counts only."""
    if split not in {"dev", "test"} or export not in {"full", "strict"}: raise ConfigError("invalid attribution scope")
    run_dir, corpus_dir = run_path(run_dir), input_path(corpus_dir)
    documents = _rows(run_dir / "documents.jsonl")
    ids = {d["doc_id"] for d in documents}
    if len(ids) != len(documents): raise ConfigError("duplicate run documents")
    split_ids = read_object(gold_root / "split.json")
    scope = split_ids["dev"] if split == "dev" else split_ids.get("test_subset", split_ids.get("pilot", []))
    if not ids <= set(scope):
        raise ConfigError("run scope outside dev split" if split == "dev" else "run scope outside test_subset")
    corpus = {d["doc_id"]: sha256_text(d["text"]) for d in iter_jsonl(corpus_dir / "corpus.jsonl")}
    if any(corpus.get(d["doc_id"]) != sha256_text(d["text"]) for d in documents):
        raise ConfigError("evaluation corpus scope/hash mismatch")
    freeze = read_object(gold_root / "freeze.json")
    from kgbuilder.core.well_convert import facts_from_graph_v2
    v2 = freeze.get("converter", "v1") == "v2"
    recall_dev = v2 and split == "dev"
    def convert(raw):
        return facts_from_graph_v2(raw, ids, lexicon) if v2 else well_facts.facts_from_graph(raw, ids)
    if freeze["corpus_sha256"] != sha256_file(corpus_dir / "corpus.jsonl"): raise ConfigError("gold corpus hash mismatch")
    filename = "graph.json" if export == "full" else "graph_strict.json"
    if not (run_dir / filename).is_file(): raise ConfigError("missing requested graph export")
    graph = read_object(run_dir / filename)
    if {d["doc_id"]: d["text"] for d in graph["documents"]} != {d["doc_id"]: d["text"] for d in documents}:
        raise ConfigError("graph document scope differs")
    gold_rows = [r for r in iter_jsonl(gold_root / "adjudicated.jsonl") if r["chunk_id"].rsplit("#", 1)[0] in ids]
    statuses = {r["chunk_id"]: r for r in gold_rows if r["record"] == "chunk"}
    scope = {k for k, r in statuses.items() if r["status"] != "unreadable"}
    gold = [well_facts.WellFact.model_validate(r) for r in gold_rows if r["record"] == "fact" and r["chunk_id"] in scope]
    pred = [f for f in convert(graph) if f.chunk_id in scope]
    scores = well_facts.score(gold, pred, policy)
    matches = {level: dict(well_facts.match(gold, pred, policy, level)) for level in ("L1", "L2", "L3")}
    for level, pairs in matches.items():
        _invariant(sum(well_facts.partition(gold[i]) == "G+" for i in pairs) == scores[level]["tp"], level + " TP")
    candidates = _rows(run_dir / "candidates.jsonl")
    recall_chunks = {c["chunk_id"]: c for c in _rows(run_dir / "chunks.jsonl")} if recall_dev else {}
    canonical = {r["candidate_id"]: r for r in _rows(run_dir / "canonical.jsonl")}
    entities = {r["entity_id"]: r["name"] for r in _rows(run_dir / "entities.jsonl")}
    mentions = _rows(run_dir / "mentions.jsonl")
    calls = _rows(run_dir / "llm_calls.jsonl")
    manifest = read_object(run_dir / "manifest.json")
    linked, canon_counts, verifier, schema_relations = _link_edc(run_dir, candidates, canonical, manifest, calls)
    statements = _rows(run_dir / "statements.jsonl")
    rejections = _rows(run_dir / "rejected.jsonl")
    statements += [r["record"] for r in rejections if r["kind"] == "statement"]
    by_candidate = defaultdict(list)
    for statement in statements:
        for cid in statement["candidate_ids"]: by_candidate[cid].append(statement)
    dropped = {r["id"]: r for r in rejections if r["kind"] == "candidate" and r["stage"] == "canon"}
    exported = {s["statement_id"] for s in graph["statements"]}
    replacements = {r["candidate_id"]: r["after"] for r in _rows(run_dir / "literals.jsonl") if r["rule"] in {"typed", "status"}}
    all_graph = read_object(run_dir / "graph.json")
    converted = {}
    for statement in statements:
        if statement["status"] == "accepted":
            converted[statement["statement_id"]] = convert({**all_graph, "statements": [statement]})
    rows = []
    for index, fact in enumerate(gold):
        if well_facts.partition(fact) != "G+": continue
        chunk = fact.chunk_id
        chunk_candidates = [c for c in candidates if c["chunk_id"] == chunk]
        carriers = [c for c in chunk_candidates if carries(c["object"], fact.object, policy)]
        row = {"chunk_id": chunk, "fact_no": fact.fact_no, "relation": fact.relation, "object_kind": fact.object["kind"],
               "gold_object_text": fact.object["text"], "sub": {}, "best_carrier": None, "canon_predicate": None,
               "canon_source": None, "verifier_raw": None, "verifier_effective": None, "verifier_answer": None,
               "statement_id": None, "converted_kind": None, "converted_text": None, "n_carriers": len(carriers),
               **dict.fromkeys(_MECHANISMS, False)}
        paths = []
        for carrier in carriers:
            cid = carrier["candidate_id"]
            decision = canonical.get(cid)
            if decision is None:
                _invariant(cid in dropped, "carrier has no canon decision or rejection")
                paths.append(("canon_dropped", carrier, None, None))
                continue
            if not carries(entities[decision["object_id"]], fact.object, policy):
                paths.append(("resolve_changed", carrier, None, None))
                continue
            _invariant(bool(by_candidate[cid]), "carrier has no statement")
            for statement in by_candidate[cid]:
                conversion = next((f for f in converted.get(statement["statement_id"], []) if f.chunk_id == chunk), None)
                if v2:
                    chunk_facts = [f for f in converted.get(statement["statement_id"], []) if f.chunk_id == chunk]
                    conversion = next((f for f in chunk_facts if well_facts.value_equal(fact.object, f.object, policy)),
                                      next((f for f in chunk_facts if f.object["kind"] == fact.object["kind"]), conversion))
                if statement["status"] == "rejected": stage = "validate_rejected"
                elif statement["statement_id"] not in exported: stage = "export_excluded"
                else:
                    _invariant(conversion is not None, "exported carrier has no converted fact")
                    stage = "convert_unparsed" if conversion.object["kind"] != fact.object["kind"] else "convert_mismatch"
                paths.append((stage, carrier, statement, conversion))
        best = min(paths, key=lambda p: (-_PATHS.index(p[0]), p[1]["candidate_id"], (p[2] or {}).get("statement_id", ""))) if paths else None
        if index in matches["L3"]: stage = "tp_L3"
        elif index in matches["L2"]:
            stage = "tp_L2_only"
            row["sub"]["reason"] = "qualifier" if well_facts._subject(fact.subject, pred[matches["L2"][index]].subject, policy) else "subject"
        elif index in matches["L1"]:
            stage = "tp_L1_only"
            row["sub"]["reason"] = "other_relation" if pred[matches["L1"][index]].relation in RELATIONS else "open_predicate"
        elif any(p.chunk_id == chunk and well_facts.value_equal(fact.object, p.object, policy) for p in pred): stage = "match_lost"
        elif best: stage = best[0]
        else:
            slots = [(c, slot) for c in chunk_candidates for slot in ("subject", "predicate") if carries(c[slot], fact.object, policy)]
            if slots:
                stage = "extract_wrong_slot"
                c, slot = min(slots, key=lambda p: (p[0]["candidate_id"], p[1]))
                row["best_carrier"] = {k: c[k] for k in ("candidate_id", "subject", "predicate", "object")}
                row["best_carrier"]["slot"] = slot
            else:
                stage = "extract_entity_only" if any(m["chunk_id"] == chunk and carries(m["surface"], fact.object, policy) for m in mentions) else "extract_missed"
        row["stage"] = stage
        if best:
            _, c, statement, conversion = best
            cid = c["candidate_id"]
            row["best_carrier"] = {**{k: c[k] for k in ("candidate_id", "subject", "predicate", "object")}, "slot": "object"}
            decision = canonical.get(cid, {})
            row.update(canon_predicate=decision.get("predicate"), canon_source=decision.get("predicate_source"))
            if cid in linked:
                row.update(verifier_raw=linked[cid]["raw"], verifier_effective=linked[cid]["effective"], verifier_answer=linked[cid]["answer"])
            if statement: row["statement_id"] = statement["statement_id"]
            if conversion: row.update(converted_kind=conversion.object["kind"], converted_text=conversion.object["text"])
            if stage == "validate_rejected": row["sub"]["reason"] = "+".join(sorted(statement["reasons"]))
            if stage == "canon_dropped":
                row["sub"].update(reason="+".join(sorted(dropped[cid]["reasons"])), verifier=row["verifier_effective"])
                retrieved = [linked[c["candidate_id"]]["result"].get("candidates", {}) for c in carriers if c["candidate_id"] in linked]
                row["sub"]["gold_relation_retrieved"] = str(any(fact.relation in r for r in retrieved)).lower() if retrieved else "na"
        if stage == "convert_unparsed":
            for end, c, statement, _ in paths:
                if end != "convert_unparsed" or fact.object["kind"] not in _kinds(statement["predicate"]): continue
                row["relation_accepts_gold_kind"] = True
                decision = canonical[c["candidate_id"]]
                surface = replacements.get(c["candidate_id"], c["subject"] if decision["predicate_source"] == "inverse" else c["object"])
                replacement = _replacement(surface, statement["predicate"], lexicon)
                row["typed_unique"] |= replacement is not None and carries(replacement, fact.object, policy)
        if stage == "canon_dropped":
            for carrier in carriers:
                link = linked.get(carrier["candidate_id"], {})
                row["verifier_fixable"] |= not verifier["verifier_normalization_enabled"] and link.get("raw") != "choice" and link.get("normalised") == "choice"
                result = link.get("result", {})
                choices = result.get("candidates", {})
                if choices and result.get("reason") != "edc_undefined":
                    relation = min(choices, key=lambda r: (-choices[r], r))
                    kinds = _kinds(relation) & _TYPED
                    replacement = well_literals.typed_surface(carrier["object"], kinds) if relation in schema_relations and kinds else None
                    row["fallback_ok"] |= replacement is not None and carries(replacement, fact.object, policy)
        if fact.relation == "casing_size":
            for c in chunk_candidates:
                if c["extractor"] == "derived": continue
                for surface in (c["subject"], c["object"]):
                    if any(re.search(r"\b" + re.escape(head) + r"\b", surface, re.I) for head in lexicon["tubular_heads"]):
                        replacement = well_literals.typed_surface(surface, ("size",))
                        row["tubular_head"] |= replacement is not None and carries(replacement, fact.object, policy)
        if recall_dev and stage in _EXTRACTION_STAGES:
            row.update(_recall_labels(fact, recall_chunks[chunk], chunk_candidates))
        rows.append(row)
    stages = {stage: sum(r["stage"] == stage for r in rows) for stage in STAGES}
    _invariant(sum(stages.values()) == scores["partitions"]["G+"], "stage sum")
    for level, names in (("L1", STAGES[:3]), ("L2", STAGES[:2]), ("L3", STAGES[:1])):
        _invariant(sum(stages[n] for n in names) == scores[level]["tp"], level + " stage TP")
    sub = {stage: defaultdict(Counter) for stage in STAGES}
    grouped = {key: {} for key in ("by_relation", "by_kind", "by_subject", "per_chunk")}
    for fact, row in zip((g for g in gold if well_facts.partition(g) == "G+"), rows):
        stage = row["stage"]
        labels = dict(row["sub"])
        if stage == "convert_unparsed": labels.update({k: row[k] for k in _MECHANISMS[:2]})
        if stage == "canon_dropped": labels.update({k: row[k] for k in _MECHANISMS[2:4]})
        if fact.relation == "casing_size": labels["tubular_head"] = row["tubular_head"]
        for name, value in labels.items(): sub[stage][name][str(value).lower() if isinstance(value, bool) else str(value)] += 1
        subject = "implicit" if "implicit" in fact.subject else "report_well" if fact.subject.get("role") == "report_well" else "explicit:" + fact.subject["type"]
        for key, value in (("by_relation", fact.relation), ("by_kind", fact.object["kind"]), ("by_subject", subject), ("per_chunk", fact.chunk_id)):
            grouped[key].setdefault(value, dict.fromkeys(STAGES, 0))[stage] += 1
    length_rows = [r for r in calls if r.get("finish_reason") == "length"]
    length_verify = Counter()
    for row in length_rows:
        if row.get("stage") == "canon" and row.get("asked_max_tokens") == 1:
            letters, none = choice.parse_choices(row["messages"][0]["content"])
            length_verify[choice.classify(row.get("content") or "", letters, none)] += 1
    policy_hashes = [v for k, v in freeze.get("frozen_inputs", {}).items() if k.endswith("bsee_eval.yaml")]
    inputs = {name: sha256_file(path) if path.is_file() else None for name, path in {
        "graph": run_dir / filename, "candidates.jsonl": run_dir / "candidates.jsonl", "llm_calls.jsonl": run_dir / "llm_calls.jsonl",
        **{name: gold_root / name for name in ("freeze.json", "split.json", "adjudicated.jsonl")}}.items()}
    inputs.update(policy=policy_hashes[0] if len(policy_hashes) == 1 else sha256_text(cj(policy)),
                  lexicon=sha256_file(getattr(lexicon, "source", PROJECT_ROOT / "configs/domains/bsee/bsee_literals.yaml")))
    result = {"format": "kgb.attribution/1", "split": split, "export": export, "level": manifest.get("ablation", manifest.get("config", {}).get("ablation")),
              "inputs": inputs, "n_chunks": len(scope), "n_gplus": len(rows), "stages": stages, "sub": sub,
              **{k: v for k, v in grouped.items() if k != "per_chunk"}, "canon": canon_counts, "verifier": verifier,
              "truncation": {"finish_length": dict(Counter(r.get("stage", "unknown") for r in length_rows)),
                             "verify_raw": {k: length_verify[k] for k in ("choice", "none_of_above", "unparsed")}},
              "predictions": {"n": len(pred), "schema_relation": sum(p.relation in RELATIONS for p in pred), "open_predicate": sum(p.relation not in RELATIONS for p in pred)},
              "scores": {level: {k: scores[level][k] for k in ("tp", "fp", "fn")} for level in matches},
              "triggers": None, "llm_calls": 0}
    if split == "dev":
        result["per_chunk"] = grouped["per_chunk"]
        if result["level"] == "A4" and export == "full": result["triggers"] = triggers({**result, "per_fact": rows})
        if recall_dev:
            recall_diagnostics = {stage: defaultdict(Counter) for stage in STAGES}
            for row in rows:
                if row["stage"] in _EXTRACTION_STAGES:
                    for label in _RECALL_LABELS:
                        recall_diagnostics[row["stage"]][label][str(row[label]).lower()] += 1
            result["recall_diagnostics"] = recall_diagnostics
            if result["level"] == "A4" and export == "full":
                result["recall_triggers"] = recall_triggers(rows, result)
    out_dir.mkdir(parents=True, exist_ok=True)
    if split == "dev": write_jsonl(out_dir / "per_fact.jsonl", rows)
    write_json(out_dir / "attribution.json", result)
    lines = ["# Well attribution", "", f"Split: {split}; export: {export}; readable chunks: {len(scope)}; G+: {len(rows)}", ""]
    for name in ("stages", "sub", "by_relation", "by_kind", "by_subject", "canon", "verifier", "truncation", "predictions", "scores", "triggers", *[k for k in ("recall_diagnostics", "recall_triggers") if k in result]):
        lines.extend(["## " + name, "", "```json", cj(result[name]), "```", ""])
    (out_dir / "attribution.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return result
