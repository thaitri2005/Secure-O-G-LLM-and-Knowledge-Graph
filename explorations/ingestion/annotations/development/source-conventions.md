# Source annotations for X4–X6

All records have **status: corrected**. Each record lists its `annotator` and `reviewed` date. The annotations were drafted from source PDF renders and direct PDFium text/character layers, then checked a second time against the renders; scope decisions were approved by the repository owner. They were produced with AI assistance by a single annotator, so no inter-annotator agreement is available; report this limitation with any results. The frozen annotations under `data/gold/` are unchanged.

Corrected annotations are frozen. Scoring must never rewrite them, and they must not be edited to change a score.

The only annotation inputs are source PDF renders and direct PDFium text/character layers captured by [gold_sources.py](../spikes/gold_sources.py). [draft_gold.py](../spikes/draft_gold.py) assembles the reviewed source regions; it does not read conversion outputs. Scanned-page text was entered manually from the render. Source hashes and render paths are recorded in each JSON manifest.

All page numbers are one-based physical PDF pages. Rectangles are `[left, top, right, bottom]` in PDF points on the rendered physical page, with top-left origin. The rotated FORGE form also has an upright review image; its stored boxes still refer to the original physical orientation. Table boxes are manually measured enclosing regions. Form boxes use direct source glyph unions inside manually selected regions; blank values have a null value box. A shared printed cost-column heading may label several values. The manifests distinguish the key and value boxes.

## Continued tables

`continued_tables/` contains one rectangular UTF-8 CSV per logical table: the AK-3 non-productive-time report (pp1–2, header repeated on p2) and the AK-3 liner component details (pp1–2, no repeated header). As in the frozen grid conventions, merged cells occupy their top-left anchor and covered cells are empty; wrapped source lines within a cell become spaces. No extra CSV schema header is inserted. `header_rows` counts printed column-heading rows. Repeated continuation headings occur once in the logical CSV. `first_row` and `last_row` are zero-based, inclusive CSV row indices for the data in that part; the initial printed header precedes the first data row. Page headers, total bands and watermarks are excluded as specified in each record.

`excluded/` keeps the AK-3 account-code list (drilling plan pp34–35). It is an unruled code-and-description list under a heading, with no cells or column headings, so it is text rather than a table. It is not part of the continued-table set or X4 recall.

## Forms

`forms/` contains CSV columns `block,key,value`, with one printed pair per row, including empty values. The scope is each daily-report header down to the block before Operations Summary; safety, weather and environment blocks lower on the page are out of scope. Repeated AFE column headings are paired with each cost-row entry and totals; they are disambiguated by `block`. Titles and logos are not field pairs. S3 has no visible Job ID; a hidden text-layer label is excluded. Source clipping wins over the hidden full text for the Field value. `Town: 112W` and `Rng: S005` are printed in that order on the AK-3 forms and are kept as printed. The CSVs contain 48, 48 and 45 pairs respectively.

## Transcriptions

`transcriptions/` contains printed/typed text, line by line in reading order. Side-by-side fields are linearized left to right within their form bands; table rows are linearized across columns. Blank form entries contribute their printed labels only. Handwritten marks, signatures, checkbox states, received stamps and seal lettering are excluded; typed text crossed out by hand is retained. The two crossed-out typed coordinates on p25 are not critical tokens. `[?]` marks uncertain characters.

Reading order across the cells of the p25 form is a convention. Rank engines on that page by critical-token accuracy and order-independent word recall; report CER there but do not use it for ranking. CER is used for p23 and p24.
