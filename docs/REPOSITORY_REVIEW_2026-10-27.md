# Repository assessment and proposed next development direction

Date: 27 October 2026. Reviewed baseline: `e20395f`, with a clean working tree before this review.

This is an assessment and a proposed revision direction. It does not replace `PROJECT_DESIGN.md`, change stakeholder commitments, or authorize spending. Existing source code and published bundles were left unchanged.

**Documentation follow-through, 27 October:** specification v2.3 and plan v2.2 incorporate the review and subsequent team/user direction: domain-agnostic core, one English oil-well application, interpretation/expert-note and multilingual expansion later (D-26/D-27). The [unified progress report](reports/KNOWLEDGE_GRAPH_BUILDER_PROGRESS_2026-10-27.md) retains the project’s ingestion, method, graph and prototype results. [E9](experiments/E9-repository-review.md) records verification; runtime defects and host/budget/reviewer decisions remain open. Baseline drift observations below are historical.

## Overall judgment

The project has a credible ingestion foundation, useful provenance work, and an informative architecture prototype. The proposed system architecture is broadly appropriate for three students. The largest risks are delivering too much scope at once, mistaking development-sample results for general performance, underestimating human review, and promoting prototype shortcuts into the application.

The next investment should produce a small, complete user workflow: register a report, extract bounded claims, inspect exact evidence, make a real review decision, publish a validated revision, answer a supported question, and withdraw its source. This would resolve more uncertainty than another general ingestion expansion or a larger model alone.

Keep the modular Python application, PostgreSQL authority, immutable evidence, derived graph, constrained model output, and fixed query templates. Reduce the breadth of the first delivery and move security, evaluation, and recovery demonstrations into the early slices. Treat the broad platform as an extension path.

## Review coverage and verification

Reviewed the repository layout, stakeholder-requirement digest, design and plan, component documentation and experiment records; inspected the corpus and dataset pipelines, legacy ingestion interfaces, schemas, prototype extraction/review/publication/QA implementation, dependency configuration, and representative tests across subsystems. This was a repository assessment, not a line-by-line formal audit or penetration test.

Executed in the existing repository environment:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m unittest prototype.test_ontology
```

Results: **128 main tests passed in 17.191 seconds; four prototype ontology tests passed.** The cache-backed PDF regression ran without a reported skip. Docling emitted warnings about clamping out-of-bounds coordinates in cached material; the regression still passed. These warnings should remain visible in ingestion-quality investigations.

Also ran isolated temporary-fixture probes for export interruption, duplicate CSV headers, invalid calendar dates, and dataset validation ordering. Findings below distinguish these reproductions from static code observations. No new model calls, service startup, downloads, paid resources, or publication commands were used. Historical E4/E8 model and corpus results were inspected, not rerun.

## What exists and how it fits together

| Area | What is implemented | Assessment |
|---|---|---|
| `corpus/` | SQLite catalog; originals stored by SHA256; format detection; per-page OCR analysis; segmented conversion; passage/table chunks; validation; resume and export | The best starting point for application document ingestion. Service concurrency, publication, and security still need work. |
| `datasets/` | Mapping-driven CSV/XLSX/JSONL import, ZIP member access, typed fields, checks, row provenance, graph rules | A useful deterministic complement to extraction. It must feed the same evidence/claim contracts as documents. |
| `ingestion/`, `graph/bsee.py` | Earlier reproducible PDF/BSEE pipelines and linked graph | Valuable regression references. Avoid maintaining two independently evolving product paths. |
| `prototype/` | Local model extraction, validation, PostgreSQL reviews, Neo4j generations, bounded cited QA | Demonstrates integration feasibility. Its localhost trust model and persistence shortcuts must be replaced during promotion. |
| Gold/evaluation | Ingestion fixtures, 41 development facts, 31 development questions, experiment records | Useful development evidence; insufficient for independent domain or release claims. |
| Secure application | Design, requirements, gates and planned workflows | Authentication, production role enforcement, review UI, durable job orchestration, migrations, restore and operational ownership remain delivery work. |

The current data path is roughly:

```text
Documents -> corpus SQLite + immutable originals -> chunks/tables/quality reports
Datasets  -> configured importer -> typed records + row-backed nodes/edges

Separate AK-3 prototype:
legacy chunks -> local LLM -> validator -> PostgreSQL candidates/reviews
             -> Neo4j generation -> fixed-query QA with citations
```

The application is not yet an integration of the new corpus/importer paths with the prototype. That joining work is a major next milestone, not a small UI addition.

### Foundations worth preserving

- Source and artifact hashes, explicit provenance, offsets, page regions and table context make answers inspectable and enable reliable reprocessing.
- The implementation separates deterministic structured-data import from probabilistic document extraction.
- E4 records wrong answers, missed facts, scorer changes and oracle review openly. E8 reports the interrupted run and OCR losses rather than hiding them.
- PostgreSQL as authoritative accepted knowledge and Neo4j as a rebuildable projection is a sound recovery boundary.
- Constrained output and fixed parameterized queries keep model mistakes away from database commands.
- Local inference, a small initial workload and a single host are consistent with the resource constraints.

## Highest-priority findings

Priorities below mean: P1 before promoting the affected component into a team service; P2 during the next delivery slices; P3 maintenance improvement. Prototype-only findings do not imply an internet-exposed deployment exists.

### P1: Publication can expose missing or incomplete data

**Corpus export replacement is not an atomic directory swap.** `corpus/catalog.py:215` moves the current destination to `.old`, then renames the staged directory into place. There is an interval with no destination; interruption after the first rename leaves it missing. A temporary-fixture probe injected that failure and observed `published_exists=False`, with the old data retained under `.old`. The dataset importer uses the same two-rename pattern.

Use immutable release directories, validate and close all files, then switch a small publication pointer in a transaction or via an atomic file replacement. Readers must resolve and pin that version once. Never overwrite an accepted export name. A completed staging directory is useful, but not sufficient to make its replacement atomic or crash-durable.

**Dataset validation happens after replacement in the CLI.** `run_import()` publishes its staged result before the CLI calls `validate_bundle()`. A valid mapping without `key` can emit duplicate `record_id` values: a probe imported two `A` rows successfully, then post-publication validation reported `duplicate record_id`. On replacement, that can retire a previously good bundle before discovering the new bundle is invalid.

Validate the staged bundle before any pointer change; enforce record identity independently of optional natural keys. Preserve the existing accepted version on failure.

**Prototype graph checks do not prove completeness.** In `prototype/kgproto/extract.py:135`, the check is essentially “every existing claim has evidence, and nonempty accepted input produced a nonempty graph.” If one accepted claim fails its `MATCH` on a missing chunk, another can still project and the checks can pass. This is a static code finding, not a live Neo4j reproduction.

Freeze the accepted revision set for a generation. Compare expected distinct claim IDs and evidence IDs with actual projected IDs, plus ontology/input digests. Write a completion marker and verify it on every answer before serving the pinned generation. Activation must also check that the accepted revision used for the build is still eligible.

### P1: Localhost prototype trust is not application authorization

`prototype/kgproto/api.py` has no authentication/authorization dependencies, and `Decision.actor` is supplied by the caller. That is acceptable only within the explicitly trusted prototype boundary. In the application, derive the actor from authenticated identity, enforce roles on every operation and evidence route, and reject decisions on ineligible candidates at the service and database levels.

Keep the prototype's documented throwaway credentials isolated from deployment. Its fixed read queries are a positive control; a driver's `READ` routing mode should not be treated as database permission enforcement. Neo4j's documented RBAC capabilities depend on edition; verify the selected pinned version and budget before promising separate database roles. Current official documentation assigns the full authorization functionality to Enterprise and only limited user management to Community. [Neo4j documentation](https://neo4j.com/docs/operations-manual/current/authentication-authorization/).

### P1: Safe file handling needs an enforced process boundary

Signature detection and compressed-size/page limits are useful. They do not cover all expensive work: Office containers are opened before an expanded-size budget is enforced, image dimensions need explicit limits, and dataset downloads currently have no streaming byte cap. The 2 GiB ZIP-member allowance is a size check, not a complete memory or CPU budget; XLSX members can also be read fully into memory.

For a service, parse untrusted inputs in a restricted process/container with bounded CPU, RAM, runtime, temporary disk and output size, read-only original evidence, and no network. Apply preflight limits before conversion. Do not give parsing workers database-administrator or host credentials.

Remote acquisition should be an operator-controlled step. Both corpus and dataset downloaders check the final host after `urlopen()` has already followed redirects. That rejects the final response too late to prevent the outbound request. Before exposing remote URL ingestion, enforce HTTPS/host/address/port policy on every redirect before requesting it, reject private/link-local targets as appropriate, and apply network egress policy. Redirect/DNS exploitability was not tested in this review.

### P2: Cache identity is weaker than the reproducibility claim

`corpus/config.py:60` includes config, a manually maintained pipeline version, Docling/core versions, and OCR model digests. `engine_fingerprint()` also computes OCR runtime versions, but callers pass only `ocr['models']` into the processing fingerprint. Changing an OCR runtime can therefore reuse output under the same key. Pipeline code and layout/table-model identity are also not fully represented.

Separately, the process-local converter cache is keyed only by `(kind, mode)` in `corpus/process.py:56`; repeated library calls with different settings/model roots in one process can reuse an earlier converter.

Define an explicit processing version and complete dependency/model manifest, and include the output-affecting digest in cache eligibility and converter reuse. Keep per-source identity explicit. Distinguish semantic output identity from execution metadata such as timestamps and timings; byte-identical complete manifests are not a realistic goal when they contain those fields.

### P2: Validation can silently lose or misinterpret evidence

Duplicate CSV headers are converted with `dict(zip(header, row))` in `datasets/readers.py:76`; XLSX uses the same approach. A probe with `code,depth,depth` and `A,100,999` returned only `depth=999`. Reject empty/duplicate normalized headers or require explicit positional mapping.

The prototype date validator accepts `2016-02-31` if the corresponding words occur, and month `13` raises `IndexError`. Both were reproduced. Parse calendar dates before checking evidence and make invalid model output a bounded candidate rejection.

More generally, finding a number in a quote does not establish the correct subject/property/unit/context. The same row can contain several depths, diameters or temperatures. Keep original and normalized units, measured-depth versus vertical-depth distinctions, planned versus actual state, and conditions. Add negative fixtures with a correct number assigned to the wrong column or well. Exact quote membership is a necessary integrity check, not proof of entailment.

### P2: Evaluation presently supports a feasibility conclusion

E4's latest reported extraction result is 0.97 precision and 0.68 recall on 41 development facts. The reviewed end-to-end result is 19/31 questions. The 31/31 QA-layer score explicitly allows honest no-answer when extraction missed the fact. These are different measurements; the latter is not 100% useful answer accuracy.

The oracle reviewer has access to gold labels and is not evidence about actual reviewer quality, speed or fatigue. Repeated prompt changes on the same slice make that slice development data. Freeze a separate, deduplicated, document-level held-out set **before** the next prompt/model comparison, reversing the order suggested near the end of E4.

The QA scorer primarily compares returned values, while extraction matching includes more fields. Strengthen answer scoring to include subject, property, units, qualifier, depth/context, evidence support and missing/extra items. The injection graph fingerprint counts nodes and relationships; equal counts do not prove properties or edges are unchanged. Use exact expected state/digests for adversarial fixtures.

### P2/P3: Development and deployment contracts need consolidation

- No checked-in CI workflow was present. Add a deterministic fixture suite on each PR, then a separate explicit host/GPU integration job. Include the prototype ontology suite in routine checks until it is promoted.
- Some tests assert documentation phrases; these should not substitute for behavioral contracts. Protect publication, evidence, permissions, retry and withdrawal behavior first.
- The lock is a Windows CPU environment snapshot. The documented manual Linux installation path is not reproducible deployment. Produce a separately tested Linux/GPU lock and pinned image inventory when the host is known.
- `corpus/validate.py` resolves schemas relative to the checkout, while setuptools discovers `src` packages without a schema data declaration. Editable use works; a standalone wheel is not established. Package schemas with the application and test an installed wheel outside the checkout.
- `prototype/kgproto/db.py` runs schema DDL on each connection. API calls do not consistently manage connection lifetime. Promote to migrations, a bounded pool, transaction-scoped review/publication operations and database constraints.
- Keep old ingestion as a frozen compatibility/regression path. Extract shared proven logic behind stable interfaces rather than expanding both paths or doing a large rewrite.
- `.gitignore` covers the known private-original folder but not every possible secret/private-data location. Add secret scanning and a clearly designated ignored private-data root. Ignoring files is an accident-prevention measure, not access control.

## Scope and planning changes

The design already has good ideas about trust boundaries and failure behavior. The plan needs fewer simultaneous obligations and clearer evidence of completion.

The reviewed baseline had a 720-hour illustration (576 planned plus 144 reserve) that had absorbed second-domain and expert-note work without re-estimation. The current team decision removes that delivery scope and starts in English. Re-estimate the remaining oil-well profile, generic-core interfaces, reliability, review and deployment work; keep the historical hours as an illustration until capacity is confirmed.

There is also current-state drift: design section 3.2 says no graph-extraction/QA benchmark exists, despite E4. It should say there is a development prototype benchmark but no independent release benchmark. Other gap descriptions still mix legacy publication limits with the newer corpus pipeline. These discrepancies weaken the value of the designated source of truth.

### Proposed first delivery boundary

Under the team’s current one-profile, English-first direction, define the assessable product as:

> A small internal pilot on a domain-agnostic core that answers an agreed English oil-well question catalogue from reviewed claims, with exact evidence, conflicting values, cross-source identity and known coverage gaps.

Start with roughly 5–10 representative English well reports and 5–8 supported oil-well question intents as an integration workload, not as a replacement for the larger held-out acceptance sample. Choose reports for content diversity rather than page count. Include prose, born-digital tables, one poor scan, cross-source aliases, a revised value and a conflict. These workload numbers are proposed engineering limits, not measured capacity.

Deliver one `oil_wells` profile. Move ontology, well identifier/alias rules, units, MD/TVD/planned-actual constraints, extraction examples and trusted query templates out of generic workflow code. Check the configuration boundary using a synthetic non-well vocabulary fixture. Defer real second-domain delivery, subsurface interpretation and expert-note workflows; preserve their design as extension points.

The AK-3 reports and BSEE records do not by themselves demonstrate the same real-world entity across sources. Select an approved report for a well represented in the structured dataset, or use clearly labeled synthetic fixtures for the contract and disclose the remaining real-data gap. Do not fabricate a linkage between unrelated wells.

Defer additional languages/formats, fine-tuning, autonomous agents, open-ended text-to-Cypher, large graph visualization, multi-tenancy, high availability and a dedicated vector service until a concrete supported workflow needs them. Keep citation integrity, access checks, withdrawal and independent recovery in the first internal-service release.

Separate two acceptance packages: a public-data technical demonstrator and a private-data internal pilot. The latter requires approved host/data boundaries, identity, ownership, restore and access evidence. If those dependencies do not arrive, the demonstrator can still be delivered honestly.

## Recommended architecture

```text
Browser -> HTTPS proxy -> FastAPI application
                           |-- authentication / policy / audit
                           |-- review and publication workflows
                           |-- bounded question service
                           |
                           +-> PostgreSQL: authoritative entities, revisions,
                           |               reviews, jobs, publication state
                           +-> artifact volume: immutable originals/bundles
                           +-> Neo4j: completed, versioned graph projection

Worker -> PostgreSQL job leases -> isolated document parser / dataset adapter
                               -> local LLM admission queue
                               -> candidate validation and persistence
                               -> graph build and completion checks

Controlled acquisition -> approved packages/models/public inputs
Independent backup    -> PostgreSQL + referenced evidence + tombstones
```

This is a modular application with separate execution processes, hosted initially with Compose on one approved machine. The present design is close to this; the main recommendation is to implement its invariants on a small workflow before adding breadth.

### Ownership and contracts

PostgreSQL owns identities, permissions, source lifecycle, ontology versions, immutable claim revisions, reviews and publication state. Artifact storage owns exact evidence bytes. Neo4j owns no irreplaceable decisions. A per-corpus SQLite catalog may remain a local processing implementation detail; it must not become a competing application authority for retirement, roles or accepted knowledge.

Keep semantics in the versioned `oil_wells` profile and adapters; the core stores generic entities, claims and evidence. The existing AK-3 prototype is well-specific, so profile-driven extraction/query dispatch is remaining work. See [specification §4.4](PROJECT_DESIGN.md#44-core-and-domain-profile-boundary).

Use narrow module boundaries: `sources/evidence`, `ontology/registry`, `extraction/validation`, `review/publication`, `query`, and `operations`. Do not turn these into independent network services. Reuse existing ingestion through adapters with explicit return contracts.

Define and test these records before parallel application development:

| Record | Minimum important identity/context |
|---|---|
| Source version | Source ID, version ID, original SHA256, permission/classification, lifecycle |
| Processing bundle | Source version, processing/config/model manifest, output digests, coverage |
| Evidence | Bundle ID, exact chunk/row/span locator, page/region or dataset snapshot/member/row |
| Entity | Opaque canonical ID, type, scoped external identifiers, language-tagged names and aliases |
| Claim revision | Subject, predicate, typed object/value, units, conditions/time, claim kind, evidence, ontology version |
| Review | Authenticated actor, eligible revision, decision, reason, time, expected revision |
| Publication | Generation, exact accepted revision set/digest, completed projection marker |
| Withdrawal | Source/revision IDs, immediate serving block, dependent artifact/cache/purge policy |

A logical claim, its source evidence, and its accepted revision are different identities. Rechunking should not silently invalidate a citation to an earlier accepted bundle. A reviewed interpretation is not thereby an observed fact; preserve epistemic kind separately from workflow status. Model confidence, source authority and reviewer acceptance also mean different things.

### Jobs and graph publication

Start with a PostgreSQL job table and one worker. Lease work in short transactions; parse/infer outside those transactions; use heartbeat, attempt limits and a fencing token. Keep idempotent stage identities. `FOR UPDATE SKIP LOCKED` can support competing queue consumers, but is not a general consistent-read strategy. [PostgreSQL documentation](https://www.postgresql.org/docs/current/sql-select.html).

Use either a durable generation-build job created transactionally with a frozen revision set, or an outbox for committed projection requests. Avoid implementing per-claim incremental graph updates and full-generation reconciliation simultaneously without a demonstrated need. Initially serialize publication and retain the previous validated generation.

Keep small per-generation projection copies at first; measure build duration and disk growth before optimizing to deltas. Domain labels describe semantics, not an authorization boundary. Scope every query and cache by workspace, publication and access policy.

### Question answering and proving graph value

Implement explicit structured lookup first, then let the local model map natural language into a validated intent/parameter schema. The model cannot select arbitrary queries or publish data. Return deterministic values/tables with citations; generated wording is optional.

Add a minimal English passage-search baseline on the same oil-well corpus and evaluation questions. PostgreSQL full-text search is a reasonable first baseline; add local embeddings only if measured English retrieval failures justify them. Compare three conditions where practical: passage retrieval, accepted-claim lookup, and bounded graph traversal. Keep corpus, test set and model conditions comparable.

A graph earns its extra operating cost when it improves identity-aware joins, planned/actual comparisons, well-related traversals and conflicting values. Single-property lookups alone do not demonstrate that advantage. Retain Neo4j for the capstone graph work, but keep a query boundary and make its operational burden visible. Domain modules do not require separate database servers.

## Security priorities

Local hosting controls where computation occurs; it does not establish that the application is secure. The next threat model should name actual actors and routes: anonymous browser, reader, reviewer, administrator, malicious file author, compromised parser, model output and host operator.

Before the first shared staging demo, implement server-derived review identity, role checks on direct API and evidence requests, private model/database interfaces, request limits and safe error handling. Before sensitive material enters, demonstrate parser isolation and blocked egress, log redaction/retention, protected backups and approved data handling. Before pilot acceptance, demonstrate immediate withdrawal and restore-time suppression of retired content.

Treat document text and model output as untrusted across every language. The defense is bounded capabilities, independently validated contracts and authorization in code; a prompt saying “ignore instructions” cannot be the trust boundary. This follows OWASP's guidance on least privilege, untrusted content and adversarial tests. [OWASP prompt injection guidance](https://genai.owasp.org/llmrisk/llm01-prompt-injection/).

Avoid blanket claims such as “injection safe” based on two prompts. Test unauthorized reads and writes, stale review decisions, wrong evidence ownership, malicious file references, log leakage, partial generations and source withdrawal directly. Keep a small residual-risk register tied to the chosen deployment and edition.

## Cost and resource model

No verified budget, host allocation or provider quote is available. Do not invent a monthly hosting number. The main near-term cost is team and expert time; local model serving avoids per-token vendor fees but still consumes shared hardware, storage, electricity and maintenance.

| Cost | How to estimate/control it |
|---|---|
| Engineering | Estimate the remaining slices and actual integration work. Reforecast weekly from completed acceptance behavior. Keep contingency separate from added features. |
| Review/annotation | Measure candidates/page and median minutes/candidate, plus corrections, source navigation and disagreement adjudication. Track useful accepted claims per reviewer-hour. |
| Inference | Record calls/pages, input/output tokens, prompt reuse, failure/retry rate and GPU hours per accepted claim. Cache identical stage inputs; reserve interactive capacity. |
| Parsing/OCR | Report born-digital, scanned prose and scanned form costs separately. Choose an evaluated English OCR configuration; retain Vietnamese measurements for later scope; rerun only affected sources/configurations. |
| Storage | Measure originals, parser output, caches, retained bundles, model files, graph generations and backups separately. Set retention and safe cleanup before increasing corpus size. |
| Optional cloud | Approved public/synthetic input only; hours × quoted rate plus storage/transfer. Hard budget and idle shutdown. No always-on GPU dependency. |
| Operations | Named time for updates, access changes, backup checks, restore practice and handover. Include any license/edition needs explicitly. |

Illustrative review burden, **not a forecast**: 5,000 pages × 3 candidates/page × 30 seconds/candidate = **125 reviewer-hours**, before corrections and annotation. That is substantial relative to the plan's 576 delivery hours. Measure the actual values before committing to a 5,000-page published knowledge base.

Prefer the existing school allocation, one eligible quantized model at a time, CPU parsing and separately scheduled extraction. Choose a larger model only if held-out useful-answer coverage or review savings justify its latency/memory cost. Exact GPU fit and concurrency remain host benchmarks, not assumptions derived from parameter count. Do not buy hardware for the current prototype.

The E8 English-form failure makes an English OCR comparison on required well pages a priority. Use the E5 RapidOCR/VietOCR English results to shortlist configurations, then check real dense forms, tables and degraded pages before freezing the profile. Existing Vietnamese OCR results stay as completed research; further Vietnamese quality work is deferred.

## Proposed delivery sequence

These are acceptance-sized slices, not a new promised calendar. Re-estimate their remaining work against actual weekly availability. Existing M0–M7 can remain the reporting framework; split their backlog into these demonstrable outcomes and bring controls forward.

| Order | Slice | Evidence required to close |
|---|---|---|
| 0 | Product/data/host decision record | Named users/reviewer, supported questions, one English oil-well profile, core/profile boundary, approved corpus, deadline/capacity, host permissions, spending ceiling and pilot owner |
| 1 | Stable evidence and publication boundary | Corpus and dataset adapters share versioned evidence; staged validation; immutable release pointer; interrupted replacement cannot remove accepted data |
| 2 | Small extraction/review slice | One prose passage and one table through independent validation, real reviewer and source viewer; source units/context preserved; held-out data frozen first |
| 3 | Durable registry and accepted knowledge | Scoped identifiers/aliases, revisions and migrations; review transaction checks; conservative cross-source link; no fuzzy automatic merge |
| 4 | Validated graph and bounded QA | Exact projected-set checks, completion marker, generation pinning; 3 initial intents with citations; wrong/missing/unsupported cases demonstrated |
| 5 | Profile portability and graph value | Synthetic configuration fixture loads/validates/dispatches without core edits; English oil-well QA compared with a passage baseline; measured cross-source identity |
| 6 | Pilot hardening and handover | Route/role, retry/crash/withdrawal tests; measured host workload; blocked-internet operation; independent restore; user tasks; named operator |

Roles should contribute to the same slice: data owner supplies frozen evidence/gold, backend owner implements the transaction/contracts, application/operations owner makes it inspectable and runs the staging checks. Avoid three long-running subsystem branches that only meet near the final demo.

### Immediate backlog, in order

1. Record the initial question catalogue and resolve the scope/hardware/reviewer unknowns already listed in the design. Distinguish proposed assumptions from supervisor decisions.
2. Freeze an independent document-level evaluation split before further E4 prompt changes. Define the full claim/answer matching rubric and reviewer-time measurements.
3. Fix publication staging/activation, duplicate-header loss and date validation; add targeted regression cases for these concrete failures.
4. Define the small shared evidence/entity/claim-revision contract and adapt one corpus document plus one synthetic dataset row to it.
5. Add deterministic CI, explicitly including prototype ontology checks; separate optional expensive/cache/GPU checks from mandatory fixtures.
6. Implement authenticated review with a minimal evidence screen and one real reviewer session. Measure corrections and time.
7. Promote generation building with exact expected-set verification and crash cases, then deliver three cited question intents.
8. Run the controlled extraction/model/OCR comparisons and baseline retrieval evaluation; use the evidence to decide the next expansion.

The next milestone demo should be: **a real reviewer accepts a claim from a versioned report; a supported question returns that claim with exact evidence; an interrupted replacement leaves it available; withdrawing the source prevents it from being served.** That is a useful integration and security milestone on which the rest of the platform can build.

## Documentation changes to make when the direction is agreed

Maintain specification v2.3 as the source of truth: reusable core plus one English oil-well application, explicit profile boundaries and deferred FR-17/multilingual delivery. Keep demonstrator/pilot acceptance and store/publication invariants. Re-estimate the narrowed scope and remaining defects. Work items should have requirement IDs, owners and observable acceptance examples.

Keep experiment records factual and immutable enough to interpret old runs. Add an evaluation manifest with source split, gold revision, rubric, model/prompt/runtime hashes and scorer version. Mark oracle-review scores separately from human-review scores. No new production claims should be inferred merely from the passing unit tests or the existence of this review.
