# E25: Table mappings on an unseen end-of-well report

| | |
|---|---|
| **Date** | 4 November 2026 |
| **Question** | Do K2's table mappings, written while looking at AK-3, work on an end-of-well report they were not written from? |
| **Requirement** | B-D20, next-runs E25 |
| **Input** | Utah FORGE monitoring well 78-32 end-of-well report: 96 pages, 294 chunks, 72 tables. Chosen because it is a real end-of-well report, pinned in the source registry, and never used to write the mappings. Registry: `configs/sources/gdr_e25_78-32.json`. Named run `e25_78-32` (ignored by git); `data/processed/` is unchanged |
| **Code** | `graphrag/tables.py --run e25_78-32` |
| **Gold data** | Hand-check against the rendered PDF pages 6 and 65, not against parsed text |
| **Models** | None for table facts |
| **Outputs** | `graphrag/results/E25_tables_78-32.json` (mappings as they were), `E25_tables_78-32_fixed.json`, `E25_tables_three_fixed.json` |
| **Status** | Done |

## Results

| | Mappings as written | After the two fixes |
|---|---:|---:|
| Facts found | 3 | 23 |
| Casing strings with the right depth | 3 of 3 | 3 of 3 |
| Casing strings with the right size as well | **1 of 3** | 3 of 3 |
| Survey rows found, of the 20 on page 65 | **0** | 20, all matching the page |
| LLM calls | 0 | 0 |
| Facts changed on the original three reports | n/a | **0 of 130** |

**Cost per page:** no LLM calls for table facts. Parsing took 124.5 seconds for 96 pages, about 1.3 seconds per page.

## What went wrong as written

1. **Decimal casing sizes were cut off.** 78-32 writes `9.625` and `5.5`; the mapping's size pattern read them as `9` and `5`. The depths were right, but the facts were attached to the wrong sizes.
2. **The survey table was missed.** A section row, `Wellbore: Original Wellbore`, directly under the two header rows was counted as a third header. The joined header became longer than the 50-character limit, so the depth column was not recognized.

Both fixes are general and were recorded as a separate run, as the runbook asks: sizes accept decimals, and a row starting with a `label:` after the first header row is not a header.

## Still missed after the fixes

- **Casing forms:** tables t071 and t073 hold `Casing Shoe MD (ft): 704.47` and more, as key-value rows, and the mappings do not read them. The result is not wrong: Table 1 gives 704 for the same string.
- **Daily-report forms inside the report** (for example t041, t050) come out as mixed grids, the same parsing problem as [E24](E24-ak3-daily-reports.md).
- **Well-level values in a key-value table:** page 5 has `Total Depth (ft): 3,280 ft.` and `Rotary Table Height (ft): 5.70 ft above GL`, which these mappings did not read. The prose also states the 3,280 ft.

Only 1 of the 72 tables gave facts as written, and 2 after the fixes. Most of the others are forms, logs or lists that these mappings do not target; we did not review all 72 by hand, so this is not a recall figure.

## What was learned

1. **The caveat in E22 was real.** Written from AK-3, the mappings had the right values but got most keys wrong or missed the table on an unseen report. Generic header rules are not enough until tried on several layouts.
2. **The fixes were cheap and safe:** two small rules, 20 more correct facts, and no change on the three existing reports.
3. **One unseen report is one sample.** 78-32 comes from the same project and contractor as 68-32, so it says little about reports from other operators.
