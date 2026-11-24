import { memo, useEffect, useRef, useState } from "react";
import type { AnswerOut, Citation, Verdict } from "../api/types";
import { advice, badge, distinctSources, EXPLAIN, headline, place, sourceNote, steps, summary, technical } from "../lib/wording";
import { Icon, type IconName } from "./Icon";
import { Tip } from "./Tip";

const SHOWN = 3;
const BADGE_ICON: Record<ReturnType<typeof badge>["tone"], IconName> = {
  calculated: "calculator",
  ai: "sparkle",
  unconfirmed: "alert",
  none: "empty",
};

interface Props {
  answer: AnswerOut;
  /** Move the keyboard and screen reader to this answer: it has just arrived. */
  arrive: boolean;
  onOpenSource: (answer: AnswerOut, citation: Citation) => void;
  onFeedback: (answerId: string, verdict: Verdict, comment: string) => Promise<void>;
}

/** The open answer: how far to trust it, the value, what it is based on, its sources, and a way to rate it. */
export const Answer = memo(function Answer({ answer, arrive, onOpenSource, onFeedback }: Props) {
  const [writing, setWriting] = useState(false);
  const [comment, setComment] = useState("");
  const [saved, setSaved] = useState<Verdict | null>(null);
  const [failed, setFailed] = useState(false);
  const [allSources, setAllSources] = useState(false);
  const [copied, setCopied] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const trust = badge(answer);
  const next = advice(answer);
  // Each report or page once; the first few are enough until someone asks for all.
  const distinct = distinctSources(answer.citations);
  const sources = allSources ? distinct : distinct.slice(0, SHOWN);

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

  async function copyLink() {
    const link = new URL(window.location.href);
    link.search = new URLSearchParams({ q: answer.question, ...(answer.mode === "exact" ? { graph: "1" } : {}) }).toString();
    try {
      await navigator.clipboard.writeText(link.toString());
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section className="answer card" aria-label="Answer">
      <p className="answer__question">{answer.question}</p>
      <p className={`badge badge--${trust.tone}`}>
        <Icon name={BADGE_ICON[trust.tone]} size={16} /> {trust.label}
        <Tip about={trust.label.toLowerCase()}>{trust.tip}</Tip>
      </p>
      <h2 ref={heading} tabIndex={-1} className={answer.status === "answered" ? "answer__value" : "answer__value answer__value--none"}>
        {headline(answer)}
      </h2>
      <p className="answer__summary">{summary(answer)}</p>
      {next && <p className="answer__advice"><Icon name="info" size={16} /> {next}</p>}
      {answer.mode === "exact" && (
        <p className="answer__mode">
          Verified data only <Tip about="verified data only">{EXPLAIN.verifiedOnly}</Tip>
        </p>
      )}

      {distinct.length > 0 && (
        <div className="answer__block">
          <h3>Where this comes from</h3>
          <ol className="sources" aria-label="Sources">
            {sources.map((citation, index) => {
              const openable = citation.page !== null && citation.text !== null;
              return (
                <li key={`${citation.chunk_id}-${index}`}>
                  <button
                    type="button"
                    className="source"
                    aria-label={`Source ${index + 1}: ${place(citation.file_id, citation.page)}`}
                    disabled={!openable}
                    onClick={() => onOpenSource(answer, citation)}
                  >
                    <span className="source__icon"><Icon name="document" size={18} /></span>
                    <span className="source__where">
                      {place(citation.file_id, citation.page)}
                      <small>{sourceNote(citation)}</small>
                    </span>
                    {openable && <span className="source__open">Open page <Icon name="open" size={14} /></span>}
                  </button>
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
            <button type="button" className="chip chip--plain feedback__copy" onClick={() => void copyLink()}>
              <Icon name={copied ? "check" : "link"} size={16} /> {copied ? "Link copied" : "Copy link"}
            </button>
          </div>
        )}
        {failed && <p role="alert" className="error">We couldn’t save that. Check your connection and try again.</p>}
      </div>
    </section>
  );
});
