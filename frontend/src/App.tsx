import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, type Api } from "./api/client";
import type { AnswerOut, ChunkOut, Health, Mode, PageOut } from "./api/types";
import { Answer } from "./components/Answer";
import { Evidence } from "./components/Evidence";

// One of each kind of question the system answers, on the reports loaded for the demonstration.
const TRY = [
  "How many hours of non-productive time did AK-3 have?",
  "What total depth did well AK-3 reach?",
  "Which of AK-3, 56-32 and 68-32 was drilled deepest?",
];

function loaded(health: Health): string {
  const data = health.data;
  return `${data.wells} wells, ${data.end_of_well_chunks} end-of-well passages, ${data.events} daily operations and ${data.facts} checked facts are loaded.`;
}

export default function App({ api, examples = false }: { api: Api; examples?: boolean }) {
  const [question, setQuestion] = useState("");
  const [graphOnly, setGraphOnly] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answers, setAnswers] = useState<AnswerOut[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [page, setPage] = useState<PageOut | null>(null);
  const [pageChunk, setPageChunk] = useState<string | null>(null);
  const started = useRef(false);

  async function ask(text: string, mode: Mode) {
    const trimmed = text.trim();
    if (!trimmed || asking) return;
    setAsking(true);
    setError(null);
    try {
      const answer = await api.ask(trimmed, mode);
      setAnswers((earlier) => [answer, ...earlier]);
      setSelected(answer.id);
      setPage(null);
      setQuestion("");
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : "Something went wrong while asking. Try again.");
    } finally {
      setAsking(false);
    }
  }

  async function openPage(chunk: ChunkOut) {
    if (chunk.page === null) return;
    try {
      setPage(await api.page(chunk.file_id, chunk.page));
      setPageChunk(chunk.chunk_id);
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : "That page could not be opened.");
    }
  }

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    api.health().then(setHealth).catch(() => setHealth(null));
    // A link can carry a question: ?q=...&graph=1
    const params = new URLSearchParams(window.location.search);
    const linked = params.get("q");
    if (linked) {
      setGraphOnly(params.get("graph") === "1");
      void ask(linked, params.get("graph") === "1" ? "exact" : "allow_fallback");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    void ask(question, graphOnly ? "exact" : "allow_fallback");
  }

  const current = answers.find((answer) => answer.id === selected) ?? null;

  return (
    <div className="app">
      <header className="masthead">
        <h1>Drilling reports</h1>
        <p>
          Ask a question about the end-of-well and daily drilling reports. Every answer shows the passages or
          operations it rests on.
        </p>
        {health && <p className="masthead__loaded">{loaded(health)}</p>}
        {examples && (
          <p className="masthead__examples">
            Example answers. No language model is connected: the evidence is real, and each answer is a prepared one.
          </p>
        )}
      </header>

      <form className="ask" onSubmit={submit}>
        <label htmlFor="question">Ask about the reports</label>
        <div className="ask__row">
          <input
            id="question"
            type="text"
            maxLength={500}
            autoComplete="off"
            placeholder="For example: how many hours did AK-3 spend drilling in August 2016?"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
          />
          <button type="submit" className="button" disabled={asking}>{asking ? "Asking" : "Ask"}</button>
        </div>
        <label className="switch">
          <input type="checkbox" checked={graphOnly} onChange={(event) => setGraphOnly(event.target.checked)} />
          <span>
            Graph answers only
            <small>Answer from stored facts and daily operations. Do not fall back to searching the report text.</small>
          </span>
        </label>
        {error && <p role="alert" className="error">{error}</p>}
      </form>

      {answers.length === 0 ? (
        <section className="start" aria-label="Questions to try">
          <h2>Questions to try</h2>
          <ul>
            {TRY.map((text) => (
              <li key={text}>
                <button type="button" className="try" disabled={asking} onClick={() => void ask(text, graphOnly ? "exact" : "allow_fallback")}>
                  {text}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <main className="work">
          <div className="answers">
            {answers.map((answer) => (
              <Answer
                key={answer.id}
                answer={answer}
                selected={answer.id === selected}
                onSelect={() => {
                  setSelected(answer.id);
                  setPage(null);
                }}
                onOpenSource={(citation) => {
                  setSelected(answer.id);
                  void openPage(citation);
                }}
                onFeedback={(verdict, comment) => api.feedback(answer.id, verdict, comment)}
              />
            ))}
          </div>
          {current && (
            <Evidence answer={current} page={page} pageChunk={pageChunk} onOpenPage={(chunk) => void openPage(chunk)} onClosePage={() => setPage(null)} />
          )}
        </main>
      )}
    </div>
  );
}
