# Supervisor meeting, 28 October 2026 (digest)

**Kind:** input to the [project specification](../PROJECT_DESIGN.md) · **Recorded:** Teams transcript, 40 minutes, 28 October 2026 · **Present:** MSc. Nguyen Anh Tuan (VPI supervisor), Thai Huu Tri, Nguyen Le Hung, Tran Quang Khai

This digest paraphrases the supervisor's direction. The transcript was produced automatically from Vietnamese speech and is noisy, so some phrases are reconstructed from context; items where the meaning is uncertain are marked *(unclear)*. The raw transcript is not committed. The specification records the direction as decisions **D-36 to D-47** (version 3.0) and removes the parts of the earlier design that no longer fit. [§13](#13-effect-on-the-documentation) of this digest lists what was removed or replaced, and why.

This meeting changes the direction more than any earlier one. Where it conflicts with the [7 October meeting](supervisor-meeting-2026-10-07.md), this meeting wins. Parts of 7 October still apply: the ontology is the user's input, entities need unified IDs, people stay in the loop, and the team should reuse open-source work.

## 1. The new direction in one page

| Topic | Direction |
|---|---|
| Approach | **GraphRAG**: an LLM extracts entities and relations under rules (ontology) the team provides, and retrieval combines the graph with vector embeddings. Do not train custom extraction models (NER, relation extraction): there is no dataset for that. |
| Starting point | Find existing open-source GraphRAG repositories, take over their pipeline and develop it. Do not build from scratch. |
| Models | **Open-source models only, about 7B parameters or smaller.** No commercial models or APIs (ChatGPT, Gemini, Claude). |
| Compute | Development and testing may call open-source models through a paid hosted API such as OpenRouter; the supervisor will help with the cost. Large runs (for example 5,000 pages) use the school's GPU machines, booked by time slot. |
| Document parsing | Re-evaluate OCR and move to **vision-language models (VLMs)** that turn pages, especially tables, into machine-readable Markdown or HTML. |
| Tables | Drilling reports, above all daily reports, are mostly tables: text nested in cells, many merged cells, tables running over 3–4 pages without repeated headers. They need their own evaluation and handling. |
| Data scope | By **document type**, not by sub-domain: everything in drilling reports such as the End of Well Report and the Daily Drilling Report, including their short geology sections at a general level. |
| Storage and IDs | Design where raw files, chunks, metadata, triples and vectors are stored, and an ID system that links files, pages, parent and child chunks, vector payloads and graph entities across documents and databases. |
| Ontology control | Plan where entity and relation types are defined, how they are injected into the LLM during ingestion, and how they are verified. |
| Human in the loop | Show confidence scores; low-scoring items go to people, who correct them in the user interface. |
| Product | A capstone, not research: deliver a **full application** (data, ingestion, architecture, governance, application, end user). Prefer what is effective. Start with a basic pipeline and upgrade parts as better ones are found. |
| Order | Ingestion first, then data organization and storage, then retrieval. Start on **one document** before processing many. |
| Process | Weekly 30-minute check-in with the supervisor, frequent short updates in the group chat, a light plan (slides are fine), and roles split into data, backend and frontend. |

## 2. Models: open source, about 7B, no commercial APIs

- The supervisor does not want commercial models. The project would be easy with them, but the team should take on the harder constraint: **no commercial models and no commercial APIs** (for example the ChatGPT API).
- **Reason 1, security.** Oil-and-gas data is confidential, so commercial LLMs cannot be used on it in practice.
- **Reason 2, honest evaluation.** Commercial models are too capable to show how well the method works. A pipeline that scores above 90% on ChatGPT, Gemini or Claude may drop to 30–40% on a 7B model in the real environment, and that gap would be hard to explain. Evaluating on 7B-class models under realistic conditions keeps the results meaningful.
- **Size limit.** Keep to open-source models of about **7B parameters or smaller**. Then the problem fits the hardware that a deployment could realistically have: the GPU configuration needed to run a 7B model. In a real application the open-source model is deployed locally, not called through a commercial API.
- **Development compute.** The team does not have to run models on its own machines. Hosted open-source models are acceptable during development: the supervisor has topped up an account with a provider of open-source model APIs before and suggested **OpenRouter**. The cost is small; around US$5–10 runs a reasonable amount. The supervisor will help, and the team can also share the cost. The condition is the same model class: the API serves the same open-source ~7B models that would be deployed locally.
- **Large runs.** When a large volume must be processed (the slide's example was 5,000 pages, which takes a long time), register for the **school's GPU machines** and run day and night within the booked hours. Access is booked by time slot, and a new slot means queueing again. Khai noted that the school has four GPUs *(model unclear)*; Dr. Le Duy Dung can explain how to get access. The supervisor does not think the team needs them during the current build phase.
- **Code consequence.** Build the pipeline against an API now. For the real runs it can be pointed at, or redeployed onto, a local model; the supervisor sees no problem with that.

## 3. Document parsing: from OCR engines to vision-language models

- The supervisor reviewed the OCR work: an OCR engine, EasyOCR and PP-OCR *(names reconstructed)*. He wants to go **directly to VLMs** for this part and asked the team to look for suitable models, within the same open-source, size-limited rule.
- With a VLM, the page and its tables should be converted to a **machine-readable format**: HTML, Markdown or similar.
- Later in the meeting he skipped OCR as a topic. The direction is to evaluate VLMs, not to refine the OCR engines further.

## 4. GraphRAG instead of building extraction models

- The supervisor's first idea had been to build models that automatically extract knowledge (entities, relations, triples) from drilling documents. That would be very hard for the team and for him: it needs a dataset, named-entity recognition and relation extraction, and he would have to build the database himself. It will not be done.
- **GraphRAG** uses an LLM for extraction, and the team supplies only the rules (the ontology and prompts). The team can handle that, and it keeps the scope under control. "Go that way, it is easier."
- The team should **find repositories** that already do this, take over their pipeline and develop it further. What to optimize: the use of local LLMs, and quality on domain material.
- When going the RAG route, include **embedding models** in the plan. Plenty of ready-made models are available, as Tri noted.
- Khai had cloned GraphRAG repositories and read papers. Each has its own strength: entity clustering and canonicalization ("university" and "uni" recognized as one entity), events, or richer relations. He asked whether to build on them. The supervisor's answer is in §5.

## 5. A capstone, not a research project

- A capstone differs from scientific research. A paper must chase a research gap. The capstone should maximize **effectiveness**, within the constraints the team stated: confidential data, therefore local models.
- The output is a **full application**: data, ingestion, architecture, governance, application and the end user.
- Keep up with new methods, but prefer what works. A research method is often good only under narrow conditions (one dataset, one language, small data). For a system meant to be used in many places, find the best overall pipeline. Otherwise build the basic pipeline and improve it step by step, upgrading parts as better ones appear.
- Plenty of non-research repositories have basic GraphRAG pipelines. They are not optimized for:
  - drilling documents;
  - **injecting the ontology during ingestion**;
  - application features such as sending hard cases to a person (human in the loop) to check.
- A real customer request he has seen: "Here is my data dictionary. Run versioning on it; where you get one or two million items wrong, correct them automatically." Requests like that need not be research-grade, but they point toward a **platform**.
- The team need not dig deep into academic work.

## 6. Data scope: by document type

- Two weeks earlier the data was scoped to wells. One of the team's three questions asked whether the scope is drilling or geology.
- Answer: take **all the objects in drilling reports**, for example the End of Well Report and the Daily Drilling Report. These contain mostly drilling content plus one or two short geology sections; take the general information from those too.
- So both drilling and geology content are combined, but **scoped by document type** (end-of-well report, daily report), not by sub-domain (drilling only or geology only).

## 7. Tables

- The supervisor wants a **separate evaluation session on tables**. Drilling reports, especially the Daily Well (Drilling) Report, are almost entirely tables, with text nested in cells and many merged cells. He is unsure how well **Docling** parses them.
- With a VLM, page tables should be emitted as HTML or Markdown.
- Tables in real reports often run for **3–4 pages and lose their header** on later pages. Handle this explicitly.
- Chunking tables for RAG needs its own design.
- Tri described the current method:
  - tables are exported to Markdown;
  - chunks are made per row: a split falls only between rows, never inside one;
  - the ruling lines of a table are the structure used to split it.

  The supervisor understood the approach.

## 8. Storage, linking and IDs

The supervisor asked the team to design the following.

1. **How documents link to each other.** One object, such as a well, appears in many documents and remains one well in Neo4j. Its ID must be unified, and its references must point to every document and document type that mentions it. Design the identifiers, for example a well identifier, consistent across databases and documents.
2. **Raw files**: PDFs kept in object storage such as **MinIO**, or on a storage drive.
3. **After chunking**: how chunks are stored, and how the page structure is kept so a page can be rebuilt as text.
4. **Separate stores**: triples and metadata may live in one database and the **vector database** in another.
5. **An ID system**: a file ID tied to the file, and after chunking, parent and child chunk IDs, so each piece is linked to its payload and metadata and "nothing gets detached".

He also asked whether the code is in a shared GitHub repository and asked to be added to it, and whether Neo4j runs locally.

## 9. Ontology control

- Looking at the Neo4j schema shown in the meeting, the supervisor asked how relation types and the ontology are controlled. Where are they defined, and how are they injected into the LLM during ingestion? A plan is needed.
- He asked whether the dataset comes with an ontology or whether the team is assuming one. If it is assumed: when a user supplies an ontology, at which ingestion step does it enter, and how is it verified?
- Application idea: an area where users **define abbreviations** and terms.
- Commercial tools he knows **show a score** for each extracted item; items with a low score are left for users to update in the front end.
- Khai showed a graph built by an LLM pipeline on a larger amount of data. The supervisor's reading: the result is hard to separate and control because the ontology is not large enough. A large set of relation and entity types also runs into the LLM's context limit.

## 10. Cost and limits of LLM ingestion

- Tri reported that the context limit also affects ingestion. Rows are already processed separately, but this is slow: a table of 50 rows means 50 LLM calls.
- Very long rows (over about 1,500 characters) still exceed the limit and get cut. Normally rows stay within the limit, but some do not.
- Supervisor: using LLMs to solve this thoroughly is not optimal.
  - Computation is a cost in itself.
  - With a large document volume, paying per input and output token loses money.
  - Classical machine learning is not an option either, for lack of training data.

  Even so, take the GraphRAG route first because it is the easiest, and optimize afterwards.

## 11. What the supervisor wants to see next

1. **The real workflow**, demonstrated: how it runs and what it outputs (how many wells, what was extracted), how data is stored in code and storage, and what is missing. Ontology is an example of a gap: does the dataset have one, or is it assumed?
2. **Ingestion made clear first.** Evaluation has not been reached and is not the priority yet.
3. **Data organization next**: where inputs are stored, how outputs are stored after processing, how Neo4j is organized.
4. **A retrieval plan for GraphRAG**: if it is not there yet, plan it, including which **embedding model** to use.
5. **One document first.** Process a single document of a few pages and judge the GraphRAG quality on it before processing large volumes. This saves time and keeps the work under control.
6. Access to the **GitHub** repository, and a look at the **BSEE data** itself. He had only seen the website; Khai offered to share it as a ZIP.

## 12. The team's three questions and process

**Answers to the three questions.**

1. *Data scope:* by document type (§6).
2. *The two papers:* the supervisor cannot access them either. A friend studying abroad will download them, and he will send them on.
3. *The question set for evaluation:* he has asked a **drilling expert group** to provide one.

The team's main concern going in was that computation is heavy; §2 answers it.

**Product framing.** The supervisor asked what Dr. Dung had originally set as the brief. Tri: a project-style build rather than a research study. The supervisor had understood it the same way.

**Process.**

- Meet the supervisor **weekly for about 30 minutes**.
- Report in the group chat without hesitation. If the team is uncomfortable posting in front of Dr. Dung, a separate group without him is fine.
- Ask for help or post quick updates whenever needed, so the supervisor knows what support to give. If a week passes without contact, the team should message him: time drifts quickly.
- Changing direction late wastes a week of the team's work, so frequent contact avoids it.
- **Split tasks** for a full application: one person on data, one on backend, one on frontend.
- **A plan.** A weekly plan is fine. Share it so the supervisor knows where the team is digging and can push. Hung will draft it this week.
- **Format.** No need for detailed reports like the current progress report ("too detailed"). A short PowerPoint showing what is being done and where is enough. Between meetings, post anything new to the shared group chat every few days so Dr. Dung can follow too. Do not polish every sentence before sending.
- Then follow the plan.

## 13. Effect on the documentation

The [specification](../PROJECT_DESIGN.md) was rewritten as version 3.0 on 29 October 2026, and the [development plan](../DEVELOPMENT_PLAN.md) as version 3.0. The table records what was **removed or replaced** so nobody follows the old design by mistake. Superseded decisions remain listed, as history, in [specification §13.1](../PROJECT_DESIGN.md#131-decision-register).

| Earlier content | Where it was | What happened | Why (section of this digest) |
|---|---|---|---|
| Question answering only through developer-written Cypher templates with deterministic answers (D-08); "add embeddings only if templates prove insufficient" | Spec §8, §9 | **Replaced** by GraphRAG retrieval: vector, keyword and graph retrieval with an open ~7B model writing a cited answer. The E4 templates stay only as the measured baseline for property lookups | §4, §11 |
| "QA comes second, after the builder and admin application" (D-30 order) | Spec §1.6, plan | **Replaced** by: ingestion first, then storage and data organization, then a thin GraphRAG slice on one document, then the full application | §11 |
| Every report claim approved by a person before publication (D-07); auto-acceptance only after held-out calibration (D-31) | Spec §5.2–§5.3, FR-23, G3 | **Replaced** by review by exception: every item carries a score, low scores and warnings go to people, and users correct items in the UI. Identity merges still always need a person | §9 |
| Subsurface interpretations, competing hypotheses, expert notes and claim-to-claim links (§5.8, FR-17, D-20) | Spec §5.8, §7 | **Removed** from the design. Not part of a practical first application | §5 |
| Geology and geophysics excluded (D-34) | Spec §1, data sources | **Replaced** by scope by document type: end-of-well and daily drilling reports in full, geology sections at summary level | §6 |
| PP-OCRv6 + VietOCR as the default OCR, Vietnamese OCR quality work, RapidOCR/EasyOCR comparison as the next step (D-22) | Spec §9, plan M1 | **Removed** as direction. A VLM evaluation replaces OCR-engine tuning. The OCR code and E2/E5/E8 records stay as history | §3 |
| "Model selected by benchmark" with no limits (D-11); 7–8B 4-bit on a 16 GB GPU | Spec §9, §11 | **Narrowed**: open-weight, about 7B or smaller, never commercial | §2 |
| School RTX 4080 SUPER / A100 as the assumed host (D-03); "cloud only for public experiments" | Spec §10–§11 | **Replaced** by hosted open-model APIs (OpenRouter) on public data for development, and booked school GPU slots for large runs | §2 |
| Research workstream: WebNLG/2Wiki ablations, method suite, plan backlog item "bring the method-evaluation code into the repository" | Plan §7, experiments register | **Removed** from the plan. The results stay in the 27 October report as history. Method comparisons now run only on drilling documents, inside the GraphRAG pipeline | §5 |
| Portability runs on one or two other public domains as a deliverable (D-29) | Spec §1.3, §6.5, plan M7 | **Removed** as a deliverable. The ontology stays a user input and the synthetic fixture stays as a check; other domains are optional later work | §5, §6 |
| Twenty-week, 720-hour plan with Student A/B/C roles and the M0–M7 milestones | Plan §1–§3 | **Replaced** by a weekly plan, data/backend/frontend roles and new milestones | §12 |
| Detailed weekly written reports (D-35 process) | Plan §6 | **Replaced** by a weekly 30-minute check-in, group-chat updates every few days and a short slide plan | §12 |
| Production-operations depth (RPO/RTO, runbooks, 10–20-user envelope) as near-term work | Spec §11, plan M6 | **Shortened** to targets for the second semester; governance features of the application (versions, audit, corrections) come first | §5 |

New in version 3.0:

- object storage for raw files;
- a vector store and embedding model;
- a parent/child chunk ID scheme linked across stores;
- VLM page parsing;
- multi-page table handling;
- ontology injection points and verification;
- a glossary and abbreviation area;
- review by exception;
- a model endpoint that switches between a hosted open model and a local one;
- a cost and token budget per run;
- an end-user chat with citations.
