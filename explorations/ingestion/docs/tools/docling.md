# docling

Pinned: `4f00195b8dadbc1a67f4cefae6b619c47e4e515f` ([source](https://github.com/docling-project/docling.git)). Code licence: MIT, read from `third_party/docling/LICENSE:1-21`. Weights: See NOTICE model table: code MIT, TableFormerV2 preview weights Apache-2.0, and individually pinned model cards.

Standard parsing and the alternate table structure table option are separate experiments; their outputs differ on ak3-abbreviations. The MinerU preset explicitly selects a two-stage layout/recognition format. Evidence: `third_party/docling/docling/datamodel/pipeline_options.py:178-201`; `third_party/docling/docling/datamodel/stage_model_specs.py:1438-1465`.

DocumentExtractor produces per-page extracted JSON and raw text. It does not itself populate a grounded KeyValueItem graph. Evidence: `third_party/docling/docling/pipeline/extraction_vlm_pipeline.py:44-112`.

MinerU layout decoding requires box/ref special tokens. Responses stripped of these tokens cannot be parsed into regions. Evidence: `third_party/docling/docling/utils/mineru_utils.py:50-57`; `third_party/docling/docling/utils/mineru_utils.py:197-230`.

[Captured scores, native anchors, output text and errors](../../results/tool-survey.json). [Pins and runtime inputs](../../configs/inputs.lock.json); [licences](../../NOTICE.md).

| Method | Content case | Metric | Result |
| --- | --- | --- | --- |
| docling | ak3-abbreviations | cell accuracy | 100.00% |
| docling | forge68-rotated-daily-report | value recall | 98.33% |
| docling | ak3-daily-operations | cell accuracy | 100.00% |
| docling-extractor | ak3-daily-operations | cell accuracy | 0.00% |
| docling-alternate-tables | ak3-abbreviations | cell accuracy | 24.00% |
| docling-alternate-tables | forge68-rotated-daily-report | value recall | 65.00% |
| docling-alternate-tables | ak3-daily-operations | cell accuracy | 35.71% |
| docling-vlm | ak3-abbreviations | cell accuracy | 100.00% |
| docling-vlm | forge68-rotated-daily-report | value recall | 100.00% |
| docling-vlm | ak3-daily-operations | cell accuracy | 96.43% |
| docling-vlm-empty-response | ak3-abbreviations | cell accuracy | 0.00% |
| docling-vlm-empty-response | forge68-rotated-daily-report | value recall | 0.00% |
| docling-vlm-empty-response | ak3-daily-operations | cell accuracy | 0.00% |

**docling, ak3-abbreviations.** The 25-by-2 grid retains "ADEC" / "Alaska Department of Environmental Conservation" and all 50 gold cells. No grid mismatch on ak3-abbreviations; this whitespace-normalized grid is identical to Docling VLM, MinerU, Paddle standard/VLM, OpenDataLoader local and pdfplumber.

**docling-alternate-tables, ak3-abbreviations.** The alternate table structure grid still has 25 rows and two columns. Its first key cell is empty; the adjacent cell is "ADEC Alaska Department of Environmental Conservation" instead of only the expansion. Only 12/50 cells match.

**docling-vlm, ak3-abbreviations.** The VLM separates "TOTCO" from "Common trade name in use for single-shot inclination-only survey tool, mechanical inclination indicator". All 50 ak3-abbreviations cells match; its normalized grid is identical to the standard grid, despite a separate image/layout inference path.

**docling, forge68-rotated-daily-report.** Standard Docling contains 59 of the 60 nonempty gold values, including "University of Utah". The water value is reordered as "acre-ft 0.000", so gold "0.000 acre-ft" is absent as a contiguous substring; the broad merged table still recalls most values.

**docling-alternate-tables, forge68-rotated-daily-report.** The alternate table structure output contains "Original Wellbore" and 39/60 gold value strings. It truncates the operations text to "Rollins graded road to rig. Spotted 2 each 500 bbl baker tanks. Unloaded 45 joints of" and omits "University of Utah" entirely.

**docling-vlm, forge68-rotated-daily-report.** The five VLM tables contain all 60 gold value strings, including "Waiting on day ligth" with the source spelling. The extra sentence "Theorem 1.2. The following are equivalent." is invented; 60/60 value recall does not penalize this hallucination.

**docling, ak3-daily-operations.** The operations table matches all 28 data cells and seven header cells, including "0:00" / "8:00" / "8.00" / "0" / "WOD". Outside this operations score, the header still pairs "Days On Location:" with "1700" instead of 1; zero KeyValueItems are reported.

**docling-alternate-tables, ak3-daily-operations.** The alternate table structure grid keeps "0:00", "8:00" and "8.00" in its first activity row. It fuses depth and code into "0 WOD", leaving only six columns rather than seven; 10/28 data cells and 3/7 headers match.

**docling-vlm, ak3-daily-operations.** The VLM operations table retains seven columns and all seven headers; its separate header correctly says "Days On Location: 1". One exact-match cell differs: "Fly loads to site, begin construction of camp and drill pad." omits the gold space before the comma in "site ,"; data score 27/28.

**docling-extractor, ak3-daily-operations.** The requested JSON fields are "Report No": "1", "Report For": "12-Aug-16", "Days On Location": "1" and "Proposed TD (ft)": "1700". This field-only request produces no operations table: expected "From" and "personnel at lodge and town on Akutan" are missing, giving 0/28 for the requested grid target.

**docling-vlm-empty-response, ak3-abbreviations.** The captured ak3-abbreviations native document is retained with partial_success and zero tables. Its text and tables are empty, so expected "ADEC" is absent; this is scored as an empty produced document, not skipped.

**docling-vlm-empty-response, forge68-rotated-daily-report.** The captured forge68-rotated-daily-report native document is retained with partial_success and zero tables. Its text and tables are empty, so expected "Forge 68-32" is absent; this is scored as an empty produced document, not skipped.

**docling-vlm-empty-response, ak3-daily-operations.** The captured ak3-daily-operations native document is retained with partial_success and zero tables. Its text and tables are empty, so expected "From" is absent; this is scored as an empty produced document, not skipped.

**docling, ak3-nonproductive-time.** The second fragment retains "WOO", "25", "05-Sep-16" and "115.00". The first header is polluted with "Report Date Field: Hot" and "Activity Description 112W Rng: S005 County: Aleutians East State: AK"; the two fragments are not consolidated.

**docling-alternate-tables, ak3-nonproductive-time.** Both alternate table structure fragments retain the ending total "115.00". The last activity fuses "25 05-Sep-16 6:30 9:00" into one cell and "1955 WOO Waiting on well design" into another, losing the nine-column alignment.

**docling-vlm, ak3-nonproductive-time.** The VLM preserves the nine-column activity header on each page. The merged total "Well Total: 115.00" repeats in all nine Markdown columns, while "Field: Hot Springs Bay Va" truncates Valley; the output still has two tables.

**docling, ak3-scanned-well-schematic.** Standard parsing returns three image placeholders and zero HybridChunker chunks. Its empty text omits even "Planned Well Schematic" and the dimension "7-1/2" hole to 220'" visible in the source.

**docling-alternate-tables, ak3-scanned-well-schematic.** The alternate table structure Markdown is byte-identical to standard ak3-scanned-well-schematic: three "<!-- image -->" placeholders. No alternate table structure label text is recovered, including "Top of HRQ Liner @ 700'"; the identical Markdown does not imply identical internal image-region metadata.

**docling-vlm, ak3-scanned-well-schematic.** The VLM transcribes "AK-3" and "Planned Well Schematic" above the image. It adds "FG" as a logo transcription and omits the internal "PQ (4.834") hole to 800'" label.

**docling, ak3-scanned-permit-letter.** docling returns 342 words on ak3-scanned-permit-letter in 35.744 seconds; count is output volume, not accuracy. Docling standard replaces the digit in "H2S detector" with Z, producing "HZS detector". The standard surface-location text reads "T7OS, RlI2W" for the printed "T70S, R112W". Standard OCR corrupts the final statutory reference as "25.07106)(2)" rather than "25.071(b)(2)".

**docling-vlm, ak3-scanned-permit-letter.** docling-vlm returns 352 words on ak3-scanned-permit-letter in 480.489 seconds; count is output volume, not accuracy. Docling VLM substitutes "Sevenin" for "Seventh" in the street address. The VLM stores "1. Well operations shall be conducted in accordance with 20 AAC 25." with enumerated=false and an empty marker; Markdown adds a bullet as "- 1. Well operations" to the printed numbered list. The VLM detaches the bottomhole location ending "SM" into its own paragraph after "Sec. 5,"; the source wraps the same location field onto the next line.

**docling, ak3-scanned-permit-letter: 342 words, 35.744 seconds.** Docling standard replaces the digit in "H2S detector" with Z, producing "HZS detector". The standard surface-location text reads "T7OS, RlI2W" for the printed "T70S, R112W". Standard OCR corrupts the final statutory reference as "25.07106)(2)" rather than "25.071(b)(2)".

**docling-vlm, ak3-scanned-permit-letter: 352 words, 480.489 seconds.** Docling VLM substitutes "Sevenin" for "Seventh" in the street address. The VLM stores "1. Well operations shall be conducted in accordance with 20 AAC 25." with enumerated=false and an empty marker; Markdown adds a bullet as "- 1. Well operations" to the printed numbered list. The VLM detaches the bottomhole location ending "SM" into its own paragraph after "Sec. 5,"; the source wraps the same location field onto the next line.
