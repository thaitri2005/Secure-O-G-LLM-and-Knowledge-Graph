import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, type Api, type QuestionFilters } from "../api/client";
import type { LoggedQuestion, LoggedQuestionDetail, QuestionCounts } from "../api/types";
import {
  askedAt, citedReports, countTiles, emptyLog, ENDED, KIND, kindName, loggedAnswer, loggedBadge, markLabel, showing,
} from "../lib/wording";
import { Icon, type IconName } from "./Icon";
import { Tip } from "./Tip";

export const PAGE_SIZE = 20;

const BADGE_ICON: Record<string, IconName> = { calculated: "calculator", ai: "sparkle", unconfirmed: "alert", none: "empty", choose: "help" };

const MARKS: { value: QuestionFilters["verdict"] | ""; label: string }[] = [
  { value: "", label: "Any" },
  { value: "right", label: "Marked right" },
  { value: "wrong", label: "Marked wrong" },
  { value: "none", label: "Not marked" },
];

interface Props {
  api: Api;
  /** The question opened, or null for the list. */
  opened: string | null;
  onOpen: (questionId: string | null) => void;
}

/**
 * For the team and the advisors: the questions people asked here, how each was answered and how it was marked. It
 * only reads: nothing on it changes or deletes anything. The selection can be saved as a question set, the start
 * of a test written from real questions.
 */
export function Questions({ api, opened, onOpen }: Props) {
  if (opened) return <Opened api={api} questionId={opened} onBack={() => onOpen(null)} />;
  return <List api={api} onOpen={onOpen} />;
}

function List({ api, onOpen }: { api: Api; onOpen: (questionId: string) => void }) {
  const [filters, setFilters] = useState<QuestionFilters>({});
  const [typed, setTyped] = useState("");
  const [offset, setOffset] = useState(0);
  const [found, setFound] = useState<{ questions: LoggedQuestion[]; total: number } | null>(null);
  const [counts, setCounts] = useState<QuestionCounts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const latest = useRef(0);
  const sought = useRef("");

  const load = useCallback(async () => {
    const asking = ++latest.current;
    setError(null);
    try {
      const [page, counted] = await Promise.all([api.questions(filters, PAGE_SIZE, offset), api.questionCounts(filters)]);
      if (asking !== latest.current) return;
      setFound({ questions: page.questions, total: page.total });
      setCounts(counted);
    } catch (failure) {
      if (asking === latest.current) setError(failure instanceof ApiError ? failure.message : "We couldn’t read the questions.");
    }
  }, [api, filters, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  // The search applies a moment after typing stops, not on every key.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const words = typed.trim();
      // Only a change of the words starts the list again from its first page; otherwise paging would be undone.
      if ((sought.current ?? "") === words) return;
      sought.current = words;
      setFilters((now) => ({ ...now, q: words || undefined }));
      setOffset(0);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [typed]);

  function choose(change: Partial<QuestionFilters>) {
    setFilters((now) => ({ ...now, ...change }));
    setOffset(0);
    setSaved(null);
  }

  async function download() {
    setSaving(true);
    setError(null);
    try {
      const file = await api.exportQuestions(filters);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(new Blob([file.text], { type: "application/json" }));
      link.download = file.filename;
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(link.href);
      setSaved(file.filename);
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : "We couldn’t make the file.");
    } finally {
      setSaving(false);
    }
  }

  const filtered = Boolean(filters.kind || filters.status || filters.verdict || filters.q || filters.date_from || filters.date_to);

  return (
    <div className="log">
      <h1 className="log__title" tabIndex={-1}>Questions people asked</h1>
      <p className="log__lead">
        Every question asked here, the answer it got, and how people marked it. This page is for the project team and
        the advisors. It only shows: nothing here can be changed or deleted.
      </p>

      {counts && (
        <dl className="log__counts" aria-label="Counts">
          {countTiles(counts).map((tile) => (
            <div key={tile.label} className="card log__count">
              <dt>{tile.label}</dt>
              <dd>{tile.value}</dd>
            </div>
          ))}
        </dl>
      )}

      <form className="card log__filters" role="search" aria-label="Filter the questions" onSubmit={(event) => event.preventDefault()}>
        <label className="log__field">
          <span>Kind of question</span>
          <select value={filters.kind ?? ""} onChange={(event) => choose({ kind: event.target.value || undefined })}>
            <option value="">Any</option>
            {Object.entries(KIND).map(([kind, name]) => <option key={kind} value={kind}>{name}</option>)}
          </select>
        </label>
        <label className="log__field">
          <span>How it ended</span>
          <select value={filters.status ?? ""} onChange={(event) => choose({ status: (event.target.value || undefined) as QuestionFilters["status"] })}>
            {ENDED.map((end) => <option key={end.label} value={end.value}>{end.label}</option>)}
          </select>
        </label>
        <label className="log__field">
          <span>How it was marked</span>
          <select value={filters.verdict ?? ""} onChange={(event) => choose({ verdict: (event.target.value || undefined) as QuestionFilters["verdict"] })}>
            {MARKS.map((mark) => <option key={mark.label} value={mark.value}>{mark.label}</option>)}
          </select>
        </label>
        <label className="log__field log__field--wide">
          <span>Words in the question</span>
          <input type="search" value={typed} maxLength={200} placeholder="For example: stuck pipe" onChange={(event) => setTyped(event.target.value)} />
        </label>
        <label className="log__field">
          <span>Asked from</span>
          <input type="date" value={filters.date_from ?? ""} onChange={(event) => choose({ date_from: event.target.value || undefined })} />
        </label>
        <label className="log__field">
          <span>Asked until</span>
          <input type="date" value={filters.date_to ?? ""} onChange={(event) => choose({ date_to: event.target.value || undefined })} />
        </label>
        {filtered && (
          <button
            type="button"
            className="link log__clear"
            onClick={() => {
              setTyped("");
              sought.current = "";
              setFilters({});
              setOffset(0);
              setSaved(null);
            }}
          >
            Clear the filters
          </button>
        )}
      </form>

      <div className="log__export">
        <button type="button" className="button button--small" disabled={saving || found?.total === 0} onClick={() => void download()}>
          <Icon name="document" size={16} /> Download these as a question set
        </button>
        <p className="note">
          A file of the questions the filters select, with a place for the right answer to each. Once someone writes the
          right answers into it, it becomes a test the system can be run against.
        </p>
        {saved && <p className="feedback__saved" role="status"><Icon name="check" size={16} /> Saved as {saved}.</p>}
      </div>

      {error && (
        <p role="alert" className="error">
          <Icon name="alert" size={18} /> <span>{error}</span>
          <button type="button" className="link" onClick={() => void load()}>Try again</button>
        </p>
      )}

      {found === null && !error && <p className="note" role="status">Reading the questions…</p>}
      {found && (
        <section aria-labelledby="log-list">
          <h2 id="log-list" className="log__showing">{showing(offset, found.questions.length, found.total, filtered)}</h2>
          {found.total === 0 ? (
            <p className="log__empty"><Icon name="info" size={18} /> {emptyLog(filtered)}</p>
          ) : (
            <ol className="log__list" aria-label="Questions">
              {found.questions.map((question) => (
                <li key={question.id}>
                  <button type="button" className="logq" onClick={() => onOpen(question.id)}>
                    <span className="logq__meta">{askedAt(question.asked_at)} · {kindName(question.kind)}</span>{" "}
                    <span className="logq__question">{question.question}</span>
                    <span className="logq__answer">
                      {loggedAnswer(question)}
                      <Mark verdict={question.verdict} />
                      {question.feedback.some((mark) => mark.comment) && (
                        <span className="logq__comments">
                          {question.feedback.filter((mark) => mark.comment).length === 1
                            ? "1 comment"
                            : `${question.feedback.filter((mark) => mark.comment).length} comments`}
                        </span>
                      )}
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          )}
          {found.total > PAGE_SIZE && (
            <div className="log__paging">
              <button type="button" className="chip" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                <Icon name="arrowLeft" size={16} /> Newer
              </button>
              <button type="button" className="chip" disabled={offset + PAGE_SIZE >= found.total} onClick={() => setOffset(offset + PAGE_SIZE)}>
                Older
              </button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function Mark({ verdict }: { verdict: "right" | "wrong" | null }) {
  return <span className={`mark mark--${verdict ?? "none"}`}>{markLabel(verdict)}</span>;
}

function Opened({ api, questionId, onBack }: { api: Api; questionId: string; onBack: () => void }) {
  const [question, setQuestion] = useState<LoggedQuestionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setQuestion(await api.question(questionId));
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : "We couldn’t open that question.");
    }
  }, [api, questionId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (question) heading.current?.focus();
  }, [question]);

  const back = <button type="button" className="back" onClick={onBack}><Icon name="arrowLeft" size={16} /> Back to the list</button>;

  if (error || !question) {
    return (
      <div className="log">
        {back}
        {error ? (
          <p role="alert" className="error">
            <Icon name="alert" size={18} /> <span>{error}</span>
            <button type="button" className="link" onClick={() => void load()}>Try again</button>
          </p>
        ) : (
          <p className="note" role="status">Opening the question…</p>
        )}
      </div>
    );
  }

  const trust = loggedBadge(question, question.record);
  const reports = citedReports(question.record.citations);
  const cost = question.record.cost as { calls?: number; seconds?: number } | undefined;

  return (
    <div className="log">
      {back}
      <article className="card log__detail" aria-labelledby="log-question">
        <p className="answer__question">{askedAt(question.asked_at)} · {kindName(question.kind)}</p>
        <h1 id="log-question" ref={heading} tabIndex={-1} className="log__asked">{question.question}</h1>
        {question.mode === "exact" && <p className="answer__mode">Asked with “Verified data only” on</p>}

        <section className="log__part" aria-labelledby="log-answer">
          <h2 id="log-answer">The answer it got</h2>
          <p className={`badge badge--${trust.tone}`}>
            <Icon name={BADGE_ICON[trust.tone]} size={16} /> {trust.label}
            <Tip about={trust.label.toLowerCase()}>{trust.tip}</Tip>
          </p>
          <p className={question.status === "answered" ? "answer__value" : "answer__value answer__value--none"}>{loggedAnswer(question, question.record)}</p>
          {question.fallback && <p className="note">The daily activity log had no match, so the report text was searched instead.</p>}
          {reports.length > 0 && <p className="note">From: {reports.join("; ")}.</p>}
        </section>

        <section className="log__part" aria-labelledby="log-marks">
          <h2 id="log-marks">Marks and comments</h2>
          {question.feedback.length === 0 ? (
            <p className="note">Nobody has marked this answer yet.</p>
          ) : (
            <ol className="log__marks" aria-label="Marks">
              {question.feedback.map((mark, index) => (
                <li key={index}>
                  <Mark verdict={mark.verdict} />
                  <span className="log__when">{askedAt(mark.at)}</span>
                  {mark.comment ? <q className="log__comment">{mark.comment}</q> : <span className="log__when">No comment</span>}
                </li>
              ))}
            </ol>
          )}
        </section>

        {cost?.calls !== undefined && (
          <p className="how__technical">
            Technical details: {cost.calls === 1 ? "1 AI call" : `${cost.calls} AI calls`}
            {cost.seconds !== undefined ? `, ${cost.seconds < 10 ? cost.seconds.toFixed(1) : Math.round(cost.seconds)} seconds` : ""}.
          </p>
        )}
      </article>
    </div>
  );
}
