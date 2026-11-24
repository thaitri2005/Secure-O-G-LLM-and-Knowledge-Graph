import { elapsed, WAITING, WAITING_STEPS, waitingNote, waitingStep } from "../lib/wording";
import { Icon } from "./Icon";

interface Props {
  question: string;
  /** Whole seconds since the question was asked. */
  seconds: number;
  onStop: () => void;
}

/**
 * While a question is being answered, which can take a minute on modest hardware: what is happening in plain
 * words, how long it has been, and a way to stop. The step that is under way is told by the time that has passed.
 * Only the step is announced to a screen reader as it changes; the seconds are there to read, not read out.
 */
export function Waiting({ question, seconds, onStop }: Props) {
  const current = waitingStep(seconds);
  return (
    <section className="waiting card" aria-labelledby="waiting-title">
      <div className="waiting__head">
        <div role="status">
          <h2 id="waiting-title">{WAITING.title}</h2>
          <p className="waiting__question">“{question}”</p>
          <p className="visually-hidden">{WAITING_STEPS[current].title}.</p>
        </div>
        <button type="button" className="chip waiting__stop" onClick={onStop}><Icon name="close" size={16} /> {WAITING.stop}</button>
      </div>
      <div className="waiting__bar" aria-hidden="true"><span /></div>
      <ol className="waiting__steps" aria-label="What is happening">
        {WAITING_STEPS.map((step, index) => {
          const state = index < current ? "done" : index === current ? "now" : "next";
          return (
            <li key={step.title} className={`waiting__step waiting__step--${state}`} aria-current={state === "now" ? "step" : undefined}>
              <span className="waiting__mark" aria-hidden="true">{state === "done" && <Icon name="check" size={14} />}</span>
              <span className="waiting__title">{step.title}{state === "done" && <span className="visually-hidden"> (done)</span>}</span>
              <span className="waiting__detail">{step.detail}</span>
            </li>
          );
        })}
      </ol>
      <p className="waiting__time">
        <span className="waiting__seconds">{elapsed(seconds)}</span>
        <span>{waitingNote(seconds)}</span>
      </p>
    </section>
  );
}
