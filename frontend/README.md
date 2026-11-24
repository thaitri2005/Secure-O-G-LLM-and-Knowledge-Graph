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
| `npm test` | 41 tests, no server needed |
| `npm run build` | Type-check and build into `dist/` for the proxy to serve |
| `npm run types` | Regenerate `src/api/schema.d.ts` from `backend/openapi.json`. Run it after the backend's contract changes |

## What it does

- **Ask** from a bar that stays at the top. `/` puts the cursor in it. While the model works, the question and a count of seconds are shown.
- **The answer**: the value, one sentence on where it came from, and the three steps of how it was answered (understood as, read, answered), with the number of model calls and seconds.
- **Evidence beside the answer**, as tabs:
  - *Operations*: for a number computed from the daily reports, one 24-hour strip per report day with non-productive time hatched, and the same operations as a table. Picking an operation on a strip marks its row, and the reverse.
  - *Passages*: what the model read, cited ones first, with the answer's value marked where the report writes it. A long passage opens at the mark.
  - *Checked facts*: the validated facts the model was given.
- **Sources** open the page they are on, as the report's text. Esc goes back.
- **Graph answers only**: answers from stored facts and daily operations, with no fallback to the report text.
- **Right or wrong**: one click for right; wrong asks what it should say. Both go to the question log.
- **Earlier questions** fold to one line and are kept until the tab is closed. A link can carry a question: `?q=...&graph=1`.

## Design

| Choice | Reason |
|---|---|
| Report text is set in a serif (Source Serif 4), everything the application says in a sans (Archivo) | A reader can always tell the report's words from the system's |
| Amber is used for non-productive time and for warnings, and nowhere else | It is the thing most questions over time ask about |
| The day strip | It is the time breakdown a daily drilling report prints, drawn; it shows at a glance what a total was added up from |
| A computed answer says "No model wrote this number" | The difference between calculated and generated is the point of the event graph |
| Light and dark follow the system setting | No switch to maintain |

Fonts are bundled from npm, so the application needs no outside network.

## Files

| Path | Holds |
|---|---|
| `src/api/` | `client.ts` (the real API and its error messages), `examples.ts` (the example responses, loaded only in examples mode), `schema.d.ts` (generated) |
| `src/lib/` | Pure logic with tests: `wording.ts` (every sentence the application says), `strips.ts` (operations placed on a day), `highlight.ts` (marking a value in report text) |
| `src/components/` | `Answer.tsx`, `Evidence.tsx`, `DayStrips.tsx` |
| `src/App.tsx` | State: asking, answers, selection, the page view |
| `src/styles.css` | One stylesheet; colours and type sizes are variables at the top |

## Limits

- **Never run against a real model.** Built and tested on the example responses and on stand-ins; the first run on the desktop is still to do.
- The page view shows a page's text, not its image; the image comes with the file store ([backend design](../docs/tracks/C-storage/backend-design.md) §7).
- Report names are file IDs made readable (`ak3 eowr`), until documents carry titles.
- No login: the access gate is at the proxy.
- Answers are kept in the browser's session storage, so they include report text on that machine until the tab closes.
