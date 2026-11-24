import { useState } from "react";
import type { AnswerOut, Citation, Verdict } from "../api/types";
import { advice, basis, checked, headline, reportName } from "../lib/wording";

const SHOWN = 4;

interface Props {
  answer: AnswerOut;
  selected: boolean;
  onSelect: () => void;
  onOpenSource: (citation: Citation) => void;
  onFeedback: (verdict: Verdict, comment: string) => Promise<void>;
}

/** One question with its answer, where it came from, its sources, and a way to say it is wrong. */
export function Answer({ answer, selected, onSelect, onOpenSource, onFeedback }: Props) {
  const [writing, setWriting] = useState(false);
  const [comment, setComment] = useState("");
  const [saved, setSaved] = useState<Verdict | null>(null);
  const [failed, setFailed] = useState(false);
  const [allSources, setAllSources] = useState(false);
  // A computed answer can rest on dozens of passages; the first few are enough until someone asks for all.
  const sources = allSources ? answer.citations : answer.citations.slice(0, SHOWN);
  const next = advice(answer);

  async function save(verdict: Verdict, text: string) {
    setFailed(false);
    try {
      await onFeedback(verdict, text);
      setSaved(verdict);
      setWriting(false);
    } catch {
      setFailed(true);
    }
  }

  return (
    <section className={selected ? "answer answer--selected" : "answer"} onClick={onSelect}>
      <p className="answer__question">{answer.question}</p>
      <h2 className={answer.status === "answered" ? "answer__value" : "answer__value answer__value--none"}>{headline(answer)}</h2>
      <p className="answer__basis">{basis(answer)}</p>
      {answer.mode === "exact" && <p className="answer__mode">Graph answers only</p>}
      {next && <p className="answer__advice">{next}</p>}
      {answer.evidence.model_note && answer.status === "answered" && (
        <p className="answer__note"><span>The model’s reading:</span> {answer.evidence.model_note}</p>
      )}

      {answer.citations.length > 0 && (
        <ol className="sources" aria-label="Sources">
          {sources.map((citation, index) => (
            <li key={`${citation.chunk_id}-${index}`}>
              <button
                type="button"
                className="source"
                aria-label={`Source ${index + 1}: ${reportName(citation.file_id)}${citation.page === null ? "" : `, page ${citation.page}`}`}
                disabled={citation.page === null || citation.text === null}
                onClick={(event) => {
                  event.stopPropagation();
                  onOpenSource(citation);
                }}
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
      )}
      {!allSources && answer.citations.length > SHOWN && (
        <button
          type="button"
          className="link sources__more"
          onClick={(event) => {
            event.stopPropagation();
            setAllSources(true);
          }}
        >
          Show all {answer.citations.length} sources
        </button>
      )}

      <div className="feedback" onClick={(event) => event.stopPropagation()}>
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
            <textarea id={`comment-${answer.id}`} rows={2} maxLength={2000} value={comment} onChange={(event) => setComment(event.target.value)} />
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
          </div>
        )}
        {failed && <p role="alert" className="error">Your mark was not saved. Check the connection and try again.</p>}
      </div>
    </section>
  );
}
