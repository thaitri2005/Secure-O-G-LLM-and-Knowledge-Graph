import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, type Api } from "../api/client";
import type { EventOut, PageOut, ReportDay, WellFact, WellOut } from "../api/types";
import { anyPlanned, casingRows, wholeDays } from "../lib/well";
import {
  depthLabel, documentSize, EXPLAIN, factLabel, factValue, longDate, noDays, number, place, propertyName, propertyTip,
  reportName, wellTotals,
} from "../lib/wording";
import { DayStrips } from "./DayStrips";
import { Icon } from "./Icon";
import { PageView } from "./PageView";
import { Tip } from "./Tip";

const NO_VALUES: string[] = [];

interface Props {
  api: Api;
  wellId: string;
  onBack: () => void;
}

/**
 * A page about one well: what the reports say about it (each fact openable at its page), its reports, and its days
 * as a timeline with the non-productive time marked. Everything here is read from the reports; no AI writes it.
 */
export function Well({ api, wellId, onBack }: Props) {
  const [well, setWell] = useState<WellOut | null>(null);
  const [events, setEvents] = useState<EventOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState<{ shown: PageOut; chunk: string } | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const side = useRef<HTMLDivElement>(null);
  const dayRows = useRef(new Map<string, HTMLTableRowElement | null>());

  const load = useCallback(async () => {
    setError(null);
    setWell(null);
    setEvents([]);
    setPage(null);
    try {
      const found = await api.well(wellId);
      setWell(found);
      if (found.report_days.length > 0) setEvents(await api.wellEvents(wellId));
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : "We couldn’t open this well’s page.");
    }
  }, [api, wellId]);

  useEffect(() => {
    void load();
  }, [load]);

  const openFact = useCallback(async (fact: WellFact) => {
    if (fact.page === null) return;
    setPageError(null);
    try {
      setPage({ shown: await api.page(fact.file_id, fact.page), chunk: fact.chunk_id });
      // Only when the page view is out of sight: below the facts on a narrow screen, or above after scrolling down.
      side.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
    } catch (failure) {
      setPageError(failure instanceof ApiError ? failure.message : "We couldn’t open that page.");
    }
  }, [api]);

  // Esc closes an open page, as it does beside an answer.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setPage(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const drawn = useMemo(() => (well ? wholeDays(events, well.report_days) : []), [events, well]);
  const chosenDay = selected === null ? null : (drawn[selected]?.date ?? null);

  useEffect(() => {
    if (chosenDay) dayRows.current.get(chosenDay)?.scrollIntoView?.({ block: "nearest" });
  }, [chosenDay]);

  if (error) {
    return (
      <main className="well">
        <button type="button" className="back" onClick={onBack}><Icon name="arrowLeft" size={16} /> Back</button>
        <h1 className="well__title">{wellId}</h1>
        <p role="alert" className="error">
          <Icon name="alert" size={18} /> <span>{error}</span>
          <button type="button" className="link" onClick={() => void load()}>Try again</button>
        </p>
      </main>
    );
  }

  if (!well) {
    return (
      <main className="well">
        <h1 className="well__title">{wellId}</h1>
        <p className="note" role="status">Gathering what the reports say about {wellId}…</p>
      </main>
    );
  }

  const { general, depths_and_dates: depths, casing_strings: casings, readings } = well.facts;
  const factCount = general.length + depths.length + casings.reduce((sum, c) => sum + c.facts.length, 0)
    + readings.reduce((sum, r) => sum + r.facts.length, 0);
  const totals = wellTotals(well.totals);
  const planned = anyPlanned(casings);
  const drawnDays = new Set(drawn.map((event) => event.date)).size;

  return (
    <main className="well">
      <button type="button" className="back" onClick={onBack}><Icon name="arrowLeft" size={16} /> Back</button>
      <h1 className="well__title">Well {well.well_id}</h1>
      <p className="well__lead">
        {totals ?? "No daily reports are loaded for this well."}
        {totals && well.totals.npt_hours > 0 && <> <Tip about="these codes">{EXPLAIN.nptCodes}</Tip></>}
      </p>

      <div className="work">
        <section className="card well__facts" aria-labelledby="well-facts">
          <h2 id="well-facts">What we know about {well.well_id} <Tip about="these facts">{EXPLAIN.wellFacts}</Tip></h2>
          {factCount === 0 ? (
            <p className="note">The reports loaded here give no checked facts about this well yet.</p>
          ) : (
            <p className="note">Click a value to see the page of the report it is written on.</p>
          )}
          {pageError && <p role="alert" className="error"><Icon name="alert" size={18} /> <span>{pageError}</span></p>}

          <FactTable title="General" facts={general} onOpen={openFact} />
          <FactTable title="Depths and dates" facts={depths} onOpen={openFact} />

          {casings.length > 0 && (
            <div className="well__group">
              <h3>Casing strings <Tip about="casing strings">{EXPLAIN.casing}</Tip></h3>
              <div className="scroll">
                <table className="data" aria-label="Casing strings">
                  <thead>
                    <tr>
                      <th>Casing</th><th>Detail</th>
                      {planned && <th>Planned</th>}
                      <th>Actual</th>
                    </tr>
                  </thead>
                  <tbody>
                    {casings.flatMap((casing) => casingRows(casing).map((row, index) => (
                      <tr key={`${casing.size_in}-${row.property}`} className={index === 0 ? "well__first" : undefined}>
                        <td>{index === 0 ? `${casing.size_in} in` : ""}</td>
                        <td>{propertyName(row.property)}{propertyTip(row.property) && <Tip about={propertyName(row.property).toLowerCase()}>{propertyTip(row.property)}</Tip>}</td>
                        {planned && <td><Value fact={row.planned} onOpen={openFact} /></td>}
                        <td><Value fact={row.actual} onOpen={openFact} /></td>
                      </tr>
                    )))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {readings.map((reading) => (
            <div className="well__group" key={reading.property}>
              <h3>
                {propertyName(reading.property)} at depths{" "}
                <Tip about={propertyName(reading.property).toLowerCase()}>{propertyTip(reading.property) ?? EXPLAIN.readings}</Tip>
              </h3>
              <div className="scroll well__readings">
                <table className="data" aria-label={`${propertyName(reading.property)} at depths`}>
                  <thead>
                    <tr><th>Depth</th><th className="num">{propertyName(reading.property)}</th></tr>
                  </thead>
                  <tbody>
                    {reading.facts.map((fact, index) => (
                      <tr key={index}>
                        <td>{depthLabel(fact.context?.depth_ft)}</td>
                        <td className="num"><Value fact={fact} onOpen={openFact} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </section>

        <div className="well__side" ref={side}>
          {page ? (
            <PageView
              key={`${page.shown.file_id}-${page.shown.page}-${page.chunk}`}
              page={page.shown}
              pageChunk={page.chunk}
              values={NO_VALUES}
              onClose={() => setPage(null)}
              closeLabel="Back to the days and reports"
              cited="fact"
            />
          ) : (
            <>
              <section className="card well__days" aria-labelledby="well-days">
                <h2 id="well-days">Day by day</h2>
                {well.report_days.length === 0 ? (
                  <p className="well__none"><Icon name="info" size={18} /> {noDays(well.well_id, well.documents)}</p>
                ) : (
                  <>
                    {drawn.length > 0 && <DayStrips events={drawn} selected={selected} onSelect={setSelected} hint="Hover over a bar to see what happened. Click it to find its day in the list below." />}
                    {drawnDays < well.report_days.length && (
                      <p className="note well__partial">
                        {drawnDays === 0
                          ? "The activities of these days are not at hand, so the timeline is not drawn. The list below gives every day."
                          : `The timeline shows the ${drawnDays === 1 ? "1 day" : `${drawnDays} days`} whose activities are all at hand; the list below gives every day.`}
                      </p>
                    )}
                    <h3 className="evidence__sub">Every day of reports</h3>
                    <DayTable
                      days={well.report_days}
                      chosen={chosenDay}
                      rows={dayRows.current}
                      onChoose={(date) => {
                        const first = drawn.findIndex((event) => event.date === date);
                        if (first >= 0) setSelected(first);
                      }}
                    />
                  </>
                )}
              </section>

              <section className="card well__reports" aria-labelledby="well-reports">
                <h2 id="well-reports">Its reports</h2>
                {well.documents.length === 0 ? (
                  <p className="note">No reports are loaded for this well.</p>
                ) : (
                  <ul className="well__docs">
                    {well.documents.map((document) => (
                      <li key={document.file_id}>
                        <span className="source__icon"><Icon name="document" size={18} /></span>
                        <span className="source__where">
                          {reportName(document.file_id)}
                          <small>{documentSize(document)}</small>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </main>
  );
}

/** A value that opens the page it is written on; plain text when that page is not on this computer. */
function Value({ fact, onOpen }: { fact: WellFact | null; onOpen: (fact: WellFact) => void }) {
  if (!fact) return <span className="well__blank">Not given</span>;
  const value = factValue(fact);
  if (fact.page === null) return <span title="The page of this fact is not available on this computer">{value}</span>;
  return (
    <button type="button" className="link well__value" aria-label={`${value}: open ${place(fact.file_id, fact.page)}`} onClick={() => onOpen(fact)}>
      {value}
    </button>
  );
}

function FactTable({ title, facts, onOpen }: { title: string; facts: WellFact[]; onOpen: (fact: WellFact) => void }) {
  if (facts.length === 0) return null;
  return (
    <div className="well__group">
      <h3>{title}</h3>
      <div className="scroll">
        <table className="data" aria-label={title}>
          <tbody>
            {facts.map((fact, index) => (
              <tr key={index}>
                <td>
                  {factLabel(fact)}
                  {propertyTip(fact.property) && <Tip about={propertyName(fact.property).toLowerCase()}>{propertyTip(fact.property)}</Tip>}
                </td>
                <td className="num"><Value fact={fact} onOpen={onOpen} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface DayTableProps {
  days: ReportDay[];
  chosen: string | null;
  rows: Map<string, HTMLTableRowElement | null>;
  onChoose: (date: string) => void;
}

/** Every report day: its hours, the non-productive hours marked, how deep it reached, and its activity codes. */
function DayTable({ days, chosen, rows, onChoose }: DayTableProps) {
  return (
    <div className="scroll well__daylist">
      <table className="data data--pick" aria-label="Report days">
        <thead>
          <tr>
            <th>Day</th>
            <th className="num">Hours</th>
            <th className="num">Non-productive <Tip about="non-productive time">{EXPLAIN.nonProductive}</Tip></th>
            <th className="num">Deepest point</th>
            <th>Activity codes <Tip about="the codes">{EXPLAIN.code}</Tip></th>
          </tr>
        </thead>
        <tbody>
          {days.map((day) => (
            <tr key={day.date} ref={(row) => { rows.set(day.date, row); }} aria-selected={chosen === day.date} onClick={() => onChoose(day.date)}>
              <td>{longDate(day.date)}</td>
              <td className="num">{number(day.hours)}</td>
              <td className="num">
                {day.npt_hours > 0 ? <span className="npt" title={day.npt_codes.join(", ")}>{number(day.npt_hours)} h</span> : "–"}
              </td>
              <td className="num">{number(day.end_md)} ft</td>
              <td>{[...new Set(day.codes)].join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
