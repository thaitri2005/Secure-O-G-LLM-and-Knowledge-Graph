# llama.cpp

Pinned: `e0f142d5ddc1461ce721644d92af33db23545105` ([source](https://github.com/ggml-org/llama.cpp.git)). Code licence: MIT, read from `third_party/llama.cpp/LICENSE:1-21`. Weights: Not used; no weight rights inferred from the code licence.

[Captured scores, native anchors, output text and errors](../../results/tool-survey.json). [Pins and runtime inputs](../../configs/inputs.lock.json); [licences](../../NOTICE.md).

| Method | Content case | Metric | Result |
| --- | --- | --- | --- |
| docling-vlm | ak3-abbreviations | cell accuracy | 100.00% |
| docling-vlm | forge68-rotated-daily-report | value recall | 100.00% |
| docling-vlm | ak3-daily-operations | cell accuracy | 96.43% |
| docling-vlm-empty-response | ak3-abbreviations | cell accuracy | 0.00% |
| docling-vlm-empty-response | forge68-rotated-daily-report | value recall | 0.00% |
| docling-vlm-empty-response | ak3-daily-operations | cell accuracy | 0.00% |

**docling-vlm, ak3-abbreviations.** The VLM separates "TOTCO" from "Common trade name in use for single-shot inclination-only survey tool, mechanical inclination indicator". All 50 ak3-abbreviations cells match; its normalized grid is identical to the standard grid, despite a separate image/layout inference path.

**docling-vlm, forge68-rotated-daily-report.** The five VLM tables contain all 60 gold value strings, including "Waiting on day ligth" with the source spelling. The extra sentence "Theorem 1.2. The following are equivalent." is invented; 60/60 value recall does not penalize this hallucination.

**docling-vlm, ak3-daily-operations.** The VLM operations table retains seven columns and all seven headers; its separate header correctly says "Days On Location: 1". One exact-match cell differs: "Fly loads to site, begin construction of camp and drill pad." omits the gold space before the comma in "site ,"; data score 27/28.

**docling-vlm-empty-response, ak3-abbreviations.** The captured ak3-abbreviations native document is retained with partial_success and zero tables. Its text and tables are empty, so expected "ADEC" is absent; this is scored as an empty produced document, not skipped.

**docling-vlm-empty-response, forge68-rotated-daily-report.** The captured forge68-rotated-daily-report native document is retained with partial_success and zero tables. Its text and tables are empty, so expected "Forge 68-32" is absent; this is scored as an empty produced document, not skipped.

**docling-vlm-empty-response, ak3-daily-operations.** The captured ak3-daily-operations native document is retained with partial_success and zero tables. Its text and tables are empty, so expected "From" is absent; this is scored as an empty produced document, not skipped.

**docling-vlm, ak3-nonproductive-time.** The VLM preserves the nine-column activity header on each page. The merged total "Well Total: 115.00" repeats in all nine Markdown columns, while "Field: Hot Springs Bay Va" truncates Valley; the output still has two tables.

**docling-vlm, ak3-scanned-well-schematic.** The VLM transcribes "AK-3" and "Planned Well Schematic" above the image. It adds "FG" as a logo transcription and omits the internal "PQ (4.834") hole to 800'" label.

**docling-vlm, ak3-scanned-permit-letter.** docling-vlm returns 352 words on ak3-scanned-permit-letter in 480.489 seconds; count is output volume, not accuracy. Docling VLM substitutes "Sevenin" for "Seventh" in the street address. The VLM stores "1. Well operations shall be conducted in accordance with 20 AAC 25." with enumerated=false and an empty marker; Markdown adds a bullet as "- 1. Well operations" to the printed numbered list. The VLM detaches the bottomhole location ending "SM" into its own paragraph after "Sec. 5,"; the source wraps the same location field onto the next line.

**docling-vlm, ak3-scanned-permit-letter: 352 words, 480.489 seconds.** Docling VLM substitutes "Sevenin" for "Seventh" in the street address. The VLM stores "1. Well operations shall be conducted in accordance with 20 AAC 25." with enumerated=false and an empty marker; Markdown adds a bullet as "- 1. Well operations" to the printed numbered list. The VLM detaches the bottomhole location ending "SM" into its own paragraph after "Sec. 5,"; the source wraps the same location field onto the next line.
