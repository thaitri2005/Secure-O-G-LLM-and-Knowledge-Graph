# Datasets and licences

Project licence: **TBD by repository owner**. A dependency's licence does not assign a licence to this project's code, annotations or collected dataset material. This document records provenance and unresolved rights; it does not grant permissions absent from the source terms.

| Material | Provenance and use | Licence status |
| --- | --- | --- |
| WebNLG-10 | Texts, schema and references distributed with the pinned EDC benchmark; extraction evaluation | Consult the original WebNLG dataset terms as well as EDC's code licence before redistribution. |
| 2Wiki-10 | A subset of 2WikiMultiHopQA distributed with the pinned HippoRAG evaluation inputs | Preserve original dataset attribution and consult its terms; a code licence does not cover every source passage. |
| MINE-3 | Three essays and queries from the pinned MINE evaluation dataset; recorded extraction and judge outcomes | Dataset revision is recorded in `configs/runtime/assets.json`; verify the dataset's own licence separately from KGGen. |
| Showcase | Small demonstration documents and deterministic expected graph properties | Retained as evaluation examples; project licence remains unresolved. |
| BSEE tables and narratives | Public BSEE well, borehole, lease, company and operations-report data | Public source provenance is retained. Check BSEE notices and any underlying third-party rights before redistribution. Raw downloads are not bundled. |
| BSEE gold v1/v2 | LLM annotations and adjudication over selected BSEE narrative chunks | Generated labels are not human expert labels. No separate licence grant is asserted. |
| Recorded LLM responses | Exact request/response evidence for published configurations | Retained for reproducibility. Model and source-content terms remain applicable. |

BSEE narratives were selected with PII screening before freezing. Screening is not a formal guarantee of no PII, and public accessibility does not remove privacy obligations. Person-name detection leads to unreadable annotation status without copying the name. Preserve source text and keys when changing documentation or code paths.

No upstream repository source or paper PDF is included. Setup recreates dependencies at the exact commits in the lock file. [NOTICE](../NOTICE.md) lists upstream URLs and detected licence metadata. Some detections rely on package metadata rather than a licence file; retain that distinction when deciding whether to redistribute.
