import { useEffect, useMemo, useRef, type ReactNode } from "react";
import type { EventOut } from "../api/types";
import { firstDays } from "../lib/fold";
import { readable } from "../lib/highlight";
import { dayLost, daySummary, EXPLAIN, longDate } from "../lib/wording";
import { FoldControl, useFold } from "./Fold";
import { Tip } from "./Tip";

export interface ActivityRow {
  key: string;
  /** Null when the activity's line could not be read; `text` is then shown as it is. */
  event: EventOut | null;
  text?: string;
  /** Part of the problem a cause answer is about. */
  problem?: boolean;
  /** Labels shown above the description. */
  tags?: ReactNode;
}

interface Props {
  /** The table's name for a screen reader. */
  label: string;
  rows: ActivityRow[];
  /** The activity marked, here and on the timeline. */
  selected: number | null;
  onSelect: (index: number) => void;
}

/**
 * Logged activities as a table, grouped by day: each day has one heading line with its hours and its non-productive
 * hours. A long list shows its first days and a button for the rest. An activity chosen elsewhere (a bar on the
 * timeline, a cause that cites it) is unfolded if need be and brought into view.
 *
 * On a phone each activity is drawn as two lines instead of four columns (styles.css). The table's roles are
 * written out, because some browsers forget them once a table is no longer drawn as one.
 */
export function ActivityList({ label, rows, selected, onSelect }: Props) {
  const first = useMemo(() => firstDays(rows.map((row) => row.event?.date ?? "")), [rows]);
  const fold = useFold(rows.length, first, selected !== null && selected >= first, selected);
  const lines = useRef<(HTMLTableRowElement | null)[]>([]);

  useEffect(() => {
    if (selected !== null && selected < fold.limit) lines.current[selected]?.scrollIntoView?.({ block: "nearest" });
  }, [selected, fold.limit]);

  // Consecutive activities of one day form a group; a line that could not be read stands alone, without a heading.
  const days = useMemo(() => {
    const groups: { date: string | null; from: number; rows: ActivityRow[] }[] = [];
    rows.slice(0, fold.limit).forEach((row, index) => {
      const date = row.event?.date ?? null;
      const last = groups[groups.length - 1];
      if (last && date !== null && last.date === date) last.rows.push(row);
      else groups.push({ date, from: index, rows: [row] });
    });
    return groups;
  }, [rows, fold.limit]);

  return (
    <>
      <div className="scroll">
        <table role="table" className="data data--pick activities" aria-label={label}>
          <thead role="rowgroup">
            <tr role="row">
              <th role="columnheader" scope="col">Time</th>
              <th role="columnheader" scope="col" className="num">Hours</th>
              <th role="columnheader" scope="col">Code <Tip about="the code">{EXPLAIN.code}</Tip></th>
              <th role="columnheader" scope="col">What happened</th>
            </tr>
          </thead>
          {days.map((day) => {
            const events = day.rows.flatMap((row) => (row.event ? [row.event] : []));
            const hours = events.reduce((sum, event) => sum + event.hours, 0);
            const lost = events.filter((event) => event.npt_code).reduce((sum, event) => sum + event.hours, 0);
            return (
              <tbody role="rowgroup" key={`${day.date}-${day.from}`}>
                {day.date !== null && (
                  <tr role="row" className="activities__day">
                    <th role="rowheader" colSpan={4} scope="rowgroup">
                      <span className="activities__date">{longDate(day.date)}</span>{" "}
                      <span className="activities__sum">{daySummary(events.length, hours)}</span>
                      {lost > 0 && <> <span className="npt">{dayLost(lost)}</span></>}
                    </th>
                  </tr>
                )}
                {day.rows.map((row, offset) => {
                  const index = day.from + offset;
                  const chosen = selected === index;
                  const classes = [row.problem ? "around--problem" : "", chosen ? "is-selected" : ""].filter(Boolean).join(" ");
                  return (
                    <tr role="row" key={row.key} ref={(line) => { lines.current[index] = line; }} className={classes || undefined} onClick={() => onSelect(index)}>
                      {row.event ? (
                        <>
                          <td role="cell" className="activities__time">
                            {/* The row can be clicked anywhere; this button is the same thing for a keyboard. */}
                            <button type="button" className="pick" aria-pressed={chosen} onClick={(click) => { click.stopPropagation(); onSelect(index); }}>
                              {row.event.start}–{row.event.end}
                            </button>
                          </td>
                          <td role="cell" className="num activities__hours">{row.event.hours}<span className="activities__unit"> h</span></td>
                          <td role="cell" className="activities__code">{row.event.code}{row.event.npt_code ? <abbr className="npt" title="Non-productive time">NPT</abbr> : null}</td>
                          <td role="cell" className="report-text">{row.tags}{readable(row.event.description)}</td>
                        </>
                      ) : (
                        <td role="cell" colSpan={4} className="report-text">{row.tags}{readable(row.text ?? "")}</td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            );
          })}
        </table>
      </div>
      {fold.folds && <FoldControl shown={first} total={rows.length} things="activities" open={fold.open} onToggle={fold.toggle} />}
    </>
  );
}
