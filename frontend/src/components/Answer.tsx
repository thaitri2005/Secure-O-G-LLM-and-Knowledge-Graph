import { memo, useEffect, useRef, useState } from "react";
import type { AnswerOut, Citation, Mode, Verdict } from "../api/types";
import { reask, reasoningOf } from "../lib/cause";
import {
  advice, badge, COPY, distinctSources, EXPLAIN, headline, NO_SOURCES, place, PRINTED_FROM, sourceNote, steps, summary, technical,
} from "../lib/wording";
import { AskWhich, CauseAnswer } from "./Cause";
import { Icon, type IconName } from "./Icon";
import { Tip } from "./Tip";

const SHOWN = 3;
const BADGE_ICON: Record<ReturnType<typeof badge>["tone"], IconName> = {
  calculated: "calculator",
  ai: "sparkle",
  unconfirmed: "alert",
  none: "empty",
  choose: "help",
};

const NOTHING = () => {};

interface Props {
  answer: AnswerOut;
  /** Move the keyboard and screen reader to this answer: it has just arrived. */
  arrive: boolean;
  onOpenSource: (answer: AnswerOut, citation: Citation) => void;
  onFeedback: (answerId: string, verdict: Verdict, comment: string) => Promise<void>;
  /** Ask a question: used when the reader picks one of several problems. */
  onAsk?: (question: string, mode: Mode) => void;
  /** Show a piece of the evidence a cause rests on. */
  onShowEvidence?: (answerId: string, label: string) => void;
}

/** The open answer: how far to trust it, the value, what it is based on, its sources, and a way to rate it. */
export const Answer = memo(function Answer({ answer, arrive, onOpenSource, onFeedback, onAsk = NOTHING, onShowEvidence = NOTHING }: Props) {
  const [writing, setWriting] = useState(false);
  const [comment, setComment] = useState("");
  const [saved, setSaved] = useState<Verdict | null>(null);
  const [failed, setFailed] = useState(false);
  const [allSources, setAllSources] = useState(false);
  const [copied, setCopied] = useState<"done" | "failed" | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const trust = badge(answer);
  const next = advice(answer);
  // Each report or page once; the first few are enough until someone asks for all.
  const distinct = distinctSources(answer.citations);
  const sources = allSources ? distinct : distinct.slice(0, SHOWN);
  // A question about a cause is answered in parts, each cause with its own sources; or with choices to pick from.
  const reasoning = reasoningOf(answer);
  const choosing = reasoning !== null && answer.status === "ask_which";
  const causes = reasoning !== null && !choosing && answer.status !== "invalid";

  useEffect(() => {
    if (arrive) heading.current?.focus();
  }, [arrive, answer.id]);

  async function save(verdict: Verdict, text: string) {
    setFailed(false);
    try {
      await onFeedback(answer.id, verdict, text);
      setSaved(verdict);
      setWriting(false);
    } catch {
      setFailed(true);
    }
  }

  // A link that asks this question again: what "Copy link" copies, and what is printed under the answer on paper.
  const link = new URL(window.location.href);
  link.search = new URLSearchParams({ q: answer.question, ...(answer.mode === "exact" ? { graph: "1" } : {}) }).toString();

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(link.toString());
      setCopied("done");
    } catch {
      setCopied("failed");
    }
  }

  // The confirmation shows for a few seconds, then the button is itself again.
  useEffect(() => {
    if (copied !== "done") return;
    const timer = window.setTimeout(() => setCopied(null), 4000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  return (
    <section className="answer card" aria-label="Answer">
      <p className="visually-hidden">You asked:</p>
      <p className="answer__question">{answer.question}</p>
      <p className={`badge badge--${trust.tone}`}>
        <Icon name={BADGE_ICON[trust.tone]} size={16} /> {trust.label}
        <Tip about={trust.label.toLowerCase()}>{trust.tip}</Tip>
      </p>
      <h2 ref={heading} tabIndex={-1} className={answer.status === "answered" && !reasoning ? "answer__value" : "answer__value answer__value--none"}>
        {headline(answer)}
      </h2>
      <p className="answer__summary">{summary(answer)}</p>
      {next && <p className="answer__advice"><Icon name="info" size={16} /> {next}</p>}
      {answer.mode === "exact" && (
        <p className="answer__mode">
          Verified data only <Tip about="verified data only">{EXPLAIN.verifiedOnly}</Tip>
        </p>
      )}

      {choosing && <AskWhich reasoning={reasoning} onChoose={(index) => onAsk(reask(answer.question, reasoning.candidates[index]), answer.mode)} />}
      {causes && <CauseAnswer answer={answer} reasoning={reasoning} onOpenSource={onOpenSource} onShowEvidence={(label) => onShowEvidence(answer.id, label)} />}

      {!reasoning && distinct.length > 0 && (
        <div className="answer__block">
          <h3>Where this comes from</h3>
          <ol className="sources" aria-label="Sources">
            {sources.map((citation, index) => {
              const openable = citation.page !== null && citation.text !== null;
              return (
                <li key={`${citation.chunk_id}-${index}`} className={openable ? "sources__item" : "sources__item sources__item--off"}>
                  <span className="source__icon"><Icon name="document" size={18} /></span>
                  <span className="source__where">
                    {/* The button is the report's name, and it is pressed anywhere on the row (styles.css). */}
                    <button
                      type="button"
                      className="source"
                      aria-label={`Source ${index + 1}: ${place(citation.file_id, citation.page)}`}
                      aria-describedby={`source-note-${answer.id}-${index}`}
                      disabled={!openable}
                      onClick={() => onOpenSource(answer, citation)}
                    >
                      {place(citation.file_id, citation.page)}
                    </button>
                    <small id={`source-note-${answer.id}-${index}`}>{sourceNote(citation)}</small>
                  </span>
                  {openable && <span className="source__open" aria-hidden="true">Open page <Icon name="open" size={14} /></span>}
                </li>
              );
            })}
          </ol>
          {!allSources && distinct.length > SHOWN && (
            <button type="button" className="link sources__more" onClick={() => setAllSources(true)}>
              Show all {distinct.length} sources
            </button>
          )}
        </div>
      )}

      {!reasoning && distinct.length === 0 && answer.status === "answered" && (
        <div className="answer__block">
          <h3>Where this comes from</h3>
          <p className="note">{NO_SOURCES}</p>
        </div>
      )}

      <details className="how">
        <summary>How we got this answer</summary>
        <ol className="trail" aria-label="How we got this answer">
          {steps(answer).map((step) => (
            <li key={step.title}>
              <span className="trail__title">{step.title}</span>
              <span className="trail__detail">{step.detail}</span>
            </li>
          ))}
        </ol>
        <p className="how__technical">Technical details: {technical(answer)}.</p>
      </details>

      {!choosing && (
        <div className="feedback">
          {saved ? (
            <p className="feedback__saved"><Icon name="check" size={16} /> Thank you. Saved as {saved === "right" ? "helpful" : "wrong"}.</p>
          ) : writing ? (
            <form
              className="feedback__form"
              onSubmit={(event) => {
                event.preventDefault();
                void save("wrong", comment.trim());
              }}
            >
              <label htmlFor={`comment-${answer.id}`}>What should the answer be? (optional)</label>
              <textarea id={`comment-${answer.id}`} rows={2} maxLength={2000} autoFocus value={comment} onChange={(event) => setComment(event.target.value)} />
              <div className="feedback__buttons">
                <button type="submit" className="button button--small">Send</button>
                <button type="button" className="link" onClick={() => setWriting(false)}>Cancel</button>
              </div>
            </form>
          ) : (
            <div className="feedback__buttons">
              <span className="feedback__ask">Was this answer right?</span>
              <button type="button" className="chip" onClick={() => void save("right", "")}><Icon name="thumbUp" size={16} /> Yes</button>
              <button type="button" className="chip" onClick={() => setWriting(true)}><Icon name="thumbDown" size={16} /> No, it’s wrong</button>
              <button
                type="button"
                className={copied === "done" ? "chip chip--plain feedback__copy feedback__copy--done" : "chip chip--plain feedback__copy"}
                onClick={() => void copyLink()}
              >
                <Icon name={copied === "done" ? "check" : "link"} size={16} /> {copied === "done" ? COPY.done : COPY.ask}
              </button>
            </div>
          )}
          {copied && (
            <p role="status" className={copied === "failed" ? "note feedback__copy-note" : "visually-hidden"}>
              {copied === "done" ? COPY.announced : COPY.failed}
            </p>
          )}
          {failed && <p role="alert" className="error">We couldn’t save that. Check your connection and try again.</p>}
        </div>
      )}
      <p className="print-only answer__printed">{PRINTED_FROM} {link.toString()}</p>
    </section>
  );
});
