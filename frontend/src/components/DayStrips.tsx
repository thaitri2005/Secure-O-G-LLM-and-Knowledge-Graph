import { memo } from "react";
import type { EventOut } from "../api/types";
import { dayStrips } from "../lib/strips";

const HOURS = [0, 6, 12, 18, 24];

export function dayLabel(date: string): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}

export function describe(event: EventOut): string {
  const kind = event.npt_code ? `, non-productive (${event.npt_code})` : "";
  return `${dayLabel(event.date)}, ${event.start} to ${event.end}, ${event.hours} h, ${event.code}${kind}`;
}

interface Props {
  events: EventOut[];
  selected: number | null;
  onSelect: (index: number) => void;
}

/**
 * The operations behind a computed number, one 24-hour strip per report day: the time breakdown a daily drilling
 * report prints as a table, drawn. Non-productive time is hatched. Each operation can be picked, by pointer or
 * keyboard, and the table below shows the same one.
 */
export const DayStrips = memo(function DayStrips({ events, selected, onSelect }: Props) {
  const days = dayStrips(events);
  const active = selected === null ? null : events[selected];
  return (
    <div className="strips">
      <div className="strips__scale" aria-hidden="true">
        <span />
        <div className="strips__hours">
          {HOURS.map((hour) => (
            <span key={hour} style={{ left: `${(hour / 24) * 100}%` }}>{String(hour).padStart(2, "0")}:00</span>
          ))}
        </div>
        <span />
      </div>
      <ol className="strips__days" aria-label="Report days">
        {days.map((day, row) => (
          <li key={day.date} className="strips__day" style={{ "--row": row } as React.CSSProperties}>
            <span className="strips__date">{dayLabel(day.date)}</span>
            <div className="strips__track">
              {day.segments.map((segment) => {
                const index = events.indexOf(segment.event);
                return (
                  <button
                    key={index}
                    type="button"
                    className={[
                      "strips__segment",
                      segment.event.npt_code ? "strips__segment--npt" : "",
                      index === selected ? "strips__segment--selected" : "",
                    ].join(" ")}
                    style={{ left: `${segment.left}%`, width: `${segment.width}%` }}
                    aria-label={describe(segment.event)}
                    aria-pressed={index === selected}
                    onClick={() => onSelect(index)}
                  />
                );
              })}
            </div>
            <span className="strips__total">{day.hours} h</span>
          </li>
        ))}
      </ol>
      <div className="strips__foot">
        <p className="strips__key" aria-hidden="true">
          <span className="strips__swatch strips__swatch--npt" /> Non-productive
          <span className="strips__swatch" /> Other operations counted
        </p>
        <p className="strips__readout" role="note" aria-label="Selected operation">
          {active ? (
            <>
              <strong>{describe(active)}</strong>
              {active.description && <span className="report-text"> {active.description}</span>}
            </>
          ) : (
            "Pick an operation on a strip, or a row below, to see it in both."
          )}
        </p>
      </div>
    </div>
  );
});
