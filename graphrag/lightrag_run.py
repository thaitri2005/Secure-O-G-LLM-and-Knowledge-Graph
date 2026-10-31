"""LightRAG (HKUDS, MIT licence, used as a library) on the K1 chunks, with our client and answer harness (E19).

Runs in `.venv-lightrag` (`pip install lightrag-hku==1.5.7`). LightRAG builds its graph from our chunks
(`ainsert_custom_chunks`, so K1 chunk IDs are kept through a content lookup), calls our model client (cache
and cost ledger), and retrieves with `aquery_data`. Its entities, relations and chunks then go through
`graphrag.baseline`'s answer prompt and citation check, so only retrieval differs from the baseline.

    python -m graphrag.lightrag_run index --pool ak3 --model qwen3-8b --name E19_ak3
    python -m graphrag.lightrag_run answer --index E19_ak3 --mode mix --budget default --name E19_answers_ak3_mix
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import numpy as np
from lightrag import LightRAG, QueryParam
from lightrag.utils import EmbeddingFunc, sanitize_text_for_encoding

from .baseline import ANSWER_FORMATS, POOLS, RESULTS, answer_questions, pool, summarize
from .client import ModelClient, load_endpoints
from .data import QUESTION_SETS, ROOT, load_questions
from .retrieval import QUERY_INSTRUCTION, passage_text

WORK = ROOT / "data/interim/lightrag"
EMBED_MODEL, EMBED_DIM = "qwen3-embedding-0.6b", 1024
# Query budgets. "default" is LightRAG 1.5.7's own (constants.py); "small" is near the baseline's five passages.
BUDGETS = {
    "default": {"top_k": 40, "chunk_top_k": 20, "max_entity_tokens": 6000, "max_relation_tokens": 8000,
                "max_total_tokens": 30000},
    "small": {"top_k": 10, "chunk_top_k": 5, "max_entity_tokens": 800, "max_relation_tokens": 800,
              "max_total_tokens": 4000},
}


def make_rag(directory: Path, llm: ModelClient, embedder: ModelClient, guidance: str | None = None) -> LightRAG:
    async def complete(prompt, system_prompt=None, history_messages=None, keyword_extraction=False, **kwargs):
        messages = ([{"role": "system", "content": system_prompt}] if system_prompt else []) + list(
            history_messages or []) + [{"role": "user", "content": prompt}]
        json_mode = keyword_extraction or (kwargs.get("response_format") or {}).get("type") == "json_object"
        call = await asyncio.to_thread(llm.chat, messages, schema={"type": "object"} if json_mode else None,
                                       max_tokens=kwargs.get("max_tokens") or 4096)
        return call.content

    async def embed(texts: list[str], context: str = "document") -> np.ndarray:
        # Qwen3-Embedding wants an instruction before queries and none before passages (as in Dense).
        texts = [QUERY_INSTRUCTION + t for t in texts] if context == "query" else texts
        return np.array(await asyncio.to_thread(embedder.embed, texts), dtype=np.float32)

    directory.mkdir(parents=True, exist_ok=True)
    return LightRAG(
        working_dir=str(directory), llm_model_func=complete, llm_model_name=llm.model,
        embedding_func=EmbeddingFunc(embedding_dim=EMBED_DIM, max_token_size=8192, func=embed,
                                     model_name=EMBED_MODEL, supports_asymmetric=True),
        # One request at a time: parallel requests make llama.cpp results non-repeatable (B-F19, B-C10).
        llm_model_max_async=1, embedding_func_max_async=1, max_parallel_insert=1,
        addon_params={"entity_types_guidance": guidance} if guidance else {})


def clients(endpoint: str, model: str) -> tuple[ModelClient, ModelClient]:
    endpoints = load_endpoints()
    return ModelClient(endpoints[endpoint], model), ModelClient(endpoints["local-embed"], EMBED_MODEL, cache_dir=None)


async def index(args) -> dict:
    chunks = pool(args.pool)
    llm, embedder = clients(args.endpoint, args.model)
    guidance = Path(args.guidance).read_text(encoding="utf-8") if args.guidance else None
    rag = make_rag(WORK / args.name, llm, embedder, guidance)
    await rag.initialize_storages()
    started = time.perf_counter()
    try:
        for doc_id in dict.fromkeys(c.doc_id for c in chunks):
            texts = [passage_text(c) for c in chunks if c.doc_id == doc_id]
            await rag.ainsert_custom_chunks("\n\n".join(texts), texts, doc_id=doc_id)
            print(f"indexed {doc_id}: {len(texts)} chunks, {llm.ledger.calls} LLM calls so far", flush=True)
    finally:
        await rag.finalize_storages()
    seconds = time.perf_counter() - started
    graph = graph_size(WORK / args.name)
    pages = len({(c.doc_id, c.page) for c in chunks})
    cost = llm.ledger.summary()
    return {"pool": args.pool, "pool_description": POOLS[args.pool], "chunks": len(chunks), "pages": pages,
            "endpoint": args.endpoint, "model": args.model, "guidance": args.guidance, "lightrag": "1.5.7",
            "graph": graph, "wall_seconds": round(seconds, 1), "llm": cost,
            "embedding": embedder.ledger.summary(),
            "per_page": {"calls": round(cost["calls"] / pages, 2),
                         "tokens": round((cost["prompt_tokens"] + cost["completion_tokens"]) / pages),
                         "seconds": round(seconds / pages, 2)}}


def graph_size(directory: Path) -> dict:
    import networkx as nx
    files = list(directory.glob("graph_*.graphml"))
    if not files:
        return {}
    g = nx.read_graphml(files[0])
    types: dict[str, int] = {}
    for _, data in g.nodes(data=True):
        types[data.get("entity_type", "?")] = types.get(data.get("entity_type", "?"), 0) + 1
    return {"entities": g.number_of_nodes(), "relations": g.number_of_edges(),
            "entity_types": dict(sorted(types.items(), key=lambda kv: -kv[1]))}


def render_graph(data: dict, limit_entities: int, limit_relations: int) -> str:
    entities = [f"- {e['entity_name']} ({e.get('entity_type', '')}): {e.get('description', '')}"
                for e in data.get("entities", [])[:limit_entities]]
    relations = [f"- {r['src_id']} -> {r['tgt_id']}: {r.get('description', '')}"
                 for r in data.get("relationships", [])[:limit_relations]]
    return "\n".join((["Entities:"] + entities if entities else []) + (["Relations:"] + relations if relations else []))


async def answer(args) -> dict:
    meta = json.loads((RESULTS / f"{args.index}.json").read_text(encoding="utf-8"))
    chunks = pool(meta["pool"])
    # LightRAG returns chunk text; map it back to K1 chunk IDs so citations are checked as in the baseline.
    by_text = {sanitize_text_for_encoding(passage_text(c)): c.id for c in chunks}
    llm, embedder = clients(args.endpoint, meta["model"])
    rag = make_rag(WORK / args.index, llm, embedder)
    await rag.initialize_storages()
    budget = BUDGETS[args.budget]
    contexts: dict[str, tuple[list[str], str]] = {}
    unmapped = 0
    try:
        questions, _ = load_questions(args.questions)
        for q in questions:
            data = (await rag.aquery_data(q["question"], QueryParam(mode=args.mode, enable_rerank=False, **budget)))
            data = data.get("data", {}) or {}
            hits = []
            for c in data.get("chunks", []):
                cid = by_text.get(sanitize_text_for_encoding(c["content"]))
                unmapped += cid is None
                if cid and cid not in hits:
                    hits.append(cid)
            graph = "" if args.no_graph else render_graph(data, budget["top_k"], budget["top_k"])
            contexts[q["question"]] = (hits, graph)
    finally:
        await rag.finalize_storages()
    query_cost = llm.ledger.summary()
    reader = ModelClient(load_endpoints()[args.endpoint], meta["model"])
    rows = answer_questions(lambda question: contexts[question], chunks, reader, max_tokens=args.max_tokens,
                            questions=args.questions, answer_format=args.answer_format)
    out = {"pool": meta["pool"], "index": args.index, "mode": args.mode, "budget": args.budget, "graph_in_prompt": not args.no_graph,
           "question_set": args.questions, "answer_format": args.answer_format,
           "model": meta["model"], "unmapped_chunks": unmapped,
           "median_passages": float(np.median([r["passages"] for r in rows])),
           "query_keyword_calls": query_cost, **summarize(rows, reader)}
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    i = sub.add_parser("index")
    i.add_argument("--pool", choices=POOLS, default="ak3")
    i.add_argument("--model", required=True)
    i.add_argument("--guidance", help="a text file replacing LightRAG's entity-type guidance (ontology slice)")
    a = sub.add_parser("answer")
    a.add_argument("--index", required=True, help="the name given to `index`")
    a.add_argument("--mode", default="mix", choices=["naive", "local", "global", "hybrid", "mix"])
    a.add_argument("--budget", default="default", choices=BUDGETS)
    a.add_argument("--no-graph", action="store_true", help="give the answer model the chunks only")
    a.add_argument("--max-tokens", type=int, default=400)
    a.add_argument("--questions", choices=QUESTION_SETS, default="prototype")
    a.add_argument("--answer-format", choices=ANSWER_FORMATS, default="status_first")
    for p in (i, a):
        p.add_argument("--endpoint", default="local-llama")
        p.add_argument("--name", required=True, help="result file name under graphrag/results/ (and index directory)")
    args = parser.parse_args(argv)
    result = asyncio.run(index(args) if args.command == "index" else answer(args))
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{args.name}.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
