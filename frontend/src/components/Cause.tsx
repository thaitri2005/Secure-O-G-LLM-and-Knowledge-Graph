import type { AnswerOut, Cause, Citation, Reasoning } from "../api/types";
import { causeSource } from "../lib/cause";
import { readable } from "../lib/highlight";
import {
  causePlace, choiceLabel, EXPLAIN, hiddenNote, missingText, problemDepth, problemDescription, problemSize, problemWhen,
  removedNote, sourceNote,
} from "../lib/wording";
import { Icon } from "./Icon";
import { Tip } from "./Tip";

interface Props {
  answer: AnswerOut;
  reasoning: Reasoning;
  onOpenSource: (answer: AnswerOut, citation: Citation) => void;
  onShowEvidence: (label: string) => void;
}

/** One cause and the report words it rests on, each with a way to see where they are written. */
function CauseItem({ cause, possible, answer, reasoning, onOpenSource, onShowEvidence }: Props & { cause: Cause; possible: boolean }) {
  return (
    <li className={possible ? "cause cause--possible" : "cause"}>
      {possible && <span className="cause__label">Possibility, not a finding</span>}
      <p className="cause__text">{cause.cause}</p>
      <ul className="cause__citations" aria-label="Where the reports say this">
        {cause.citations.map((citation) => {
          const source = causeSource(answer, reasoning, citation);
          const openable = source.page !== null && source.text !== null;
          const where = causePlace(source);
          return (
            <li key={citation.evidence} className="cause__citation">
              <blockquote className="cause__quote report-text">“{readable(citation.quote)}”</blockquote>
              <p className="cause__where">
                <span>
                  {where}
                  <small>{sourceNote(source)}</small>
                </span>
                {openable ? (
                  <button type="button" className="link" aria-label={`Open the page: ${where}`} onClick={() => onOpenSource(answer, source)}>
                    Open page <Icon name="open" size={14} />
                  </button>
                ) : source.item ? (
                  <button type="button" className="link" aria-label={`Show in the evidence: ${where}`} onClick={() => onShowEvidence(citation.evidence)}>
                    Show in the evidence
                  </button>
                ) : null}
              </p>
            </li>
          );
        })}
      </ul>
    </li>
  );
}

/**
 * The answer to a question about a cause, as its parts: the problem found, what the reports say caused it, other
 * possible factors kept visibly apart, and what a real judgement would still need. The AI's sentence is not shown.
 */
export function CauseAnswer(props: Props) {
  const { reasoning } = props;
  const problem = reasoning.problem!;
  const removed = removedNote(reasoning.removed);
  const hidden = hiddenNote(reasoning.possible_hidden);
  return (
    <>
      <div className="answer__block problem" aria-labelledby="problem-title">
        <h3 id="problem-title">The problem we found</h3>
        <dl className="problem__facts">
          <div>
            <dt>What</dt>
            <dd>
              {problem.npt_code ? <>Non-productive time, coded <strong>{problem.npt_code}</strong> <Tip about="this code">{EXPLAIN.problemCode}</Tip></> : "Logged activities"}
            </dd>
          </div>
          <div><dt>When</dt><dd>{problemWhen(problem)}</dd></div>
          <div><dt>How long</dt><dd>{problemSize(problem)}</dd></div>
          <div><dt>Depth</dt><dd>{problemDepth(problem)}</dd></div>
        </dl>
        <p className="problem__words-label">In the report’s words</p>
        <p className="problem__words report-text">{readable(problemDescription(problem))}</p>
      </div>

      <div className="answer__block" aria-labelledby="stated-title">
        <h3 id="stated-title">What the reports say caused it <Tip about="what the reports say">{EXPLAIN.stated}</Tip></h3>
        {reasoning.stated.length > 0 ? (
          <ol className="causes" aria-label="Stated causes">
            {reasoning.stated.map((cause, index) => <CauseItem key={index} {...props} cause={cause} possible={false} />)}
          </ol>
        ) : (
          <p className="note">None of the reports says what caused this problem.</p>
        )}
      </div>

      {(reasoning.possible.length > 0 || hidden) && (
        <div className="answer__block" aria-labelledby="possible-title">
          <h3 id="possible-title">Other possible factors (not stated in any report) <Tip about="possible factors">{EXPLAIN.possible}</Tip></h3>
          {reasoning.possible.length > 0 && (
            <ol className="causes" aria-label="Possible factors">
              {reasoning.possible.map((cause, index) => <CauseItem key={index} {...props} cause={cause} possible />)}
            </ol>
          )}
          {hidden && <p className="note">{hidden}</p>}
        </div>
      )}

      {removed && <p className="cause__removed">{removed}</p>}

      {reasoning.missing.length > 0 && (
        <div className="answer__block missing" aria-labelledby="missing-title">
          <h3 id="missing-title">What a real judgement would still need <Tip about="what is still needed">{EXPLAIN.missing}</Tip></h3>
          <p className="note">These reports do not hold the following. An engineer would usually want them before deciding on a cause.</p>
          <ul aria-label="Still needed">
            {reasoning.missing.map((item) => (
              <li key={item.text}>
                {missingText(item.text)}
                {item.source === "model" && <small> (suggested by the AI)</small>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

/** Several problems fit the question: they are offered as choices, and picking one asks again about it. */
export function AskWhich({ reasoning, onChoose }: { reasoning: Reasoning; onChoose: (index: number) => void }) {
  return (
    <div className="answer__block">
      <h3>Pick the problem you mean</h3>
      <ul className="choices" aria-label="Problems that fit">
        {reasoning.candidates.map((problem, index) => (
          <li key={`${problem.date_from}-${problem.start}-${index}`}>
            <button type="button" className="choice" onClick={() => onChoose(index)}>
              <span className="choice__when">{choiceLabel(problem)}</span>
              <span className="choice__words report-text">{readable(problemDescription(problem))}</span>
              {problem.npt_code && <span className="choice__code">Coded {problem.npt_code}</span>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
