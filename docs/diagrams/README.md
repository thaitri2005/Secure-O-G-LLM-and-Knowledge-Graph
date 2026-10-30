# Architecture diagram assets

These SVGs are the portable exports used in [the project specification](../PROJECT_DESIGN.md), [development plan](../DEVELOPMENT_PLAN.md) and [data sources](../DATA_SOURCES.md). Their editable Mermaid source sits directly below each image, in an expandable block in the corresponding document. That source is authoritative; the SVGs are derived presentation assets.

Current direction (28 October 2026): a GraphRAG application for drilling reports ([specification](../PROJECT_DESIGN.md) 3.0). On 29 October these were redrawn:

- diagram 02: target components with object store, vector store, page parser, model endpoints, hosted development models and school GPU slots;
- diagram 03: the item lifecycle with review by exception;
- diagram 04: the data model with parent/child chunks and vector points;
- diagram 05: the GraphRAG answer flow;
- diagram 07: the new milestones;
- diagram 09: the three layers as built in the capstone.

Diagram 01 (current implementation) was relabelled to show the prototype as the baseline. Diagram 06 (deployment and recovery) was removed with the production-operations detail it illustrated; that work is now second-semester scope. Diagram 08 is unchanged and describes the current two tracks.

| File | Diagram | Used in |
|---|---|---|
| `01-current-ingestion.svg` | What is built: document and data pipelines, releases, shared contracts, registry, baseline prototype | Design §3 |
| `02-target-architecture.svg` | Target components, stores and model endpoints | Design §4 |
| `03-claim-lifecycle.svg` | Item lifecycle with review by exception | Design §5.2 |
| `04-data-model.svg` | Files, pages, parent/child chunks, vector points, entities, items, corrections, answers | Design §7 |
| `05-question-answering.svg` | GraphRAG retrieval and cited answer sequence | Design §8 |
| `07-milestone-dependencies.svg` | Milestones M0–M6, with M1 as the three-track first build | Plan §3 |
| `08-source-integration.svg` | The two development tracks: BSEE data (import, graph, registry) and end-of-well reports (ontology file, extraction, review, QA) | Data sources, Design §5.7 |
| `09-three-layers.svg` | Three layers as delivered by the capstone | Design §1.3 |
| `10-first-build-tracks.svg` | First build: track A ingestion, track B GraphRAG engine, track C storage, IDs and runner | Design §4.5 |

## Regenerating a diagram

All exports use Mermaid 11.17.2 with the shared theme in [`mermaid-config.json`](mermaid-config.json): dark blue text, pale blue nodes and warm neutral groups on white. These are documentation tools only; they add no runtime dependency.

1. Copy the Mermaid block from the document into a temporary `.mmd` file.
2. Render it, using the diagram's number in the SVG ID:

   ```powershell
   npx -y @mermaid-js/mermaid-cli@11.17.0 -i diagram.mmd -o docs/diagrams/08-source-integration.svg -c docs/diagrams/mermaid-config.json -b white -I diagram8
   ```

   If Puppeteer cannot download Chromium, point it at an installed Chromium-based browser. Pass `-p puppeteer.json` with `{"executablePath": "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"}`.
3. Open the SVG and check for clipping, overlapping labels and text size before committing. Update the source block and the SVG in the same commit.

Diagrams 01, 02, 03, 04, 05 and 09 were regenerated on 29 October 2026; diagram 07 was regenerated and diagram 10 added on 30 October (first build in three tracks); diagram 08 dates from 27 October.
