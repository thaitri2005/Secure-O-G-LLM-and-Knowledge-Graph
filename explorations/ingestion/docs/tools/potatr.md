# potatr

Pinned: `fdb8f57c5124ff27ad7c12bcb976b48a615f1131` ([source](https://github.com/kensho-technologies/POTATR.git)). Code licence: MIT, read from `third_party/potatr/LICENSE:1-21`. Weights: MIT: `third_party/models/potatr/README.md:1-10`; pin in model lock.

The page-level image-to-graph model assembles tables from predicted nodes/edges and externally supplied word tokens. Output contains HTML, cells, captions and bbox; pages without word files are skipped. Evidence: `third_party/potatr/src/potatr/inference.py:98-145`; `third_party/potatr/src/potatr/inference.py:185-205`.

[Captured scores, native anchors, output text and errors](../../results/tool-survey.json). [Pins and runtime inputs](../../configs/inputs.lock.json); [licences](../../NOTICE.md).
