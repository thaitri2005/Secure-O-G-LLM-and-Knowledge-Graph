# ragflow

Pinned: `c90fe46c56867b878c38c1b14c991ae9188c7855` ([source](https://github.com/infiniflow/ragflow.git)). Code licence: Apache-2.0, read from `third_party/ragflow/LICENSE:1-25`. Weights: Not used; no weight rights inferred from the code licence.

The current Go implementation projects merged cells differently for table, general-data and QA consumers; header spans are kept out of data rows. This is more precise than flattening one grid for all uses. Evidence: `third_party/ragflow/internal/parser/tableutil/table_rows.go:20-52`.

DeepDoc native TSR returns structural labels and original-pixel boxes. The listed historical Python paths are absent at this pin. Evidence: `third_party/ragflow/internal/deepdoc/native/tsr.go:5-49`.

Read-only current-source study. The README identifies Go/native build requirements and CPU DeepDoc in the 1.0 release; no Windows or Vietnamese run was attempted (`third_party/ragflow/README.md:213`, `third_party/ragflow/README.md:252`).

[Captured scores, native anchors, output text and errors](../../results/tool-survey.json). [Pins and runtime inputs](../../configs/inputs.lock.json); [licences](../../NOTICE.md).
