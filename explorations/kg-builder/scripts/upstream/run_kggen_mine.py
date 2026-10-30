"""KGGen (stair-lab/kg-gen @ 6259b4c) MINE minitest on LM Studio.

    . ./scripts/onprem_env.ps1
    .venvs/kggen/Scripts/python.exe scripts/upstream/run_kggen_mine.py --dry-run   # no model calls
    .venvs/kggen/Scripts/python.exe scripts/upstream/run_kggen_mine.py             # needs approval

Per essay, exactly what upstream process_single_evaluation does: generate (SEMHASH dedup),
export, to_nx, generate_embeddings, evaluate_accuracy. The judge (EvaluateResponse +
evaluate_accuracy) is imported from experiments/MINE/_1_evaluation.py unchanged; that module
configures DSPy with a hosted-model default at import (no network call), and we re-point DSPy's global
LM at LM Studio right after. Essays run one at a time (upstream default is 64 workers).
"""

import _onprem
import argparse
import importlib.util
import json
import time
from pathlib import Path

PROJECT_ROOT = _onprem.PROJECT_ROOT
MINE_SCRIPT = PROJECT_ROOT / "third_party" / "kg-gen" / "experiments" / "MINE" / "_1_evaluation.py"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", type=Path, default=PROJECT_ROOT / "data" / "benchmarks" / "mine" / "mine_5.jsonl")
    p.add_argument("--model", default="qwen3.6-35b-a3b", help="LM Studio model id")
    p.add_argument("--retrieval-model", default="sentence-transformers/all-MiniLM-L6-v2",
                   help="same encoder as upstream MINE")
    p.add_argument("--max-tokens", type=int, default=4096)
    p.add_argument("--limit", type=int, default=None, help="first N essays only")
    p.add_argument("--out", type=Path, default=PROJECT_ROOT / "runs" / "upstream" / "kggen" / "mine_5")
    p.add_argument("--dry-run", action="store_true", help="imports, config and data only")
    args = p.parse_args()
    args.out = args.out.resolve()
    return args


def load_upstream_mine():
    spec = importlib.util.spec_from_file_location("kggen_mine_eval", MINE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def usage(lm) -> dict:
    totals = {"calls": len(lm.history), "prompt_tokens": 0, "completion_tokens": 0}
    for entry in lm.history:
        u = entry.get("usage") or {}
        totals["prompt_tokens"] += u.get("prompt_tokens", 0) or 0
        totals["completion_tokens"] += u.get("completion_tokens", 0) or 0
    return totals


def main() -> None:
    args = parse_args()
    base_url, api_key = _onprem.local_endpoint()
    essays = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    essays = essays[: args.limit] if args.limit else essays

    llm_log = args.out.parent / f"llm_calls_{args.out.name}.jsonl"
    if not args.dry_run:
        import _nothink

        net_log = _onprem.guard_network(f"net_kggen_{args.out.name}")
        base_url = _nothink.start(base_url, llm_log)

    import dspy
    from kg_gen import KGGen
    from kg_gen.steps._3_deduplicate import DeduplicateMethod

    mine = load_upstream_mine()
    model = f"lm_studio/{args.model}"  # LiteLLM chat route; "openai/" would force /v1/responses
    judge_lm = dspy.LM(model=model, api_base=base_url, api_key=api_key, temperature=0.0,
                       max_tokens=args.max_tokens)
    dspy.configure(lm=judge_lm)
    kggen = KGGen(model=model, api_base=base_url, api_key=api_key, temperature=0.0,
                  max_tokens=args.max_tokens, retrieval_model=args.retrieval_model)

    if args.dry_run:
        from kg_gen.models import Graph
        from kg_gen.utils.deduplicate import run_semhash_deduplication

        toy = Graph(entities={"Alan Turing", "Alan Turings", "London"}, edges={"born in"},
                    relations={("Alan Turing", "born in", "London")})
        print(json.dumps({
            "semhash_offline": sorted(run_semhash_deduplication(toy, 0.95).entities),
            "essays": len(essays),
            "queries": sum(len(e["generated_queries"]) for e in essays),
            "kggen_lm": {"model": kggen.lm.model, "model_type": kggen.lm.model_type,
                         "api_base": kggen.lm.kwargs.get("api_base")},
            "judge_lm": dspy.settings.lm.model,
            "judge_signature": mine.EvaluateResponse.__doc__,
            "retrieval_model_dim": kggen.retrieval_model.get_sentence_embedding_dimension(),
        }, indent=2))
        return

    args.out.mkdir(parents=True, exist_ok=False)
    rows, start = [], time.time()
    for essay in essays:
        t0 = time.time()
        graph = kggen.generate(essay["essay_content"], deduplication_method=DeduplicateMethod.SEMHASH)
        KGGen.export_graph(graph, str(args.out / f"kg_{essay['id']}.json"))
        nx_graph = kggen.to_nx(graph)
        node_embeddings, _ = kggen.generate_embeddings(nx_graph)
        result_file = args.out / f"results_{essay['id']}.json"
        mine.evaluate_accuracy(kggen, essay["generated_queries"], node_embeddings, nx_graph, str(result_file))
        accuracy = json.loads(result_file.read_text(encoding="utf-8"))[-1]["accuracy"]
        rows.append({"id": essay["id"], "accuracy": accuracy, "entities": len(graph.entities),
                     "relations": len(graph.relations), "seconds": round(time.time() - t0, 1),
                     "published_kggen_accuracy": essay["kggen_accuracy"]})
        print(json.dumps(rows[-1]), flush=True)

    summary = {"model": args.model, "retrieval_model": args.retrieval_model, "essays": rows,
               "wall_seconds": round(time.time() - start, 1),
               "extraction_usage": usage(kggen.lm), "judge_usage": usage(judge_lm),
               "proxy": _nothink.summarize(llm_log), "llm_log": str(llm_log.relative_to(PROJECT_ROOT)),
               "net_log": str(net_log.relative_to(PROJECT_ROOT))}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
