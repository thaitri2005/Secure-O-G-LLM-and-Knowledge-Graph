import { useEffect, useMemo, useRef, useState } from "react";
import type { AnswerOut, ChunkOut, PageOut } from "../api/types";
import { highlight, readable } from "../lib/highlight";
import { EXPLAIN, place } from "../lib/wording";
import { DayStrips } from "./DayStrips";
import { Icon } from "./Icon";
import { PageImage } from "./PageImage";
import { Tip } from "./Tip";

type Tab = "timeline" | "facts" | "text";

/** Report text, in the reports' own typeface, with the answer's values highlighted where they are written. */
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
        <span><Icon name="document" size={16} /> {place(chunk.file_id, chunk.page)}{chunk.section ? ` · ${chunk.section}` : ""}</span>
        {cited && <span className="passage__flag"><Icon name="check" size={14} /> The answer is here</span>}
      </header>
      {chunk.text === null ? (
        <p className="passage__missing">This report’s text is not available on this computer.</p>
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

/** What the answer rests on: the activities a number was added up from, the report text, the key facts. */
export function Evidence({ answer, page, pageChunk, onOpenPage, onClosePage }: Props) {
  const { computed, facts, passages } = answer.evidence;
  const [tab, setTab] = useState<Tab>(computed ? "timeline" : passages.length > 0 ? "text" : "facts");
  const [activity, setActivity] = useState<number | null>(null);
  const [pageTab, setPageTab] = useState<"image" | "text">("image");
  const rows = useRef<(HTMLTableRowElement | null)[]>([]);
  const cited = useMemo(() => new Set(answer.citations.map((c) => c.chunk_id)), [answer.citations]);
  // Only an AI-written answer is highlighted in the text: a calculated total is written in no passage.
  const values = useMemo(() => (computed ? [] : answer.answers.map((a) => a.value)), [computed, answer.answers]);
  const ordered = useMemo(() => [...passages].sort((a, b) => Number(cited.has(b.chunk_id)) - Number(cited.has(a.chunk_id))), [passages, cited]);

  useEffect(() => {
    if (activity !== null) rows.current[activity]?.scrollIntoView?.({ block: "nearest" });
  }, [activity]);

  if (page) {
    const imageUrl = page.image_url ?? null;
    const citedChunks = page.chunks.filter((chunk) => chunk.chunk_id === pageChunk);
    const pageText = (chunks: ChunkOut[]) =>
      chunks.map((chunk) => (
        <div key={chunk.chunk_id} className={chunk.chunk_id === pageChunk ? "page__chunk page__chunk--cited" : "page__chunk"}>
          {chunk.section && <p className="page__section">{chunk.section}</p>}
          <ReportText text={chunk.text ?? ""} values={values} />
        </div>
      ));
    return (
      <section className="evidence card" aria-label="Evidence">
        <button type="button" className="back" onClick={onClosePage}><Icon name="arrowLeft" size={16} /> Back to the evidence</button>
        <h2 className="evidence__title">{place(page.file_id, page.page)}</h2>
        {imageUrl && (
          <div className="tabs" role="tablist" aria-label="Page view">
            {(["image", "text"] as const).map((id) => (
              <button
                key={id}
                type="button"
                role="tab"
                id={`pagetab-${id}`}
                aria-selected={pageTab === id}
                aria-controls={`pagepanel-${id}`}
                className="tabs__tab"
                onClick={() => setPageTab(id)}
              >
                {id === "image" ? "Page as printed" : "Page text"}
              </button>
            ))}
          </div>
        )}
        {imageUrl && pageTab === "image" ? (
          <div role="tabpanel" id="pagepanel-image" aria-labelledby="pagetab-image" className="page-view">
            <PageImage key={imageUrl} url={imageUrl} fileId={page.file_id} page={page.page} />
            <div className="page-view__passage">
              <p className="note">The part the answer came from, as the system read it:</p>
              <div className="page">{pageText(citedChunks.length > 0 ? citedChunks : page.chunks)}</div>
            </div>
          </div>
        ) : (
          <div role="tabpanel" id="pagepanel-text" aria-labelledby="pagetab-text">
            <p className="note">This is the text of the page as the system read it. The part the answer came from is highlighted in blue.</p>
            <div className="page">{pageText(page.chunks)}</div>
          </div>
        )}
      </section>
    );
  }

  const textLabel = answer.status === "answered" || computed ? "Report text" : "Closest report text";
  const tabs: { id: Tab; label: string; count: number }[] = [
    ...(computed ? [{ id: "timeline" as Tab, label: "Timeline", count: computed.events.length }] : []),
    ...(passages.length > 0 ? [{ id: "text" as Tab, label: textLabel, count: passages.length }] : []),
    ...(facts.length > 0 ? [{ id: "facts" as Tab, label: "Key facts", count: facts.length }] : []),
  ];

  if (tabs.length === 0) {
    return (
      <section className="evidence card" aria-label="Evidence">
        <h2 className="evidence__title">The evidence</h2>
        <p className="note">Nothing in the reports matched this question, so there is nothing to show here.</p>
      </section>
    );
  }

  return (
    <section className="evidence card" aria-label="Evidence">
      <h2 className="evidence__title">The evidence</h2>
      <p className="evidence__lead">Check the answer yourself. This is exactly what it is based on.</p>
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

      {tab === "timeline" && computed && (
        <div role="tabpanel" id="panel-timeline" aria-labelledby="tab-timeline">
          <DayStrips events={computed.events} selected={activity} onSelect={setActivity} />
          <h3 className="evidence__sub">Every activity that was counted</h3>
          <div className="scroll">
            <table className="data data--pick" aria-label="Activities">
              <thead>
                <tr>
                  <th>Date</th><th>From</th><th>To</th><th className="num">Hours</th>
                  <th>Code <Tip about="the code">{EXPLAIN.code}</Tip></th>
                  <th>What happened</th>
                </tr>
              </thead>
              <tbody>
                {computed.events.map((event, index) => (
                  <tr
                    key={index}
                    ref={(row) => { rows.current[index] = row; }}
                    aria-selected={activity === index}
                    onClick={() => setActivity(index)}
                  >
                    <td>{event.date}</td><td>{event.start}</td><td>{event.end}</td><td className="num">{event.hours}</td>
                    <td>{event.code}{event.npt_code ? <span className="npt" title="Non-productive time">NPT</span> : null}</td>
                    <td className="report-text">{readable(event.description)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "text" && (
        <div role="tabpanel" id="panel-text" aria-labelledby="tab-text">
          <p className="note">
            {computed
              ? "The pages of the daily reports these activities were read from."
              : answer.status === "answered"
                ? "The text the AI read."
                : "No answer was found. This is the report text closest to your question."}
            {!computed && answer.status === "answered" && <> The answer is highlighted in <mark>yellow</mark>. <Tip about="the report text">{EXPLAIN.reportText}</Tip></>}
          </p>
          {ordered.map((chunk) => (
            <Passage key={chunk.chunk_id} chunk={chunk} cited={cited.has(chunk.chunk_id)} values={values} onOpenPage={onOpenPage} />
          ))}
        </div>
      )}

      {tab === "facts" && (
        <div role="tabpanel" id="panel-facts" aria-labelledby="tab-facts">
          <p className="note">Facts the system pulled out of the reports in advance and checked against the original text. <Tip about="key facts">{EXPLAIN.keyFacts}</Tip></p>
          <div className="scroll">
            <table className="data" aria-label="Key facts">
              <thead>
                <tr>
                  <th>Well</th><th>Fact</th><th className="num">Value</th><th>Applies to</th>
                  <th>Found by <Tip about="found by">{EXPLAIN.readBy}</Tip></th>
                </tr>
              </thead>
              <tbody>
                {facts.map((fact, index) => (
                  <tr key={index}>
                    <td>{fact.well}</td>
                    <td>{fact.property.replace(/_/g, " ")}{fact.qualifier !== "actual" && fact.qualifier !== "none" ? ` (${fact.qualifier})` : ""}</td>
                    <td className="num">{fact.value}{fact.unit ? ` ${fact.unit}` : ""}</td>
                    <td>{fact.context ? Object.entries(fact.context).map(([key, value]) => `${key.replace(/_/g, " ")} ${value}`).join(", ") : ""}</td>
                    <td>{fact.source === "table_mapping" ? "A table rule" : "AI, then checked"}</td>
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
