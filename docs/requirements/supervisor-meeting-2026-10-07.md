# Supervisor meeting, 7 October 2026 (digest)

**Kind:** input to the [project specification](../PROJECT_DESIGN.md) · **Recorded:** Teams transcript, 37 minutes, retrieved 27 October 2026 · **Present:** MSc. Nguyen Anh Tuan (VPI supervisor), Thai Huu Tri, Nguyen Le Hung, Tran Quang Khai

This digest paraphrases the supervisor's direction. It predates the BSEE/AK-3 data direction (25 October, D-13) and the team's scope agreement (27 October, D-26/D-27), and it is the basis for both. The specification records it as decisions D-28 to D-35 and resolves conflicts in [§13.1](../PROJECT_DESIGN.md#131-decision-register). The raw transcript is not committed.

## 1. Reframe: build a knowledge-graph builder, apply it to oil and gas

- The team's first plan went straight at petroleum data. The supervisor judged that this makes the work depend on oil-and-gas expertise the team does not have, and that the team would get stuck and lose control of it.
- The product is a **Graph Builder**: a technology product that turns documents into a knowledge graph. Oil and gas is the **use case** (domain) it is demonstrated on. The overall direction of the capstone does not change, only the way in.
- The deliverable must not depend on the team authoring the domain ontology. Domain users bring their ontology and data; the pipeline processes them.

## 2. The builder is the hard part; question answering comes second

- Question answering over a graph is "not hard": an LLM converts the user's question, together with the graph's schema, into a query, and the result is returned. Many QA approaches exist (an external API, a self-built vector database); the project's distinctive, controlled approach is the graph.
- The first and most important phase is the **graph builder**: converting a document or a collection of documents into a graph database (for example Neo4j with hundreds of thousands of nodes and millions of edges). The store of the system is the knowledge graph, not a QA engine.
- Retrieval (natural language to a graph query) belongs to the second half.

## 3. What makes a graph builder hard

1. **Duplicate nodes.** One real-world object must not become two nodes because, for example, the names differ by a space.
2. **Which connections to make.** Relationships have depth. Classmates are clearly connected; a friend of a friend met once is not worth a link. The builder must judge the strength and depth of a connection, not link everything.
3. **Three kinds of entity mention:**
   - Entities with standard names that are consistent across databases, such as offshore wells. A domain user supplies the list (for example an Excel file); the team loads it and confirms the canonical names.
   - Other proper nouns, which can become nodes directly.
   - Mentions that are not names: pronouns ("he", "him") and other referring expressions. The builder must resolve them to the named entity, or it creates a wrong node and wrong links.
4. **Relation vocabulary.** Relation names ("A knows B") are defined in advance, or a dictionary of terms is defined so an LLM can extract them.
5. **Ontology.** Node and relation definitions together form the ontology. It guides extraction and the mapping from documents into the database.
6. **References.** Every extracted node and relation records which document and passage it came from.

## 4. Application layer for the builder (admin)

- The pipeline (which may first be built as notebooks or scripts, using an LLM or a small model for extraction and mapping) is wrapped in an **application** that lets an administrator control each step:
  - manage the ontology: add node concepts and relation definitions, then update and re-run extraction to refresh the graph;
  - control the extraction steps;
  - **human in the loop**: results with high confidence can be accepted automatically above a threshold; unclear ones are raised for a person to approve;
  - tools that search the graph for highly similar nodes, so a person can check whether the machine made a mistake and merge them, and delete redundant relations;
  - references to source documents and passages.
- An LLM-based **agent** design is acceptable: steps that critique, revise and raise warnings.
- The output of the first half is an admin application that builds a knowledge graph, with an ontology as input.

## 5. The ontology is the user's input, not the team's burden

- If the team authors the ontology, the product works for one domain only. If the product leaves the ontology open, it works for any domain: the user uploads an ontology and re-runs the pipeline.
- The product may include an **AI assistant that helps create an ontology**, from rules set up in advance. If that is not good enough, the customer builds their own ontology and uploads it.
- The capstone does not need to go deep into ontology engineering. For testing, the team may take an ontology or dataset from the internet, or ask an AI to generate a dataset or an ontology from a document.
- Ontologies are hard to find online; documents such as drilling reports and well data are easier.

## 6. Data and domain

- VPI will not supply a dataset: domain data falls under confidentiality rules. The supervisor wants an open platform.
- Use public data; the United States publishes a lot. The supervisor would send pointers (these became the BSEE and AK-3 sources, D-13).
- At the end, the supervisor can provide a petroleum document and evaluate the system with the team on it.
- Within oil and gas, focus on **upstream wells: drilling and production**, the well and the borehole. Drop geology and geophysics.
- Test on oil and gas first, then try other domains to see how the builder generalizes. Other domains are acceptable.

## 7. Process and schedule

- Start with a **literature review**, and survey open-source implementations on GitHub: pull them, run them, see where the technology is and which tech stack it uses. The team does not have to build from scratch, but must understand the essentials.
- Redo the five-round plan in that order. Next two weeks: literature review on knowledge graphs and the overall architecture.
- Report to the supervisor **weekly**, without waiting for the two-weekly meeting with Dr. Dung.
- With AI coding support, the whole thing, graph builder and the QA second half, in English, should fit in **one semester**; the next semester does something else (improvements chosen per area).
- System design thinking and control of the architecture matter more than hand-writing code.

## 8. Security and permissions: later

- Access control and permissions are not needed yet; this phase is the admin layer for the person who ingests data.
- An end-to-end application architecture covering end users and administrators may be drawn later in this phase, to plan integration.
