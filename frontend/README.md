# frontend: the application people use

The React application of the second build ([specification §4.6](../docs/PROJECT_DESIGN.md#46-second-build-one-connected-application)). It asks the [backend](../backend/README.md) a question and shows the answer beside what it rests on. Written for people who read drilling reports, not for developers: nothing on screen names the system's parts.

## Run it

```powershell
cd frontend
npm install                 # once
npm run dev:examples        # no server, no model: the committed example responses
npm run dev                 # against the real API on http://127.0.0.1:8000 (start the backend first)
```

Then open http://localhost:5173. Node 20.19 or later.

| Command | Does |
|---|---|
| `npm run dev:examples` | The application on [`backend/fixtures/`](../backend/fixtures/). Evidence is real; each answer is a prepared one, and the screen says so. Add `&slow=30` to the address to make an answer take 30 seconds, which shows what waiting looks like |
| `npm run dev` | The application on the API. Calls to `/v1` go to port 8000 |
| `npm test` | No server needed. Includes an accessibility check of every main screen (axe-core) |
| `npm run build` | Type-check and build into `dist/` for the proxy to serve |
| `npm run types` | Regenerate `src/api/schema.d.ts` from `backend/openapi.json`. Run it after the backend's contract changes |

## What it does

Everything on screen is written for someone who reads drilling reports and has never seen the system. No word names a part of it: there is no "graph", "lane" or "model call" anywhere, and a test fails if one appears.

### Asking

- **A guide opens on the first visit** ("How it works") and can always be reopened from the top bar. It covers what to ask, how to read an answer, how to check it and how to say it is wrong, with example questions that can be asked in one click. It is skippable.
- **Ask in plain English** from a search box that stays in reach. Before the first question, the screen offers example questions in four groups and a table of the reports that are loaded.
- **While a question is being answered** (a real model can take a minute or more) the screen says what is happening, in three steps told by the time that has passed: reading the question, looking through the reports, writing the answer and checking it. It counts the seconds, changes its one line of reassurance as the wait grows, and has a "Stop" button; a stopped question goes back into the box. The browser waits up to four minutes, longer than the server does.

### Reading an answer

- **Every answer carries a label that says how far to trust it:**
  - green, *Calculated from the reports*: the system added the number up itself;
  - blue, *Written by AI, checked against the reports*: an AI wrote it and the value was found in the text;
  - amber, *Written by AI, not confirmed*;
  - grey, *No answer found*.
- **A small "i" explains anything unfamiliar** on hover, on keyboard focus, or on a tap (which pins it open): the labels, "Verified data only", non-productive time, key facts, the timeline, the table columns.
- **The evidence sits beside the answer**, as tabs. On a wide screen the answer stays in view while the evidence scrolls; on a phone the order is the answer, its evidence, then the earlier questions.
  - *Timeline*: for a calculated number, one bar per day from midnight to midnight, non-productive time in amber and hatched. Hovering a bar says what happened; clicking it marks the same activity in the list below, and the reverse.
  - *The list of activities* is grouped by day, each day with one heading line (date, activities, hours, non-productive hours). A long list shows its first days and a button, "Show all 28 activities"; an activity chosen on the timeline is unfolded and brought into view. On a phone each activity is two lines instead of four columns.
  - *Report text*: what the AI read, the cited passage first and flagged "The answer is here", with the answer's value highlighted in yellow. A long passage opens at the highlight.
  - *Key facts*: the checked facts the AI was given.

### Questions about a cause

- **A question about a cause** ("What caused the stuck pipe on AK-3 on 20 August 2016?") is answered in parts, never as one AI sentence:
  - *The problem we found*: when, how long, the depth, the report's code (explained on hover) and its own description;
  - *What the reports say caused it*: each cause with the report's words quoted and where they are written; the page opens like any source, and an activity whose page is not on this machine is shown in the evidence instead;
  - *Other possible factors (not stated in any report)*: dashed, grey and labelled "Possibility, not a finding". With "Verified data only" they are hidden, and the answer says how many;
  - *What a real judgement would still need*: the records these reports do not hold;
  - one quiet line when causes were left out because no report text supported them;
  - the evidence: the activities before, during and after the problem (those of the problem marked) on the timeline and in the same folded list, and the report text gathered around it.
- **When several problems match**, the application lists them as choices (days, hours, depth, the report's description). Picking one asks the question again with that problem's first day written into it, since a date in the question decides which problem is meant.

### Checking the source, and saying it is wrong

- **Where this comes from** lists each report once, by a readable name ("AK-3 end-of-well report, page 7"), and opens the page: as the printed page beside the cited text when an image exists (click it for full size; the credit line for the report's authors and licence is shown), and as text on a second tab or when there is none.

### When something is wrong

- **When something is wrong** the person sees a plain message and the button that helps:
  - "Try again" when the server is down, slow or restarting, when several people are asking at once, or when the answering service or the report database does not respond (the server says which, `src/api/client.ts`);
  - "Reload the page" when the password has expired or a page that is not the API's came back;
  - a notice before the first question when the server says it cannot answer questions just now; it looks again once a minute and goes by itself;
  - an answer that names no page says so; a broken screen shows a reload button, never a blank page.

### Other things on the answer

- **Verified data only**: a switch for answers from checked numbers and facts only.
- **Was this answer right?** Yes in one click; "No, it's wrong" asks what it should be. Both are saved. "Copy link" confirms that the link was copied, or says to copy it from the address bar.
- **An answer prints with what it rests on** (or saves as a PDF): the answer and its sources, then the evidence on the open tab with every activity listed, without the buttons, and with a link back to the answer.
- **How we got this answer** is folded away for those who want it: three numbered steps, and the technical cost.

### A page for each well

- **A page for each well**, opened from the list of wells on the start page or from a well's name under an answer:
  - one sentence on its days ("27 days of reports, 115 hours of non-productive time: 66 hours KICK, 24 WAIT, ...");
  - *What we know about it*: the facts in groups (general, depths and dates, casing strings with planned beside actual, values at depths), with plain names, units and an "i" on the terms; a long table of values at depths shows its first six and a button for the rest; a value opens the page it is written on, in the same page view as a source;
  - *Day by day*: the timeline of the days whose activities are all at hand, and a list of the report days with their hours, non-productive hours, depth and codes: the first ten, then "Show all 27 days". A bar marks its day in the list and unfolds the list if the day is not showing. A well with no daily reports says so instead;
  - *Its reports*, each with its pages, or that its text is not on this computer.

### The questions people asked

- **Questions people asked** (`?view=questions`), for the team and the advisors, linked quietly from the top bar and left out of the guide. It only reads:
  - the counts (asked, answered, marked right, marked wrong, not marked, and "could not be answered" when there are any) and the list, newest first, 20 at a time;
  - a question the system failed to answer is listed as "Could not be answered", and when opened says why in plain words (the system was busy, or the answering service did not respond);
  - filters: kind of question, how it ended, how it was marked, words in the question, and the days asked;
  - an opened question: when and how it was asked, the answer it got with its label, and every mark with its comment;
  - "Download these as a question set" saves the questions the filters select as a question file, as the server wrote it. Someone writes the right answers into it, and it becomes a test.
- Earlier questions fold to one line and are kept until the tab is closed. `/` puts the cursor in the search box; Esc closes a page, the guide or an explanation.

### Moving around

- **Each screen names itself on the browser tab** (the question and its answer, the well, the questions page), so the history and a printed page say what they are.
- **Links and the back button work without a router:** the screen is in the query string, as a question already was. `?q=...&graph=1` asks a question, `?well=AK-3` opens a well, `?view=questions&question=<id>` one logged question (`src/lib/route.ts`).

## Design

| Choice | Reason |
|---|---|
| Always light, white cards on a pale blue-grey page, one friendly blue for things to press | It is shown to non-developers on shared screens; one look is easier to explain than two. A dark theme was tried and dropped |
| Plus Jakarta Sans for the application, Source Serif 4 for the reports' own words | Rounded and approachable for the interface; the serif tells a reader at a glance which words are the report's |
| Green means calculated, blue means AI and checked, amber means non-productive time or a warning, yellow marks the answer in text | Four colours, each with one meaning, so they can be learnt in a minute |
| Explanations on hover instead of text on the page | The screen stays calm for someone who knows the terms, and nobody is left guessing |
| The words "we" and "the system", never the names of its parts | The readers are engineers and managers, not developers |
| Buttons and switches are at least 40 pixels high; motion stops for people who ask for less | Usable on a tablet and by people sensitive to motion |
| Long lists are folded to a sensible first part, with one button that says how many there are | A 28-row table pushed the answer off the screen; the first days are enough to check the sum, and the rest is one click away |
| Built to WCAG 2.2 AA | Checked by axe-core on every main screen, in the tests and in a browser (see below) |

Fonts, icons and the browser-tab icon are bundled, so the application needs no outside network.

### Accessibility

- **Keyboard:** a "Skip to the content" link comes first. Tabs follow the usual pattern (Tab reaches the open tab, the arrow keys, Home and End move between tabs). The timeline is one stop for Tab, and the arrow keys move from bar to bar. A row of a list is marked with the button in its first cell.
- **Focus:** the guide keeps Tab inside it and gives the keyboard back to the button that opened it. An opened page takes the keyboard to its heading and gives it back to its source when it closes. A new screen starts at its heading, a new answer at its headline.
- **Screen readers:** one main part, one top heading per screen, tables with row and column headings, and announcements for waiting (the step, not every second), a copied link, a saved file and errors.
- **Seeing:** text has at least 4.5:1 contrast; the edges of fields, the switch and the timeline's bars have at least 3:1; non-productive time is hatched as well as amber. An explanation stays on the screen at any width and can be closed with Esc. Nothing scrolls sideways down to 320 pixels wide, except a wide table inside its own box.
- **How it is checked:** `src/Polish.test.tsx` runs axe-core on each main screen for structure, names and roles. Contrast and the size of things to press cannot be worked out without a browser, so they were checked with axe-core in Chromium on the running application, at 1360 and 390 pixels wide: 315 findings before this work, none after. No one has yet tested it with a screen reader.

**Where it finds the API:** on its own origin (`/v1`), which is how it runs behind the proxy and through the development server. Only when `VITE_API_BASE` is set at build time does it call another address. No development address is in the production files.

## Files

| Path | Holds |
|---|---|
| `src/api/` | `client.ts` (the real API, its error messages, stopping a question), `examples.ts` (the example responses, loaded only in examples mode), `schema.d.ts` (generated) |
| `src/lib/` | Pure logic with tests: `wording.ts` (every sentence the application says, the plain names and units of properties, and the hover explanations), `cause.ts` (answers about causes: the activities around the problem, where a cited cause is written, the question asked again), `well.ts` (casing tables, the days the timeline can draw), `route.ts` (the screen in the address), `strips.ts` (operations placed on a day), `highlight.ts` (marking a value in report text), `fold.ts` (how much of a long list to show first, where the answer's column sticks), `hooks.ts` (the window's width, the sticky column) |
| `src/components/` | `Answer.tsx`, `Cause.tsx` (an answer about a cause, and the choices), `Evidence.tsx`, `CauseEvidence.tsx` (what a cause answer rests on), `PageView.tsx` (a page of a report), `Passage.tsx` (report text), `DayStrips.tsx` (the timeline), `ActivityList.tsx` (activities grouped by day), `Fold.tsx` (a long list and its button), `Tabs.tsx`, `Waiting.tsx` (while a question is answered), `Well.tsx` (a well's page), `Questions.tsx` (the questions people asked), `RouteLink.tsx`, `Guide.tsx` (how it works), `Tip.tsx` (the hover explanations), `Icon.tsx` |
| `src/App.tsx` | State: the screen, asking and stopping, answers, selection, the page view, the browser tab's title |
| `src/styles.css` | One stylesheet; colours and type sizes are variables at the top; the phone and print layouts are at the end |
| `src/*.test.tsx` | The screens in use: `App`, `Cause`, `Well`, `Questions`, and `Polish` (waiting, keyboard, long lists, narrow screens, edge cases, accessibility) |

## Limits

- **Run once against the real model** through the whole stack, on the stores (Track B log B-F73, B-F76). No one outside the team has used it.
- **The steps shown while waiting are told by the clock**, not by the server, which does not report its progress: after 4 seconds "looking through the reports", after 15 "writing the answer and checking it".
- **A short activity is a thin bar on the timeline**, narrower than the 24 pixels a thing to press should have, because a bar's width is its length in time. The same activity can be marked from its row in the list below, which is the way round this that WCAG allows; axe-core lists these bars for a person to review, not as failures.
- A stopped question stops the browser's request. Whether the server also stops working on it is the backend's matter.
- The questions page can filter for answered questions and for those that could not be answered, not for each kind of "no answer".
- A page's image shows only where the backend has rendered it (`platform/render_pages.py`, `BACKEND_PAGE_IMAGES`); there is no highlight of the cited passage on the image yet, because K1 passages carry no region ([backend design](../docs/tracks/C-storage/backend-design.md) §7).
- The activities around a cause's problem arrive with their fields. An answer saved before they did is read back from the lines the AI was shown (`src/lib/cause.ts`); a line that cannot be read is shown as it is, without a timeline.
- Report names are file IDs made readable (`ak3 eowr`), until documents carry titles. Two of AK-3's daily reports therefore share one name on its page.
- **The questions page cannot always give an AI-written answer its exact label:** the log does not keep whether the value was confirmed in the text, so such an answer is labelled "Written by AI" and says the check was not saved. A calculated answer is recognised by the activity log having answered it.
- Property units the reports leave out (ft, °F, lb/ft, ...) come from `wording.ts`, after the test profile in `prototype/profiles/oil_wells.json`; casing weight in lb/ft is the usual unit, not one the facts state.
- **Example mode** has a well page for AK-3 only, and its timeline draws the 4 days whose activities the examples hold completely (the list gives all 27). Its question log is the entries of `admin_questions.json` (four, of which the list shows three); the export is put together from `admin_export.json`. Pages other than page 7 open as the text the examples hold of them.
- No login: the access gate is at the proxy.
- Answers are kept in the browser's session storage, so they include report text on that machine until the tab closes.
