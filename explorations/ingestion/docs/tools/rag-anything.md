# rag-anything

Pinned: `2cd2b3329c470ccb53923f8a6d320596b34e56c5` ([source](https://github.com/HKUDS/RAG-Anything.git)). Code licence: MIT, read from `third_party/rag-anything/LICENSE:1-21`. Weights: Not used; no weight rights inferred from the code licence.

The Docling conversion path maps page_no to zero-based page_idx and emits table_body. An adapter must preserve a richer provenance sidecar rather than assume the downstream content format retains every cell. Evidence: `third_party/rag-anything/raganything/parser.py:2880-2962`.

[Captured scores, native anchors, output text and errors](../../results/tool-survey.json). [Pins and runtime inputs](../../configs/inputs.lock.json); [licences](../../NOTICE.md).
