# opendataloader-pdf

Pinned: `73073ddb617e31ad64f508f00bd5ec13e969472a` ([source](https://github.com/opendataloader-project/opendataloader-pdf.git)). Code licence: Apache-2.0, read from `third_party/opendataloader-pdf/LICENSE:1-25`. Weights: Local mode uses no inference weights; hybrid mode uses the same pinned Docling/EasyOCR stack recorded in the runtime evidence.

The hybrid server constructs an OCR-aware converter and exposes a local service. The studied source is newer than the installed package; runtime claims are restricted to the retained results. Evidence: `third_party/opendataloader-pdf/python/opendataloader-pdf/src/opendataloader_pdf/hybrid_server.py:1099-1165`.

[Captured scores, native anchors, output text and errors](../../results/tool-survey.json). [Pins and runtime inputs](../../configs/inputs.lock.json); [licences](../../NOTICE.md).

| Method | Content case | Metric | Result |
| --- | --- | --- | --- |
| opendataloader-pdf | ak3-abbreviations | cell accuracy | 100.00% |
| opendataloader-pdf | forge68-rotated-daily-report | value recall | 95.00% |
| opendataloader-pdf | ak3-daily-operations | cell accuracy | 14.29% |
| opendataloader-pdf-hybrid | ak3-abbreviations | cell accuracy | 40.00% |
| opendataloader-pdf-hybrid | forge68-rotated-daily-report | value recall | 95.00% |
| opendataloader-pdf-hybrid | ak3-daily-operations | cell accuracy | 35.71% |

**opendataloader-pdf, ak3-abbreviations.** The local parser assigns "VFJ" and "Valley Flush Joint casing connection" to separate final-region cells. Its 25-by-2 normalized grid is identical to the other perfect ak3-abbreviations grids; there are no cell mismatches in the 50-cell comparison.

**opendataloader-pdf-hybrid, ak3-abbreviations.** Hybrid mode preserves the row text containing "ADEC" and "Conservation". The first row splits into "ADEC Alaska Department of Environmental" / "Conservation", cutting the expansion at the wrong boundary; 20/50 cells match.

**opendataloader-pdf, forge68-rotated-daily-report.** Local OpenDataLoader preserves the source typo "Waiting on day ligth" and 57/60 value strings. Its content separates "0.000" from "acre-ft" and drops "No Rig Information for this report." and "No Weather Information for this report.".

**opendataloader-pdf-hybrid, forge68-rotated-daily-report.** Hybrid output retains "University of Utah" and the same 57/60 values as local mode; the missing-value sets are identical, not the complete outputs. It serializes "Cum. Water Hauled: acre-ft 0.000" and has neither of the gold "No Rig Information" / "No Weather Information" sentences.

**opendataloader-pdf, ak3-daily-operations.** Local mode keeps "Days On Location:" and 1 together in the report grid. The selected table is the entire 30-by-22 report: row 0 column 2 contains "Daily Drilling Report" while gold operations headers start with "From". Its 4/28 matches are empty cells.

**opendataloader-pdf-hybrid, ak3-daily-operations.** Hybrid mode returns an operations-sized five-row, seven-column candidate. It combines header cells as "From To" and "Elapsed End MD(ft)" and combines the first times as "0:00 8:00"; only 10/28 data cells and 3/7 headers match.

**opendataloader-pdf, ak3-nonproductive-time.** The local second fragment keeps "1955" and "WOO" in separate cells and "Report Total: 115.00". Its first header contains "NPT Rp" in column 1 and "tField:ReportHot SpringsTimeBayTimeValley" in column 3, mixing the report banner into the table.

**opendataloader-pdf-hybrid, ak3-nonproductive-time.** Hybrid recognizes both "Well Total:" and "115.00" after the activity fragments. It merges two distinct activities into cells beginning "WAIT WOE" and "2 13-Aug-16 5 16-Aug-16", so the original row boundaries are lost.

**opendataloader-pdf, ak3-scanned-well-schematic.** Local digital parsing extracts "Draft 10", "Aug 16" and "Page | 13". The well drawing remains two image references; the visible title "Planned Well Schematic" is absent from text.

**opendataloader-pdf-hybrid, ak3-scanned-well-schematic.** Hybrid OCR recovers "AK-3" and "7-1/2" hole to 220"". It misspells the title as "Planned Well Schemalic", reduces 10-3/4 to "10 % hole to 40'", and turns a feet mark after 220 into an inch mark.

**opendataloader-pdf-hybrid, ak3-scanned-permit-letter.** opendataloader-pdf-hybrid returns 342 words on ak3-scanned-permit-letter in 25.487 seconds; count is output volume, not accuracy. OpenDataLoader hybrid repeats the EasyOCR substitution "HZS detector" for the source gas detector "H2S". Hybrid joins the slash as a letter in "flowlinjection test" instead of "flow/injection test". The hybrid final paragraph renders the rule number "25.07106)(2)" and loses the source parenthesized b.

**opendataloader-pdf-hybrid, ak3-scanned-permit-letter: 342 words, 25.487 seconds.** OpenDataLoader hybrid repeats the EasyOCR substitution "HZS detector" for the source gas detector "H2S". Hybrid joins the slash as a letter in "flowlinjection test" instead of "flow/injection test". The hybrid final paragraph renders the rule number "25.07106)(2)" and loses the source parenthesized b.
