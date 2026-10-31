# Frozen source annotations

The development and held-out annotations come from rendered source pages and direct PDF text/character layers. Parser and candidate output were not annotation inputs. Corrected table and form manifests are frozen. Source wording, clipping, blank fields, merged-cell anchors, repeated cost headings and the shared activity row are preserved as reviewed. The excluded key-value panels remain excluded from grid scoring.

Page numbers are one-based physical PDF pages. Rectangles use top-left PDF points in the displayed physical frame. Table CSVs have no extra schema row; merged cells occupy their top-left anchor. Form CSVs use `block,key,value`, including blank values. Scanned transcriptions cover printed/typed text and exclude handwriting, signatures, stamps and checkbox states as specified in each manifest.

Every source file, including the original review sheets, is relocated without changing bytes. [The content-hash map](../results/annotation-relocation.json) records old path, new path and matching hashes. [The path resolver](../configs/annotation-paths.json) is used by evaluation; original JSON paths and metadata remain unchanged. Original review-sheet relative links are historical provenance, while this page and the evaluation documentation use current locations.

Methods and criteria were fixed before scoring. The form template and header-cleaning method were frozen before held-out selection. The prototype's header-only extension is informed by reviewed held-out failures and is not independent held-out evidence. All annotations are single-annotator and AI-assisted, with a source-render second review and no inter-annotator agreement.

| Set | Tables | Forms | Scanned pages | Review provenance |
| --- | --- | --- | --- | --- |
| Development | [Continued tables](development/continued-tables/continued_tables.json) | [Headers](development/forms/forms.json) | [Transcriptions](development/scanned-pages/transcriptions.json) | [Conventions](development/source-conventions.md), [review sheet](development/REVIEW.md) |
| Held-out | [Continued tables](held-out/continued-tables/continued_tables.json) | [Headers](held-out/forms/forms.json) | — | [Review sheet](held-out/REVIEW.md) |

Repository grid and reading-order annotations remain at their original read-only paths outside this exploration. The [unified evaluation](../results/evaluation.json) includes them without copying or editing them.
