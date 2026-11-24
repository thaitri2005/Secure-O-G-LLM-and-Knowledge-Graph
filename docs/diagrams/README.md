# Diagrams

The Mermaid block in a document is the source of each diagram. The SVG files here are exports of those blocks, shown as images above them so the diagram also reads outside GitHub. Change the block first, then export it again; never edit an SVG by hand.

| File | Diagram | Source block |
|---|---|---|
| `02-target-architecture.svg` | Target components: proxy, backend with the coordinator and its four lanes, stores, model endpoints by role, rented compute | [Specification §4.1](../PROJECT_DESIGN.md#41-components-and-trust-boundary) |
| `03-claim-lifecycle.svg` | Item lifecycle with review by exception | [Specification §5.2](../PROJECT_DESIGN.md#52-item-lifecycle-and-review-by-exception) |
| `04-data-model.svg` | Logical data model: files, pages, chunks, vectors, entities, items, corrections, answers | [Specification §7.1](../PROJECT_DESIGN.md#71-source-to-answer-model) |
| `05-question-answering.svg` | Answer sequence: frame call, lanes, fallback, result reported by code or answer call, checks, question log | [Specification §8.2](../PROJECT_DESIGN.md#82-answer-sequence) |
| `07-milestone-dependencies.svg` | Milestones M0 to M6 | [Plan §3](../DEVELOPMENT_PLAN.md#3-milestones) |
| `08-source-integration.svg` | The two data sources, BSEE well data and drilling reports, and what each feeds | [Data sources](../DATA_SOURCES.md) |
| `09-three-layers.svg` | The three layers as the capstone delivers them | [Specification §1.3](../PROJECT_DESIGN.md#13-three-layer-target-and-what-the-capstone-delivers) |
| `10-first-build-tracks.svg` | First build: tracks A, B and C joined by files | [Specification §4.5](../PROJECT_DESIGN.md#45-first-build-three-tracks-joined-by-files) |
| `11-second-build.svg` | Second build: from a K1 package to the application | [Specification §4.6](../PROJECT_DESIGN.md#46-second-build-one-connected-application) |
| `12-first-build-pipeline.svg` | The measured pipeline, with the lane chosen per run | [Specification §8.4](../PROJECT_DESIGN.md#84-what-the-first-build-runs-today) |
| `13-graph-model.svg` | One graph, two regions (facts and events), joined at `Well` and `Chunk` | [Specification §8.5](../PROJECT_DESIGN.md#85-the-graph-nodes-and-relationships) |
| `14-deployment.svg` | Deployment: browser, proxy with the password, backend, stores, model endpoint; ports and volumes | [deploy/README.md](../../deploy/README.md#what-runs) |
| `15-life-of-a-question.svg` | The life of a question in the coordinator | [graphrag/README.md](../../graphrag/README.md#architecture) |

Numbers 01 and 06 are not used.

Two small diagrams have no SVG copy and are drawn by GitHub from their block: the document map in [docs/README.md](../README.md) and the service's modules in the [backend design](../tracks/C-storage/backend-design.md). The stint report's figures are not Mermaid: `scripts/stint_figures.py` draws them ([how](../reports/stints/README.md)).

## Style

One theme for every export, in [`mermaid-config.json`](mermaid-config.json): dark blue text (`#1b2a3a`) on pale fills, Arial at 16 px, white background. Every text and fill pair has a contrast ratio above 12:1.

Flowcharts colour a node by what it is. The five classes are written at the end of each block, so GitHub draws the same colours from the block alone:

| Class | Fill, border | Used for |
|---|---|---|
| `ui` | green `#e4f3ea`, `#3b7d57` | People, the browser, the frontend, what a person sees |
| `svc` | blue `#e8f0fa`, `#3d6a9c` | Code the team runs: services, lanes, steps done in code |
| `store` | amber `#fdf0d0`, `#a67512` | Stores and stored data |
| `model` | violet `#f0e7f9`, `#7b52ab` | Model endpoints and model calls |
| `ext` | grey `#f3f4f6`, `#6b7280`, dashed | Outside the deployment: rented compute, source files |

```
    classDef ui fill:#e4f3ea,stroke:#3b7d57,color:#1b2a3a
    classDef svc fill:#e8f0fa,stroke:#3d6a9c,color:#1b2a3a
    classDef store fill:#fdf0d0,stroke:#a67512,color:#1b2a3a
    classDef model fill:#f0e7f9,stroke:#7b52ab,color:#1b2a3a
    classDef ext fill:#f3f4f6,stroke:#6b7280,color:#1b2a3a,stroke-dasharray:5 4
```

The graph model uses three classes of its own (shared nodes, fact region, event region), and the milestones two (done, now).

Rules that keep a diagram readable at the width GitHub shows (about 900 px):

- One idea per diagram, flowing top to bottom or left to right.
- At most four boxes side by side: an export wider than about 1,250 px has text too small to read once it is scaled down.
- Break a label with `<br/>` before it reaches about 26 characters; Mermaid wraps at 200 px on its own, often badly.
- Solid arrows are calls or data flow. Dotted arrows are what is read from something built earlier, planned, or outside the deployment.
- Names follow the specification's [glossary](../PROJECT_DESIGN.md#134-glossary).

## Exporting a diagram

Exports use mermaid-cli 11.17.0. These are documentation tools only; they add no runtime dependency.

1. Copy the Mermaid block from the document into a temporary `diagram.mmd`, outside the repository.
2. Render it from the repository root, with the diagram's number in the SVG ID:

   ```sh
   npx -y @mermaid-js/mermaid-cli@11.17.0 -i diagram.mmd -o docs/diagrams/02-target-architecture.svg -c docs/diagrams/mermaid-config.json -b white -I diagram02
   ```

   The command is the same in PowerShell. To use a browser that is already installed instead of the one Puppeteer downloads, add `-p puppeteer.json`:

   | System | `puppeteer.json` |
   |---|---|
   | Linux | `{"executablePath": "/usr/bin/chromium", "args": ["--no-sandbox"]}` (use the path of your Chromium or Chrome; `--no-sandbox` is needed in a container or as root), and set `PUPPETEER_SKIP_DOWNLOAD=1` before the command |
   | Windows | `{"executablePath": "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"}` |

3. Render a PNG the same way (`-o diagram.png -s 2`) and look at it: no clipped or overlapping labels, and the text still readable when the image is 900 px wide.
4. Commit the block and the SVG together.

A new diagram takes the next free number, an image line above its block, and a row in the table above:

````markdown
![What the diagram shows](diagrams/16-name.svg)

<details>
<summary>Diagram source (Mermaid)</summary>

```mermaid
...
```

</details>
````
