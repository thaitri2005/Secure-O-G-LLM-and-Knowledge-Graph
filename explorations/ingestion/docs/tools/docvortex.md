# docvortex

Pinned: `2de5f42b1884495313d9df63868e6a2f3d85fea0` ([source](https://github.com/myhloli/DocVortex.git)). Code licence: MIT root licence; bundled component notices separate, read from `third_party/docvortex/LICENSE.md:1-21`. Weights: Not used; no weight rights inferred from the code licence.

The pinned source examines only consecutive page boundaries, skips transparent boundary blocks, and marks the later table as continues_prev. It preserves page fragments instead of immediately flattening them. Evidence: `third_party/docvortex/src/docvortex/content/table/document.py:40-104`.

Continuation decisions examine captions, footnotes, width compatibility and column/row structure; header comparison includes spans and normalized text. This is more nuanced than a universal identical-header rule. Evidence: `third_party/docvortex/src/docvortex/content/table/structure.py:16-49`; `third_party/docvortex/src/docvortex/content/table/structure.py:144-208`.

[Captured scores, native anchors, output text and errors](../../results/tool-survey.json). [Pins and runtime inputs](../../configs/inputs.lock.json); [licences](../../NOTICE.md).
