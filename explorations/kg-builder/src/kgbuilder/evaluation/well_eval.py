"""Independent silver, rule, AI-gold and descriptive self-consistency evaluation."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from kgbuilder.core.config import ConfigError
from kgbuilder.core.contracts import GraphRecord
from kgbuilder.core.domain import input_path, read_object, run_path, verify_bundle
from kgbuilder.core.project import PROJECT_ROOT
from kgbuilder.core.text import cj, iter_jsonl, match_key, sha256_file, sha256_text, split_sentences, write_json, write_jsonl
from kgbuilder.core.well_facts import AnnotationFacts, OBJECT_FIELDS, WellFact, bootstrap_ci, facts_from_graph, iaa_score, load_annotations, match, metrics, paired_bootstrap, partition, score, sign_test, value_equal
from kgbuilder.core.well_values import NUMBER, hash_is_pressure, in_name, parse_quantity, parse_us_date


LABELS = {"silver": "table-silver (answerable fields only)", "rules": "rules/v2 (deterministic silver)",
          "ai_gold": "AI-gold (agent-annotated, adjudicated; not human gold)", "self_consistency": "self-consistency (not accuracy)"}
LIMITATIONS = ("Annotators are LLMs; correlated errors are possible and agreement is not correctness. "
              "The adjudicator shares the model family of annotator A; A/B anonymisation mitigates this. "
              "Blindness is procedural and ordering-checked. Packet IDs carry report serials but annotators have no table access. "
              "No domain expert reviewed the guideline.")
RULE_RELATIONS = {"reached_td", "drilled_to", "set_casing_at", "casing_size", "set_plug_at", "set_equipment_at", "tagged_at", "cut_at",
                  "tested_to_pressure", "fit_lot_emw", "perforated_interval", "has_mud_weight", "completed_in", "has_well_status", "pumped"}


def _policy(cfg):
    return cfg.model_dump() if hasattr(cfg, "model_dump") else cfg


def verify_policy(config_path: Path, gold: Path) -> str:
    """Bind the actual CLI policy bytes to the verified gold freeze."""
    frozen = read_object(gold / "freeze.json")["frozen_inputs"]
    hashes = [digest for name, digest in frozen.items() if name.endswith("bsee_eval.yaml")]
    actual = sha256_file(config_path)
    if len(hashes) != 1 or actual != hashes[0]:
        raise ConfigError("evaluation policy hash differs from freeze")
    return actual


def mention_spans(text, obj, policy):
    """Find mention candidates from literal surfaces without any model or labels."""
    kind = obj["kind"]
    found = []
    if kind in {"entity", "text", "status"}:
        names = policy.get("status_lexicon", {}).get(obj.get("value"), []) if kind == "status" else [obj.get("text", obj.get("value", ""))]
        for name in names:
            # Compare normalized word windows but preserve original offsets.
            words = list(re.finditer(r"[\w/'&-]+", text))
            size = len(match_key(name).split())
            for i in range(len(words)):
                for width in range(max(1, size - 1), size + 3):
                    if i + width > len(words): continue
                    start, end = words[i].start(), words[i + width - 1].end()
                    # Punctuation is part of match_key (for example, "Inc.").
                    ends = [end]
                    while end < len(text) and not text[end].isalnum() and not text[end].isspace():
                        end += 1
                        ends.append(end)
                    for end in ends:
                        candidate = {"kind": "entity", "text": text[start:end]}
                        equal = match_key(text[start:end]) == match_key(name) if kind == "status" else value_equal(obj, candidate, policy)
                        if equal: found.append({"start": start, "end": end})
        return sorted({(r["start"], r["end"]) for r in found})
    if kind == "date":
        patterns = [r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", r"\b\d{1,2}-\d{1,2}-(?:\d{4}|\d{2})\b",
                    r"\b[A-Za-z]+\s+(?:\d{1,2},?\s+)?\d{4}\b", r"\b\d{4}-\d{2}-\d{2}\b", r"\b\d{4}\b"]
        for pattern in patterns:
            for hit in re.finditer(pattern, text):
                iso, precision = parse_us_date(hit[0])
                if value_equal(obj, {"kind": "date", "text": hit[0], "iso": iso, "precision": precision}, policy): found.append((hit.start(), hit.end()))
        return sorted(set(found))
    suffix = {"depth": r"(?:'|(?:ft|feet|m)(?!\w))(?:\s*(?:MD|TVD|BML|AML|SLM|CTM|WLM|DPM|KBM|RKB|KB)(?!\w))?",
              "pressure": r"(?:psig?(?!\w)|#)", "density": r"(?:ppg|lb/gal|EMW)(?!\w)", "size": r'(?:"|in(?!\w))',
              "volume": r"(?:bbls?|sx|cu\s*ft|gal)(?!\w)"}
    if kind == "interval":
        pattern = rf"{NUMBER}\s*(?:'|ft|feet|m)?\s*(?:MD|TVD)?\s*(?:-|to)\s*{NUMBER}\s*" + suffix["depth"]
    elif kind == "size": pattern = rf"(?:\d+[- ]\d+/\d+|{NUMBER})\s*" + suffix[kind]
    else: pattern = rf"{NUMBER}\s*" + suffix[kind]
    for hit in re.finditer(r"(?<![\w.,/+-])" + pattern + r"(?!\w)", text, re.I):
        if kind in {"depth", "interval"} and in_name(text, hit.start(), hit.end()):
            # A quantity immediately inside a geologic name is not a depth mention.
            continue
        if kind == "size" and re.search(rf"{NUMBER}\s*[xX]\s*$", text[:hit.start()]):
            continue
        if kind == "pressure" and "#" in hit[0]:
            sentence = next((text[a:b] for a, b in split_sentences(text) if a <= hit.start() < b), "")
            if not hash_is_pressure(sentence):
                continue
        q = parse_quantity(hit[0], kind)
        if q.status == "ok" and value_equal(obj, {"kind": kind, "text": hit[0], **{k: getattr(q, k) for k in OBJECT_FIELDS[kind]}}, policy):
            found.append((hit.start(), hit.end()))
    return sorted(set(found))


def make_silver(tables: Path, corpus_dir: Path, cfg, out_dir: Path) -> dict:
    """Project dictionary-verified report observations and measure mention rates."""
    bundle = verify_bundle(tables)
    policy = _policy(cfg)
    docs = {r["doc_id"]: r for r in iter_jsonl(corpus_dir / "eligible.jsonl")}
    sources = {r["doc_id"]: r for r in iter_jsonl(corpus_dir / "doc_sources.jsonl") if r["doc_id"] in docs}
    by_report, by_api = defaultdict(list), defaultdict(list)
    for identity, row in sources.items():
        if row["text_sha256"] != sha256_text(docs[identity]["text"]): raise ConfigError("silver source text hash mismatch")
        by_report[str(row["SN_EOR"])].append(identity); by_api[row["API12"]].append(identity)
    if set(sources) != set(docs): raise ConfigError("silver corpus sources incomplete")
    scopes = {"eligible": set(docs), "ai_gold": {r["doc_id"] for r in iter_jsonl(corpus_dir / "corpus.jsonl")},
              "test_subset": {r["doc_id"] for r in iter_jsonl(corpus_dir / "test_subset.jsonl")}}
    rates = {s: defaultdict(Counter) for s in scopes}
    count = 0
    def observations():
        nonlocal count
        for node in iter_jsonl(tables / "nodes.jsonl"):
            props = node["props"]
            candidates = []
            if node["type"] == "Observation":
                candidates.append((props["field"], props["value"], by_report.get(str(props["SN_EOR"]), [])))
            elif node["type"] == "EorReport" and props.get("BUS_ASC_NAME"):
                candidates.append(("BUS_ASC_NAME", {"kind": "entity", "text": props["BUS_ASC_NAME"], "type": "Company"}, by_report.get(str(props["SN_EOR"]), [])))
            elif node["type"] == "Borehole" and props.get("WELL_SPUD_DATE"):
                value = props["WELL_SPUD_DATE"]
                if isinstance(value, dict) and value.get("iso"):
                    candidates.append(("WELL_SPUD_DATE", {"kind": "date", "text": value["raw"], "iso": value["iso"], "precision": "day"}, by_api.get(node["id"].rsplit(":", 1)[1], [])))
            for field, value, identities in candidates:
                if field not in policy["field_relations"]: continue
                if not any(field in ref["fields"] for ref in node["sources"]): raise ConfigError("observation lacks verified source field")
                obj = {"kind": value["kind"], "text": value.get("text", str(value.get("raw", ""))), "occ": 0}
                obj.update({k: value.get(k, "unknown" if k in {"reference", "datum"} else None) for k in OBJECT_FIELDS[value["kind"]]})
                for identity in identities:
                    spans = mention_spans(docs[identity]["text"], obj, policy)
                    row = {"id": sha256_text(f"{node['id']}|{identity}|{field}"), "doc_id": identity,
                           "chunk_id": identity + "#c000", "report": sources[identity]["SN_EOR"], "field": field,
                           "relation": policy["field_relations"][field], "value": obj, "sources": node["sources"],
                           "mentioned": bool(spans), "mention_spans": [{"start": a, "end": b} for a, b in spans]}
                    for scope, ids in scopes.items():
                        if identity in ids: rates[scope][field].update(observations=1, mentioned=int(bool(spans)))
                    count += 1
                    yield row
    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "observations.jsonl", observations())
    totals = {s: {f: {**c, "rate": c["mentioned"] / c["observations"]} for f, c in sorted(values.items())} for s, values in rates.items()}
    write_json(out_dir / "mention_rates.json", totals)
    manifest = {"tables_sha256": sha256_file(tables / "graph.json"), "source_manifest_sha256": bundle.source_manifest_sha256,
                "policy_sha256": sha256_text(cj(policy)),
                "corpus_sha256": sha256_file(corpus_dir / "corpus.jsonl"), "observations_sha256": sha256_file(out_dir / "observations.jsonl"),
                "evaluator_sha256": {name: sha256_file(PROJECT_ROOT / name) for name in ("src/kgbuilder/evaluation/well_eval.py", "src/kgbuilder/build/refine/well_link.py")},
                "count": count, "not_mapped": policy["not_mapped"], "llm_calls": 0}
    write_json(out_dir / "manifest.json", manifest)
    return {"observations": count, "mention_rates": totals, "not_mapped": policy["not_mapped"], "llm_calls": 0}


def silver_score(observations, pred, policy, _per_field=True):
    """Assess only mentioned fields; unknown units cannot create contradictions."""
    fields = defaultdict(list)
    for row in observations:
        fields[(row["chunk_id"].rsplit("#", 1)[0], row["field"])].append(row)

    def compatible(row, fact):
        a, b = row["value"], fact.object
        kinds = a["kind"] == b["kind"] or {a["kind"], b["kind"]} <= {"entity", "text"}
        refs = (a.get("reference", "unknown"), b.get("reference", "unknown"))
        return row["relation"] == fact.relation and kinds and (refs[0] == refs[1] or "unknown" in refs)

    attributed = [{key for key, values in fields.items() if key[0] == p.chunk_id.rsplit("#", 1)[0]
                   and any(compatible(r, p) for r in values)} for p in pred]
    rows = [r for r in observations if r["mentioned"]]
    gold = [WellFact.model_construct(chunk_id=r["chunk_id"], relation=r["relation"], object=r["value"],
            subject={"implicit": "report_well", "type": "Borehole"}, qualifiers={}, evidence={"start": r["mention_spans"][0]["start"]}) for r in rows]
    pairs = match(gold, pred, policy, "L2")
    used = {j for _, j in pairs}
    contradictions = defaultdict(set)
    for j, fact in enumerate(pred):
        if j in used: continue
        same = [r for key in attributed[j] for r in fields[key]]
        if (any(r["mentioned"] for r in same) and fact.object.get("unit") != "unknown"
                and not any(value_equal(r["value"], fact.object, policy) for r in same)):
            contradictions[j].update(key[1] for key in attributed[j])

    def counts(matched, contradicted, answerable, predictions):
        return {"matched": matched, "contradicted": contradicted, "unassessable": predictions - matched - contradicted,
                "answerable": answerable, "predictions": predictions,
                "precision": matched / (matched + contradicted) if matched + contradicted else None,
                "coverage": (matched + contradicted) / predictions if predictions else None,
                "recall": matched / answerable if answerable else None}

    result = counts(len(pairs), len(contradictions), len(rows), len(pred))
    if _per_field:
        result["per_field"] = {}
        for field in sorted({r["field"] for r in observations}):
            values = counts(sum(rows[i]["field"] == field for i, _ in pairs),
                            sum(field in names for names in contradictions.values()),
                            sum(r["field"] == field for r in rows),
                            sum(any(key[1] == field for key in keys) for keys in attributed))
            values["status"] = "insufficient (n<5)" if values["answerable"] < policy.get("insufficient", 5) else "sufficient"
            result["per_field"][field] = values
    return result


def evaluate_wells(text_run: Path, corpus_dir: Path, cfg, out_dir: Path, labels: Path | None, rules: Path | None,
                   gold: Path | None, baseline: Path | None, *, policy_file_sha256: str | None = None,
                   split: str = "test") -> dict:
    """Evaluate verified equal-text run scope, with each reference kept separate."""
    policy = _policy(cfg)
    from kgbuilder.core import well_convert, well_literals
    from kgbuilder.core.project import PROJECT_ROOT
    freeze = read_object(gold / "freeze.json") if gold else {}
    converter = freeze.get("converter", "v1")
    if converter == "v2":
        lexicon_path = PROJECT_ROOT / "configs/domains/bsee/bsee_literals.yaml"
        if sha256_file(lexicon_path) != freeze["frozen_inputs"].get("configs/domains/bsee/bsee_literals.yaml"):
            raise ConfigError("converter lexicon hash differs from freeze")
        lexicon = well_literals.load_lexicon(lexicon_path)
    if split not in {"dev", "test"}: raise ConfigError("invalid gold split")
    if split == "dev" and gold is None: raise ConfigError("--split dev requires --gold")
    policy_hash = sha256_text(cj(policy))
    text_run, corpus_dir = run_path(text_run), input_path(corpus_dir)
    corpus_hash = sha256_file(corpus_dir / "corpus.jsonl")
    corpus = {r["doc_id"]: r for r in iter_jsonl(corpus_dir / "corpus.jsonl")}
    documents = list(iter_jsonl(text_run / "documents.jsonl"))
    if len({d["doc_id"] for d in documents}) != len(documents): raise ConfigError("duplicate run documents")
    for doc in documents:
        if doc["doc_id"] not in corpus or sha256_text(doc["text"]) != sha256_text(corpus[doc["doc_id"]]["text"]):
            raise ConfigError("evaluation corpus scope/hash mismatch")
    ids = {d["doc_id"] for d in documents}
    scope_hash = sha256_text(cj(sorted((d["doc_id"], sha256_text(d["text"])) for d in documents)))
    observations, rule_facts, gold_facts = [], [], AnnotationFacts()
    references = {"silver": None, "rules": None, "ai_gold": None}
    if labels:
        manifest = read_object(labels / "manifest.json")
        if manifest["corpus_sha256"] != corpus_hash or manifest["observations_sha256"] != sha256_file(labels / "observations.jsonl"):
            raise ConfigError("silver corpus/observation hash mismatch")
        if manifest.get("policy_sha256") != policy_hash: raise ConfigError("silver policy hash mismatch")
        references["silver"] = sha256_file(labels / "manifest.json")
        observations = [r for r in iter_jsonl(labels / "observations.jsonl") if r["doc_id"] in ids]
    if rules:
        references["rules"] = sha256_file(rules / "rules.jsonl")
        rule_facts = [WellFact.model_validate(r) for r in iter_jsonl(rules / "rules.jsonl") if r["record"] == "fact" and r["chunk_id"].rsplit("#", 1)[0] in ids]
    dev, statuses = set(), {}
    annotators = {}
    if gold:
        references["ai_gold"] = {name: sha256_file(gold / name) for name in ("freeze.json", "split.json", "adjudicated.jsonl")}
        references["ai_gold"]["annotations"] = {p.relative_to(gold).as_posix(): sha256_file(p)
                                               for role in ("annotator_a", "annotator_b") for p in sorted((gold / "annotations" / role).glob("batch_*.jsonl"))}
        if read_object(gold / "freeze.json")["corpus_sha256"] != corpus_hash: raise ConfigError("gold corpus hash mismatch")
        split_ids = read_object(gold / "split.json")
        dev = set(split_ids["dev"])
        if split == "dev" and not ids <= dev: raise ConfigError("run scope outside dev split")
        for row in iter_jsonl(gold / "adjudicated.jsonl"):
            if row["chunk_id"].rsplit("#", 1)[0] not in ids: continue
            if row["record"] == "chunk": statuses[row["chunk_id"]] = row
            else: gold_facts.append(WellFact.model_validate(row))
        gold_facts = AnnotationFacts([f for f in gold_facts if (f.chunk_id.rsplit("#", 1)[0] in dev) == (split == "dev")],
                                    {k: v for k, v in statuses.items() if (k.rsplit("#", 1)[0] in dev) == (split == "dev")})
        texts = {identity + "#c000": row["text"] for identity, row in corpus.items()}
        for role in ("annotator_a", "annotator_b"):
            annotators[role] = []
            for path in sorted((gold / "annotations" / role).glob("batch_*.jsonl")):
                batch_texts = {r["chunk_id"]: texts[r["chunk_id"]] for r in iter_jsonl(path) if r["record"] == "chunk"}
                annotators[role].extend(f for f in load_annotations(path, batch_texts)
                                        if f.chunk_id in gold_facts.statuses and gold_facts.statuses[f.chunk_id]["status"] != "unreadable")
    results = {"scope_hash": scope_hash, "corpus_sha256": corpus_hash, "policy_sha256": policy_hash,
               "policy_file_sha256": policy_file_sha256, "references": references,
               "n_documents": len(ids), "dev_excluded": len(ids & dev),
               "labels": LABELS, "limitations": LIMITATIONS, "exports": {}}
    prior = read_object(baseline / "scores.json") if baseline else None
    if split == "dev":
        results.update(gold_split="dev", dev_excluded=0)
    if prior is not None:
        if prior.get("gold_split", "test") != split: raise ConfigError("baseline split mismatch")
        if prior.get("scope_hash") != scope_hash: raise ConfigError("baseline scope hash mismatch")
        if prior.get("corpus_sha256") != corpus_hash: raise ConfigError("baseline corpus hash mismatch")
        if prior.get("policy_sha256") != policy_hash: raise ConfigError("baseline policy hash mismatch")
        if prior.get("references") != references: raise ConfigError("baseline reference identity mismatch")
    details = []
    if converter == "v2": results["converter"] = {"version": "v2", "counts": {}}
    for filename, level in (("graph.json", "full"), ("graph_strict.json", "strict")):
        if not (text_run / filename).is_file(): continue
        raw = read_object(text_run / filename)
        try: graph = GraphRecord.model_validate(raw)
        except ValueError as exc: raise ConfigError("invalid evaluation graph") from exc
        if {d.doc_id: d.text for d in graph.documents} != {d["doc_id"]: d["text"] for d in documents}:
            raise ConfigError("graph document scope differs")
        pred = well_convert.facts_from_graph_v2(raw, ids, lexicon) if converter == "v2" else facts_from_graph(raw, ids)
        row = {"silver": silver_score(observations, pred, policy) if labels else None,
               "rules": score(rule_facts, [p for p in pred if p.relation in RULE_RELATIONS], policy) if rules else None,
               "ai_gold": None, "self_consistency": None}
        scored = [p for p in pred if (p.chunk_id.rsplit("#", 1)[0] in dev) == (split == "dev")]
        if gold:
            row["ai_gold"] = score(gold_facts, scored, policy)
            if converter == "v2":
                results["converter"]["counts"][level] = well_convert.conversion_counts(raw, ids, lexicon)
                v1_scored = [p for p in facts_from_graph(raw, ids) if (p.chunk_id.rsplit("#", 1)[0] in dev) == (split == "dev")]
                v1_scores = score(gold_facts, v1_scored, policy)
                row["ai_gold_converter_v1"] = {level: {k: v1_scores[level][k] for k in ("tp", "fp", "fn", "precision", "recall", "f1")}
                                               for level in ("L1", "L2", "L3")}
            row["ai_gold"]["iaa_reference"] = iaa_score(annotators["annotator_a"], annotators["annotator_b"], policy)
            if rules:
                restricted = AnnotationFacts([f for f in gold_facts if f.relation in RULE_RELATIONS], gold_facts.statuses)
                row["rules"]["system_vs_ai_gold_same_relations"] = score(restricted, [p for p in scored if p.relation in RULE_RELATIONS], policy)
                predicted = [p for p in rule_facts if p.chunk_id in restricted.statuses and restricted.statuses[p.chunk_id]["status"] != "unreadable"]
                row["rules"]["rules_vs_ai_gold"] = score(restricted, [p for p in predicted if partition(p) == "G+"], policy)
                row["rules"]["rules_vs_ai_gold"]["excluded_predictions"] = dict(Counter(partition(p) for p in predicted if partition(p) != "G+"))
            chunk_scores = {}
            for chunk in sorted(gold_facts.statuses):
                if gold_facts.statuses[chunk]["status"] == "unreadable": continue
                chunk_scores[chunk] = score([f for f in gold_facts if f.chunk_id == chunk], [p for p in scored if p.chunk_id == chunk], policy)
            row["ai_gold"]["per_chunk"] = chunk_scores
            for matching in ("L1", "L2", "L3"):
                def aggregate(rows):
                    counts = [sum(r[matching][k] for r in rows) for k in ("tp", "fp", "fn")]
                    return metrics(*counts)["f1"]
                row["ai_gold"][matching]["ci95"] = bootstrap_ci(list(chunk_scores.values()), aggregate, **policy["bootstrap"])
        if baseline:
            # A0 disables validation, so its full export is also its strict baseline.
            prior_level = "full" if level == "strict" and "strict" not in prior["exports"] else level
            prior_facts = [WellFact.model_construct(**r["fact"]) for r in iter_jsonl(baseline / "per_fact.jsonl") if r["export"] == prior_level]
            row["self_consistency"] = score(prior_facts, pred, policy)
            if gold:
                previous = prior["exports"][prior_level]["ai_gold"]["per_chunk"]
                current = row["ai_gold"]["per_chunk"]
                if set(previous) != set(current): raise ConfigError("paired gold scope mismatch")
                paired = {}
                for matching in ("L1", "L2", "L3"):
                    def aggregate(rows): return metrics(*(sum(r[matching][k] for r in rows) for k in ("tp", "fp", "fn")))["f1"]
                    keys = sorted(current)
                    paired[matching] = paired_bootstrap([previous[k] for k in keys], [current[k] for k in keys], aggregate, **policy["bootstrap"])
                    differences = [current[k][matching]["f1"] - previous[k][matching]["f1"] for k in keys
                                   if current[k][matching]["f1"] is not None and previous[k][matching]["f1"] is not None]
                    paired[matching]["sign_test"] = sign_test(sum(d > 0 for d in differences), sum(d < 0 for d in differences))
                row["ai_gold"]["paired"] = paired
        results["exports"][level] = row
        details.extend({"export": level, "fact": f.model_dump()} for f in pred)
    if not results["exports"]: raise ConfigError("no graph exports")
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "scores.json", results)
    write_jsonl(out_dir / "per_fact.jsonl", details)
    lines = ["# Well evaluation", "", f"Scope SHA-256: {scope_hash}; n={len(ids)}", ""]
    for layer, label in LABELS.items():
        lines.extend([label, "", "| Export | n | Results |", "| --- | ---: | --- |"])
        for level, row in results["exports"].items():
            if row[layer] is not None: lines.append(f"| {level} | {len(ids)} | {cj(row[layer])} |")
        lines.append("")
        if layer == "ai_gold": lines.extend([LIMITATIONS, ""])
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return results
