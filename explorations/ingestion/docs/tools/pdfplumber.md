# pdfplumber

Pinned: `4c64b92d5caccd71c645e98e0fabb0c4dba7ff45` ([source](https://github.com/jsvine/pdfplumber.git)). Code licence: MIT, read from `third_party/pdfplumber/LICENSE.txt:1-21`. Weights: Not used; no weight rights inferred from the code licence.

[Captured scores, native anchors, output text and errors](../../results/tool-survey.json). [Pins and runtime inputs](../../configs/inputs.lock.json); [licences](../../NOTICE.md).

| Method | Content case | Metric | Result |
| --- | --- | --- | --- |
| pdfplumber | ak3-abbreviations | cell accuracy | 100.00% |
| pdfplumber | ak3-daily-operations | cell accuracy | 14.29% |

**pdfplumber, ak3-abbreviations.** pdfplumber keeps the long "TOTCO" expansion intact across its source line break. No ak3-abbreviations cell differs after whitespace normalization (50/50); this normalized grid is identical to the other perfect ak3-abbreviations outputs.

**pdfplumber, ak3-daily-operations.** The source grid contains the activity "personnel at lodge and town on Akutan" without OCR. The retained candidate is a 32-by-26 page grid, whose second row is "Report No: 1 Report For 12-Aug-16"; matching it unchanged to the five-row operations gold gives 4/28 empty-cell matches.

**pdfplumber, ak3-nonproductive-time.** The second source grid keeps "1955" and "WOO" in adjacent separate cells. The grids have ten columns, including an empty column after report number; page-one text also corrupts overlapping labels as "Criteria: Well IWDe =ll AIDK:-A3K-3".
