# Stint report: 10 to 27 November 2026

**Status: draft.** The stint ends on 27 November; this report is updated until then.<br>
**For:** MSc. Nguyen Anh Tuan · **From:** Thai Huu Tri, Nguyen Le Hung, Tran Quang Khai<br>
**Follows:** the [9 November meeting](../../requirements/supervisor-meeting-2026-11-09.md) and the [project report of 9 November](../PROJECT_REPORT_2026-11-09.md)

## 1. In short

- On 9 November you asked for a **coordinator** that routes questions, the three parts **connected behind a simple application** that domain experts can touch, and **reasoning questions** as a target.
- This stint we designed and built all three. There is now one application: a person types a question about the drilling reports and sees the answer, a label that says how far to trust it, and the page or the activities it rests on.
- **It has run from end to end with the real AI model.** On one machine, starting from the public PDF reports: the reports were read, loaded into the stores (PostgreSQL and Neo4j), and the application answered from them behind a password, with our own copy of the model (Qwen3-8B). Our earlier baseline result came out the same, answer for answer.
- **Three wells are loaded:** the end-of-well reports of AK-3, 56-32 and 68-32, and AK-3's daily reports. Each well has its own page, and every question people ask is kept and can be downloaded as a test set.
- A total such as "hours of non-productive time" is **calculated by code and never written by an AI**, so it cannot be a guess.
- A question about **the cause of a problem** gets an answer in parts. We measured this for the first time: the system finds the cause the reports state, in the report's own words, but it also lists nearby events as causes. It is not ready to show as a finding (§10).
- **Before putting people in front of it, we had the design, the code and the security reviewed,** and fixed what was found (§9).
- **What is left needs people or money, not code:** a server others can reach, a graphics card for the one long measurement, and experts to try it (§12).

## 2. What you asked for, and where each stands

| You asked on 9 November | State | What exists |
|---|---|---|
| A coordinator that routes each question; later it uses tools and connectors | **Built**; its full measurement needs a graphics card | One AI call understands the question; code then decides where to look. Each place it can look has the same interface, so it can later be offered as a tool |
| A switch for exact answers only | **Built** | "Verified data only" in the application |
| A simple application early, on the connected parts, for domain experts | **Built, connected, and run with the real model**; not yet on a server others reach | A backend service and a web application, written for people who are not developers, reading the stores |
| Reasoning about the causes of a drilling problem | **Built and measured once:** good in one part, not ready in another | A fourth place to look, for causes (§10), tried on twenty trial questions about AK-3 |
| The model can be swapped | **Built** | One small file names a model and where it runs. One command checks that model and measures it on our questions |
| People review part of the machine-made data | **Built, first form** | Every answer can be marked right or wrong. A page lists every question asked with its marks, and downloads them as a test set |
| State the node and relationship logic of the graph | **Written down** | §6 below |

## 3. The system now

![The four parts of the system and who owns each](figures/architecture.svg)

**Figure 1. The four parts and who owns each.** All arrows work today, on one machine. The engine can read the same data from files or from the stores.

| Part | What it does | State at the end of this stint |
|---|---|---|
| 1. Reading the reports | Turns a PDF into passages, tables and forms, each with a stable ID that points back to its page | A package for the demo, built by one command: the end-of-well reports of AK-3, 56-32 and 68-32, AK-3's four daily-report attachments and its non-productive-time report (302 pages, about 1,430 passages). It was built again from nothing on a second machine. New reading options exist; their effect is still to be measured |
| 2. Stores | Keeps passages and their search vectors in PostgreSQL, and the knowledge graph in Neo4j | One command loads a package and checks every step: the passages, a search vector for each, 161 daily activities, 207 well facts. Search by meaning runs inside the database. The question log is in PostgreSQL. The stores restart by themselves after a failure. On our own machines; a shared server is next |
| 3. Answering engine | Understands the question, looks in the right place, answers, and checks the answer | The coordinator and its four places to look, reading files or the stores. With the real model: the earlier baseline is reproduced, and answers about causes are measured (§10). A bench checks any model and runs the whole measurement in one command |
| 4. Application | Lets a person ask, read the answer, check its sources and mark it right or wrong | Backend service and web application run together behind one password, as containers that start with one command. Besides asking: a page per well, and a page of the questions people asked. It tells the user plainly when it is busy or when something is down |

## 4. How a question is answered

![How a question is answered, step by step](figures/question-flow.svg)

**Figure 2. The path of a question.** Blue boxes use the AI model. Green boxes are plain code. The AI is used at most twice: once to understand the question, once to write an answer. It never chooses where to look, and it never writes a query that runs. A question about a cause takes the same path: code finds the problem and gathers what surrounds it, and one AI call writes the answer in parts (§10).

1. **Understand.** One AI call returns the kind of question, the reports it concerns and, for a total over time, a small plan (for example: total hours, non-productive, August). Code reads the well name and the dates itself.
2. **Choose where to look.** Code decides from a fixed table. If the first place has nothing, it falls back to the report text.
3. **Produce the answer.**
   - *A total over time:* code runs the plan on the daily activities and reports the result. No AI is involved, so the number cannot be mistyped.
   - *Anything else:* one AI call writes the answer, using only the facts and passages it was given.
4. **Check.** Code confirms that every value in an AI-written answer really appears in the text that was read. If it does not, the answer is not shown as confirmed.

**"Verified data only".** With this switch on, the report text is not searched and no AI writes from it. The answer comes from the daily activities or the checked facts, or the application says that the verified data holds no answer.

| Kind of question | Example | Where it looks | Who produces the answer |
|---|---|---|---|
| A total over a period | How many hours of non-productive time did AK-3 have? | Daily activities | Code |
| A fact about a well | What total depth did well AK-3 reach? | Well facts, then report text | AI, then checked by code |
| What happened on one day | What was the mud weight on AK-3 on 20 August 2016? | Report text of that well and day | AI, then checked by code |
| A comparison between wells | Which of AK-3, 56-32 and 68-32 was drilled deepest? | Well facts and report text of each well | AI, then checked by code |
| The cause of a problem | What caused the stuck pipe on AK-3 on 20 August 2016? | The daily activities around the problem, and the report text of those days | AI, in parts; code removes any cause without a source |

## 5. Four questions, as the application shows them

### A total, calculated by code

![A calculated answer with its timeline](figures/app-calculated.png)

**Figure 3.** "How many hours of non-productive time did AK-3 have?" The answer, 115 hours, carries a green label: *Calculated from the reports*. On the right, each row is one day from midnight to midnight, and each amber bar is an activity the reports marked as non-productive. Hovering a bar says what happened; the list below it is grouped by day and can be opened in full. The end-of-well report's own summary table also gives 115 hours.

### A fact, written by AI and checked

![An AI-written answer with its source highlighted](figures/app-ai-answer.png)

**Figure 4.** "What total depth did well AK-3 reach?" The label is blue: *Written by AI, checked against the reports*. The passage the answer comes from is listed first and flagged, and the value is highlighted where the report writes it. The reader can open the whole page. In this screenshot the answer itself is a prepared example; the report text, the page and the highlight are real.

### No answer

![The application saying it found no answer](figures/app-not-found.png)

**Figure 5.** With "Verified data only" on, a question about a well that is not loaded gets "Not in the verified data", advice on what to try, and the closest report text. The system says it does not know instead of guessing.

### The cause of a problem

![An answer about a cause, in parts, with the activities around the problem](figures/app-cause.png)

**Figure 6.** "What caused the stuck pipe on AK-3 on 20 August 2016?" The application first shows the problem it found in the daily activities: 66 hours of non-productive time from 20 to 23 August at 176 ft. Then, apart: what the reports say caused it, with the report's own words; other possible factors, in a dashed box marked *Possibility, not a finding*; and, below what is shown here, what a real judgement would still need. On the right are the activities before, during and after the problem. In this screenshot the answer is a prepared example; the problem, the activities and the report's words are real.

![The application asking which problem is meant](figures/app-cause-which.png)

**Figure 7.** When a question fits several problems, the application asks which one is meant instead of guessing.

## 6. The knowledge graph

![The knowledge graph: one graph, two regions, joined at the well](figures/knowledge-graph.svg)

**Figure 8. One graph, two regions, joined at the well.** Every fact and every activity points to the passage it was read from, so any answer can be traced to a page.

| Region | Built from | By | State |
|---|---|---|---|
| Activities (amber) | The operations tables of the daily reports and the non-productive-time report | Code only, no AI | 161 activities on 27 days for AK-3, in Neo4j |
| Facts (blue) | Tables of the end-of-well reports by fixed rules, and their text by an AI, then checked | Code, and AI then code | 207 checked facts for 5 wells, in Neo4j beside the activities; 202 of them point to a passage in the store |

The two regions answer different questions. Activities answer "how many hours" and "on which days". Facts answer "how deep" and "which casing". A relationship that the report does not state, such as a cause, is never stored.

## 7. The application

![The guide that opens on a first visit](figures/app-guide.png)

**Figure 9.** The guide that opens on a first visit. It can be closed at once and reopened from "How it works".

It is written for people who read drilling reports, not for developers. Nothing on screen names a part of the system.

| A user can | How |
|---|---|
| Ask in plain English | One search box, with example questions to click |
| See how far to trust an answer | A coloured label: calculated, written by AI and checked, written by AI and not confirmed, or no answer found |
| Check the answer | The evidence beside it: a timeline of activities, the report text with the answer highlighted, the key facts; any source opens its page, as an image of the printed page when one has been made |
| Ask what caused a problem | The answer comes in parts (Figure 6); if several problems fit, the application asks which |
| Get an explanation | A small "i" beside each term, shown on hover or tap |
| Ask for verified data only | One switch |
| Say it is wrong | "Was this answer right?" Yes, or No with a note. Both are saved |
| Look up a well | A page per well (Figure 11) |
| See what people asked | A page of every question and its marks, with a download (Figure 12) |
| Learn how it works | A guide on first visit and from the top bar |

Every question, how it was answered, and every right or wrong mark is logged in the database, also when a question could not be answered. When domain experts use it, that log gives us their real questions.

![The waiting screen, with its steps and a stop button](figures/app-waiting.png)

**Figure 10.** While the system works, the screen says what it is doing and how long it has taken, and the question can be stopped. An answer takes seconds on a graphics card and minutes without one, so waiting has to be bearable. If several people ask at once, or the system is down, the application says which, in plain words, and offers to try again.

The application was checked for use by keyboard and by screen reader software with an automated tool, on every screen at two sizes, and the 315 points it raised are fixed. It also works on a phone.

### A page for each well

![The page of well AK-3: facts, timeline and reports](figures/app-well.png)

**Figure 11.** The page of well AK-3. On the left, what the reports say about the well, in plain words with units, planned beside actual; each value opens the page it was read from. On the right, every day of reports as a bar from midnight to midnight, with non-productive time in amber. It also shows a fact we know to be wrong (§9): the page shows the data as it is, which is how such errors get found.

### The questions people asked

![The page listing the questions people asked](figures/app-questions.png)

**Figure 12.** Every question asked, the answer it got, and how it was marked. The button downloads the selected questions as a file with a place for the right answer to each. Once an expert fills those in, the file is a test the system can be run against. This is how the application turns use into the real questions we are waiting for. The entries shown are examples.

## 8. What each of us built

### Tri: answering engine and application

- **The design of the second build**, written into the specification and the plan: the coordinator, the knowledge graph's structure, the reasoning questions, the application.
- **The coordinator**: one AI call to understand the question; routing, fallback and "verified data only" in code.
- **Four places to look, behind one interface**: report text, well facts, daily activities, and the causes of a problem. The shared interface is what lets them be offered as tools later.
- **Totals reported by code.** The daily-activities path returns the number itself, so no AI retypes it.
- **Answers about causes**: code finds the problem and gathers the activities and report text around it; the AI answers in parts; code removes any cause whose source it cannot find. Twenty trial questions, in two sets, each written and fixed before it was run; the first measurement is in §10.
- **The well facts exported as a graph**: 207 checked facts for 5 wells, after a stricter check removed nine wrong ones (§9).
- **A bench for models**: a small file names a model and where it runs; one command checks it (does it answer in the required form, with reasoning switched off, and does our longest prompt fit), one runs every measurement and can resume if interrupted, one prints the comparison. It works with any server that speaks the common interface, on our own machine or rented.
- **The web application** (§7), with 178 automated tests: the answer screens, the cause screens, the page view, a page per well, the questions people asked, and plain messages when the server cannot be reached.
- **The first runs with the real model**, on a machine without a graphics card: the earlier baseline reproduced answer for answer (28 of 31, the same three wrong), and the answers about causes measured on twenty trial questions (§10).
- **Three independent reviews before anyone uses it:** of the design, of the code and of the security. Together with an earlier review they raised about fifty points, large and small; those that code can fix are fixed, each with a test (§9).
- **Every diagram redrawn** in one style and checked against the code.

### Hung: stores and backend

- **Passages and search vectors in PostgreSQL**, each with its well and report date, and a check that searching the store gives the same results as searching in memory (67 of 67 searches).
- **The daily activities in Neo4j**: 27 days and 161 activities for AK-3, read back identical to the source, with 58 of 58 recorded queries giving their recorded results.
- **The well facts in Neo4j**, beside the activities, read back identical, the activities untouched.
- **A reader for the store**, so the engine can take passages from PostgreSQL in the form it already reads.
- **The stores made ready to share**: passwords kept out of the repository, a script that sets up a server, a nightly backup, and a step-by-step guide. Until a server is found, one team machine hosts the stores on a private network.

### Tri and Hung together: the backend and the connection

- **The service the application talks to**: asking a question, marking an answer, reading a passage, a page and its image, a well and its activities, and a health check, with a written contract and an example response for each call.
- **The engine reads the stores.** One setting switches it from files to PostgreSQL and Neo4j; on the same data it holds the same passages, activities and facts either way. Search by meaning runs inside the database and returns the same results as the search in memory, now on the real search vectors of the whole package (67 of 67 searches).
- **The question log in PostgreSQL**: every question, how it was answered, and every mark; it can be listed, filtered, counted and downloaded as a test set.
- **One command from a report package to a loaded store**, each step checked, each run recorded. Run twice, it changes nothing the second time.
- **The whole application as containers**: the service, a proxy that serves the web application over HTTPS behind one shared password, and a guide from a new server to a running application. A check that asks a question from outside passes with the real model answering: 6 of 6 steps.
- **Built for one model that answers one question at a time:** questions take turns with a limit on the wait; a question that fails is still logged; the stores and the application restart by themselves; a monitor tells the group chat when the application goes down; the backup is copied off the server and can be checked by restoring it.
- **A guard on where report text may go:** the application refuses to start with an outside AI service unless the loaded package has been named as public.
- **Automatic tests on every change** pushed to the repository.

### Khai: reading the reports

- **Tables that continue across pages**: an option to join them and carry the header.
- **Section context**: the heading a passage belongs to, carried onto the passage.
- **Form recognition and label repair**: candidate settings for reading form areas and for pairing a label with its value.
- **Page orientation, quarantine of bad pages, and runs that can stop and resume.**
- **More checks** on the output: tables against their passages, labels against values, conflicts between forms, structure across pages.
- All of these are options that are off by default. Measuring each and deciding which to switch on comes next.

### Khai and Tri together: the package for the demo

- **One package holding everything the demo needs**, built by one command: the end-of-well reports of AK-3, 56-32 and 68-32, AK-3's four daily-report attachments and its non-productive-time report. 302 pages, about 1,430 passages, each end-of-well passage carrying its well's name. It passes the package checks. It was built a second time from nothing, on another machine, from the public PDFs: the same pages, and one passage more in one scanned report.
- **The daily activities are built from this package alone**: 161 activities, every one pointing to a passage that is in the store.
- **The well facts moved onto the package's passages without an AI**: each fact's source was matched to the same text in the new package and its value checked there again. 202 of 207 moved; 5 could not, because two source passages have no match.
- **A dated record** of the work on reading the reports, as a draft for Khai to correct.

## 9. What we learned

- **Reporting a calculated total in code, instead of letting an AI retype it, repairs nine answers.** Replaying the plans recorded in the earlier experiment this way gives 33 of 35 and 22 of 23 right, against 27 and 19. This replays recorded plans without a model, and the questions were written by us to suit this kind of answer, so it is an indication and not a new measurement.
- **A second pair of eyes found what tests did not.** The review found, for example, that "20-22 August" was read as a well name, which turned a right answer into "not stated". Wells are now recognised only if the system holds them.
- **Showing the data to a person exposes errors fast.** The application's list of facts showed AK-3 with 3 days from spud to rig release, beside report text that says 19. Our automatic check passes it, because a "3" appears nearby. Two more doubtful facts are logged. This is the human review you asked for, in its first form.
- **Building in parallel exposed mismatches early.** With the stores as the source, "Verified data only" could show no passage, because the well facts pointed to passages by an older ID than the store holds. Moving the facts onto the new package fixed it: a question about AK-3's casing now shows six passages where it showed none.

- **The real model makes mistakes that our stand-ins never made.** Until now every test of the new parts used a scripted stand-in for the model. The first real runs showed, within an hour: an activity code written where the non-productive code belongs; a code the question never mentioned; an answer of "1955 in" for a depth the report gives as "1,955 feet in 27 days". Each is now caught by code. The rule is the same every time: what code can read from the question or the report outranks what the model says.
- **Our check on facts was weaker than we thought.** It asked whether a fact's value is written in its passage, and accepted digits inside a longer number: a ground elevation of 150 read out of "1500'", a temperature of 180 out of a map coordinate. Nine of 216 facts were wrong this way. The check is fixed and 207 facts remain. No earlier score had depended on those nine.
- **A real quote is not a reason.** In answers about causes, the model supported each claim with words that really are in the report, and our check passed them. But many were things that happened near the problem, not its cause (§10).
- **The reviews were worth their cost.** The design review found that nothing limited how long a question could wait, that a question which failed left no trace, and that the stores would not come back after a restart. The code review found a total that could be computed over the wrong days. The security review found nothing serious and two things to tighten. Trying the application against the real stores found a link that did not open.

## 10. Reasoning about causes

For "a problem happened here; what caused it?" the system does what an engineer does, with code doing the gathering:

1. **Find the problem** in the daily activities: by date, depth, non-productive code, or words such as "stuck". AK-3's 28 non-productive activities form 6 problems, 115 hours together. If several fit the question, the application asks which.
2. **Gather what surrounds it**: the activities of the days before and after, that day's report text, and the end-of-well report's account. The amount is limited, so one question costs about twice a simple lookup.
3. **Answer in two parts**: what the reports state as the cause, and other possible factors, each with its source and labelled as a possibility. Code removes anything whose source it cannot find. With "Verified data only" on, the possible factors are hidden.
4. **Say what is missing** for a real judgement.

### What the first measurement showed

We wrote twenty trial questions about AK-3 in two sets of ten, each set fixed before it was run, and ran them with the real model. These are our own questions, not an expert's, and the first set was used to find and fix faults, so the numbers describe behaviour; they are not an evaluation.

| | First set | Second set, unseen |
|---|---:|---:|
| The right problem was found | 8 of 10 | 6 of 10 |
| The cause the reports state was found, with the report's words | 8 of 10 | 5 of 10 |
| Things stated as a cause that the reports do not give as one | 17 | 8 |
| Answers right on every count | 2 of 10 | 3 of 10 |

- **The good part:** whenever the system reached the right problem in the first set, the model named the cause the reports state and quoted the report for it. "What caused the stuck pipe on 20 August?" gave "plugged inner barrel", with the words "due to plugged inner barrel".
- **The weak part:** beside the true cause it listed other things from the same days as stated causes: "high torque", "crews at lodge for night", "receive 8 joints". Each has a real quote, so our source check passed them.
- **What we changed:** a stated cause must now rest on words in which the report gives a reason ("due to", "because", "waiting on", "unable"). Anything else is shown as a possible factor. That removes about half of the extra items (17 to 8 in the first set, 8 to 5 in the unseen one).
- **What remains:** AK-3's 66-hour well-control problem contains a stuck pipe and, a day later, a lost rod. Asked about one, the model gives the reasons for both. Our unit for "the problem" is too large; making it smaller is the next change.
- **"Other possible factors" are mostly generic:** "inadequate communication", "inadequate mud properties". We would like an expert to say whether that part is worth keeping.
- **Cost:** two AI calls and about three times the text of a simple lookup.

One well's reports do not hold offset wells, formation pressures or lessons learned, so the purpose stays what it was: to show you a concrete answer and learn what a useful one needs. Detail: [experiment E34](../../experiments/E34-reasoning-probe.md).

## 11. Weak points

- **The coordinator is still not measured in full.** Whether one AI call can route every kind of question as well as choosing by hand is tested on 221 questions, twice over. Without a graphics card an answer takes two to six minutes, so that run takes a day. The short measurements were made; this one needs rented compute.
- **Answers about causes over-state** (§10). Not ready to show as findings.
- **We have no graphics card and no server of our own.** The end-to-end run was made on a cloud machine without a graphics card, and on public data only. A private document cannot go on a rented machine without VPI's agreement.
- **Not on a server others can reach.** Everything a server needs is written and was run on one machine: the containers, the password gate, the monitor, the backup. A real address and its certificate have not been tried.
- **Every test question is written by us.** None is reviewed by an expert. Our scoring is also lenient in one known way: a number within half a percent of the right one counts as right.
- **Three wells from two projects, one report author.** Other authors' reports are untested or fail.
- **No domain expert has used the application.** Whether it is clear to them is not known.
- **One stored fact is known to be wrong** (AK-3, days from spud to rig release) and five facts point to passages the store does not hold. They are shown as they are.
- **The demo package is not identical from machine to machine:** built a second time, one scanned report gave one passage more. Each result therefore names the exact package it used.

## 12. What we need from you

1. **Who can try the application**: one or two people from the expert group is enough. Their questions are logged, which gives us real ones. We would also ask one of them to read ten answers about causes and say whether that kind of answer is useful (§10).
2. **What it is for**: which report types stay in scope, and which kinds of question users ask.
3. **A budget for rented compute: 5 million VND for the next three months**, from the capstone funding. A GPU by the hour (about 10 hours a week) for measurements and experiments, a small server that stays on for the application, and pay-per-use hosted models for a demo that answers at any hour. We are asking through the school, as Dr. Dung said; your support for the request would help. Detail: [resource plan](../RESOURCE_REQUEST_2026-11-24.md).
4. **If a private VPI document is to be used later:** where it may be processed, since we will have no machine of our own.

## 13. What comes next

Everything that code and our own machines can do for this build is done. Each next step starts with a person or with the budget.

**Before this stint ends, 27 November**

| Who | What |
|---|---|
| Tri | Send the request for rented compute, and this report |
| Hung | Say whether his machine hosts the application until there is a server; review the loading command and the container setup |
| Khai | Review the demo package and the record written for him; decide which reading options go on |

**Next stint, to 12 December**

1. **With a server (half a day of work):** the application at one address behind the password, watched by the monitor, with its backup copied elsewhere.
2. **With a graphics card (one session of a few hours):** the coordinator measured on all 221 questions, and the decision whether to keep it.
3. **With one or two experts:** the application in their hands, their questions in the log, and their reading of the answers about causes.
4. **Ours meanwhile:** a smaller unit for "the problem" in answers about causes; one question shown to you going through the whole system, live.

## Where the detail is

[Specification](../../PROJECT_DESIGN.md) (design, §4.6, §8 and §11.4) · [development plan](../../DEVELOPMENT_PLAN.md#7-what-to-do-now) (tasks) · track records: [engine](../../tracks/B-graphrag/log.md), [stores](../../tracks/C-storage/log.md), [reading the reports](../../tracks/A-ingestion/log.md) · [backend design](../../tracks/C-storage/backend-design.md) · [running it on a server](../../../deploy/README.md)
