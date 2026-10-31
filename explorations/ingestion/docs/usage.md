# Reproduction

Run these commands from the repository root in PowerShell. The existing Windows environments, local model cache and pinned Tesseract installation are reused. All generated documents, derivatives, caches and renders go under ignored exploration directories. Source hashes and model hashes are in [the input lock](../configs/inputs.lock.json); code and weight terms are in [NOTICE](../NOTICE.md).

```powershell
./explorations/ingestion/scripts/setup.ps1
./explorations/ingestion/scripts/run.ps1 -Corpus ak3
./explorations/ingestion/scripts/run.ps1 -Corpus reports
./explorations/ingestion/scripts/evaluate.ps1
./explorations/ingestion/.venvs/docling/Scripts/python.exe -B -m unittest discover -s explorations/ingestion/tests -v
```

Setup verifies existing environments and assets without network access. `-Install` creates missing selected tool environments from pinned requirements and constraints; `-FetchSources` fetches pinned source checkouts. Model inference never downloads weights. On another machine, acquire the exact locked model/native assets into the indicated relative paths before verification; the lock records their retrieval URLs and hashes. The already installed Docling environment includes the repository OCR dependencies. A newly created environment also needs the local corpus OCR dependencies documented in the repository component guide.

`run.ps1 -RunName another-name` creates an independent run with no shared converted caches. Corpus definitions are [listed explicitly](../configs/corpora.json): AK-3 has 45 documents and 492 pages; the report set has five documents and 325 pages, including the AK-3 main report shared with the first corpus. Completed output files are hash-checked before reuse. An interrupted incomplete segment is recomputed, while completed segments are reused. Change configuration only with an empty run directory; `-Refresh` remaps retained native caches with the current prototype and is not an independent conversion.

Each run contains `work/<doc_id>/`, per-segment native caches, OCR derivatives, upright attempts, measurements and a validated `bundle/`. `bundle/SHA256SUMS` covers canonical records and text; elapsed times are external. The [verification results](../results/pipeline-checks.json) distinguish independent fresh conversions, cache remapping and actual process interruption.

Evaluation reads completed corpora only. It scores repository annotations plus both exploration annotation sets and rewrites [evaluation.json](../results/evaluation.json) and [the generated table](../results/evaluation.md). It performs no conversion or inference. Use `evaluate.ps1 -Runs <first-run>,<report-run>` to select other completed bundles. For the retained default runs, the command must reproduce JSON bytes exactly. [Annotation path resolution](../configs/annotation-paths.json) lets frozen manifests retain their original values after relocation.

The [parser comparison replay](../experiments/parser_comparison.py), [hard-page selection replay](../experiments/hard_page_selection.py) and [text-support replay](../experiments/text_support.py) consume retained native snapshots or measurements. They reproduce decision calculations without starting a model. The source tool harness remains under [scripts/tools](../scripts/tools/run_tool.py); prepare its content-named slices with `scripts/tools/prepare_pages.py`. Run each tool with its own environment. Optional model and hybrid servers bind `127.0.0.1`; no remote model endpoint is supported.

Results exclude PDFs, weights, native converter dumps and process logs. Those stay in ignored local directories or the permitted local report/archive directories. The exploration does not modify or publish a production corpus, index, graph or vector database.
