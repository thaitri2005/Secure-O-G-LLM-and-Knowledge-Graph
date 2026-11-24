// Long lists are folded: a sensible first part is shown, and one button shows the rest.

/**
 * How many of a day-ordered list of activities to show before folding: whole days, until at least `enough`
 * activities are shown. A list barely longer than that is shown whole, since folding two rows helps nobody.
 */
export function firstDays(dates: string[], enough = 6, slack = 4): number {
  if (dates.length <= enough + slack) return dates.length;
  let shown = 0;
  while (shown < dates.length) {
    const day = dates[shown];
    while (shown < dates.length && dates[shown] === day) shown += 1;
    if (shown >= enough) break;
  }
  return dates.length - shown <= slack ? dates.length : shown;
}

/** How many rows of a plain list to show before folding. */
export function firstRows(total: number, enough = 6, slack = 3): number {
  return total <= enough + slack ? total : enough;
}

/**
 * Where a column that follows the page should stick. A column shorter than the window sticks under the question
 * box; a taller one sticks by its bottom edge instead, so its end can still be reached by scrolling.
 */
export function stickyTop(columnHeight: number, windowHeight: number, under: number, gap = 16): number {
  return Math.round(Math.min(under, windowHeight - columnHeight - gap));
}
