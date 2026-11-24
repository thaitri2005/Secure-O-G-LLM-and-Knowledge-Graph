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
| `npm run dev:examples` | The application on [`backend/fixtures/`](../backend/fixtures/). Evidence is real; each answer is a prepared one, and the top bar says so |
| `npm run dev` | The application on the API. Calls to `/v1` go to port 8000 |
| `npm test` | 49 tests, no server needed |
| `npm run build` | Type-check and build into `dist/` for the proxy to serve |
| `npm run types` | Regenerate `src/api/schema.d.ts` from `backend/openapi.json`. Run it after the backend's contract changes |

## What it does

Everything on screen is written for someone who reads drilling reports and has never seen the system. No word names a part of it: there is no "graph", "lane" or "model call" anywhere, and a test fails if one appears.

- **A guide opens on the first visit** ("How it works") and can always be reopened from the top bar. It covers what to ask, how to read an answer, how to check it and how to say it is wrong, with example questions that can be asked in one click. It is skippable.
- **Ask in plain English** from a search box that stays in reach. Before the first question, the screen offers example questions in three groups and a table of the reports that are loaded.
- **Every answer carries a label that says how far to trust it:**
  - green, *Calculated from the reports*: the system added the number up itself;
  - blue, *Written by AI, checked against the reports*: an AI wrote it and the value was found in the text;
  - amber, *Written by AI, not confirmed*;
  - grey, *No answer found*.
- **A small "i" explains anything unfamiliar** on hover, on keyboard focus, or on a tap (which pins it open): the labels, "Verified data only", non-productive time, key facts, the timeline, the table columns.
- **The evidence sits beside the answer**, as tabs:
  - *Timeline*: for a calculated number, one bar per day from midnight to midnight, non-productive time in amber. Hovering a bar says what happened; clicking it marks the same activity in the list below, and the reverse.
  - *Report text*: what the AI read, the cited passage first and flagged "The answer is here", with the answer's value highlighted in yellow. A long passage opens at the highlight.
  - *Key facts*: the checked facts the AI was given.
- **Where this comes from** lists each report once, by a readable name ("AK-3 end-of-well report, page 7"), and opens the page as text.
- **Verified data only**: a switch for answers from checked numbers and facts only.
- **Was this answer right?** Yes in one click; "No, it's wrong" asks what it should be. Both are saved.
- **How we got this answer** is folded away for those who want it: three numbered steps, and the technical cost.
- Earlier questions fold to one line and are kept until the tab is closed. A link can carry a question (`?q=...&graph=1`). `/` puts the cursor in the search box; Esc closes a page or the guide.

## Design

| Choice | Reason |
|---|---|
| Always light, white cards on a pale blue-grey page, one friendly blue for things to press | It is shown to non-developers on shared screens; one look is easier to explain than two. A dark theme was tried and dropped |
| Plus Jakarta Sans for the application, Source Serif 4 for the reports' own words | Rounded and approachable for the interface; the serif tells a reader at a glance which words are the report's |
| Green means calculated, blue means AI and checked, amber means non-productive time or a warning, yellow marks the answer in text | Four colours, each with one meaning, so they can be learnt in a minute |
| Explanations on hover instead of text on the page | The screen stays calm for someone who knows the terms, and nobody is left guessing |
| The words "we" and "the system", never the names of its parts | The readers are engineers and managers, not developers |
| Buttons and switches are at least 40 pixels high; everything works by keyboard; motion stops for people who ask for less | Usable on a tablet, with a keyboard, and by people sensitive to motion |

Fonts and icons are bundled, so the application needs no outside network.

## Files

| Path | Holds |
|---|---|
| `src/api/` | `client.ts` (the real API and its error messages), `examples.ts` (the example responses, loaded only in examples mode), `schema.d.ts` (generated) |
| `src/lib/` | Pure logic with tests: `wording.ts` (every sentence the application says, and the hover explanations), `strips.ts` (operations placed on a day), `highlight.ts` (marking a value in report text) |
| `src/components/` | `Answer.tsx`, `Evidence.tsx`, `DayStrips.tsx` (the timeline), `Guide.tsx` (how it works), `Tip.tsx` (the hover explanations), `Icon.tsx` |
| `src/App.tsx` | State: asking, answers, selection, the page view |
| `src/styles.css` | One stylesheet; colours and type sizes are variables at the top |

## Limits

- **Never run against a real model.** Built and tested on the example responses and on stand-ins; the first run on the desktop is still to do.
- The page view shows a page's text, not its image; the image comes with the file store ([backend design](../docs/tracks/C-storage/backend-design.md) §7).
- Report names are file IDs made readable (`ak3 eowr`), until documents carry titles.
- No login: the access gate is at the proxy.
- Answers are kept in the browser's session storage, so they include report text on that machine until the tab closes.
