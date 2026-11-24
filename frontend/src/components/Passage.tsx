import { useEffect, useMemo, useRef, useState } from "react";
import type { ChunkOut } from "../api/types";
import { highlight, readable } from "../lib/highlight";
import { place } from "../lib/wording";
import { Icon } from "./Icon";

/** Report text, in the reports' own typeface, with the answer's values highlighted where they are written. */
export function ReportText({ text, values }: { text: string; values: string[] }) {
  const parts = useMemo(() => highlight(readable(text), values), [text, values]);
  const box = useRef<HTMLParagraphElement>(null);
  const [scrolls, setScrolls] = useState(false);
  // A long passage is shown in a box that scrolls; open it where the answer's value is written.
  useEffect(() => {
    const first = box.current?.querySelector("mark");
    // A box that scrolls must be reachable with the keyboard, or its lower lines cannot be read without a mouse.
    setScrolls(Boolean(box.current && box.current.scrollHeight > box.current.clientHeight));
    if (box.current && first instanceof HTMLElement && box.current.scrollHeight > box.current.clientHeight) {
      // The box is the mark's offset parent (it is positioned), so offsetTop is already measured from its top.
      box.current.scrollTop = Math.max(0, first.offsetTop - 48);
    }
  }, [parts]);
  return (
    <p className={scrolls ? "report-text report-text--scrolls" : "report-text"} ref={box} tabIndex={scrolls ? 0 : undefined}>
      {parts.map((part, index) => (part.hit ? <mark key={index}>{part.text}</mark> : part.text))}
    </p>
  );
}

interface PassageProps {
  chunk: ChunkOut;
  cited: boolean;
  values: string[];
  onOpenPage: (chunk: ChunkOut) => void;
  /** What the flag on a cited passage says. */
  flag?: string;
  id?: string;
}

export function Passage({ chunk, cited, values, onOpenPage, flag = "The answer is here", id }: PassageProps) {
  return (
    <article id={id} tabIndex={id ? -1 : undefined} className={cited ? "passage passage--cited" : "passage"}>
      <header className="passage__where">
        <span><Icon name="document" size={16} /> {place(chunk.file_id, chunk.page)}{chunk.section ? ` · ${chunk.section}` : ""}</span>
        {cited && <span className="passage__flag"><Icon name="check" size={14} /> {flag}</span>}
      </header>
      {chunk.text === null ? (
        <p className="passage__missing">This report’s text is not available on this computer.</p>
      ) : (
        <ReportText text={chunk.text} values={values} />
      )}
      {chunk.page !== null && chunk.text !== null && (
        <button type="button" className="link" onClick={() => onOpenPage(chunk)}>Read the whole page</button>
      )}
    </article>
  );
}
