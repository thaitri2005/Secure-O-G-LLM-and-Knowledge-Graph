# mineru

Pinned: `dc60e7c6722ebf25a04ae2bc3b59f5b55118a040` ([source](https://github.com/opendatalab/MinerU.git)). Code licence: MinerU Open Source License (Apache-2.0 plus additional terms), read from `third_party/mineru/LICENSE.md:1-25`. Weights: 2604 and 2605 VLM cards are individually recorded; the ONNX bundle explicitly defers to original component licences (`third_party/models/mineru-onnx/README.md:3-11`).

Small-model backend and VLM engine are selected independently. The registry supplies ONNX assets and llama.cpp GGUF assets; the default at this pin is the 2605 model. Evidence: `third_party/mineru/mineru/model/registry.py:43-109`.

Shared table operations are delegated to docvortex. The optional LLM-aided cross-page cell merge is a separate feature, not the basic table-continuation switch. Evidence: `third_party/mineru/mineru/backend/postprocess/table_merge/__init__.py:1-22`; `third_party/mineru/mineru/config.py:392-420`; `third_party/mineru/mineru/backend/postprocess/llm_aided.py:14-45`.

The code licence requires a separate commercial licence above either affiliated MAU >100 million or total monthly revenue >USD20 million, plus attribution for third-party online services. This requires an organizational decision before adoption: `third_party/mineru/LICENSE.md:3-23`.

[Captured scores, native anchors, output text and errors](../../results/tool-survey.json). [Pins and runtime inputs](../../configs/inputs.lock.json); [licences](../../NOTICE.md).

| Method | Content case | Metric | Result |
| --- | --- | --- | --- |
| mineru | ak3-abbreviations | cell accuracy | 100.00% |
| mineru | forge68-rotated-daily-report | value recall | 86.67% |
| mineru | ak3-daily-operations | cell accuracy | 0.00% |
| mineru-captured-response | forge68-rotated-daily-report | value recall | 96.67% |

**mineru, ak3-abbreviations.** MinerU HTML anchors keep "GOCAD" separate from "Geologic Object Computer Aided Drawing, geologic modeling software". The 50/50 grid has no wrong cell; after whitespace normalization it is identical to Docling standard and the other perfect ak3-abbreviations grids.

**mineru, forge68-rotated-daily-report.** The configured MinerU output retains the full "Rollins graded road to rig." activity and 52/60 gold values. It prints "Waiting on day lighth" instead of gold "Waiting on day ligth" and lacks "01-Mar-19"; the captured run has a different missing-value set.

**mineru-captured-response, forge68-rotated-daily-report.** The captured dependency configuration retains "01-Mar-19" and 58/60 form values. It also emits "Waiting on day lighth", but additionally drops "No Bit Information for this report."; neither error is repaired by a value-label graph.

**mineru, ak3-daily-operations.** The configured native output retains "Daily Drilling Report". Its single title table declares colspan="4471" and contains no "personnel at lodge and town on Akutan" activity; the selected grid scores 0/28.

**mineru, ak3-nonproductive-time.** The final activity retains the ending "Top of lap joint (TOL): 755' BGS.". The first header/activity band becomes one colspan=9 cell with "NPT RptFielRd:e Hpootrt SprinTgims e BayT Vimaelley"; two HTML tables remain and no continues_prev link is emitted.

**mineru, ak3-scanned-well-schematic.** MinerU keeps one Markdown image reference. The entire Markdown is "![](<image-data-omitted>)" with no "AK-3" title or "HRQ Rod" label text.
