# unstructured

Pinned: `910d9f41e70a17e561797106ef4b9096a8554254` ([source](https://github.com/Unstructured-IO/unstructured.git)). Code licence: Apache-2.0, read from `third_party/unstructured/LICENSE.md:1-25`. Weights: Not used; no weight rights inferred from the code licence.

Element metadata includes page, coordinates and parent information. Metadata consolidation deliberately drops coordinates/parent_id and keeps the first page; orig_elements must be retained when evidence matters. Evidence: `third_party/unstructured/unstructured/documents/elements.py:167-224`; `third_party/unstructured/unstructured/documents/elements.py:540-591`.

Hash conversion is available, but default UUID creation and explicit hash mapping are different paths; stable IDs should not be assumed merely from the element class. Evidence: `third_party/unstructured/unstructured/documents/elements.py:608-625`; `third_party/unstructured/unstructured/documents/elements.py:812-835`.

[Captured scores, native anchors, output text and errors](../../results/tool-survey.json). [Pins and runtime inputs](../../configs/inputs.lock.json); [licences](../../NOTICE.md).
