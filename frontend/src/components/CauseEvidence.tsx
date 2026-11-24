import { useEffect, useMemo, useState } from "react";
import type { AnswerOut, ChunkOut, Reasoning } from "../api/types";
import { citedLabels, gathered, passageChunk } from "../lib/cause";
import { EXPLAIN } from "../lib/wording";
import { ActivityList } from "./ActivityList";
import { DayStrips } from "./DayStrips";
import { Passage } from "./Passage";
import { TabList } from "./Tabs";
import { Tip } from "./Tip";

/** A piece of evidence a cause answer pointed to; `at` lets the same piece be pointed to twice. */
export interface Pointer {
  label: string;
  at: number;
}

type Tab = "around" | "text";
const NO_VALUES: string[] = [];

interface Props {
  answer: AnswerOut;
  reasoning: Reasoning;
  pointed: Pointer | null;
  onOpenPage: (chunk: ChunkOut) => void;
}

/**
 * What a cause answer rests on: the activities logged before, during and after the problem, those of the problem
 * itself marked, and the report text gathered around it. A cited piece can be pointed to from the answer.
 */
export function CauseEvidence({ answer, reasoning, pointed, onOpenPage }: Props) {
  const { events, passages } = useMemo(() => gathered(reasoning), [reasoning]);
  const cited = useMemo(() => citedLabels(reasoning), [reasoning]);
  const [tab, setTab] = useState<Tab>(events.length > 0 ? "around" : "text");
  const [activity, setActivity] = useState<number | null>(null);
  // The timeline needs every activity's day and hours; if a line could not be read, only the list is shown.
  const timeline = useMemo(() => (events.every((e) => e.event) ? events.map((e) => e.event!) : null), [events]);
  const activities = useMemo(
    () => events.map(({ item, event, problem }) => ({
      key: item.id, event, text: item.text, problem, tags: <Tags problem={problem} cited={cited.has(item.id)} />,
    })),
    [events, cited],
  );

  useEffect(() => {
    if (!pointed) return;
    const index = events.findIndex((e) => e.item.id === pointed.label);
    if (index >= 0) {
      setTab("around");
      setActivity(index);
    } else if (passages.some((p) => p.id === pointed.label)) {
      setTab("text");
    }
  }, [pointed, events, passages]);

  // Bring the passage pointed to into view once its tab is drawn. (The list of activities does so for an activity.)
  useEffect(() => {
    if (tab === "text" && pointed) {
      const passage = document.getElementById(`evidence-${pointed.label}`);
      passage?.scrollIntoView?.({ block: "nearest" });
      passage?.focus();
    }
  }, [tab, pointed]);

  if (answer.status === "ask_which") {
    return (
      <section className="evidence card" aria-labelledby="evidence-title">
        <h2 id="evidence-title" tabIndex={-1} className="evidence__title">The evidence</h2>
        <p className="note">
          Choose one of the problems first. We will then gather the activities logged around it and the report text
          that mentions it, and show them here.
        </p>
      </section>
    );
  }

  const tabs: { id: Tab; label: string; count: number }[] = [
    ...(events.length > 0 ? [{ id: "around" as Tab, label: "Around the problem", count: events.length }] : []),
    ...(passages.length > 0 ? [{ id: "text" as Tab, label: "Report text", count: passages.length }] : []),
  ];

  if (tabs.length === 0) {
    return (
      <section className="evidence card" aria-labelledby="evidence-title">
        <h2 id="evidence-title" tabIndex={-1} className="evidence__title">The evidence</h2>
        <p className="note">Nothing was gathered around this problem, so there is nothing to show here.</p>
      </section>
    );
  }

  return (
    <section className="evidence card" aria-labelledby="evidence-title">
      <h2 id="evidence-title" tabIndex={-1} className="evidence__title">The evidence</h2>
      <p className="evidence__lead">Check the causes yourself. This is everything the AI was shown about the problem.</p>
      <TabList label="Evidence" tabs={tabs} selected={tab} onSelect={setTab} />

      {tab === "around" && (
        <div role="tabpanel" id="panel-around" aria-labelledby="tab-around" tabIndex={0}>
          <p className="note">
            The activities logged before, during and after the problem, in the daily reports’ own words.{" "}
            <Tip about="the problem’s activities">{EXPLAIN.problemEvents}</Tip>
          </p>
          {timeline && <DayStrips events={timeline} selected={activity} onSelect={setActivity} />}
          <h3 className="evidence__sub">Activities around the problem</h3>
          <ActivityList label="Activities around the problem" rows={activities} selected={activity} onSelect={setActivity} />
        </div>
      )}

      {tab === "text" && (
        <div role="tabpanel" id="panel-text" aria-labelledby="tab-text" tabIndex={0}>
          <p className="note">Report text from the days of the problem, and from the end-of-well report where it mentions the problem.</p>
          {passages.map((item) => (
            <Passage
              key={item.id}
              id={`evidence-${item.id}`}
              chunk={passageChunk(answer, item)}
              cited={cited.has(item.id)}
              flag="Cited for a cause"
              values={NO_VALUES}
              onOpenPage={onOpenPage}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function Tags({ problem, cited }: { problem: boolean; cited: boolean }) {
  if (!problem && !cited) return null;
  return (
    <span className="around__tags">
      {problem && <span className="around__tag around__tag--problem">The problem</span>}
      {cited && <span className="around__tag around__tag--cited">Cited for a cause</span>}
    </span>
  );
}
