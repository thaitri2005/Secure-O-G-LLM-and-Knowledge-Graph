"""KGGen (stair-lab/kg-gen @ 6259b4c) on the 3 hand-made showcase docs, scored against gold.

    . ./scripts/onprem_env.ps1
    .venvs/kggen/Scripts/python.exe scripts/upstream/run_kggen_showcase.py     # local inference

One KGGen.generate per doc (SEMHASH dedup), then one cluster pass over the merged graph.
Minimal scorer (gold is not exhaustive, so recall is the headline number):
  * pair match:   subject and object equal gold after alias normalisation (gold_entities.jsonl);
  * triple match: pair match and every gold predicate word (born_in -> born, in) appears,
                  crudely stemmed, in the predicted relation.
Validity intervals (valid_from/valid_to) are not produced by KGGen and are not scored.
"""

import _onprem
import argparse
import json
import re
import time
from pathlib import Path

PROJECT_ROOT = _onprem.PROJECT_ROOT
SHOW = PROJECT_ROOT / "data" / "showcase"


def stem(word: str) -> str:
    return re.sub(r"(ed|s)$", "", word) if len(word) > 3 else word


def words(text: str) -> set:
    return {stem(w) for w in re.findall(r"[a-z]+", text.lower())}


def score(predicted: list, gold: list, alias: dict) -> dict:
    norm = lambda e: alias.get(e.strip().lower(), e.strip().lower())  # noqa: E731
    pred = [(norm(s), p, norm(o)) for s, p, o in predicted]
    hits = []
    for g in gold:
        gs, go = norm(g["subject"]), norm(g["object"])
        pair = [p for s, p, o in pred if (s, o) == (gs, go)]
        triple = [p for p in pair if words(g["predicate"].replace("_", " ")) <= words(p)]
        hits.append({"gold": [g["subject"], g["predicate"], g["object"]],
                     "pair_match": bool(pair), "triple_match": bool(triple), "predicted_relations": pair})
    n = len(gold)
    return {"gold_triples": n, "predicted_triples": len(pred),
            "pair_recall": round(sum(h["pair_match"] for h in hits) / n, 3),
            "triple_recall": round(sum(h["triple_match"] for h in hits) / n, 3), "per_gold": hits}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default="qwen3.6-35b-a3b")
    p.add_argument("--max-tokens", type=int, default=2048)
    p.add_argument("--out", type=Path, default=PROJECT_ROOT / "runs" / "upstream" / "kggen" / "showcase")
    args = p.parse_args()
    args.out = args.out.resolve()

    import _nothink

    net_log = _onprem.guard_network(f"net_kggen_{args.out.name}")
    base_url, api_key = _onprem.local_endpoint()
    llm_log = args.out.parent / f"llm_calls_{args.out.name}.jsonl"
    base_url = _nothink.start(base_url, llm_log)

    from kg_gen import KGGen
    from kg_gen.steps._3_deduplicate import DeduplicateMethod

    load = lambda name: [json.loads(l) for l in (SHOW / name).read_text(encoding="utf-8").splitlines() if l.strip()]  # noqa: E731,E741
    docs, gold = load("corpus.jsonl"), load("gold_triples.jsonl")
    alias = {a.lower(): e["canonical"].lower() for e in load("gold_entities.jsonl") for a in [e["canonical"], *e["aliases"]]}

    kggen = KGGen(model=f"lm_studio/{args.model}", api_base=base_url, api_key=api_key,
                  temperature=0.0, max_tokens=args.max_tokens)
    args.out.mkdir(parents=True, exist_ok=False)
    start, graphs, per_doc = time.time(), [], {}
    for doc in docs:
        t0 = time.time()
        g = kggen.generate(doc["text"], deduplication_method=DeduplicateMethod.SEMHASH)
        KGGen.export_graph(g, str(args.out / f"kg_{doc['doc_id']}.json"))
        graphs.append(g)
        per_doc[doc["doc_id"]] = {"entities": len(g.entities), "relations": len(g.relations),
                                  "seconds": round(time.time() - t0, 1)}
    merged = kggen.aggregate(graphs)
    KGGen.export_graph(merged, str(args.out / "kg_merged.json"))

    summary = {"model": args.model, "docs": per_doc, "wall_seconds": round(time.time() - start, 1),
               "score": score(sorted(merged.relations), gold, alias),
               "proxy": _nothink.summarize(llm_log), "llm_log": str(llm_log.relative_to(PROJECT_ROOT)),
               "net_log": str(net_log.relative_to(PROJECT_ROOT))}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
