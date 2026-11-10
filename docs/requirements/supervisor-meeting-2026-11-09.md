# Supervisor meeting, 9 November 2026 (digest)

**Kind:** input to the [project specification](../PROJECT_DESIGN.md) · **Recorded:** Teams transcript, 54 minutes, 9 November 2026 · **Present:** MSc. Nguyen Anh Tuan (VPI supervisor), Thai Huu Tri, Nguyen Le Hung, Tran Quang Khai

This digest paraphrases the meeting. The transcript was produced automatically from Vietnamese speech, and Tri's microphone cut out for much of the first half, so several of his answers are lost; items whose meaning is uncertain are marked *(unclear)*. The raw transcript is not committed. The specification records the decisions as D-58 to D-63. The [28 October meeting](supervisor-meeting-2026-10-28.md) remains the direction; this meeting adds to it and changes nothing in it.

## 1. Purpose of the meeting

The supervisor set three questions: where the team is, what to report to the professor on **Wednesday 11 November**, and what to prepare next. The team walked through the three tracks using the [project report](../reports/PROJECT_REPORT_2026-11-09.md).

## 2. Track B: question types, routing and the graphs

**A fifth question type: reasoning about causes.** The report lists four kinds of question (lookup, lookup by date, across wells, totals over time). The supervisor added one that managers really ask: *a drilling problem happened at some point in the well; what are the likely causes?* An experienced engineer recognises which property of the drilling process is involved, reads the related documents, forms a judgement, and then verifies it. An AI that does this would let a new graduate, or someone from another discipline, follow the same reasoning. It needs several sources and real reasoning, not just a query, and the team's current data will likely not be enough to answer it. He has met questions like this in practice.

**Routing ("chia luồng").**

- The concept is not wrong and covers the questions in the current plan. He does not judge it right or wrong yet, because he has not yet given the team the full purpose of use.
- Whether the lanes should be split, merged, or chosen by rules depends on the final picture: which document types are in scope, and which main kinds of question users ask. The current lanes are built on assumed questions.
- **Keep a coordinator ("con điều phối") that routes questions.** An intelligent system connects many small blocks. Later the coordinator should use the existing data as one source among others, and also tools, MCP and connectors to outside systems, rather than one straight pipeline. That turns part of the work into AI engineering (agents), with RAG as one tool among several.
- Falling back from the event graph to plain RAG when a question does not fit is right for now. In a finished system, add a **user switch**: exact answers only (the graph), or allow fallback to approximate semantic search.

**How the graph is built.** He asked how the graph branch is built, what the LLM extracts from the text, what is stored in Neo4j, and how nodes and relationships are separated. Tri described the per-well fact graph (well node, fact groups for depth, time, measurements and identifiers; tables read by rule, text read by the LLM) and the event graph. Hung said Neo4j is still being set up, so Tri keeps the graphs locally. The supervisor said local is fine for now but wants the **node and relationship logic** to be clear. *(Much of Tri's answer is unclear in the transcript.)*

**Ontology papers.** He asked whether the papers he sent publish an ontology or a dataset. He fears they do not; Tri had checked and found none, which is why the team's question sets are written with AI.

**Models.** Tri said Qwen2.5-7B is not good enough and Llama-3.1-8B refuses to answer, and that Qwen3's thinking mode can be switched on at the cost of tokens and time. The supervisor: build the architecture so that **the model can be swapped** for a better one when infrastructure allows; a good architecture adapts to harder end tasks. He did not judge the models yet.

**Two topics in one.** He sees two parallel threads that can be combined: the domain thread (GraphRAG over drilling reports and the reasoning built on it) and the AI thread (models, plus agent engineering around them).

## 3. A simple UI, early

- He asked whether the results can be shown in a UI. Tri: not yet, because the three tracks must be connected first; he would try within a day or two.
- A UI makes review easier: one sees the source text, what was found, and how well it matches the question and the answer.
- More important, it is how to **talk to the domain experts**. They are not developers and do not care how RAG works; they need something they can touch. Put a simple UI in front of them and ask what they would ask. That also addresses the evaluation question set.
- Quality is now limited by two things outside the team: the domain ontology (some papers publish one) and the evaluation question set from end users, which is AI-written today.

## 4. Track C: storage

Hung has built the stores and loaded Khai's package into PostgreSQL; nothing else is tested yet. Before Wednesday he will test storing vectors and loading Neo4j. The supervisor: fine, report it as it is.

## 5. Track A: ingestion

- Khai described the Docling errors on the Operations Summary tables and the rebuild from coordinates. The supervisor asked whether the coordinates come from page images (pixels); Khai explained they come from the text layer of digital PDFs.
- **The pipeline chooses automatically** between Docling and the rebuild, not the user.
- The supervisor asked how the QA layers are applied in practice: by a person or by a tool? Khai: automatic self-checks for now.
- **People must review machine-made data.** Because machines produce the data, some part must be reviewed by a person. Build first, then add human control.
- **Models versus rules.** OCR and vision models may do better, at a cost in hardware or money. Khai's position, which the supervisor accepted: push the non-LLM methods as far as they go first, then turn to models.
- Khai worries about overfitting to the five AK-3 files and will try other documents. Tables over several pages and rotated pages are not done.

## 6. How to report to the professor on Wednesday

The supervisor found the current material too detailed and wordy for the professor, who follows many capstone groups.

- **10 to 15 minutes, as short as possible**; the length depends on the purpose.
- **Two or three slides of core architecture**, with each track drawn as a diagram and a brief evaluation of each module. No long text, no dense tables to read aloud.
- **State the weak points** directly, for example where quality is still poor.
- Cover: what was achieved in the last two to four weeks, the core architecture, what the input data is, what the data looks like after processing, and what the application will look like.
- **Walk one data sample through the full pipeline** on the architecture, rather than listing many experiments and numbers.
- End with what the team needs, the next steps, and the support needed.
- The professor wants to control the architecture; the supervisor wants to see a sample go through it.
- **Plan to report:** connect the three tracks, then build the application and give it to domain users to try.

## 7. Process

- Message him results whenever there is something worth showing; do not wait for meetings, or things drift.
- He sometimes comes to school; on a Tuesday the team could meet in person. Khai works and is at school on Tuesdays and Wednesdays *(unclear)*.
- He asked whether OpenRouter is funded *(unclear; the answer is lost)*. Q6 stays open.

## 8. Effect on the documentation

- Specification §13.1: D-58 to D-63 (below), §13.2 Q2 and Q6 updated, Q13 added.
- Plan: the Wednesday report and a simple UI move ahead of the rest of M2.
- Track B log: B-D32 to B-D34.

| Decision | Summary |
|---|---|
| D-58 | A coordinator routes questions; later it treats retrieval and the graphs as tools among others (tools, MCP, connectors) |
| D-59 | A user switch, later: exact answers from the graph only, or allow fallback to semantic search |
| D-60 | A simple UI early, with the three tracks connected, to review answers and to put in front of domain experts |
| D-61 | Reasoning about causes of a drilling problem is a target question type; current data is likely insufficient |
| D-62 | The architecture lets the model be swapped |
| D-63 | People review part of the machine-made data; build first, then add human control |
