/** A piece of report text, marked when it is one of the answer's values. */
export interface Part {
  text: string;
  hit: boolean;
}

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** The pattern a value is written as in a report: 1955 is also 1,955; a word matches whatever its case. */
function pattern(value: string): string | null {
  const trimmed = value.trim();
  if (trimmed.length < 2) return null; // a lone digit or letter would light up half the page
  if (/^-?\d+(\.\d+)?$/.test(trimmed)) {
    const [whole, fraction] = trimmed.replace("-", "").split(".");
    const digits = whole.split("").map((digit, index) => (index > 0 && (whole.length - index) % 3 === 0 ? `,?${digit}` : digit)).join("");
    // "115" also matches "115.0", which is how a report's table may write it; never part of a longer number.
    return `(?<![\\d.,])${digits}${fraction ? `\\.${fraction}` : "(?:\\.0+)?"}(?![\\d]|[.,]\\d)`;
  }
  return escape(trimmed);
}

/**
 * Splits report text around the answer's values, so the place a number is written can be shown. Values are
 * matched as a report writes them, not as the answer normalizes them.
 */
export function highlight(text: string, values: string[]): Part[] {
  const patterns = values.map(pattern).filter((p): p is string => p !== null);
  if (patterns.length === 0 || !text) return [{ text, hit: false }];
  const finder = new RegExp(patterns.join("|"), "gi");
  const parts: Part[] = [];
  let last = 0;
  for (const match of text.matchAll(finder)) {
    const start = match.index ?? 0;
    if (start > last) parts.push({ text: text.slice(last, start), hit: false });
    parts.push({ text: match[0], hit: true });
    last = start + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), hit: false });
  return parts;
}

/**
 * Report text ready to show. PDFs carry bullets and symbols as private-use characters that no font draws; they
 * become a plain bullet, so a list still reads as a list.
 */
export function readable(text: string): string {
  return text.replace(/[\uE000-\uF8FF]/g, "\u2022");
}
