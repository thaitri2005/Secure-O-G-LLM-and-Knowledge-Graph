# Track A validation on drilling reports

24 November 2026

## Scope and scoring

The frozen dataset contains **24 source documents and 86 pages**, including **36 pages processed by OCR**. The 15 operational reports consist of 14 Volve drilling reports and one Utah FORGE completion report. The other inputs comprise eight synthetic drilling and completion reports, five of which are scanned, and one published raster chart. Source publication locations and content hashes are recorded in the manifest. The scanned reports have paired published text references. The raster chart has phrase probes. [Source manifest](../../configs/benchmarks/track_a_validation_sources.json)

Scoring covers **1,052 table cells**, **234 label–value pairs** and **38 phrases**. Table matching requires the expected page, physical region, row key and column. A missing table or row contributes missing cells. Units are scored separately in the selected headers. The reference was prepared from source text and page geometry, with visual transcription for the FORGE tables and chart. Four objective-sentence probes were corrected against their individual source pages during review. The table-cell reference was fixed before inspection of the K1 output. [Frozen reference](../../configs/benchmarks/track_a_validation_reference.json)

## Results

| Group | Correct table cells | Complete sampled rows | Correct label–value pairs |
| --- | ---: | ---: | ---: |
| Volve operational reports | 456/474 (96.2%) | 148/158 | 103/103 |
| Utah FORGE completion report | 46/46 | 10/10 | 3/7 |
| Synthetic reports with searchable text | 186/186 | 35/35 | 51/51 |
| Synthetic scanned reports | 323/346 (93.4%) | 55/62 | 58/73 |
| **Total** | **1,011/1,052 (96.1%)** | **248/265** | **215/234** |

The raster chart yielded seven of eight phrase probes. The benchmark detected incorrect OCR values and column assignments on scanned reports, including an RPM value read as `06` instead of the printed `90`. Correctness varies by report family. The scan cohort consists of simulated scans from one report family. Quarter-turn tables and rows split across pages are outside this scoring sample.

The initial FORGE export recovered **0/46** scored cells. Its PDF contains searchable text and dotted rules painted as image patterns. The existing vector grid detector lost the column boundaries. The rendered ruling fallback recovers the Time Log and Casing tables using the visible rulings and agreement between two PDF text readers. Time Log scores **18/18** and Casing scores **28/28** on the fixed reference. This report was used to diagnose the defect, so the gain is measured on the development example. The other 23 documents reproduced their original K1 and QA records. A separate regression over 79 PDFs and 229 pages reproduced 947 tables and the QA records. [Rendered ruling reader](../../src/graph_builder/corpus/rendered_grids.py)

The K1 validator rebuilt all 86 page records. Cell QA reported `unavailable` for 933 native scanned cells in the synthetic cohort. Those status counts describe available QA evidence. The table-cell scores above come from the frozen reference.

## Performance

| Stage | Time |
| --- | ---: |
| Cold conversion, two workers | 278.3 s |
| K1 export after the FORGE correction | 78.7 s |
| Source QA and retrieval publication | 5.5 s |
| **Combined stage time** | **362.5 s** |

The combined time uses the measured cold conversion and the replay of export and QA from the same conversion cache. Conversion P50 was **11.6 s/file** and P95 was **72.2 s/file**. Worker time divided by processed page count was **5.0 s/page** for Volve, **3.1 s/page** for searchable synthetic reports, and **9.0 s/page** for synthetic scans. These timings describe one local run with a four-CPU quota and locally available processing assets. They exclude source and asset downloads.

On the initial profile comparison, enabling both optional scan fallbacks produced identical cells and retrieval records. K1 export increased from **77.3 s** to **240.9 s** on this dataset. The standard profile uses these fallbacks only when enabled explicitly.

## Reproduction

Use the benchmark command in the operating guide. The final release is expected to score 46/46 cells for `forge-003` and 1,011/1,052 cells for the full reference with the recorded dependencies. Commit `226cd2a` provides the earlier export for a paired calculation. Run the same command from that revision with a separate output directory and the same source cache. [Operating guide](../components/track-a-operation.md)
