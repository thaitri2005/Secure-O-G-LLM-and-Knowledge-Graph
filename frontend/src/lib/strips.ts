import type { EventOut } from "../api/types";

/** One event placed on its day's 24-hour strip, as percentages of the day. */
export interface Segment {
  left: number;
  width: number;
  event: EventOut;
}

export interface DayStrip {
  date: string;
  hours: number;
  nonProductiveHours: number;
  segments: Segment[];
}

function minutes(clock: string): number {
  const [hours, mins] = clock.split(":").map(Number);
  return hours * 60 + mins;
}

/**
 * Groups events by report day and places each on a 24-hour strip. A daily report writes midnight as 0:00 at both
 * ends, so an event's width comes from its hours, not from its end time, and is cut at the end of the day.
 */
export function dayStrips(events: EventOut[]): DayStrip[] {
  const days = new Map<string, EventOut[]>();
  for (const event of events) {
    days.set(event.date, [...(days.get(event.date) ?? []), event]);
  }
  return [...days.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, list]) => {
      const sorted = [...list].sort((a, b) => minutes(a.start) - minutes(b.start));
      return {
        date,
        hours: sorted.reduce((sum, e) => sum + e.hours, 0),
        nonProductiveHours: sorted.filter((e) => e.npt_code).reduce((sum, e) => sum + e.hours, 0),
        segments: sorted.map((event) => {
          const left = (minutes(event.start) / 1440) * 100;
          return { left, width: Math.min((event.hours / 24) * 100, 100 - left), event };
        }),
      };
    });
}
