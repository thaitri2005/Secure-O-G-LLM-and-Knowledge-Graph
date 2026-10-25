# Documentation

Start with the first row, then read the others as needed. Each document says at the top whether it describes implemented behavior or the proposed design.

| Document | Read it for | Kind |
|---|---|---|
| [Development focus and data sources](DATA_SOURCES.md) | **What the team is building on now**: BSEE well data, the AK-3 end-of-well report, the FORGE overlap set | Current guidance |
| [Project description and system design](PROJECT_DESIGN.md) | Scope, users, architecture, data model, extraction, QA, security, operations, acceptance gates | Design baseline |
| [Development and delivery plan](DEVELOPMENT_PLAN.md) | Milestones, ownership, estimates, risks, and the next backlog | Plan |
| [BSEE well-data ingestion](bsee-ingestion.md) | Commands, outputs, value conventions and checks of the structured-data adapter | Implemented |
| [PDF ingestion](ingestion.md) | Commands, output contract and processing rules of the PDF pipeline | Implemented |
| [Ingestion evaluation](ingestion-evaluation.md) | How the PDF configuration was chosen, measured quality, reproduction commands | Measurements |
| [OCR ingestion](ocr-ingestion.md) | Local PDF registration and the opt-in Vietnamese–English OCR profile | Implemented, experimental |
| [Related work](references.md) | Papers and resources from the supervisor, access status, takeaways | Reference |
| [Diagrams](diagrams/README.md) | SVG exports and how to regenerate them | Assets |
| [Archive](archive/) | Superseded records, kept for history | Historical |

## Conventions

- **Implemented** means code, tests and a verification record exist in this repository. **Proposed** or **planned** means design intent only.
- Measurements state their date, input and configuration. Don't copy numbers between documents; link to the document that owns them.
- When behavior changes, update the subsystem document and the "Current implementation" section of the design ([§3](PROJECT_DESIGN.md#3-current-implementation-and-evidence)) in the same change.
- Diagram sources are the Mermaid blocks in the documents; the SVGs are generated from them ([how](diagrams/README.md)).
