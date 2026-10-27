# Architecture diagram assets

These SVGs are the portable exports used in [the project specification](../PROJECT_DESIGN.md), [development plan](../DEVELOPMENT_PLAN.md) and [data sources](../DATA_SOURCES.md). Their editable Mermaid source sits directly below each image, in an expandable block in the corresponding document. That source is authoritative; the SVGs are derived presentation assets.

Current direction (27 October, with the 7 October supervisor direction): a knowledge-graph builder with a user-supplied ontology, one English oil-well use case; builder and admin console first, QA second, access control later. Diagram 02 labels the web UI as the admin console and the profile as admin-loaded; diagram 07 follows the reordered milestones. Diagrams 02 and 09 include the versioned domain-profile input; diagram 04 shows the first-delivery logical model, with expert notes/interpretation links deferred. Diagrams 01/08 preserve current source-specific tracks. Architecture/lifecycle diagrams remain targets; publication/withdrawal guarantees still require implementation. M0–M7 hours/windows remain illustrative pending re-estimation.

| File | Diagram | Used in |
|---|---|---|
| `01-current-ingestion.svg` | Implemented PDF and BSEE ingestion paths | Design §3 |
| `02-target-architecture.svg` | Proposed application components and deployment boundary | Design §4 |
| `03-claim-lifecycle.svg` | Candidate, review, publication and withdrawal states | Design §5 |
| `04-data-model.svg` | First-delivery documents, dataset records, evidence, generic entities, claims and answers | Design §7 |
| `05-question-answering.svg` | Authorized query and evidence-linked answer sequence | Design §8 |
| `06-deployment-recovery.svg` | Development, release, operation and recovery | Design §11 |
| `07-milestone-dependencies.svg` | Development milestone dependency graph | Plan §3 |
| `08-source-integration.svg` | The two current development tracks: BSEE data and end-of-well reports | Data sources, Design §5.7 |
| `09-three-layers.svg` | Reusable core, versioned profiles and English oil-well application | Design §1.3 |

## Regenerating a diagram

All exports use Mermaid 11.17.2 with the shared theme in [`mermaid-config.json`](mermaid-config.json): dark blue text, pale blue nodes and warm neutral groups on white. These are documentation tools only; they add no runtime dependency.

1. Copy the Mermaid block from the document into a temporary `.mmd` file.
2. Render it, using the diagram's number in the SVG ID:

   ```powershell
   npx -y @mermaid-js/mermaid-cli@11.17.0 -i diagram.mmd -o docs/diagrams/08-source-integration.svg -c docs/diagrams/mermaid-config.json -b white -I diagram8
   ```

   If Puppeteer cannot download Chromium, point it at an installed Chromium-based browser. Pass `-p puppeteer.json` with `{"executablePath": "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"}`.
3. Open the SVG and check for clipping, overlapping labels and text size before committing. Update the source block and the SVG in the same commit.

Diagrams 02, 04, 07 and 09 were updated on 27 October 2026, 01 and 08 on 25 October 2026, and the others on 23 October 2026. Spacing differs slightly between the sets.
