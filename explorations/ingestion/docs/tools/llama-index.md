# llama-index

Pinned: `619d74664e8404612038bc15a1a40c686037277c` ([source](https://github.com/run-llama/llama_index.git)). Code licence: MIT, read from `third_party/llama-index/LICENSE:1-21`. Weights: Not used; no weight rights inferred from the code licence.

Hierarchical parsing links parents and children and defaults to 2048/512/128 chunk sizes. Auto-merging compares retrieved children with the parent child-count, using a threshold; this is retrieval behavior, not reconstruction validation. Evidence: `third_party/llama-index/llama-index-core/llama_index/core/node_parser/relational/hierarchical.py:14-21`; `third_party/llama-index/llama-index-core/llama_index/core/node_parser/relational/hierarchical.py:126-142`; `third_party/llama-index/llama-index-core/llama_index/core/retrievers/auto_merging_retriever.py:79-95`.

Read-only; no embedding/LLM or retrieval benchmark executed. Deterministic IDs need explicit control because node utilities default to UUIDs (`third_party/llama-index/llama-index-core/llama_index/core/node_parser/node_utils.py:25`).

[Captured scores, native anchors, output text and errors](../../results/tool-survey.json). [Pins and runtime inputs](../../configs/inputs.lock.json); [licences](../../NOTICE.md).
