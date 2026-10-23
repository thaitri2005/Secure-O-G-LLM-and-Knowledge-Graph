# Ingestion annotations

Reference annotations for evaluating PDF ingestion. All entries have `status: corrected`.

## Provenance

The annotations were transcribed from the rendered source pages, not copied from parser output, and cross-checked against the PDF text layer where the rendering was clipped or ambiguous. Each record lists its `annotator` and `reviewed` date, and `notes` explain non-obvious decisions. They were produced with AI assistance by a single annotator, so no inter-annotator agreement is available; treat the scores as indicative and report this limitation with any results.

Corrected annotations are frozen. Scoring must never rewrite them, and they must not be edited to change a score.

## Tables

`tables.json` maps each table to its source document, physical page, bounding box and CSV. Ten tables: four from the main reports, six from the AK-3 appendices.

Two formats are used:

- `grid`: the CSV reproduces the printed table cell by cell. The leading `header_rows` rows are headers. Merged cells hold their text in the top-left cell and leave covered cells empty. Empty source cells stay empty. Text is kept exactly as printed, including dash characters and labels clipped in the source.
- `form_fields`: for full-page forms that are not a single grid. The CSV has the columns `block,field,value` (one header row) and lists only the non-empty printed values. Score these by value recall on the page, not by cell position.

## Reading order and sections

The five files under `pages/` list the parser items found on a page (`items`) and the reference order of their IDs (`reading_order`).

- Excluded running metadata (page headers, footers, page numbers) is not listed.
- Each item's `section` is the nearest preceding printed section heading, or `null` if there is none.
- Items with several boxes appear once, at their first position.
- Source text the parser missed is recorded in `notes`.
