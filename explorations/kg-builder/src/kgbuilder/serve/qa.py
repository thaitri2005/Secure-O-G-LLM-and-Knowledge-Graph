"""Fixed graph and text retrieval, grounded reader calls, and QA scoring."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from kgbuilder.core import config, text
from kgbuilder.core.config import ConfigError, KgbError, QaConfig
from kgbuilder.core.contracts import Document, GraphRecord, ValidatedStatement, flagged
from kgbuilder.serve import query

SYSTEM = "Answer the question using only the passages and facts below. Reply with a short answer phrase only. For yes/no questions reply yes or no."
POSSESSIVE = re.compile(r"(\w)['\u2019]s\b")
CONNECTORS = frozenset("of the and de von van der la le du da di".split())
QUESTION_WORDS = frozenset("who what when where which why how did does do is are was were has have".split())


@dataclass(frozen=True)
class QaInputs:
    records: dict[str, GraphRecord]
    metrics: dict[str, dict | None]
    graph_sha256: dict[str, str]
    questions: list[dict]
    documents: list[Document]


def load_questions(path: Path, limit: int | None) -> list[dict]:
    """Validate the selected question prefix without changing file order."""
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"qa.questions: {exc}") from exc
    if not isinstance(rows, list):
        raise ConfigError("qa.questions: expected a JSON list")
    selected = rows[:limit]
    required = {"_id", "type", "question", "answer", "supporting_facts", "evidences"}
    for i, row in enumerate(selected):
        if not isinstance(row, dict) or not required.issubset(row):
            raise ConfigError(f"qa.questions: row {i}: requires {', '.join(sorted(required))}")
        if any(not isinstance(row[k], str) for k in ("_id", "type", "question", "answer")):
            raise ConfigError(f"qa.questions: row {i}: id, type, question and answer must be strings")
        for field, width in (("supporting_facts", 2), ("evidences", 3)):
            if not isinstance(row[field], list) or any(
                    not isinstance(item, list) or len(item) != width or not isinstance(item[0], str)
                    or (field == "evidences" and not all(isinstance(v, str) for v in item))
                    for item in row[field]):
                raise ConfigError(f"qa.questions: row {i}: invalid {field}")
    if not selected:
        raise ConfigError("qa.questions: no selected questions")
    return selected


def prepare(qa: QaConfig) -> QaInputs:
    """Load graph inputs and reject incomparable corpora before output is opened."""
    questions = load_questions(qa.questions, qa.limit)
    records, metrics, hashes = {}, {}, {}
    documents, corpus = [], None
    for label, path in qa.graphs.items():
        try:
            record = query.load_graph(path)
            metric_path = path / "metrics.json"
            metric = json.loads(metric_path.read_text(encoding="utf-8")) if metric_path.exists() else None
            if metric is not None and not isinstance(metric, dict):
                raise ValueError("metrics.json: expected a mapping")
            hashes[label] = text.sha256_file(path / "graph.json")
        except (ConfigError, OSError, ValueError) as exc:
            raise ConfigError(f"qa.graphs.{label}: {exc}") from exc
        docs = sorted(record.documents, key=lambda d: d.doc_id)
        current = [(d.doc_id, d.text) for d in docs]
        if corpus is not None and current != corpus:
            raise ConfigError("qa.graphs: graphs were built from different corpora")
        if corpus is None:
            documents, corpus = docs, current
        titles = {d.title for d in docs}
        for q in questions:
            for title in dict.fromkeys(f[0] for f in q["supporting_facts"]):
                if title not in titles:
                    raise ConfigError(f"qa.graphs.{label}: question {q['_id']}: missing title {title}")
        records[label], metrics[label] = record, metric
    return QaInputs(records, metrics, hashes, questions, documents)


def normalizer() -> Callable[[str], str]:
    """Read the upstream standalone normalizer without invoking an importer."""
    path = config.hipporag_eval_utils()
    ns = {"__name__": "hipporag_eval_utils"}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), ns)
    return ns["normalize_answer"]


def exact_match(gold: str, pred: str, norm) -> float:
    return float(norm(gold) == norm(pred))


def token_f1(gold: str, pred: str, norm) -> float:
    gold_tokens = norm(gold).split()
    predicted_tokens = norm(pred).split()
    common = Counter(predicted_tokens) & Counter(gold_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision = 1.0 * num_same / len(predicted_tokens)
    recall = 1.0 * num_same / len(gold_tokens)
    return 2 * (precision * recall) / (precision + recall)


def recall_at(gold_titles: set[str], retrieved_titles: list[str], k: int) -> float:
    return len(set(retrieved_titles[:k]) & gold_titles) / len(gold_titles) if gold_titles else 0.0


def seeds(record: GraphRecord, question: str, max_seeds: int, mode: str = "exact") -> list[str]:
    """Prefer the longest entity mention and suppress overlapping shorter names."""
    question = POSSESSIVE.sub(r"\1", question) if mode == "robust" else question
    q = text.surface_key(question)
    matches = set()
    for e in record.entities:
        if e.kind != "entity":
            continue
        for key in query.entity_keys(e):
            if len(key) >= 3 and key not in text.GROUND_STOPWORDS:
                for m in re.finditer(r"(?<!\w)" + re.escape(key) + r"(?!\w)", q):
                    matches.add((m.start(), m.end(), e.entity_id))
    accepted, ids = [], []
    for start, end, eid in sorted(matches, key=lambda m: (-(m[1] - m[0]), m[0], m[2])):
        if any(start < b and a < end and (start, end) != (a, b) for a, b in accepted):
            continue
        accepted.append((start, end))
        if eid not in ids:
            ids.append(eid)
            if len(ids) == max_seeds:
                break
    if mode == "robust" and len(ids) < max_seeds:
        words = list(re.finditer(r"\w+", question))
        spans, run = [], []
        for index, word in enumerate(words):
            value = word[0]
            eligible = value[0].isupper() or value[0].isdigit() or value.lower() in CONNECTORS
            if index == 0 and value.lower() in QUESTION_WORDS:
                eligible = False
            if run and question[run[-1].end():word.start()].strip():
                spans.append(run)
                run = []
            if eligible:
                run.append(word)
            elif run:
                spans.append(run)
                run = []
        if run:
            spans.append(run)
        for span in spans:
            while span and span[0][0].lower() in CONNECTORS:
                span = span[1:]
            while span and span[-1][0].lower() in CONNECTORS:
                span = span[:-1]
            if len(span) < 2:
                continue
            start = len(text.surface_key(question[:span[0].start()]))
            if start and question[span[0].start() - 1].isspace():
                start += 1
            end = start + len(text.surface_key(question[span[0].start():span[-1].end()]))
            if any(start < b and a < end for a, b in accepted):
                continue
            wanted = set(text.tokens(question[span[0].start():span[-1].end()]))
            candidates = []
            for entity in record.entities:
                if entity.kind != "entity":
                    continue
                for key in query.entity_keys(entity):
                    available = set(text.tokens(key))
                    coverage = len(wanted) / len(available) if available else 0
                    if wanted <= available and coverage >= .6:
                        candidates.append((-coverage, len(key), entity.entity_id))
            if candidates:
                eid = min(candidates)[2]
                if eid not in ids:
                    ids.append(eid)
                    if len(ids) == max_seeds:
                        break
    return ids


def graph_retrieve(record: GraphRecord, question: str, qa: QaConfig, encode=None) -> tuple[list[str], list[ValidatedStatement], list[str]]:
    """Traverse accepted undirected facts in hop, confidence and id order."""
    if qa.fact_order == "relevance" and encode is None:
        raise ValueError("relevance ordering requires an encoder")
    seed_ids = seeds(record, question, qa.max_seeds, qa.seed_linking)
    frontier, visited = set(seed_ids), set(seed_ids)
    chosen, chosen_ids = [], set()
    hops = {}
    for hop in range(qa.hops):
        layer = sorted((s for s in record.statements if s.status == "accepted"
                        and s.statement_id not in chosen_ids
                        and (s.subject_id in frontier or s.object_id in frontier)),
                       key=lambda s: (-s.confidence, s.statement_id))
        chosen.extend(layer)
        hops.update((s.statement_id, hop) for s in layer)
        chosen_ids.update(s.statement_id for s in layer)
        frontier = {eid for s in layer for eid in (s.subject_id, s.object_id)} - visited
        visited |= frontier
        if not frontier or (qa.fact_order == "confidence" and len(chosen) >= qa.max_statements):
            break
    if qa.fact_order == "relevance" and chosen:
        lines = fact_lines(record, chosen)
        scores = np.asarray(encode(lines)) @ np.asarray(encode([question]))[0]
        order = sorted(range(len(chosen)), key=lambda i: (
            flagged(chosen[i]), -round(float(scores[i]), 6), hops[chosen[i].statement_id], lines[i], chosen[i].statement_id))
        chosen = [chosen[i] for i in order]
    chosen = chosen[:qa.max_statements]
    ids = list(dict.fromkeys(e.doc_id for s in chosen for e in s.evidence))[:qa.k]
    return ids, chosen, seed_ids


def memo_encode(encode):
    """Reuse vectors for identical questions and fact lines within one graph."""
    vectors = {}
    def cached(values):
        missing = list(dict.fromkeys(value for value in values if value not in vectors))
        if missing:
            vectors.update(zip(missing, encode(missing)))
        return np.asarray([vectors[value] for value in values])
    return cached


def text_encoder(name: str) -> Callable[[list[str]], np.ndarray]:
    """Load the same offline normalized encoder used by the builder."""
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(name)
    return lambda xs: model.encode(list(xs), normalize_embeddings=True, convert_to_numpy=True)


def text_rank(documents: list[Document], doc_vectors, question: str, encode) -> list[str]:
    scores = np.asarray(doc_vectors) @ np.asarray(encode([question]))[0]
    return [documents[i].doc_id for i in sorted(range(len(documents)),
            key=lambda i: (-round(float(scores[i]), 6), documents[i].doc_id))]


def hybrid(graph_ids: list[str], text_ids: list[str], k: int) -> list[str]:
    return list(dict.fromkeys([*graph_ids, *text_ids]))[:k]


def fact_lines(record: GraphRecord, statements) -> list[str]:
    names = {e.entity_id: e.name for e in record.entities}
    return [f"- {names[s.subject_id]} {s.predicate} {names[s.object_id]}" for s in statements]


def reader_messages(question: str, passages: list[Document], facts: list[str]) -> list[dict]:
    content = "Passages:\n" + "\n".join(
        f"[{i}] {d.title or d.doc_id}: {d.text}" for i, d in enumerate(passages, 1)) + "\n\n"
    if facts:
        content += "Facts:\n" + "\n".join(facts) + "\n\n"
    content += f"Question: {question}\nAnswer:"
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]


def clean_answer(content: str) -> str:
    first = next((line.strip() for line in content.splitlines() if line.strip()), "")
    return re.sub(r"^answer:", "", first, flags=re.IGNORECASE).strip()


def ask(gateway_url: str, model: str, messages: list[dict], max_tokens: int, timeout_s: int) -> str:
    """Send a deterministic reader request through the CLI's loopback gateway."""
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0}
    req = urllib.request.Request(gateway_url.rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout_s) as response:
            content = json.loads(response.read().decode("utf-8"))["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("reader content must be a string")
        return content
    except urllib.error.HTTPError as exc:
        if exc.code == 503:
            raise KgbError(5, "qa: LLM replay miss") from exc
        raise KgbError(6, f"qa: reader call failed: {exc}") from exc
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise KgbError(6, f"qa: reader call failed: {exc}") from exc


def graph_stats(record: GraphRecord, metrics: dict | None, questions: list[dict]) -> dict:
    keys = {e.entity_id: query.entity_keys(e) for e in record.entities}
    all_keys = set().union(*keys.values()) if keys else set()
    gold = [triple for q in questions for triple in q["evidences"]]
    surfaces = {text.match_key(v) for s, _, o in gold for v in (s, o)}
    accepted = [s for s in record.statements if s.status == "accepted"]
    pairs = sum(any((text.match_key(s) in keys[st.subject_id] and text.match_key(o) in keys[st.object_id])
                    or (text.match_key(o) in keys[st.subject_id] and text.match_key(s) in keys[st.object_id])
                    for st in accepted) for s, _, o in gold)
    return {"entities": sum(e.kind == "entity" for e in record.entities),
            "entities_literal": sum(e.kind == "literal" for e in record.entities),
            "statements": len(accepted),
            "docs_with_statements": len({e.doc_id for s in accepted for e in s.evidence}),
            "evidence_entity_recall": len(surfaces & all_keys) / len(surfaces) if surfaces else 0.0,
            "evidence_pair_recall": pairs / len(gold) if gold else 0.0,
            "build": {k: metrics.get(k) for k in ("er_reduction", "statements_rejected",
                      "rejected_by_reason", "grounding", "llm", "stage_seconds")} if metrics is not None else None}


def _llm_stats(path: Path, stage: str) -> dict:
    rows = [r for r in text.read_jsonl(path) if r.get("stage") == stage] if path.exists() else []
    normal = [r for r in rows if not r.get("miss")]
    return {"calls": len(rows), "cache_hits": sum(bool(r.get("cache_hit")) for r in rows),
            "cache_misses": sum(bool(r.get("miss")) for r in rows),
            "prompt_tokens": sum(r.get("usage", {}).get("prompt_tokens", 0) for r in normal),
            "completion_tokens": sum(r.get("usage", {}).get("completion_tokens", 0) for r in normal),
            "seconds": round(sum(r.get("seconds", 0) for r in normal), 1)}


def eval_qa(qa: QaConfig, inputs: QaInputs, gateway_url: str, model: str, profile: str, timeout_s: int,
            set_stage: Callable[[str], None], out_dir: Path, encode=None) -> dict:
    """Evaluate every requested row with identical retrieval and reader settings."""
    needs_text = any(m in qa.modes for m in ("text", "hybrid"))
    if needs_text or qa.fact_order == "relevance":
        encode = encode or text_encoder(qa.embedder)
    if needs_text:
        vectors = encode([f"{d.title}\n{d.text}" if d.title else d.text for d in inputs.documents])
    graph_encoders = {label: memo_encode(encode) for label in inputs.records} if qa.fact_order == "relevance" else {}
    docs = {d.doc_id: d for d in inputs.documents}
    norm, recall_k = normalizer(), sorted({2, qa.k})
    definitions = ([("text", "text", None)] if "text" in qa.modes else []) + [
        (f"{mode}@{label}", mode, label) for mode in ("graph", "hybrid") if mode in qa.modes for label in qa.graphs]
    rows, answers, results = [], [], {}
    for row, mode, label in definitions:
        start = time.monotonic()
        set_stage("qa." + row)
        scores = []
        for q in inputs.questions:
            question = q["question"]
            seed_ids, facts = [], []
            if mode != "text":
                record = inputs.records[label]
                ids, statements, seed_ids = graph_retrieve(record, question, qa, graph_encoders.get(label))
                facts = fact_lines(record, statements)
            if mode == "text":
                ids = text_rank(inputs.documents, vectors, question, encode)[:qa.k]
            elif mode == "hybrid":
                ids = hybrid(ids, text_rank(inputs.documents, vectors, question, encode), qa.k)
            passages = [docs[i] for i in ids]
            skipped = mode == "graph" and not ids
            prediction = "" if skipped else clean_answer(ask(
                gateway_url, model, reader_messages(question, passages, facts), qa.max_tokens, timeout_s))
            gold = q["answer"]
            titles = [d.title or d.doc_id for d in passages]
            item = {"row": row, "qid": q["_id"], "type": q["type"], "question": question, "gold": gold,
                    "prediction": prediction, "em": exact_match(gold, prediction, norm),
                    "f1": token_f1(gold, prediction, norm), "retrieved": titles,
                    "seeds": [e.name for eid in seed_ids for e in inputs.records[label].entities if e.entity_id == eid],
                    "facts": facts, "skipped": skipped}
            answers.append(item)
            scores.append({**item, **{f"recall@{k}": recall_at(
                {f[0] for f in q["supporting_facts"]}, titles, k) for k in recall_k}})
        def mean(key, group):
            return sum(s[key] for s in group) / len(group)
        score_keys = ["em", "f1", *[f"recall@{k}" for k in recall_k]]
        rows.append({"row": row, "mode": mode, "graph": label, **{k: mean(k, scores) for k in score_keys},
                     "no_context": sum(s["skipped"] for s in scores),
                     "seeded": sum(bool(s["seeds"]) for s in scores) if mode != "text" else None,
                     "mean_passages": sum(len(s["retrieved"]) for s in scores) / len(scores),
                     "mean_facts": sum(len(s["facts"]) for s in scores) / len(scores),
                     "by_type": {t: {"n": len(group), **{k: mean(k, group) for k in ("em", "f1", f"recall@{qa.k}")}}
                                 for t in dict.fromkeys(q["type"] for q in inputs.questions)
                                 for group in [[s for s in scores if s["type"] == t]]},
                     "llm": _llm_stats(out_dir / "llm_calls.jsonl", "qa." + row),
                     "wall_seconds": round(time.monotonic() - start, 3)})
        results[row] = scores
    comparisons = [(r, "text") for r in results if r != "text"] if "text" in results else []
    for mode in ("graph", "hybrid"):
        variants = [f"{mode}@{label}" for label in qa.graphs if f"{mode}@{label}" in results]
        comparisons.extend((r, variants[0]) for r in variants[1:])
    pairwise = []
    for row, vs in comparisons:
        diffs = [a["f1"] - b["f1"] for a, b in zip(results[row], results[vs])]
        pairwise.append({"row": row, "vs": vs, "wins": sum(d > 0 for d in diffs),
                         "ties": sum(d == 0 for d in diffs), "losses": sum(d < 0 for d in diffs)})
    report = {"format": "kgb.qa/1", "name": qa.name, "model": model, "profile": profile,
              "config": qa.model_dump(mode="json"), "question_ids": [q["_id"] for q in inputs.questions],
              "n_questions": len(inputs.questions), "corpus_docs": len(inputs.documents), "recall_k": recall_k,
              "graphs": {label: {"run_dir": str(path), "graph_sha256": inputs.graph_sha256[label],
                         **graph_stats(inputs.records[label], inputs.metrics[label], inputs.questions)}
                         for label, path in qa.graphs.items()}, "rows": rows, "pairwise": pairwise}
    text.write_jsonl(out_dir / "answers.jsonl", answers)
    text.write_json(out_dir / "qa.json", report)
    return report

