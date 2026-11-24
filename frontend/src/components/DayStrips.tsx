import type { EventOut } from "../api/types";
import { dayStrips } from "../lib/strips";

const HOURS = [0, 6, 12, 18, 24];

function dayLabel(date: string): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}

/**
 * The operations behind a computed number, one 24-hour strip per report day: the time breakdown a daily drilling
 * report prints as a table, drawn. Non-productive time is hatched, as it is the thing these questions ask about.
 */
export function DayStrips({ events }: { events: EventOut[] }) {
  const days = dayStrips(events);
  return (
    <div className="strips">
      <div className="strips__scale" aria-hidden="true">
        <span className="strips__date" />
        <div className="strips__hours">
          {HOURS.map((hour) => (
            <span key={hour} style={{ left: `${(hour / 24) * 100}%` }}>{String(hour).padStart(2, "0")}</span>
          ))}
        </div>
        <span className="strips__total" />
      </div>
      <ol className="strips__days" aria-label="Report days">
        {days.map((day) => (
          <li key={day.date} className="strips__day">
            <span className="strips__date">{dayLabel(day.date)}</span>
            <div className="strips__track">
              {day.segments.map((segment, index) => (
                <span
                  key={index}
                  className={segment.event.npt_code ? "strips__segment strips__segment--npt" : "strips__segment"}
                  style={{ left: `${segment.left}%`, width: `${segment.width}%` }}
                  title={`${segment.event.start} to ${segment.event.end}, ${segment.event.hours} h, ${segment.event.code}${
                    segment.event.npt_code ? `, non-productive (${segment.event.npt_code})` : ""
                  }${segment.event.description ? `: ${segment.event.description}` : ""}`}
                />
              ))}
            </div>
            <span className="strips__total">{day.hours} h</span>
          </li>
        ))}
      </ol>
      <p className="strips__key">
        <span className="strips__swatch strips__swatch--npt" /> Non-productive time
        <span className="strips__swatch" /> Other operations counted
      </p>
    </div>
  );
}
