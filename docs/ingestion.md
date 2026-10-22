# PDF ingestion

## Stages and configuration

`fetch` downloads source PDFs or verifies existing files against the registry's SHA256 and byte size. A mismatch fails the command. `convert` runs Docling locally and stores complete, unfiltered JSON and Markdown documents. `chunk` filters a copy of each cached document and writes the merged chunks in registry and reading order. `validate` checks those chunks against the original PDFs and cached documents. `run` performs all four stages and fails if validation fails.

[Pipeline options](../configs/ingestion/default.json) explicitly set a 1,500-character budget, CPU execution, OCR off, table structure on, accurate TableFormer, and cell matching on. Remote services and Hugging Face telemetry are disabled. Dependencies are Python 3.12.10, docling 2.141.0, docling-core 2.103.1, torch 2.14.1+cpu, and pypdf 6.1.1. The full Windows CPU dependency set is frozen in `requirements.lock.txt`.

## Filters

Page headers, page footers, pictures, document indexes and dotted-leader TOC entries are dropped. The explicit contents heading is dropped with its detected index. Captions and existing PDF text within figures are retained without OCR. Empty tables and items without provenance are skipped and counted.

Running-line frequency keys collapse whitespace, case-fold text, and replace each digit run with `#`. Frequencies count distinct pages, with a threshold of 50% of document pages. A line entirely within the top or bottom 8% of a page anchors a running metadata block. Bboxes are converted to top-left coordinates using the source page height. Adjacent repeated lines may join an anchored block if their left edges differ by at most half the smaller line height and their vertical gap is at most one line height. The band stays at 8%; an isolated repeated line outside it is retained.

Docling sometimes splits a line across table cells. Fragments with aligned vertical bounds and a horizontal gap of at most three line heights are considered together for frequency matching. All block and fragment thresholds are in the configuration. No document-specific string or page number is used by the filter. This removes version, page-number and issue-date metadata even when digits vary or table cells divide the line. Interior text is retained. The source JSON and Markdown cache remain complete.

| Dropped occurrences/items | AK-3 | 56-32 | 68-32 |
|---|---:|---:|---:|
| Document index | 1 | 5 | 0 |
| Explicit contents heading | 1 | 1 | 1 |
| Dotted-leader entries | 0 | 0 | 13 |
| Page header | 1 | 33 | 5 |
| Page footer | 28 | 86 | 12 |
| Picture | 46 | 226 | 54 |
| Empty table | 0 | 1 | 1 |
| Running-line occurrence | 28 | 342 | 0 |

Running-line counts include matches already labelled as page headers or footers; categories overlap. AK-3's 28 running-line matches are already excluded page footers, so its chunks are unchanged. The 68-32 chunks are also unchanged. The 56-32 version/date/reference metadata is absent from the output.

## Chunking and validation

Text is grouped by physical PDF page and nearest preceding section, then packed by sentence. Long sentences split at whitespace, or at the character budget when no whitespace exists. Headings end the current text buffer and set the section; they do not create standalone chunks. A text item spanning pages is divided using its provenance character spans. Existing text within figures remains available.

Tables become Markdown. Long tables split only at row boundaries and repeat their caption and header. Markdown separator padding is compacted. A single oversized row remains intact and produces a validation warning. A multi-page table uses its first provenance page and is counted; none occurred in these inputs. Identifiers use `{doc_id}#c{index:04d}` with continuous indexes from zero per document.

Validation checks the JSON array and fields, identifiers and continuity, registry order, physical page range, nonempty text, allowed types, section type, character limits and table-row exceptions. Configured content checks verify selected phrases and page/section provenance. A document without table chunks warns. Each PDF page with more than 200 pypdf characters must have a chunk unless it is a computed index-only page.

Exemptions come from every item in the complete Docling cache, including figure children and orphaned items. A page is exempt when all items are structural exclusions, or when a detected index page contains only those exclusions, filtered running metadata, and index headings. Index headings are explicit contents/figures/tables headings or headings matching labelled running-header text within the same normalized vertical region. Substantive paragraphs, captions, ordinary headings and empty tables prevent exemption. No page numbers are hard-coded and no TOC chunks are created. Current exempt pages: AK-3 `[3]`, 56-32 `[3, 4, 5, 7]`, 68-32 `[]`; missing substantive pages: none.

## Results

Approximate reference times: Windows laptop, CPU only, cached models.

| doc_id | Pages | Text chunks | Table chunks | Characters | CPU seconds |
|---|---:|---:|---:|---:|---:|
| gdr882_ak3_eowr | 29 | 57 | 6 | 43,064 | 30 |
| gdr1295_56-32_eowr | 86 | 132 | 69 | 66,825 | 125 |
| gdr1153_68-32_eowr | 40 | 60 | 36 | 77,669 | 200 |
| Total | 155 | 249 | 111 | 187,558 | 355 |

SHA256: `70a27d3a4109d00a2c46ba4bca7ee22315b6adb6a71b99b71396d23b19dfbe18`

The deliverable uses UTF-8, unescaped Unicode, two-space indentation, LF endings and a trailing newline. It contains no run timings or timestamps. Complete offline PDF conversions produce identical chunk bytes when dependencies, cached models, inputs and options are unchanged.

## Known limitations

- Rotated daily-report tables in 68-32 have collapsed cell structure; `gdr1153_68-32_eowr#c0035` on page 17 is an example. TableFormer also reports unmatched cells. These forms need further extraction review.
- Seventeen 68-32 chunks contain an unsplittable row exceeding 1,500 characters: `c0035`, `c0041`, `c0043`, `c0045`, `c0047`, `c0049`, `c0059`, `c0061`, `c0063`, `c0065`, `c0067`, `c0068`, `c0069`, `c0070`, `c0071`, `c0072`, `c0073`.
- Two empty tables are skipped: 56-32 page 34 (`#/tables/31`) and 68-32 page 10 (`#/tables/6`). Other text still covers these pages.
- OCR is disabled. All three source PDFs have a text layer; no page has fewer than 50 pypdf characters. Appendices and more complex table handling remain future ingestion work.

Source titles, authorship, submission links and licenses are listed in the [README](../README.md#data-attribution).
