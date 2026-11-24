import { useEffect, useRef } from "react";
import { Icon, type IconName } from "./Icon";

const ASK: { icon: IconName; title: string; text: string; example: string }[] = [
  {
    icon: "clock",
    title: "Totals over a period",
    text: "Hours, days or counts added up from the daily reports.",
    example: "How many hours of non-productive time did AK-3 have?",
  },
  {
    icon: "document",
    title: "A fact about a well",
    text: "A depth, a date, a casing size: something an end-of-well report states.",
    example: "What total depth did well AK-3 reach?",
  },
  {
    icon: "compare",
    title: "Comparing wells",
    text: "The same fact across several wells.",
    example: "Which of AK-3, 56-32 and 68-32 was drilled deepest?",
  },
  {
    icon: "flag",
    title: "What caused a problem",
    text: "Why a problem such as a stuck pipe happened. You see the cause a report gives, with its words quoted. Other possible factors are listed apart: they are ideas to check, not findings.",
    example: "What caused the stuck pipe on AK-3 on 20 August 2016?",
  },
];

/**
 * A short guide for someone who has never seen the application: what to ask, how to read an answer, how to check
 * it and how to say it is wrong. It opens by itself on the first visit and can always be closed.
 */
export function Guide({ onClose, onTry }: { onClose: () => void; onTry: (question: string) => void }) {
  const close = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    close.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="guide" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="guide__panel" role="dialog" aria-modal="true" aria-labelledby="guide-title">
        <button type="button" ref={close} className="guide__close" aria-label="Close the guide" onClick={onClose}>
          <Icon name="close" size={20} />
        </button>
        <h2 id="guide-title">How it works</h2>
        <p className="guide__lead">
          Ask a question about the drilling reports in your own words. You get an answer, and you can always see
          exactly where it comes from.
        </p>

        <h3>1. Ask a question</h3>
        <ul className="guide__kinds">
          {ASK.map((kind) => (
            <li key={kind.title}>
              <span className="guide__icon"><Icon name={kind.icon} size={20} /></span>
              <div>
                <strong>{kind.title}</strong>
                <p>{kind.text}</p>
                <button type="button" className="guide__try" onClick={() => onTry(kind.example)}>
                  Try: “{kind.example}”
                </button>
              </div>
            </li>
          ))}
        </ul>

        <h3>2. Read the answer</h3>
        <ul className="guide__badges">
          <li>
            <span className="badge badge--calculated"><Icon name="calculator" size={16} /> Calculated from the reports</span>
            <p>The system added the number up itself from the daily reports. No AI wrote it.</p>
          </li>
          <li>
            <span className="badge badge--ai"><Icon name="sparkle" size={16} /> Written by AI, checked against the reports</span>
            <p>An AI read the report text and wrote the answer. The system then confirmed the value is in the text.</p>
          </li>
          <li>
            <span className="badge badge--none"><Icon name="empty" size={16} /> No answer found</span>
            <p>The system says so instead of guessing, and shows the closest report text.</p>
          </li>
        </ul>

        <h3>3. Check it yourself</h3>
        <p>
          The evidence sits beside every answer: a timeline of the activities a total was added up from, or the report
          text with the answer highlighted in yellow. Click a source to read the whole page.
        </p>

        <h3>4. Tell us when it is wrong</h3>
        <p>Use the thumbs under the answer. A wrong answer with a short note is the most useful thing you can give us.</p>

        <h3>5. Look up a well</h3>
        <p>
          Click a well’s name to open its page: what the reports say about it, each fact with the page it is written on,
          its reports, and its days on a timeline with the non-productive time marked.
        </p>

        <p className="guide__hint">
          <Icon name="info" size={16} /> Hover over any <span className="guide__i">i</span> for an explanation.
        </p>
        <div className="guide__actions">
          <button type="button" className="button" onClick={onClose}>Got it</button>
        </div>
      </div>
    </div>
  );
}
