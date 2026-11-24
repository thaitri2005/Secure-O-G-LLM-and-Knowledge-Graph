import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, type Api } from "./api/client";
import type { AnswerOut, Citation, Health, Mode, PageOut, Verdict, WellSummary } from "./api/types";
import { Answer } from "./components/Answer";
import type { Pointer } from "./components/CauseEvidence";
import { Evidence } from "./components/Evidence";
import { Guide } from "./components/Guide";
import { Icon, type IconName } from "./components/Icon";
import { Tip } from "./components/Tip";
import { EXPLAIN, headline } from "./lib/wording";

// One group per kind of question the system answers, on the reports loaded for the demonstration.
const TRY: { icon: IconName; kind: string; why: string; questions: string[] }[] = [
  {
    icon: "clock",
    kind: "Totals over a period",
    why: "Hours, days and counts, added up from the daily reports",
    questions: ["How many hours of non-productive time did AK-3 have?", "On how many days did AK-3 log drilling?"],
  },
  {
    icon: "document",
    kind: "A fact about a well",
    why: "Depths, dates and sizes stated in an end-of-well report",
    questions: ["What total depth did well AK-3 reach?", "When was well AK-3 spudded?"],
  },
  {
    icon: "compare",
    kind: "Comparing wells",
    why: "The same fact across several wells",
    questions: ["Which of AK-3, 56-32 and 68-32 was drilled deepest?"],
  },
  {
    icon: "flag",
    kind: "What caused a problem",
    why: "The cause the reports give, with other possible factors kept apart",
    questions: ["What caused the stuck pipe on AK-3 on 20 August 2016?", "What caused the non-productive time on AK-3?"],
  },
];

const STORE = "drilling-reports.answers";
const SEEN_GUIDE = "drilling-reports.guide-seen";
const KEPT = 20;

function restore(): AnswerOut[] {
  try {
    const stored = JSON.parse(window.sessionStorage.getItem(STORE) ?? "[]");
    return Array.isArray(stored) ? (stored as AnswerOut[]) : [];
  } catch {
    return [];
  }
}

function firstVisit(): boolean {
  try {
    return window.localStorage.getItem(SEEN_GUIDE) === null;
  } catch {
    return false;
  }
}

export default function App({ api, examples = false }: { api: Api; examples?: boolean }) {
  const [question, setQuestion] = useState("");
  const [verifiedOnly, setVerifiedOnly] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [waited, setWaited] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [answers, setAnswers] = useState<AnswerOut[]>(restore);
  const [selected, setSelected] = useState<string | null>(() => restore()[0]?.id ?? null);
  const [arrived, setArrived] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [failed, setFailed] = useState<{ text: string; mode: Mode } | null>(null);
  const [wells, setWells] = useState<WellSummary[]>([]);
  const [page, setPage] = useState<PageOut | null>(null);
  const [pageChunk, setPageChunk] = useState<string | null>(null);
  const [guide, setGuide] = useState(false);
  const [pointed, setPointed] = useState<(Pointer & { answer: string }) | null>(null);
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
    setFailed(null);
    try {
      const answer = await api.ask(trimmed, mode);
      setAnswers((earlier) => [answer, ...earlier].slice(0, KEPT));
      setSelected(answer.id);
      setArrived(answer.id);
      setPage(null);
      setQuestion("");
    } catch (failure) {
      setQuestion(trimmed);
      setFailed({ text: trimmed, mode });
      setError(failure instanceof ApiError ? failure.message : "Something went wrong. Please try again.");
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
      setError(failure instanceof ApiError ? failure.message : "We couldn’t open that page.");
    }
  }, [api]);

  const showEvidence = useCallback((answerId: string, label: string) => {
    setPage(null);
    setPointed({ answer: answerId, label, at: Date.now() });
  }, []);

  const feedback = useCallback((answerId: string, verdict: Verdict, comment: string) => api.feedback(answerId, verdict, comment), [api]);

  const closeGuide = useCallback(() => {
    setGuide(false);
    try {
      window.localStorage.setItem(SEEN_GUIDE, "1");
    } catch {
      // Without storage the guide simply opens again next time.
    }
    box.current?.focus();
  }, []);

  const load = useCallback(() => {
    setUnreachable(false);
    api.health().then(setHealth).catch(() => setUnreachable(true));
    api.wells().then(setWells).catch(() => setWells([]));
  }, [api]);

  // What is loaded, and a question the link may carry: ?q=...&graph=1
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    load();
    const params = new URLSearchParams(window.location.search);
    const linked = params.get("q");
    if (linked) {
      const exact = params.get("graph") === "1";
      setVerifiedOnly(exact);
      void ask(linked, exact ? "exact" : "allow_fallback");
    } else if (restore().length === 0 && firstVisit()) {
      setGuide(true); // A first visit with nothing asked: show how it works. It can always be closed.
    }
  }, [api, ask, load]);

  useEffect(() => {
    try {
      window.sessionStorage.setItem(STORE, JSON.stringify(answers));
    } catch {
      // Storage can be full or switched off; the answers on screen are unaffected.
    }
  }, [answers]);

  // An answer can take many seconds: count them, so waiting never looks like a fault.
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
    void ask(question, verifiedOnly ? "exact" : "allow_fallback");
  }

  const current = answers.find((answer) => answer.id === selected) ?? null;
  const mode: Mode = verifiedOnly ? "exact" : "allow_fallback";
  const fresh = answers.length === 0 && pending === null;

  return (
    <div className="app">
      <header className="top">
        <div className="top__inner">
          <p className="brand"><span className="brand__mark" aria-hidden="true" />Drilling Reports Assistant</p>
          <button type="button" className="chip chip--plain" onClick={() => setGuide(true)}>
            <Icon name="help" size={18} /> How it works
          </button>
        </div>
      </header>

      <div className={fresh ? "hero hero--fresh" : "hero"}>
        <div className="hero__inner">
          {fresh && (
            <>
              <h1>Ask anything about your drilling reports</h1>
              <p className="hero__lead">
                Type a question in plain English. You get an answer, and you can always see exactly which page it
                comes from.
              </p>
            </>
          )}
          {!fresh && <h1 className="visually-hidden">Drilling Reports Assistant</h1>}
          <form className="ask" onSubmit={submit}>
            <label htmlFor="question" className="visually-hidden">Ask about the reports</label>
            <div className="ask__row">
              <span className="ask__icon"><Icon name="search" size={22} /></span>
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
                <input type="checkbox" checked={verifiedOnly} onChange={(event) => setVerifiedOnly(event.target.checked)} />
                <span className="switch__track" aria-hidden="true" />
                <span>Verified data only</span>
              </label>
              <Tip about="verified data only">{EXPLAIN.verifiedOnly}</Tip>
            </div>
            {error && (
              <p role="alert" className="error">
                <Icon name="alert" size={18} /> <span>{error}</span>
                {failed && (
                  <button type="button" className="link" onClick={() => void ask(failed.text, failed.mode)}>Try again</button>
                )}
              </p>
            )}
          </form>
          {examples && (
            <p className="notice">
              <Icon name="info" size={16} /> Demo mode: no AI is connected. The report text and numbers are real; each
              answer shown is a prepared example.
            </p>
          )}
          {unreachable && !examples && (
            <p className="notice notice--warn"><Icon name="alert" size={16} /> We can’t reach the server right now. Please try again in a moment.{" "}
              <button type="button" className="link" onClick={load}>Try again</button>
            </p>
          )}
        </div>
      </div>

      {pending !== null && (
        <div className="pending" role="status">
          <div className="pending__dots" aria-hidden="true"><span /><span /><span /></div>
          <div>
            <p className="pending__state">Reading the reports for you{waited >= 3 ? ` (${waited} seconds)` : ""}</p>
            <p className="pending__question">“{pending}”</p>
          </div>
        </div>
      )}

      {fresh ? (
        <main className="start">
          <section aria-labelledby="try">
            <h2 id="try">Not sure what to ask? Try one of these</h2>
            <div className="start__groups">
              {TRY.map((group) => (
                <div key={group.kind} className="card start__group">
                  <span className="start__icon"><Icon name={group.icon} size={22} /></span>
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
            <section aria-labelledby="loaded" className="card start__loaded">
              <h2 id="loaded">Reports you can ask about</h2>
              {health && (
                <p className="note">
                  {health.data.end_of_well_chunks} passages from end-of-well reports and {health.data.events} logged
                  daily activities are loaded.
                </p>
              )}
              <div className="scroll">
                <table className="data" aria-label="Wells loaded">
                  <thead>
                    <tr>
                      <th>Well</th>
                      <th className="num">Key facts <Tip about="key facts">{EXPLAIN.keyFacts}</Tip></th>
                      <th className="num">Days of daily reports</th>
                    </tr>
                  </thead>
                  <tbody>
                    {wells.map((well) => (
                      <tr key={well.well_id}>
                        <td>{well.well_id}</td><td className="num">{well.facts}</td><td className="num">{well.report_days}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </main>
      ) : (
        answers.length > 0 && (
          <main className="work">
            <div className="answers">
              {current && <Answer key={current.id} answer={current} arrive={arrived === current.id} onOpenSource={openSource} onFeedback={feedback} onAsk={ask} onShowEvidence={showEvidence} />}
              {answers.length > 1 && (
                <section className="earlier" aria-labelledby="earlier">
                  <h2 id="earlier">Your earlier questions</h2>
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
                Start over
              </button>
            </div>
            {current && (
              <Evidence key={current.id} answer={current} page={page} pageChunk={pageChunk} onOpenPage={(chunk) => void openSource(current, { ...chunk, how: "model" })} onClosePage={() => setPage(null)} pointed={pointed?.answer === current.id ? pointed : null} />
            )}
          </main>
        )
      )}

      {guide && (
        <Guide
          onClose={closeGuide}
          onTry={(text) => {
            closeGuide();
            void ask(text, mode);
          }}
        />
      )}
    </div>
  );
}
