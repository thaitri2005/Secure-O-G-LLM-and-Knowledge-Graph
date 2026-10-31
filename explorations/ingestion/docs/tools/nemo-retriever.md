# nemo-retriever

Pinned: `de4190987f4c54db0b01be701bf2b0adc30b5c06` ([source](https://github.com/NVIDIA/NeMo-Retriever.git)). Code licence: Apache-2.0, read from `third_party/nemo-retriever/LICENSE:1-25`. Weights: Not used; no weight rights inferred from the code licence.

Metadata includes hierarchy/page fields and table bbox/serialized content. PDF extraction records errors in the extraction flow rather than requiring all results to succeed. Evidence: `third_party/nemo-retriever/nemo_retriever/src/nemo_retriever/common/api/internal/schemas/meta/metadata_schema.py:98-138`; `third_party/nemo-retriever/nemo_retriever/src/nemo_retriever/common/api/internal/schemas/meta/metadata_schema.py:217-246`; `third_party/nemo-retriever/nemo_retriever/src/nemo_retriever/operators/extract/pdf/extract.py:190-215`.

[Captured scores, native anchors, output text and errors](../../results/tool-survey.json). [Pins and runtime inputs](../../configs/inputs.lock.json); [licences](../../NOTICE.md).
