import { memo, useEffect, useRef, useState } from "react";
import type { AnswerOut, Citation, Verdict } from "../api/types";
import { advice, basis, checked, cost, headline, reportName, trail } from "../lib/wording";

const SHOWN = 4;

interface Props {
  answer: AnswerOut;
  /** Move the keyboard and screen reader to this answer: it has just arrived. */
  arrive: boolean;
  onOpenSource: (answer: AnswerOut, citation: Citation) => void;
  onFeedback: (answerId: string, verdict: Verdict, comment: string) => Promise<void>;
}

/** The open answer: the value, where it came from, how it was reached, its sources, and a way to mark it. */
export const Answer = memo(function Answer({ answer, arrive, onOpenSource, onFeedback }: Props) {
  const [writing, setWriting] = useState(false);
  const [comment, setComment] = useState("");
  const [saved, setSaved] = useState<Verdict | null>(null);
  const [failed, setFailed] = useState(false);
  const [allSources, setAllSources] = useState(false);
  const [copied, setCopied] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const next = advice(answer);
  // A computed answer can rest on dozens of passages; the first few are enough until someone asks for all.
  const sources = allSources ? answer.citations : answer.citations.slice(0, SHOWN);

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
    <section className="answer" aria-label="Answer">
      <p className="answer__question">{answer.question}</p>
      <h2 ref={heading} tabIndex={-1} className={answer.status === "answered" ? "answer__value" : "answer__value answer__value--none"}>
        {headline(answer)}
      </h2>
      <p className="answer__basis">{basis(answer)}</p>
      {next && <p className="answer__advice">{next}</p>}

      <div className="answer__how">
        <h3>How this was answered</h3>
        <ol className="trail" aria-label="How this was answered">
          {trail(answer).map((step) => (
            <li key={step.title}>
              <span className="trail__title">{step.title}</span>
              <span className="trail__detail">{step.detail}</span>
            </li>
          ))}
        </ol>
        <p className="answer__meta">
          {answer.mode === "exact" && <span className="tag">Graph answers only</span>}
          <span>{cost(answer)}</span>
        </p>
        {answer.evidence.model_note && answer.status === "answered" && (
          <p className="answer__note"><span>The model’s reading:</span> {answer.evidence.model_note}</p>
        )}
      </div>

      {answer.citations.length > 0 && (
        <>
          <h3>Sources</h3>
          <ol className="sources" aria-label="Sources">
            {sources.map((citation, index) => (
              <li key={`${citation.chunk_id}-${index}`}>
                <button
                  type="button"
                  className="source"
                  aria-label={`Source ${index + 1}: ${reportName(citation.file_id)}${citation.page === null ? "" : `, page ${citation.page}`}`}
                  disabled={citation.page === null || citation.text === null}
                  onClick={() => onOpenSource(answer, citation)}
                >
                  <span className="source__number">{index + 1}</span>
                  <span className="source__where">
                    {reportName(citation.file_id)}{citation.page === null ? "" : `, page ${citation.page}`}
                    <small>{checked(citation)}</small>
                  </span>
                </button>
              </li>
            ))}
          </ol>
          {!allSources && answer.citations.length > SHOWN && (
            <button type="button" className="link sources__more" onClick={() => setAllSources(true)}>
              Show all {answer.citations.length} sources
            </button>
          )}
        </>
      )}

      <div className="feedback">
        {saved ? (
          <p className="feedback__saved">Saved as {saved}.</p>
        ) : writing ? (
          <form
            className="feedback__form"
            onSubmit={(event) => {
              event.preventDefault();
              void save("wrong", comment.trim());
            }}
          >
            <label htmlFor={`comment-${answer.id}`}>What should it say?</label>
            <textarea id={`comment-${answer.id}`} rows={2} maxLength={2000} autoFocus value={comment} onChange={(event) => setComment(event.target.value)} />
            <div className="feedback__buttons">
              <button type="submit" className="button button--small">Save</button>
              <button type="button" className="link" onClick={() => setWriting(false)}>Cancel</button>
            </div>
          </form>
        ) : (
          <div className="feedback__buttons">
            <span>Is this answer right?</span>
            <button type="button" className="button button--quiet" onClick={() => void save("right", "")}>Right</button>
            <button type="button" className="button button--quiet" onClick={() => setWriting(true)}>Wrong</button>
            <button type="button" className="link feedback__copy" onClick={() => void copyLink()}>{copied ? "Link copied" : "Copy a link to this question"}</button>
          </div>
        )}
        {failed && <p role="alert" className="error">Your mark was not saved. Check the connection and try again.</p>}
      </div>
    </section>
  );
});
