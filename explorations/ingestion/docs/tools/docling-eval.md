# docling-eval

Pinned: `f998acba3d33fe381edf597de602f7a1d3174c1a` ([source](https://github.com/docling-project/docling-eval.git)). Code licence: MIT, read from `third_party/docling-eval/LICENSE:1-21`. Weights: Not used; no weight rights inferred from the code licence.

TEDS and table evaluation operate on structured tables; CVAT dataset conversion offers an annotation import path. Structural similarity should be paired with specific field/cell correctness checks. Evidence: `third_party/docling-eval/docling_eval/evaluators/table/teds.py:61-85`; `third_party/docling-eval/docling_eval/evaluators/table_evaluator.py:108-127`; `third_party/docling-eval/docling_eval/dataset_builders/cvat_dataset_builder.py:1-30`.

Reading-order qualification: the pinned evaluator uses Average Relative Distance but rejects external prediction loaders and runs its internal reading-order model on ground truth. It cannot directly score arbitrary parser reading-order outputs through that interface. Evidence: `third_party/docling-eval/docling_eval/evaluators/readingorder_evaluator.py:59-96`.

[Captured scores, native anchors, output text and errors](../../results/tool-survey.json). [Pins and runtime inputs](../../configs/inputs.lock.json); [licences](../../NOTICE.md).
