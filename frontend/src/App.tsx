import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, type Api } from "./api/client";
import type { AnswerOut, Citation, Health, Mode, PageOut, Verdict, WellSummary } from "./api/types";
import { Answer } from "./components/Answer";
import { Evidence } from "./components/Evidence";
import { headline } from "./lib/wording";

// One group per kind of question the system answers, on the reports loaded for the demonstration.
const TRY: { kind: string; why: string; questions: string[] }[] = [
  {
    kind: "Totals over time",
    why: "Added up in code from the daily reports’ operations",
    questions: ["How many hours of non-productive time did AK-3 have?", "On how many days did AK-3 log drilling?"],
  },
  {
    kind: "A value from an end-of-well report",
    why: "Read from the well’s checked facts and the report text",
    questions: ["What total depth did well AK-3 reach?", "When was well AK-3 spudded?"],
  },
  {
    kind: "Across wells",
    why: "Compares what several reports state",
    questions: ["Which of AK-3, 56-32 and 68-32 was drilled deepest?"],
  },
];

const STORE = "drilling-reports.answers";
const KEPT = 20;

function restore(): AnswerOut[] {
  try {
    const stored = JSON.parse(window.sessionStorage.getItem(STORE) ?? "[]");
    return Array.isArray(stored) ? (stored as AnswerOut[]) : [];
  } catch {
    return [];
  }
}

function modelName(health: Health): string {
  const answer = health.models.answer ?? "";
  return answer.includes(":") ? answer.slice(answer.indexOf(":") + 1) : answer;
}

export default function App({ api, examples = false }: { api: Api; examples?: boolean }) {
  const [question, setQuestion] = useState("");
  const [graphOnly, setGraphOnly] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [waited, setWaited] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [answers, setAnswers] = useState<AnswerOut[]>(restore);
  const [selected, setSelected] = useState<string | null>(() => restore()[0]?.id ?? null);
  const [arrived, setArrived] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [wells, setWells] = useState<WellSummary[]>([]);
  const [page, setPage] = useState<PageOut | null>(null);
  const [pageChunk, setPageChunk] = useState<string | null>(null);
  const box = useRef<HTMLInputElement>(null);
  const started = useRef(false);
  const busy = useRef(false);

  const ask = useCallback(async (text: string, mode: Mode) => {
    const trimmed = text.trim();
    if (!trimmed || busy.current) return;
    busy.current = true;
    setPending(trimmed);
    setWaited(0);
    setError(null);
    try {
      const answer = await api.ask(trimmed, mode);
      setAnswers((earlier) => [answer, ...earlier].slice(0, KEPT));
      setSelected(answer.id);
      setArrived(answer.id);
      setPage(null);
      setQuestion("");
    } catch (failure) {
      setQuestion(trimmed);
      setError(failure instanceof ApiError ? failure.message : "Something went wrong while asking. Try again.");
    } finally {
      busy.current = false;
      setPending(null);
    }
  }, [api]);

  const openSource = useCallback(async (answer: AnswerOut, citation: Citation) => {
    if (citation.page === null) return;
    setSelected(answer.id);
    try {
      setPage(await api.page(citation.file_id, citation.page));
      setPageChunk(citation.chunk_id);
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : "That page could not be opened.");
    }
  }, [api]);

  const feedback = useCallback((answerId: string, verdict: Verdict, comment: string) => api.feedback(answerId, verdict, comment), [api]);

  // What is loaded, and a question the link may carry: ?q=...&graph=1
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    api.health().then(setHealth).catch(() => setUnreachable(true));
    api.wells().then(setWells).catch(() => setWells([]));
    const params = new URLSearchParams(window.location.search);
    const linked = params.get("q");
    if (linked) {
      const exact = params.get("graph") === "1";
      setGraphOnly(exact);
      void ask(linked, exact ? "exact" : "allow_fallback");
    }
  }, [api, ask]);

  useEffect(() => {
    try {
      window.sessionStorage.setItem(STORE, JSON.stringify(answers));
    } catch {
      // Storage can be full or switched off; the answers on screen are unaffected.
    }
  }, [answers]);

  // A local model can take many seconds: count them, so waiting never looks like a fault.
  useEffect(() => {
    if (pending === null) return;
    const timer = window.setInterval(() => setWaited((seconds) => seconds + 1), 1000);
    return () => window.clearInterval(timer);
  }, [pending]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const typing = event.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName);
      if (event.key === "/" && !typing && !event.ctrlKey && !event.metaKey) {
        event.preventDefault();
        box.current?.focus();
      } else if (event.key === "Escape") {
        setPage(null);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    void ask(question, graphOnly ? "exact" : "allow_fallback");
  }

  const current = answers.find((answer) => answer.id === selected) ?? null;
  const mode: Mode = graphOnly ? "exact" : "allow_fallback";

  return (
    <div className="app">
      <header className="top">
        <div className="top__bar">
          <h1>Drilling reports</h1>
          <p className={examples || unreachable ? "top__state top__state--warn" : "top__state"}>
            {examples
              ? "Example answers: no language model is connected. The evidence is real; each answer is a prepared one."
              : unreachable
                ? "The application server is not reachable."
                : health
                  ? `Model: ${modelName(health)}`
                  : ""}
          </p>
        </div>
        <form className="ask" onSubmit={submit}>
          <label htmlFor="question">Ask about the reports</label>
          <div className="ask__row">
            <input
              id="question"
              ref={box}
              type="text"
              maxLength={500}
              autoComplete="off"
              autoFocus
              placeholder="For example: how many hours did AK-3 spend drilling in August 2016?"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
            />
            <button type="submit" className="button" disabled={pending !== null}>{pending !== null ? "Asking" : "Ask"}</button>
          </div>
          <div className="ask__options">
            <label className="switch">
              <input type="checkbox" checked={graphOnly} onChange={(event) => setGraphOnly(event.target.checked)} />
              <span>
                Graph answers only
                <small>Answer from stored facts and daily operations. Do not fall back to searching the report text.</small>
              </span>
            </label>
            <p className="ask__hint">Press <kbd>/</kbd> to type a question</p>
          </div>
          {error && <p role="alert" className="error">{error}</p>}
        </form>
      </header>

      {pending !== null && (
        <div className="pending" role="status">
          <p className="pending__question">{pending}</p>
          <p className="pending__state">Reading the reports{waited >= 3 ? `, ${waited} s` : ""}</p>
          <div className="pending__bar" aria-hidden="true" />
        </div>
      )}

      {answers.length === 0 && pending === null ? (
        <main className="start">
          <section aria-labelledby="try">
            <h2 id="try">Questions to try</h2>
            <div className="start__groups">
              {TRY.map((group) => (
                <div key={group.kind} className="start__group">
                  <h3>{group.kind}</h3>
                  <p>{group.why}</p>
                  <ul>
                    {group.questions.map((text) => (
                      <li key={text}>
                        <button type="button" className="try" onClick={() => void ask(text, mode)}>{text}</button>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </section>
          {wells.length > 0 && (
            <section aria-labelledby="loaded" className="start__loaded">
              <h2 id="loaded">What is loaded</h2>
              {health && (
                <p className="note">
                  {health.data.end_of_well_chunks} passages of end-of-well reports and {health.data.events} daily operations.
                </p>
              )}
              <table className="data" aria-label="Wells loaded">
                <thead>
                  <tr><th>Well</th><th className="num">Checked facts</th><th className="num">Report days</th></tr>
                </thead>
                <tbody>
                  {wells.map((well) => (
                    <tr key={well.well_id}>
                      <td>{well.well_id}</td><td className="num">{well.facts}</td><td className="num">{well.report_days}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
        </main>
      ) : (
        answers.length > 0 && (
          <main className="work">
            <div className="answers">
              {current && <Answer key={current.id} answer={current} arrive={arrived === current.id} onOpenSource={openSource} onFeedback={feedback} />}
              {answers.length > 1 && (
                <section className="earlier" aria-labelledby="earlier">
                  <h2 id="earlier">Earlier questions</h2>
                  <ul>
                    {answers.filter((answer) => answer.id !== selected).map((answer) => (
                      <li key={answer.id}>
                        <button
                          type="button"
                          className="earlier__item"
                          aria-label={`${answer.question} ${headline(answer)}`}
                          onClick={() => {
                            setSelected(answer.id);
                            setArrived(answer.id);
                            setPage(null);
                          }}
                        >
                          <span>{answer.question}</span>
                          <strong className={answer.status === "answered" ? "" : "earlier__none"}>{headline(answer)}</strong>
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              <button
                type="button"
                className="link answers__clear"
                onClick={() => {
                  setAnswers([]);
                  setSelected(null);
                  setPage(null);
                }}
              >
                Clear all questions
              </button>
            </div>
            {current && (
              <Evidence key={current.id} answer={current} page={page} pageChunk={pageChunk} onOpenPage={(chunk) => void openSource(current, { ...chunk, how: "model" })} onClosePage={() => setPage(null)} />
            )}
          </main>
        )
      )}
    </div>
  );
}
