# docling-serve

Pinned: `9c058dbb58f61021e3a16e37edb8a7527b2cb2d4` ([source](https://github.com/docling-project/docling-serve.git)). Code licence: MIT, read from `third_party/docling-serve/LICENSE:1-21`. Weights: Not used; no weight rights inferred from the code licence.

The service builds converter configuration and delegates orchestration to docling-jobkit. Configuration documents local threads/model sharing and distributed queue choices; an API wrapper does not alone prove durable shared task state. Evidence: `third_party/docling-serve/docling_serve/orchestrator_factory.py:1-30`; `third_party/docling-serve/docs/configuration.md:276-300`.

[Captured scores, native anchors, output text and errors](../../results/tool-survey.json). [Pins and runtime inputs](../../configs/inputs.lock.json); [licences](../../NOTICE.md).
