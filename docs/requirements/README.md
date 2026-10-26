# Stakeholder requirements

**Updated:** 27 October 2026 · **Kind:** input to the [project specification](../PROJECT_DESIGN.md), not the source of truth

This folder holds the two VPI documents that define what the project is asked to do, and an English digest of them with requirement IDs (SR-xx). They are inputs, and many details are still to be adjusted in supervisor meetings. The [project specification](../PROJECT_DESIGN.md) decides how each requirement is met, narrowed or deferred ([§1.2](../PROJECT_DESIGN.md#12-stakeholder-requirements-and-how-they-are-met)), and lists what is still to be agreed ([§13.2](../PROJECT_DESIGN.md#132-open-questions-for-supervisor-meetings)). When VPI sends a new or revised document, update this digest first, then the specification.

## The documents

| Document | Origin | Content |
|---|---|---|
| `originals/capstone-proposal-vpi.pdf` | Capstone project proposal, Vietnam Petroleum Institute (VPI) | Title, supervisors, company, one-page project description, team size |
| `originals/KGinEP-vi.docx` | "Xây dựng Đồ thị tri thức cho tài liệu chuyên ngành lĩnh vực Dầu khí" (Building knowledge graphs for oil-and-gas technical documents), in Vietnamese | VPI's view of why oil-and-gas knowledge needs knowledge graphs, the main difficulties, and the intended three-layer approach |

The originals are **not committed**: the repository is public, and `originals/` is in `.gitignore` until VPI agrees to publication. Share them through the team drive. The digest below paraphrases them.

## Capstone proposal (digest)

- **Project:** Secure Domain-Specific LLM and Knowledge Graph Platform for Oil & Gas Technical Intelligence.
- **Supervisors:** Dr. Le Duy Dung; MSc. Nguyen Anh Tuan (Vietnam Petroleum Institute). **Company:** Vietnam Petroleum Institute. **Students:** three BSCS students.
- **Motivation:** generic or commercial LLM services see limited use in oil and gas because domain data is technically complex, operational documents are sensitive, and security requirements are strict.
- **Aim:** a pilot of an in-house, secure AI platform for extracting, organizing and reasoning over PVN's technical knowledge.
- **Focus:** automated pipelines that extract structured knowledge from unstructured technical documents; a domain-specific oil-and-gas knowledge graph; customized LLM-based reasoning and question answering.
- **Deployment:** secure on-premise or private-cloud, so PVN keeps full control of sensitive data and builds long-term technological independence in industrial AI.

## Knowledge graphs in oil and gas (digest of KGinEP)

1. **Context.** Oil and gas spans upstream (exploration, field development, production) to midstream and downstream (transport, processing, refining, petrochemicals, energy). Each area has deep knowledge: theory, experimental data, operating procedures, technical standards and, above all, the experience of experts. The knowledge is large, highly specialized and intricately connected across areas.
2. **Need.** Expert knowledge built up over years is often not fully written down. When experienced staff retire or move, it is lost or becomes hard to reach. This matters most in geology, geophysics, drilling, production, refinery operation and equipment maintenance. Storing documents is not enough: knowledge must be modelled, linked and organized so users can query relationships between objects, events, conclusions and expert experience.
3. **Knowledge differs by segment.** Upstream problems are uncertain and admit several answers. One problem can be explained in different ways depending on data, assumptions or schools of thought, and conclusions can complement, compete with or contradict each other while each remains valid in some context. The graph must therefore hold several hypotheses, their supporting evidence, opposing views and the relations between them, not a single conclusion. Midstream, downstream and production operations are more systematic and deterministic: equipment belongs to a system, performs a function, takes input from one unit and feeds the next. There the graph models the operating system's structure to support retrieval, impact analysis and operational knowledge.
4. **Role of a knowledge graph.** Represent knowledge as entities, attributes and relationships instead of separate documents, so that it can link many sources; connect theory with data and practical experience; represent several viewpoints on one problem; express support, dependency, competition and contradiction; retrieve by relationship rather than keyword; and give AI/LLM systems structured context. The graph becomes a knowledge layer between documents, data, experts and AI systems.
5. **Main difficulties.** (1) Diverse sources: technical reports, design documents, procedures, standards, operation logs, geological and geophysical reports, technical databases and expert-written documents. (2) Inconsistent concepts: one object has several names across units, projects and disciplines, and one term can mean different things in different contexts. (3) Several languages: Vietnamese, English, Russian and others. (4) Complex relations: cause and effect, dependency, condition, correlation, evidence, hypothesis, contradiction, inheritance. (5) Large and growing: knowledge keeps arriving from projects, production and new experience.
6. **Approach.** One graph for the whole industry would make concepts, relations and maintenance too hard to unify. Build **domain-specific knowledge graphs** instead, for areas with clear scope such as geology, geophysics, drilling, production, equipment and maintenance, plant operation, refining and petrochemicals, safety and environment, and commerce and supply chain. Each fits its domain's data, terminology, entity types and relations. Connect them through **unified entity identification**: a well, field, piece of equipment, plant, product or organizational unit has one consistent identifier in every domain.
7. **Overall problem: three layers.** A knowledge ecosystem that is split by discipline but connected at the entity level:
   1. **Domain knowledge graphs**, one per discipline;
   2. **Unified entity and ontology layer**: identifiers, ontology and shared concepts that link entities across domains;
   3. **Knowledge application layer**: RAG, Graph RAG, expert assistants, technical question answering, decision support and domain AI models.

   The end goal is to move oil-and-gas knowledge from documents, data and individual experience into a structured, linked, queryable system that keeps growing.
8. **Reference documents.** The list has one placeholder entry ("Exploration: Example"). The actual documents are still to be supplied.

## Requirements (SR)

Each requirement paraphrases one statement of the documents above. How each is met, narrowed or deferred is decided in [specification §1.2](../PROJECT_DESIGN.md#12-stakeholder-requirements-and-how-they-are-met), not here.

| ID | Requirement | Source |
|---|---|---|
| SR-01 | Secure in-house platform; on-premise or private-cloud deployment; the data owner keeps full control of sensitive data | Proposal |
| SR-02 | Automated pipelines that extract structured knowledge from unstructured technical documents | Proposal |
| SR-03 | A domain-specific oil-and-gas knowledge graph | Proposal, KGinEP §6 |
| SR-04 | Customized LLM-based reasoning and question answering | Proposal, KGinEP §7 |
| SR-05 | Long-term technological independence | Proposal |
| SR-06 | Separate domain knowledge graphs rather than one monolithic graph | KGinEP §6 |
| SR-07 | Unified entity identification and shared ontology across domains | KGinEP §6–7 |
| SR-08 | Several hypotheses, supporting evidence and opposing views, and their relations | KGinEP §3–4 |
| SR-09 | Deterministic system structure for midstream, downstream and operations (equipment, systems, functions, flows) for impact analysis | KGinEP §3 |
| SR-10 | Rich relation types: cause and effect, dependency, condition, correlation, evidence, hypothesis, contradiction, inheritance | KGinEP §5 |
| SR-11 | Synonyms and context-dependent terms | KGinEP §5 |
| SR-12 | Vietnamese, English and Russian material | KGinEP §5 |
| SR-13 | Diverse source types (reports, designs, procedures, standards, logs, databases, expert documents) | KGinEP §5 |
| SR-14 | Continuous growth | KGinEP §5 |
| SR-15 | Preserve expert knowledge; link theory, data and practical experience | KGinEP §2, §4 |
| SR-16 | Retrieval by relationship, not only keyword | KGinEP §4 |
| SR-17 | Application layer: RAG, Graph RAG, expert assistant, technical QA, decision support | KGinEP §7 |
| SR-18 | The knowledge is PVN's technical knowledge | Proposal |
