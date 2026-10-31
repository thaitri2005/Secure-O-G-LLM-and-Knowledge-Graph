# paddleocr

Pinned: `dab3fe35379033fdcb2d0e9572fac0b36c9a9ebf` ([source](https://github.com/PaddlePaddle/PaddleOCR.git)). Code licence: Apache-2.0, read from `third_party/paddleocr/LICENSE:1-25`. Weights: PaddleOCR-VL-1.6 and PP-DocLayoutV3 cards record Apache-2.0. Original LayoutXLM card records CC-BY-NC-SA-4.0; see NOTICE.

The installed document-parser extra delegates to PaddleX OCR and generative-client packages, so the repository alone is not the whole runtime. Evidence: `third_party/paddleocr/pyproject.toml:54-80`.

The legacy KIE guide separates semantic entity recognition from relation extraction, including custom training. Those are distinct from generic page OCR. Evidence: `third_party/paddleocr/docs/version2.x/ppstructure/model_train/train_kie.md:12-32`.

[Captured scores, native anchors, output text and errors](../../results/tool-survey.json). [Pins and runtime inputs](../../configs/inputs.lock.json); [licences](../../NOTICE.md).

| Method | Content case | Metric | Result |
| --- | --- | --- | --- |
| paddleocr | ak3-abbreviations | cell accuracy | 100.00% |
| paddleocr | forge68-rotated-daily-report | value recall | 98.33% |
| paddleocr-vlm | ak3-abbreviations | cell accuracy | 100.00% |
| paddleocr-vlm | forge68-rotated-daily-report | value recall | 90.00% |
| paddleocr-vlm | ak3-daily-operations | cell accuracy | 0.00% |

**paddleocr, ak3-abbreviations.** PP-StructureV3 recognizes the lowercase key "gpm" with "gallons per minute" in its HTML table. All 25 abbreviation pairs match (50/50 cells); the normalized grid is identical to the other perfect ak3-abbreviations grids. This standard output has no exposed VLM end token.

**paddleocr-vlm, ak3-abbreviations.** Paddle VLM retains "WOC" / "Waiting on Cement" in the final HTML row. The grid is 50/50 and identical after whitespace normalization to the other perfect ak3-abbreviations grids, but the surrounding output exposes the token "</s>".

**paddleocr, forge68-rotated-daily-report.** The saved PP-StructureV3 page contains "0.000 acre-ft" and 59/60 gold values; status records completion in 450.088 seconds. The full gold activity beginning "Rollins graded road to rig." is absent, including the word "Rollins". The earlier watchdog note was stale, not proof that this saved page failed.

**paddleocr-vlm, forge68-rotated-daily-report.** Paddle VLM retains "Randy Baldwin" and the complete Rollins activity; 54/60 values match. Its text says "Waiting on day lighth" and omits the county "Beaver" and state "UT"; these differ from the standard pipeline missing activity.

**paddleocr-vlm, ak3-daily-operations.** Paddle VLM recognizes "Days On Location:" with 1 within the broad report table. The highest-IoU candidate is the whole 30-row, nine-column form, beginning "Report No: 1" rather than the operations header "From"; positional grid accuracy is 0/28, not a text-recall score.

**paddleocr-vlm, ak3-nonproductive-time.** Paddle VLM keeps the final second-page row "WOO" / "25" / "05-Sep-16" / "6:30" / "9:00" / "2.50" / "1955". The page-one and page-two HTML tables are separate files, with a new "NPT Code" header on each; "Well Total: 115.00" occurs only in the second fragment.

**paddleocr-vlm, ak3-scanned-well-schematic.** Paddle VLM detects a large image region with a 75% display width. Its only retained content is an img element with alt="Image"; "Planned Well Schematic" and all casing dimensions have no transcription.

**paddleocr-vlm, ak3-scanned-permit-letter.** paddleocr-vlm returns 345 words on ak3-scanned-permit-letter in 59.406 seconds; count is output volume, not accuracy. Paddle VLM omits the printed agency heading "Alaska Oil and Gas Conservation Commission" from its text blocks. The Paddle text has no state letterhead "THE STATE of ALASKA", although it transcribes "GOVERNOR BILL WALKER" below it. Paddle VLM appends the literal end token in "Main: 907.279.1433</s>"; the printed contact line has no such token.

**paddleocr-vlm, ak3-scanned-permit-letter: 345 words, 59.406 seconds.** Paddle VLM omits the printed agency heading "Alaska Oil and Gas Conservation Commission" from its text blocks. The Paddle text has no state letterhead "THE STATE of ALASKA", although it transcribes "GOVERNOR BILL WALKER" below it. Paddle VLM appends the literal end token in "Main: 907.279.1433</s>"; the printed contact line has no such token.
