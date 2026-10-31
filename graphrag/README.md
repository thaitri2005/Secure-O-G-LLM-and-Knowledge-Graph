# graphrag: Track B code

Track B's code for the first build: the model client, the plain-RAG baseline, and later the GraphRAG candidates (specification §4.5). Findings, decisions and runs are logged in [docs/tracks/B-graphrag/log.md](../docs/tracks/B-graphrag/log.md).

| Module | What it does |
|---|---|
| `client.py` | One OpenAI-compatible client for hosted (OpenRouter) and local (llama.cpp) endpoints. It provides chat with JSON-schema output, embeddings, a cache keyed by the full request, a per-run ledger (calls, tokens, seconds, cost) and the private-data guard |
| `data.py` | The inputs: K1 version 0 chunks (`data/processed/gdr_chunks_full.jsonl`), the prototype's 15-chunk slice, its 31 questions and its gold facts |
| `retrieval.py` | BM25, dense embeddings from an endpoint, and reciprocal-rank fusion. Every retriever takes an `allowed` chunk set (a payload filter). `wells:<retriever>` searches only the documents that name a well the question names (B-C11, E18) |
| `scoring.py` | The prototype's value-matching and answer rules, so results compare with E10; `normalize` puts dates and numbers in one form after the call |
| `citations.py` | Checks each model citation against the retrieved chunks and attaches a verified one in code (B-C08) |
| `baseline.py` | Command line for retrieval and answer runs; it writes `graphrag/results/<name>.json`. `--facts` adds a graph's extracted facts under each passage; `--withhold-unsupported` drops answers without a supported citation |
| `neo4j_kg.py` | neo4j-graphrag-python (Apache-2.0, used as a library) on the K1 chunks: the ontology profile as its schema, our client as its LLM and embedder, facts read back from Neo4j and scored against the gold facts (E16) |

Endpoints are listed in [`configs/graphrag/endpoints.json`](../configs/graphrag/endpoints.json). Hosted endpoints read their key from the environment, for example `OPENROUTER_API_KEY`. Local endpoints refuse no data class; hosted ones accept public data only.

## Running locally

Models live in ignored `data/interim/models/`. Start the servers with llama.cpp's `llama-server`. On an Nvidia GPU, use the CUDA build from the [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases) (E15 used b12015, `win-cuda-12.4-x64` plus its `cudart` zip, unpacked into ignored `data/interim/llama.cpp/`) and `-ngl 99`. On a laptop with an integrated GPU, use `--device none -ngl 0` instead: the Vulkan backend runs out of device memory.

```powershell
llama-server -m data/interim/models/Qwen3-Embedding-0.6B-Q8_0.gguf --embedding --pooling last --port 8081 -c 8192 -b 2048 -ub 2048 -ngl 99 --alias qwen3-embedding-0.6b
# The baseline answer model (E17). Thinking stays off. 8k context per slot; extraction prompts need it.
llama-server -m data/interim/models/Qwen3-8B-Q4_K_M.gguf --port 8080 -c 32768 -np 4 -ngl 99 --jinja --chat-template-kwargs '{"enable_thinking":false}' --alias qwen3-8b

python -m graphrag.baseline retrieval --pool ak3 --retrievers bm25 dense:qwen3-embedding-0.6b fusion:bm25+dense:qwen3-embedding-0.6b --name my_run
python -m graphrag.baseline answer --pool ak3 --retriever bm25 --k 5 --endpoint local-llama --model qwen3-8b --name my_answers
# The multi-report baseline (E18, D-50)
python -m graphrag.baseline answer --pool three --retriever wells:bm25 --k 5 --endpoint local-llama --model qwen3-8b --name my_three
```

Pools:

- `slice`: the 15 prototype chunks;
- `ak3`: the whole AK-3 end-of-well report, 60 chunks;
- `three`: AK-3 plus two other end-of-well reports as distractors, 372 chunks.

Measurement runs send one request at a time: parallel requests make llama.cpp results non-repeatable (B-F19).

## neo4j-graphrag-python (E16)

It needs Neo4j with APOC and its own environment, because it requires a newer `pypdf` than the main lock file allows (B-C09):

```powershell
docker compose -f configs/graphrag/docker-compose.yml up -d
py -3.12 -m venv .venv-graphrag
.venv-graphrag\Scripts\python -m pip install -r requirements-graphrag.lock.txt
.venv-graphrag\Scripts\python -m graphrag.neo4j_kg --pool ak3 --model qwen3-8b --prompt library --name my_graph
python -m graphrag.baseline answer --pool ak3 --retriever bm25 --k 5 --endpoint local-llama --model qwen3-8b --facts my_graph --name my_answers_with_facts
```

Each build clears the Neo4j database first. Neo4j Browser is at http://127.0.0.1:7474 (user `neo4j`, password `graphrag-dev`, local only).

Tests: `python -m unittest discover -s tests -p "test_graphrag.py"`. The tests make no model calls; the `neo4j_kg` tests run only in `.venv-graphrag`.
