# camelot

Pinned: `92777b852e00933a5c4b9ba642601784604356cd` ([source](https://github.com/camelot-dev/camelot.git)). Code licence: MIT, read from `third_party/camelot/LICENSE:1-22`. Weights: Not used; no weight rights inferred from the code licence.

[Captured scores, native anchors, output text and errors](../../results/tool-survey.json). [Pins and runtime inputs](../../configs/inputs.lock.json); [licences](../../NOTICE.md).

| Method | Content case | Metric | Result |
| --- | --- | --- | --- |
| camelot | ak3-abbreviations | cell accuracy | 96.00% |
| camelot | ak3-daily-operations | cell accuracy | 14.29% |

**camelot, ak3-abbreviations.** Camelot keeps "WOC" / "Waiting on Cement" at the bottom of its 25-row table. The GOCAD row instead puts "GOCAD  Geologic Object Computer Aided Drawing, geologic modeling software" in the key cell and leaves the value empty; 48/50 cells match.

**camelot, ak3-daily-operations.** Camelot extracts digital text including "Crews down for evening". Its selected grid is 32-by-24, and the report-number cell orders text as "Report No: Report For 12-Aug-16 1"; no operations header aligns and only four empty data cells match.

**camelot, ak3-nonproductive-time.** Camelot retains two fragments with 28 and 12 rows. The final row fuses "1955 WOO" in the operations-code cell and orders the total as "115.00 Well Total:"; it does not yield the source nine-column structure.
