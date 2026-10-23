# Architecture diagram assets

These SVGs are the portable diagram exports used in [the project design](../PROJECT_DESIGN.md) and [development plan](../DEVELOPMENT_PLAN.md). Their editable Mermaid source is retained directly below each image in an expandable block in the corresponding document.

| File | Diagram |
|---|---|
| `01-current-ingestion.svg` | Implemented PDF ingestion |
| `02-target-architecture.svg` | Proposed application components and deployment boundary |
| `03-claim-lifecycle.svg` | Candidate, review, publication, and withdrawal states |
| `04-data-model.svg` | Documents, evidence, entities, claims, and answers |
| `05-question-answering.svg` | Authorized query and evidence-linked answer sequence |
| `06-deployment-recovery.svg` | Development, release, operation, and recovery |
| `07-milestone-dependencies.svg` | Development milestone dependency graph |

Exports were generated with Mermaid 11.17.2 and visually checked in a headless browser. When a diagram changes, update the Mermaid source and regenerate the matching SVG together. Inspect the result for clipping, line crossings, and text size. The source in the Markdown document is authoritative; SVGs are derived presentation assets.

The color scheme uses dark blue text, pale blue nodes, and warm neutral groups on white. These are documentation assets; they add no runtime dependencies to the application.
