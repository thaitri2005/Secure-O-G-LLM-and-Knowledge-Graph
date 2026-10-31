# olmocr

Pinned: `f7cfe4c22098b154c76b6ec950d1c0a464eecf8d` ([source](https://github.com/allenai/olmocr.git)). Code licence: Apache-2.0, read from `third_party/olmocr/LICENSE:1-25`. Weights: Not used; no weight rights inferred from the code licence.

The pipeline includes pdftotext fallback, retries/rotation handling and a document fallback-rate rejection threshold. Work queues use locks/completion records. Evidence: `third_party/olmocr/olmocr/pipeline.py:233-250`; `third_party/olmocr/olmocr/pipeline.py:283-310`; `third_party/olmocr/olmocr/pipeline.py:557-570`; `third_party/olmocr/olmocr/work_queue.py:38-82`.

[Captured scores, native anchors, output text and errors](../../results/tool-survey.json). [Pins and runtime inputs](../../configs/inputs.lock.json); [licences](../../NOTICE.md).
