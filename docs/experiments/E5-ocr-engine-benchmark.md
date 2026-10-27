# E5: OCR engine benchmark for Vietnamese and English scans

| | |
|---|---|
| **Date** | 27 October 2026 |
| **Question** | Which local OCR engine should the document pipeline use for scanned Vietnamese and English pages on a small CPU-only machine? |
| **Requirement** | SR-12 (Vietnamese material), SR-13 (scanned documents), FR-13, FR-14 |
| **Input** | 11 born-digital pages rendered as scans: 8 from the Petroleum Law 12/2022/QH15 (Official Gazette copies from [chinhphu.vn](https://chinhphu.vn/?pageid=27160&docid=207713&classid=1&typegroupid=3)) and 3 from the AK-3 report; each page under three conditions, 33 cases |
| **Reference** | Each page's own embedded text layer, which is exact for born-digital PDFs |
| **Code** | [`scripts/ocr_benchmark.py`](../../scripts/ocr_benchmark.py); engines in [`graph_builder.corpus.ocr_engines`](../../src/graph_builder/corpus/ocr_engines.py) and [`vietocr_engine`](../../src/graph_builder/corpus/vietocr_engine.py) |
| **Outputs** | Ignored, local: `data/interim/ocr_benchmark/` (cases, image-only PDFs, `results.jsonl`, `summary.json`) |
| **Status** | Concluded: VietOCR recognition with PP-OCRv6 detection is the default engine |

## Method

`prepare` renders each page with pdfium and saves it as an image-only PDF under three conditions:

| Condition | Rendering |
|---|---|
| `clean300` | 300 dpi, grey |
| `scan200` | 200 dpi, rotated 0.6°, Gaussian blur 0.6, noise σ 10, JPEG quality 45 |
| `poor150` | 150 dpi, rotated −1.2°, blur 0.9, noise σ 18, JPEG quality 30 |

`run` converts every case through the same Docling path the corpus pipeline uses (full-page OCR, fast table structure, CPU) and compares the extracted text with the page's text layer. Metrics, from [`text_metrics.py`](../../src/graph_builder/corpus/text_metrics.py), all use NFC, unified quotes and collapsed whitespace:

- CER and WER (order-sensitive);
- word recall and precision as multisets (order-insensitive);
- recall of words that carry Vietnamese marks.

"Invalid Vietnamese" is the share of Vietnamese-marked output words that are not well-formed syllables ([`vietnamese.py`](../../src/graph_builder/corpus/vietnamese.py)). That measure needs no reference text.

Engines:

| Engine | Detection | Recognition | Size |
|---|---|---|---|
| `easyocr` (previous default) | CRAFT | EasyOCR Latin `vi`+`en` | 98 MB |
| `rapidocr-small` | PP-OCRv6 small | PP-OCRv6 small (multilingual) | 31 MB |
| `vietocr` | PP-OCRv6 small | [VietOCR](https://github.com/pbcquoc/vietocr) `vgg_transformer` (Apache-2.0) | 183 MB |

## Results

Means per page. VietOCR was run on the `scan200` set and on one clean page, to keep the run short on the laptop. Its first two cases used render scale 3.0 and the rest 2.5. Times come from a shared i5-1340P laptop with other jobs running, so they are indicative only.

| Engine | Lang | Condition | Pages | CER | WER | Word recall | Vietnamese word recall | Invalid Vietnamese | s/page |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| easyocr | vi | scan200 | 8 | 0.240 | 0.294 | 0.859 | 0.870 | 0.010 | 41 |
| easyocr | vi | all | 24 | 0.473 | 0.558 | 0.526 | 0.512 | 0.044 | 46 |
| easyocr | en | all | 9 | 0.507 | 0.564 | 0.477 | – | – | 46 |
| rapidocr-small | vi | scan200 | 8 | 0.141 | 0.562 | 0.440 | 0.374 | 0.098 | 28 |
| rapidocr-small | vi | all | 24 | 0.179 | 0.610 | 0.411 | 0.338 | 0.104 | 21 |
| rapidocr-small | en | scan200 | 3 | **0.021** | 0.044 | **0.998** | – | – | **13** |
| rapidocr-small | en | all | 9 | 0.032 | 0.061 | 0.989 | – | – | 13 |
| **vietocr** | vi | scan200 | 8 | **0.052** | **0.082** | **0.945** | **0.962** | **0.000** | 48 |
| **vietocr** | vi | clean300 | 1 | 0.012 | 0.026 | 0.974 | 0.981 | 0.000 | 73 |
| **vietocr** | en | scan200 | 3 | 0.028 | 0.059 | 0.985 | – | – | 26 |

## Interpretation

- **The PP-OCR recognizers cannot read Vietnamese.** They drop most precomposed letters with tone marks, so "Luật" becomes "Lut" and "Số" becomes "S". Character error looks moderate (14%) only because the base letters survive; word recall is 41–44%. The PP-OCRv5 Latin recognizer behaved the same in a spot check.
- **EasyOCR skips whole lines.** Its errors vary widely between conditions: clean pages scored worse than the moderate scans.
- **VietOCR reads Vietnamese with all its marks.** It cuts the character error rate on moderate scans by about 4.6× against EasyOCR and 2.7× against RapidOCR, and produced no malformed syllables. On English it is close to RapidOCR.
- **RapidOCR stays the faster choice for English-only corpora.** Select it with `"ocr": {"engine": "rapidocr"}` in the corpus configuration.
- **The syllable checker separates the engines without reference text.** 0% invalid Vietnamese for VietOCR against 10% for RapidOCR. This is the basis of the pipeline's page-level `review` flag.

## Limits

- One document type (legal text in the Official Gazette layout) and synthetic degradation. Real scans add skew, stamps, handwriting and bleed-through, which this set lacks.
- Small sample: 11 pages, and only the `scan200` condition for VietOCR. The `poor150` condition was not run for VietOCR.
- VietOCR's vocabulary lacks some symbols, such as "°", which it reads as another character. Numbers with units should be checked in review.
- Speed: about 25–50 s per scanned page on this laptop's CPU. Pages with a good text layer skip OCR entirely; see [E7](E7-corpus-pipeline-smoke.md) for the pipeline run.
