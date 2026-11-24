import { useEffect, useMemo, useRef, useState } from "react";
import type { AnswerOut, ChunkOut, PageOut } from "../api/types";
import { reasoningOf } from "../lib/cause";
import { readable } from "../lib/highlight";
import type { Route } from "../lib/route";
import { EXPLAIN, factLabel } from "../lib/wording";
import { CauseEvidence, type Pointer } from "./CauseEvidence";
import { DayStrips } from "./DayStrips";
import { PageView } from "./PageView";
import { Passage } from "./Passage";
import { RouteLink } from "./RouteLink";
import { Tip } from "./Tip";

type Tab = "timeline" | "facts" | "text";

interface Props {
  answer: AnswerOut;
  page: PageOut | null;
  pageChunk: string | null;
  onOpenPage: (chunk: ChunkOut) => void;
  onClosePage: () => void;
  /** A piece of evidence a cause answer pointed to, to show. */
  pointed?: Pointer | null;
  /** Opens another screen: a well's name links to its page. */
  onGo?: (route: Route) => void;
}

/** What the answer rests on: the activities a number was added up from, the report text, the key facts. */
export function Evidence({ answer, page, pageChunk, onOpenPage, onClosePage, pointed = null, onGo }: Props) {
  const { computed, facts, passages } = answer.evidence;
  const [tab, setTab] = useState<Tab>(computed ? "timeline" : passages.length > 0 ? "text" : "facts");
  const [activity, setActivity] = useState<number | null>(null);
  const rows = useRef<(HTMLTableRowElement | null)[]>([]);
  const cited = useMemo(() => new Set(answer.citations.map((c) => c.chunk_id)), [answer.citations]);
  // Only an AI-written answer is highlighted in the text: a calculated total is written in no passage.
  const values = useMemo(() => (computed ? [] : answer.answers.map((a) => a.value)), [computed, answer.answers]);
  const ordered = useMemo(() => [...passages].sort((a, b) => Number(cited.has(b.chunk_id)) - Number(cited.has(a.chunk_id))), [passages, cited]);

  useEffect(() => {
    if (activity !== null) rows.current[activity]?.scrollIntoView?.({ block: "nearest" });
  }, [activity]);

  if (page) return <PageView page={page} pageChunk={pageChunk} values={values} onClose={onClosePage} closeLabel="Back to the evidence" />;

  const reasoning = reasoningOf(answer);
  if (reasoning) return <CauseEvidence answer={answer} reasoning={reasoning} pointed={pointed} onOpenPage={onOpenPage} />;

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
                    <td>{onGo ? <RouteLink to={{ view: "well", well: fact.well }} onGo={onGo}>{fact.well}</RouteLink> : fact.well}</td>
                    <td>{factLabel(fact)}</td>
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
