import { memo, useMemo, useRef, useState, type KeyboardEvent } from "react";
import type { EventOut } from "../api/types";
import { dayStrips } from "../lib/strips";
import { readable } from "../lib/highlight";
import { EXPLAIN } from "../lib/wording";
import { Tip } from "./Tip";

const HOURS = [0, 6, 12, 18, 24];
const CLOCK = ["Midnight", "6 am", "Noon", "6 pm", "Midnight"];
const HINT = "Hover over a bar to see what happened. Click it to find it in the list below.";

export function dayLabel(date: string): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}

function hoursLabel(hours: number): string {
  return `${hours} ${hours === 1 ? "hour" : "hours"}`;
}

export function describe(event: EventOut): string {
  const lost = event.npt_code ? ", non-productive time" : "";
  return `${dayLabel(event.date)}, ${event.start} to ${event.end}, ${hoursLabel(event.hours)}${lost}`;
}

interface Props {
  events: EventOut[];
  selected: number | null;
  onSelect: (index: number) => void;
  /** What the line under the bars says before one is chosen. */
  hint?: string;
}

/**
 * Logged activities (those behind a calculated number, around a problem, or of a well's days), one bar per day from
 * midnight to midnight: the time breakdown a daily drilling report prints as a table, drawn. Hovering a block
 * explains it; clicking one marks it in the list below.
 */
export const DayStrips = memo(function DayStrips({ events, selected, onSelect, hint = HINT }: Props) {
  const days = useMemo(() => dayStrips(events), [events]);
  const [hover, setHover] = useState<number | null>(null);
  const bars = useRef(new Map<number, HTMLButtonElement | null>());
  // The bars in the order they are drawn. Tab reaches one bar (the marked one, or the first); the arrow keys move
  // between them, so a keyboard does not have to step through every activity to get past the timeline.
  const order = useMemo(() => days.flatMap((day) => day.segments.map((segment) => events.indexOf(segment.event))), [days, events]);
  const [reached, setReached] = useState<number | null>(null);
  const stop = reached !== null && order.includes(reached) ? reached : selected !== null && order.includes(selected) ? selected : order[0];

  function onKey(event: KeyboardEvent<HTMLOListElement>) {
    const at = order.indexOf(stop);
    const last = order.length - 1;
    const to = {
      ArrowRight: Math.min(at + 1, last), ArrowDown: Math.min(at + 1, last), ArrowLeft: Math.max(at - 1, 0), ArrowUp: Math.max(at - 1, 0),
      Home: 0, End: last,
    }[event.key];
    if (to === undefined) return;
    event.preventDefault();
    setReached(order[to]);
    bars.current.get(order[to])?.focus();
  }
  const shown = hover ?? selected;
  const active = shown === null ? null : events[shown];
  return (
    <div className="strips">
      <div className="strips__head">
        <h3>Timeline of activities <Tip about="the timeline">{EXPLAIN.timeline}</Tip></h3>
        <p className="strips__key">
          <span className="strips__item">
            <span className="strips__swatch strips__swatch--npt" aria-hidden="true" /> Non-productive time
            <Tip about="non-productive time">{EXPLAIN.nonProductive}</Tip>
          </span>
          <span className="strips__item"><span className="strips__swatch" aria-hidden="true" /> Other activity</span>
        </p>
      </div>
      <div className="strips__scale" aria-hidden="true">
        <span />
        <div className="strips__hours">
          {HOURS.map((hour, index) => (
            <span key={index} style={{ left: `${(hour / 24) * 100}%` }}>{CLOCK[index]}</span>
          ))}
        </div>
        <span />
      </div>
      <ol className="strips__days" aria-label="Days" onKeyDown={onKey}>
        {days.map((day, row) => (
          <li key={day.date} className="strips__day" style={{ "--row": row } as React.CSSProperties}>
            <span className="strips__date">{dayLabel(day.date)}</span>
            <div className="strips__track">
              {day.segments.map((segment) => {
                const index = events.indexOf(segment.event);
                return (
                  <button
                    key={index}
                    ref={(bar) => { bars.current.set(index, bar); }}
                    type="button"
                    tabIndex={index === stop ? 0 : -1}
                    className={[
                      "strips__segment",
                      segment.event.npt_code ? "strips__segment--npt" : "",
                      index === selected ? "strips__segment--selected" : "",
                    ].join(" ")}
                    style={{ left: `${segment.left}%`, width: `${segment.width}%` }}
                    aria-label={describe(segment.event)}
                    aria-pressed={index === selected}
                    onMouseEnter={() => setHover(index)}
                    onMouseLeave={() => setHover(null)}
                    onFocus={() => { setHover(index); setReached(index); }}
                    onBlur={() => setHover(null)}
                    onClick={() => onSelect(index)}
                  />
                );
              })}
            </div>
            <span className="strips__total">{day.hours} h</span>
          </li>
        ))}
      </ol>
      <p className={active ? "strips__readout strips__readout--on" : "strips__readout"} role="note" aria-label="Selected activity">
        {active ? (
          <>
            <strong>{describe(active)}</strong>
            {active.description && <span className="report-text"> {readable(active.description)}</span>}
          </>
        ) : (
          hint
        )}
      </p>
    </div>
  );
});
