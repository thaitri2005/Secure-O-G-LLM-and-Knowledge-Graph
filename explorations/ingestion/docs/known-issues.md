# Known issues and limits

The repository corpus converter has asymmetric cold/cache returns: the cache path validates JSON while the fresh path returns the live Docling object. Docling-core validation clamps provenance boxes, affecting region bounds and running-line filtering. The local prototype normalizes both paths; repository source remains unchanged. [Diagnosis and new regression result](../results/cache-normalization.json); `src/graph_builder/corpus/process.py:86-108`, pinned by [the input lock](../configs/inputs.lock.json).

Rotated activity grids remain difficult. On 68-32 p30, upright conversion increases nonempty cells from 84 to 140 but lowers unique-word recall from 84.23% to 80.50%; the required two-metric guard rejects it. P31 improves from 90 to 161 cells and 77.58% to 82.42% recall, so it is accepted. P32 also fails recall improvement. These choices leave incompatible table shapes across pp30–32. [Attempt evidence](../results/rotation-review.json). A better-looking grid is not sufficient evidence of word preservation.

The header-only continuation case is informed by reviewed held-out errors. Its success on the coordinates table is descriptive. The activity table includes a final event split across pages, which the prototype does not deduplicate by annotation-driven repair. Continuation precision outside annotated positives remains unknown until the additional predicted joins are labeled. [Joins, headers and wrong cells](../results/evaluation.json).

The RIMBase label template is evaluated on a small, single-annotator English sample. Generic colon extraction is deliberately unverified and can attach a real value to the wrong label. Bounding-box presence is reported separately from semantic correctness or overlap with reviewed boxes. Literal source-absent flags can be printed ellipses stored as separate PDF objects; the [semantic review](../results/form-pairing/semantic-review.json) records these cases. [Pair-level results](../results/evaluation.json).

OCRmyPDF improves the English scanned-page route, but does not guarantee identifier, punctuation, handwriting or layout fidelity. Quote normalization is reported alongside raw scores, so matching apostrophes cannot hide the raw discrepancy. Scanned-form reading order is conventional; its CER/WER are diagnostic. There is no Vietnamese scanned-page validation, no independent annotator and no broad document-domain benchmark. [OCR errors](../results/evaluation.json), [scan output examples](../results/tool-survey.json).

The frozen annotation manifests and review sheets retain historical metadata and original relative links. They are preserved byte for byte under the annotation-content constraint. The [relocation map](../results/annotation-relocation.json) verifies preservation; [annotation conventions](../annotations/README.md) explain path resolution. Their trace-scan exceptions are listed explicitly in [the final checks](../results/checks.json). New code, documentation and results use descriptive names.

The implementation is an exploration wrapper around a specific repository revision. It has no VLM second-opinion workflow, no retrieval evaluation and no production deployment or service isolation claim. Licence evidence is source-specific; code rights do not establish rights to all associated models or training datasets. [NOTICE](../NOTICE.md).
Most extracted forms are generic. In the AK-3 corpus, 81 of 312 form records use the RIMBase template and 231 come from generic colon labels; in the report corpus the split is 29 and 126. Generic records are marked `verified: false` and their pairs are not evaluated. Consumers should treat them as unverified hints. [Corpus counts](../results/pipeline-checks.json).

## Next steps

These items are known and not yet done, in order of priority:

1. **Hand over K1.** The verified bundles are generated locally under the ignored `runs/` folder and are not committed. A small committed sample (for example the AK-3 report and one daily-report appendix) would let the next stage use K1 without rebuilding the environment.
2. **Disable generic forms by default.** Only template-matched forms are evaluated; the generic records above add unverified pairs to K1.
3. **Scanned-page text order.** Text-mode conversion of the OCRmyPDF output raises prose CER from 5.7% to 17.7% on the permit letter. A diagnostic points mainly to column reading order and typographic-quote conversion; critical tokens are unchanged after quote normalization.
4. **Rotated continued tables.** The 68-32 activity table needs a better acceptance rule for upright retries; any rule should be checked on all rotation attempts in [rotation-review.json](../results/rotation-review.json).
5. **Code tidy-up.** Split `cli.py` into a per-document pipeline module and a command-line module, and apply consistent formatting. Code changes alter the pipeline identity, so the corpora must be re-run and re-verified afterwards.
6. **Move into the repository pipeline.** Port the prototype into `graph_builder.corpus`, including the cold/cache fix above.
