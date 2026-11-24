import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, Stopped, type Api } from "./api/client";
import type { AnswerOut, Citation, Health, Mode, PageOut, Verdict, WellSummary } from "./api/types";
import { Answer } from "./components/Answer";
import type { Pointer } from "./components/CauseEvidence";
import { Evidence } from "./components/Evidence";
import { Guide } from "./components/Guide";
import { Icon, type IconName } from "./components/Icon";
import { Questions } from "./components/Questions";
import { RouteLink } from "./components/RouteLink";
import { Tip } from "./components/Tip";
import { Waiting } from "./components/Waiting";
import { Well } from "./components/Well";
import { cameFromApp, HOME, pushRoute, readRoute, type Route } from "./lib/route";
import { NARROW, useMedia, useStickyColumn } from "./lib/hooks";
import { APP_NAME, DEMO, EXPLAIN, headline, NOT_READY, pageTitle, WAITING } from "./lib/wording";

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
  const [notReady, setNotReady] = useState(false);
  const [failed, setFailed] = useState<{ text: string; mode: Mode; reload: boolean } | null>(null);
  const [stopped, setStopped] = useState(false);
  const [wells, setWells] = useState<WellSummary[]>([]);
  const [page, setPage] = useState<PageOut | null>(null);
  const [pageChunk, setPageChunk] = useState<string | null>(null);
  const [guide, setGuide] = useState(false);
  const [pointed, setPointed] = useState<(Pointer & { answer: string }) | null>(null);
  const [route, setRoute] = useState<Route>(() => readRoute(window.location.search));
  const box = useRef<HTMLInputElement>(null);
  const started = useRef(false);
  const busy = useRef(false);
  /** Counts the questions asked, so an answer that arrives after its question was stopped is not shown. */
  const asking = useRef(0);
  /** What had the keyboard before the guide or a page opened, to give it back when that closes. */
  const guideOpener = useRef<HTMLElement | null>(null);
  const pageOpener = useRef<HTMLElement | null>(null);
  const column = useRef<HTMLDivElement>(null);
  const narrow = useMedia(NARROW);

  // Screens live in the address (src/lib/route.ts), so the back button and a copied link work.
  const go = useCallback((next: Route) => {
    pushRoute(next);
    setRoute(next);
    window.scrollTo?.({ top: 0 });
  }, []);

  useEffect(() => {
    const onPop = () => setRoute(readRoute(window.location.search));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  /** Back to where the reader came from inside the application, or to the start when the link was opened directly. */
  const back = useCallback(() => {
    if (cameFromApp()) window.history.back();
    else go(HOME);
  }, [go]);

  const ask = useCallback(async (text: string, mode: Mode) => {
    const trimmed = text.trim();
    if (!trimmed || busy.current) return;
    // A question asked from another screen is answered on the main one.
    if (readRoute(window.location.search).view !== "home") go(HOME);
    busy.current = true;
    const mine = ++asking.current;
    setPending(trimmed);
    setWaited(0);
    setError(null);
    setFailed(null);
    setStopped(false);
    try {
      const answer = await api.ask(trimmed, mode);
      if (mine !== asking.current) return; // stopped while it was being answered
      setAnswers((earlier) => [answer, ...earlier].slice(0, KEPT));
      setSelected(answer.id);
      setArrived(answer.id);
      setPage(null);
      setQuestion("");
    } catch (failure) {
      if (mine !== asking.current || failure instanceof Stopped) return;
      setQuestion(trimmed);
      setFailed({ text: trimmed, mode, reload: failure instanceof ApiError && failure.reload });
      setError(failure instanceof ApiError ? failure.message : "Something went wrong. Please try again.");
    } finally {
      if (mine === asking.current) {
        busy.current = false;
        setPending(null);
      }
    }
  }, [api, go]);

  /** Gives up the question being answered. It goes back into the box, to change or to ask again. */
  const stop = useCallback(() => {
    if (!busy.current) return;
    asking.current += 1;
    api.stop?.();
    busy.current = false;
    if (pending) setQuestion(pending);
    setPending(null);
    setStopped(true);
    box.current?.focus();
  }, [api, pending]);

  const closePage = useCallback(() => {
    setPage(null);
    // The keyboard goes back to the source that was opened, or to the evidence when that source is no longer drawn.
    window.requestAnimationFrame(() => {
      const opener = pageOpener.current;
      if (opener?.isConnected) opener.focus();
      else document.getElementById("evidence-title")?.focus();
      pageOpener.current = null;
    });
  }, []);

  const openSource = useCallback(async (answer: AnswerOut, citation: Citation) => {
    if (citation.page === null) return;
    setSelected(answer.id);
    if (document.activeElement instanceof HTMLElement && document.activeElement !== document.body) pageOpener.current = document.activeElement;
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
    const opener = guideOpener.current;
    guideOpener.current = null;
    if (opener?.isConnected) opener.focus();
    else box.current?.focus();
  }, []);

  const openGuide = useCallback(() => {
    guideOpener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setGuide(true);
  }, []);

  const load = useCallback(() => {
    setUnreachable(false);
    api.health().then(setHealth).catch(() => setUnreachable(true));
    api.wells().then(setWells).catch(() => setWells([]));
  }, [api]);

  /** Asks whether a question could be answered now. A server that cannot say is taken to be ready. */
  const checkReady = useCallback(() => {
    api.ready?.().then((state) => setNotReady(!state.ready)).catch(() => setNotReady(false));
  }, [api]);

  // While it is not ready, look again once a minute, so the notice goes by itself when the trouble does.
  useEffect(() => {
    if (!notReady) return;
    const timer = window.setInterval(checkReady, 60_000);
    return () => window.clearInterval(timer);
  }, [notReady, checkReady]);

  // What is loaded, and a question the link may carry: ?q=...&graph=1
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    load();
    checkReady();
    const params = new URLSearchParams(window.location.search);
    const linked = params.get("q");
    // A link to a well or to the questions page opens just that page; the guide waits for the start.
    const onStart = readRoute(window.location.search).view === "home";
    if (onStart && linked) {
      const exact = params.get("graph") === "1";
      setVerifiedOnly(exact);
      void ask(linked, exact ? "exact" : "allow_fallback");
    } else if (onStart && restore().length === 0 && firstVisit()) {
      setGuide(true); // A first visit with nothing asked: show how it works. It can always be closed.
    }
  }, [api, ask, load, checkReady]);

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
      } else if (event.key === "Escape" && document.querySelector(".answers ~ .evidence #page-title")) {
        closePage();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closePage]);

  function submit(event: FormEvent) {
    event.preventDefault();
    void ask(question, verifiedOnly ? "exact" : "allow_fallback");
  }

  const current = answers.find((answer) => answer.id === selected) ?? null;
  const mode: Mode = verifiedOnly ? "exact" : "allow_fallback";
  const home = route.view === "home";
  const fresh = home && answers.length === 0 && pending === null;
  const waiting = home && pending !== null;

  useStickyColumn(column, `${route.view} ${waiting} ${current?.id ?? ""} ${narrow}`);

  // Each screen has its own name on the browser tab, in the history and at the head of a printed page.
  useEffect(() => {
    let screen: string | null = null;
    if (route.view === "well") screen = `Well ${route.well}`;
    else if (route.view === "questions") screen = "Questions people asked";
    else if (pending !== null) screen = pending;
    else if (current) screen = `${current.question} ${headline(current)}`;
    document.title = pageTitle(screen);
  }, [route, pending, current]);

  // A new screen starts at its heading for the keyboard and a screen reader, as a new page would.
  const firstScreen = useRef(true);
  useEffect(() => {
    if (firstScreen.current) {
      firstScreen.current = false;
      return;
    }
    if (route.view === "home") box.current?.focus({ preventScroll: true });
    else document.querySelector<HTMLElement>("#main h1")?.focus({ preventScroll: true });
  }, [route]);

  const earlier = answers.length > 1 && (
    <section className="earlier" aria-labelledby="earlier">
      <h2 id="earlier">Your earlier questions</h2>
      <ul>
        {answers.filter((answer) => answer.id !== selected).map((answer) => (
          <li key={answer.id}>
            <button
              type="button"
              className="earlier__item"
              title={answer.question}
              onClick={() => {
                setSelected(answer.id);
                setArrived(answer.id);
                setPage(null);
              }}
            >
              <span>{answer.question}</span>{" "}
              <strong className={answer.status === "answered" ? "" : "earlier__none"}>{headline(answer)}</strong>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
  const startOver = (
    <button
      type="button"
      className="link answers__clear"
      onClick={() => {
        setAnswers([]);
        setSelected(null);
        setPage(null);
        box.current?.focus();
      }}
    >
      Start over
    </button>
  );

  return (
    <div className="app">
      <a className="skip" href="#main">Skip to the content</a>
      <header className="top">
        <div className="top__inner">
          <RouteLink to={HOME} onGo={go} className="brand"><span className="brand__mark" aria-hidden="true" /><span className="brand__name">{APP_NAME}</span></RouteLink>
          <nav className="top__nav" aria-label="Pages">
            <RouteLink to={{ view: "questions", question: null }} onGo={go} className="top__quiet" label="Questions people asked">Questions<span className="top__more">&nbsp;people asked</span></RouteLink>
            <button type="button" className="chip chip--plain top__help" onClick={openGuide}>
              <Icon name="help" size={18} /> <span className="top__label">How it works</span>
            </button>
          </nav>
        </div>
      </header>

      {/* The questions page is for the team; it has its own search, so the question box is not shown there. */}
      <section className={fresh ? "hero hero--fresh" : "hero"} aria-label="Ask a question" hidden={route.view === "questions"}>
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
          {!fresh && home && <h1 className="visually-hidden">{APP_NAME}</h1>}
          <form className="ask" role="search" onSubmit={submit}>
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
                enterKeyHint="search"
                placeholder="For example: how many hours did AK-3 spend drilling in August 2016?"
                value={question}
                onChange={(event) => {
                  setQuestion(event.target.value);
                  setStopped(false);
                }}
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
              {examples && !fresh && <p className="notice notice--inline"><Icon name="info" size={16} /> {DEMO.short}</p>}
            </div>
            {error && (
              <p role="alert" className="error">
                <Icon name="alert" size={18} /> <span>{error}</span>
                {failed && (failed.reload ? (
                  <button type="button" className="link" onClick={() => window.location.reload()}>Reload the page</button>
                ) : (
                  <button type="button" className="link" onClick={() => void ask(failed.text, failed.mode)}>Try again</button>
                ))}
              </p>
            )}
            {stopped && !error && <p role="status" className="notice"><Icon name="info" size={16} /> {WAITING.stopped}</p>}
          </form>
          {examples && fresh && <p className="notice"><Icon name="info" size={16} /> {DEMO.full}</p>}
          {notReady && !unreachable && pending === null && (
            <p className="notice notice--warn" role="status"><Icon name="alert" size={16} /> <span>{NOT_READY}{" "}
              <button type="button" className="link" onClick={checkReady}>Check again</button></span>
            </p>
          )}
          {unreachable && !examples && (
            <p className="notice notice--warn"><Icon name="alert" size={16} /> <span>We can’t reach the server right now. Please try again in a moment.{" "}
              <button type="button" className="link" onClick={load}>Try again</button></span>
            </p>
          )}
        </div>
      </section>

      <main id="main" tabIndex={-1} className="main">
        {waiting ? (
          <div className="start"><Waiting question={pending} seconds={waited} onStop={stop} /></div>
        ) : route.view === "questions" ? (
          <Questions api={api} opened={route.question} onOpen={(question) => go({ view: "questions", question })} />
        ) : route.view === "well" ? (
          <Well key={route.well} api={api} wellId={route.well} onBack={back} />
        ) : fresh ? (
          <div className="start">
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
                <p className="note">
                  {health && (
                    <>
                      {health.data.end_of_well_chunks} passages from end-of-well reports and {health.data.events} logged
                      daily activities are loaded.{" "}
                    </>
                  )}
                  Click a well’s name to see everything we know about it.
                </p>
                <div className="scroll">
                  <table className="data" aria-label="Wells loaded">
                    <thead>
                      <tr>
                        <th scope="col">Well</th>
                        <th scope="col" className="num">Key facts <Tip about="key facts">{EXPLAIN.keyFacts}</Tip></th>
                        <th scope="col" className="num">Days of daily reports</th>
                      </tr>
                    </thead>
                    <tbody>
                      {wells.map((well) => (
                        <tr key={well.well_id}>
                          <th scope="row"><RouteLink to={{ view: "well", well: well.well_id }} onGo={go}>{well.well_id}</RouteLink></th>
                          <td className="num">{well.facts}</td><td className="num">{well.report_days}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
          </div>
        ) : (
          answers.length > 0 && (
            <div className="work">
              <div className="answers" ref={column}>
                {current && <Answer key={current.id} answer={current} arrive={arrived === current.id} onOpenSource={openSource} onFeedback={feedback} onAsk={ask} onShowEvidence={showEvidence} />}
                {/* Beside the evidence on a wide screen; on a narrow one the evidence comes first, then these. */}
                {!narrow && earlier}
                {!narrow && startOver}
              </div>
              {current && (
                <Evidence key={current.id} answer={current} page={page} pageChunk={pageChunk} onOpenPage={(chunk) => void openSource(current, { ...chunk, how: "model" })} onClosePage={closePage} pointed={pointed?.answer === current.id ? pointed : null} onGo={go} />
              )}
              {narrow && <div className="answers answers--after">{earlier}{startOver}</div>}
            </div>
          )
        )}
      </main>

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
