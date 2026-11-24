import { useEffect, useMemo, useRef, useState } from "react";
import type { AnswerOut, ChunkOut, PageOut } from "../api/types";
import { highlight, readable } from "../lib/highlight";
import { reportName } from "../lib/wording";
import { DayStrips } from "./DayStrips";

type Tab = "operations" | "facts" | "passages";

function where(chunk: ChunkOut): string {
  return `${reportName(chunk.file_id)}${chunk.page === null ? "" : `, page ${chunk.page}`}`;
}

/** Report text, in the reports' own face, with the answer's values marked where they are written. */
function ReportText({ text, values }: { text: string; values: string[] }) {
  const parts = useMemo(() => highlight(readable(text), values), [text, values]);
  const box = useRef<HTMLParagraphElement>(null);
  // A long passage is shown in a box that scrolls; open it where the answer's value is written.
  useEffect(() => {
    const first = box.current?.querySelector("mark");
    if (box.current && first instanceof HTMLElement && box.current.scrollHeight > box.current.clientHeight) {
      // The box is the mark's offset parent (it is positioned), so offsetTop is already measured from its top.
      box.current.scrollTop = Math.max(0, first.offsetTop - 48);
    }
  }, [parts]);
  return (
    <p className="report-text" ref={box}>
      {parts.map((part, index) => (part.hit ? <mark key={index}>{part.text}</mark> : part.text))}
    </p>
  );
}

function Passage({ chunk, cited, values, onOpenPage }: { chunk: ChunkOut; cited: boolean; values: string[]; onOpenPage: (chunk: ChunkOut) => void }) {
  return (
    <article className={cited ? "passage passage--cited" : "passage"}>
      <header className="passage__where">
        <span>{where(chunk)}{chunk.section ? `: ${chunk.section}` : ""}</span>
        {cited && <span className="passage__flag">Cited in the answer</span>}
      </header>
      {chunk.text === null ? (
        <p className="passage__missing">This report is not loaded on this machine, so its text cannot be shown.</p>
      ) : (
        <ReportText text={chunk.text} values={values} />
      )}
      {chunk.page !== null && chunk.text !== null && (
        <button type="button" className="link" onClick={() => onOpenPage(chunk)}>Read the whole page</button>
      )}
    </article>
  );
}

interface Props {
  answer: AnswerOut;
  page: PageOut | null;
  pageChunk: string | null;
  onOpenPage: (chunk: ChunkOut) => void;
  onClosePage: () => void;
}

/** Everything the answer rests on: the operations a number was computed from, the checked facts, the passages. */
export function Evidence({ answer, page, pageChunk, onOpenPage, onClosePage }: Props) {
  const { computed, facts, passages } = answer.evidence;
  const [tab, setTab] = useState<Tab>(computed ? "operations" : passages.length > 0 ? "passages" : "facts");
  const [operation, setOperation] = useState<number | null>(null);
  const rows = useRef<(HTMLTableRowElement | null)[]>([]);
  const cited = useMemo(() => new Set(answer.citations.map((c) => c.chunk_id)), [answer.citations]);
  // Only a model's answer is marked in the text: a computed total is written in no passage.
  const values = useMemo(() => (computed ? [] : answer.answers.map((a) => a.value)), [computed, answer.answers]);
  const ordered = useMemo(() => [...passages].sort((a, b) => Number(cited.has(b.chunk_id)) - Number(cited.has(a.chunk_id))), [passages, cited]);

  useEffect(() => {
    if (operation !== null) rows.current[operation]?.scrollIntoView?.({ block: "nearest" });
  }, [operation]);

  if (page) {
    return (
      <section className="evidence" aria-label="Evidence">
        <button type="button" className="link evidence__back" onClick={onClosePage}>Back to the evidence</button>
        <h2 className="evidence__title">{reportName(page.file_id)}, page {page.page}</h2>
        <p className="note">The page as the report’s text was read. Press Esc to go back.</p>
        <div className="page">
          {page.chunks.map((chunk) => (
            <div key={chunk.chunk_id} className={chunk.chunk_id === pageChunk ? "page__chunk page__chunk--cited" : "page__chunk"}>
              {chunk.section && <p className="page__section">{chunk.section}</p>}
              <ReportText text={chunk.text ?? ""} values={values} />
            </div>
          ))}
        </div>
      </section>
    );
  }

  const passagesLabel = computed ? "Source passages" : answer.status === "answered" ? "Passages" : "Closest passages";
  const tabs: { id: Tab; label: string; count: number }[] = [
    ...(computed ? [{ id: "operations" as Tab, label: "Operations", count: computed.events.length }] : []),
    ...(passages.length > 0 ? [{ id: "passages" as Tab, label: passagesLabel, count: passages.length }] : []),
    ...(facts.length > 0 ? [{ id: "facts" as Tab, label: "Checked facts", count: facts.length }] : []),
  ];

  if (tabs.length === 0) {
    return (
      <section className="evidence" aria-label="Evidence">
        <p className="note">Nothing in the loaded reports matched this question.</p>
      </section>
    );
  }

  return (
    <section className="evidence" aria-label="Evidence">
      <div className="tabs" role="tablist" aria-label="Evidence">
        {tabs.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            id={`tab-${item.id}`}
            aria-selected={tab === item.id}
            aria-controls={`panel-${item.id}`}
            aria-label={`${item.label} ${item.count}`}
            className="tabs__tab"
            onClick={() => setTab(item.id)}
          >
            {item.label} <span className="tabs__count">{item.count}</span>
          </button>
        ))}
      </div>

      {tab === "operations" && computed && (
        <div role="tabpanel" id="panel-operations" aria-labelledby="tab-operations">
          <p className="note">The daily reports’ operations this number was added up from. Code did the adding: {computed.text}.</p>
          <DayStrips events={computed.events} selected={operation} onSelect={setOperation} />
          <div className="scroll">
            <table className="data data--pick" aria-label="Operations">
              <thead>
                <tr><th>Date</th><th>From</th><th>To</th><th className="num">Hours</th><th>Code</th><th>Non-productive</th><th>Description</th></tr>
              </thead>
              <tbody>
                {computed.events.map((event, index) => (
                  <tr
                    key={index}
                    ref={(row) => { rows.current[index] = row; }}
                    aria-selected={operation === index}
                    onClick={() => setOperation(index)}
                  >
                    <td>{event.date}</td><td>{event.start}</td><td>{event.end}</td><td className="num">{event.hours}</td>
                    <td>{event.code}</td><td>{event.npt_code ?? ""}</td><td className="report-text">{event.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "passages" && (
        <div role="tabpanel" id="panel-passages" aria-labelledby="tab-passages">
          <p className="note">
            {computed
              ? "The report passages these operations were read from."
              : answer.status === "answered"
                ? "What the model was given to read. The answer’s value is marked where it is written."
                : "No answer was found. These are the passages closest to the question."}
          </p>
          {ordered.map((chunk) => (
            <Passage key={chunk.chunk_id} chunk={chunk} cited={cited.has(chunk.chunk_id)} values={values} onOpenPage={onOpenPage} />
          ))}
        </div>
      )}

      {tab === "facts" && (
        <div role="tabpanel" id="panel-facts" aria-labelledby="tab-facts">
          <p className="note">Read from the reports’ tables and text, then checked in code: each value is written in its source passage.</p>
          <div className="scroll">
            <table className="data" aria-label="Checked facts">
              <thead>
                <tr><th>Well</th><th>Property</th><th className="num">Value</th><th>Applies to</th><th>Read by</th></tr>
              </thead>
              <tbody>
                {facts.map((fact, index) => (
                  <tr key={index}>
                    <td>{fact.well}</td>
                    <td>{fact.property.replace(/_/g, " ")}{fact.qualifier !== "actual" && fact.qualifier !== "none" ? ` (${fact.qualifier})` : ""}</td>
                    <td className="num">{fact.value}{fact.unit ? ` ${fact.unit}` : ""}</td>
                    <td>{fact.context ? Object.entries(fact.context).map(([key, value]) => `${key.replace(/_/g, " ")} ${value}`).join(", ") : ""}</td>
                    <td>{fact.source === "table_mapping" ? "Table rule" : "Model, then checked"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
