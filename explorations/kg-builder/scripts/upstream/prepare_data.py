"""Build the small, deterministic benchmark subsets under data/ (offline, no LLM calls).

    .venvs/kggen/Scripts/python.exe scripts/upstream/prepare_data.py

Needs configs/runtime/assets.json from fetch_assets.py (for the MINE parquet).
Writes data/benchmarks/{webnlg,mine,2wiki}/ and data/manifest.json (sources, licenses, SHA-256).
"""

import _onprem  # noqa: F401
import ast
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq

PROJECT_ROOT = _onprem.PROJECT_ROOT
DATA = PROJECT_ROOT / "data"
TP = PROJECT_ROOT / "third_party"
SEED = 42
N_WEBNLG = 30
N_MINE = 5
N_2WIKI = {"compositional": 8, "comparison": 8, "bridge_comparison": 7, "inference": 7}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(line.rstrip("\n") + "\n" for line in lines), encoding="utf-8")


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def files_entry(*paths: Path) -> dict:
    return {rel(p): sha256(p) for p in paths}


def webnlg() -> dict:
    src_text = TP / "edc" / "datasets" / "webnlg.txt"
    src_ref = TP / "edc" / "evaluate" / "references" / "webnlg.txt"
    texts = src_text.read_text(encoding="utf-8").splitlines()
    refs = src_ref.read_text(encoding="utf-8").splitlines()
    assert len(texts) == len(refs), (len(texts), len(refs))
    idx = sorted(random.Random(SEED).sample(range(len(texts)), N_WEBNLG))
    out_text = DATA / "benchmarks" / "webnlg" / f"webnlg_{N_WEBNLG}.txt"
    out_ref = DATA / "benchmarks" / "webnlg" / f"webnlg_{N_WEBNLG}.ref.txt"
    write_lines(out_text, [texts[i] for i in idx])
    write_lines(out_ref, [refs[i] for i in idx])
    gold_triples = sum(len(ast.literal_eval(refs[i])) for i in idx)
    return {
        "purpose": "construction accuracy (EDC evaluate/evaluation_script.py, WebNLG P/R/F1)",
        "source_url": "https://github.com/clear-nus/edc/tree/02aad17e2fc1e9845c84746b384e7fd3160edc1a/datasets",
        "source_files": files_entry(src_text, src_ref),
        "license": "WebNLG corpus: CC BY-NC-SA 4.0 (GEM/web_nlg card lists CC BY-NC 4.0); EDC code MIT",
        "full_size": len(texts),
        "selection": {"seed": SEED, "n": N_WEBNLG, "line_indices_0based": idx},
        "gold_triples": gold_triples,
        "files": files_entry(out_text, out_ref),
    }


def mine() -> dict:
    assets = json.loads((PROJECT_ROOT / "configs" / "runtime" / "assets.json").read_text(encoding="utf-8"))
    info = assets["datasets"]["josancamon/kg-gen-MINE-evaluation-dataset"]
    parquet = PROJECT_ROOT / info["file"]
    rows = sorted(pq.read_table(parquet).to_pylist(), key=lambda r: r["id"])
    picked = sorted(random.Random(SEED).sample(rows, N_MINE), key=lambda r: r["id"])
    keep = ("id", "essay_topic", "essay_content", "generated_queries",
            "kggen_accuracy", "graphrag_accuracy", "openie_accuracy")
    out = DATA / "benchmarks" / "mine" / f"mine_{N_MINE}.jsonl"
    write_lines(out, [json.dumps({k: r[k] for k in keep}, ensure_ascii=False) for r in picked])
    return {
        "purpose": "information retention (KGGen MINE: KG retrieval + LLM judge, accuracy per essay)",
        "source_url": f"https://huggingface.co/datasets/josancamon/kg-gen-MINE-evaluation-dataset/tree/{info['revision']}",
        "source_files": files_entry(parquet),
        "license": "not declared on the HF dataset card; kg-gen code MIT (pyproject only). Cite, do not redistribute",
        "full_size": len(rows),
        "selection": {"seed": SEED, "n": N_MINE, "essay_ids": [r["id"] for r in picked]},
        "queries": sum(len(r["generated_queries"]) for r in picked),
        "essay_chars": [len(r["essay_content"]) for r in picked],
        "reference_accuracy_note": "kggen/graphrag/openie_accuracy are the published per-essay scores (LLM judge)",
        "files": files_entry(out),
    }


def two_wiki() -> dict:
    src_q = TP / "hipporag" / "reproduce" / "dataset" / "2wikimultihopqa.json"
    src_c = TP / "hipporag" / "reproduce" / "dataset" / "2wikimultihopqa_corpus.json"
    questions = json.loads(src_q.read_text(encoding="utf-8"))
    corpus_by_title = {}
    for doc in json.loads(src_c.read_text(encoding="utf-8")):
        corpus_by_title.setdefault(doc["title"], doc["text"])
    by_type = defaultdict(list)
    for q in questions:
        by_type[q["type"]].append(q)
    rng = random.Random(SEED)
    picked = []
    for qtype, n in N_2WIKI.items():
        picked += rng.sample(by_type[qtype], n)
    picked.sort(key=lambda q: q["_id"])

    corpus, seen = [], set()
    for q in picked:
        context = {title: sents for title, sents in q["context"]}
        for title, _ in q["supporting_facts"]:
            if title in seen:
                continue
            seen.add(title)
            text = corpus_by_title.get(title) or " ".join(s.strip() for s in context[title])
            corpus.append({"title": title, "text": text, "idx": len(corpus)})

    out_q = DATA / "benchmarks" / "2wiki" / f"2wiki_{len(picked)}.json"
    out_c = DATA / "benchmarks" / "2wiki" / f"2wiki_{len(picked)}_corpus.json"
    write_json(out_q, picked)
    write_json(out_c, corpus)
    return {
        "purpose": "graph-as-index QA (EM/F1 on answer, Recall@k on supporting passages; evidences = gold triples)",
        "source_url": "https://github.com/OSU-NLP-Group/HippoRAG/tree/d5c8329422e0a0b834a15874545cb6a74b4f9b26/reproduce/dataset",
        "upstream_dataset": "https://github.com/Alab-NII/2wikimultihop",
        "source_files": files_entry(src_q, src_c),
        "license": "2WikiMultihopQA: Apache-2.0 (Wikipedia text CC BY-SA); HippoRAG code MIT",
        "full_size": len(questions),
        "selection": {"seed": SEED, "per_type": N_2WIKI, "question_ids": [q["_id"] for q in picked]},
        "corpus_passages": len(corpus),
        "corpus_policy": "supporting passages of the selected questions only (other questions' passages act as distractors)",
        "gold_evidence_triples": sum(len(q["evidences"]) for q in picked),
        "files": files_entry(out_q, out_c),
    }


def showcase() -> dict:
    folder = DATA / "showcase"
    return {
        "purpose": "synthetic demonstration: entity merge (IBM), relation canonicalization including inverse (Turing), temporal edges (Alice)",
        "source_url": "Project-authored synthetic examples; see docs/datasets-and-licenses.md",
        "license": "TBD by repository owner",
        "files": files_entry(*sorted(folder.glob("*.jsonl"))),
    }


def main() -> None:
    manifest = {
        "seed": SEED,
        "webnlg": webnlg(),
        "mine": mine(),
        "2wiki": two_wiki(),
        "showcase": showcase(),
    }
    write_json(DATA / "manifest.json", manifest)
    for name, entry in manifest.items():
        if isinstance(entry, dict):
            print(name, list(entry["files"]))


if __name__ == "__main__":
    main()
