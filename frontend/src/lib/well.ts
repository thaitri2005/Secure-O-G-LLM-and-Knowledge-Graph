// A page about one well: its casing strings laid out as the reports' casing tables are, planned beside actual, and
// which of its days the timeline can draw.
import type { CasingString, EventOut, ReportDay, WellFact } from "../api/types";

export interface CasingRow {
  property: string;
  planned: WellFact | null;
  actual: WellFact | null;
}

/** One casing string's facts as rows (depth, weight, grade) with the planned and the actual value side by side. */
export function casingRows(casing: CasingString): CasingRow[] {
  const rows = new Map<string, CasingRow>();
  for (const fact of casing.facts) {
    const row = rows.get(fact.property) ?? { property: fact.property, planned: null, actual: null };
    if (fact.qualifier === "planned") row.planned ??= fact;
    else row.actual ??= fact;
    rows.set(fact.property, row);
  }
  return [...rows.values()];
}

/** Whether any row of these casing strings has a planned value; without one, the planned column is left out. */
export function anyPlanned(casings: CasingString[]): boolean {
  return casings.some((casing) => casing.facts.some((fact) => fact.qualifier === "planned"));
}

/**
 * The activities the timeline draws: those of days whose logged hours they add up to. A day only partly at hand
 * would be drawn with gaps that are not in the report, so it is left to the day table.
 */
export function wholeDays(events: EventOut[], days: ReportDay[]): EventOut[] {
  const logged = new Map(days.map((day) => [day.date, day.hours]));
  const held = new Map<string, number>();
  for (const event of events) held.set(event.date, (held.get(event.date) ?? 0) + event.hours);
  return events.filter((event) => {
    const hours = logged.get(event.date);
    return hours !== undefined && Math.abs((held.get(event.date) ?? 0) - hours) < 0.01;
  });
}
