import { useEffect, useState } from "react";
import { showAll, showFewer, showingFirst } from "../lib/wording";

/**
 * A long list shown as its first part, with one button for the rest. `reveal` opens it from outside (a bar clicked
 * on the timeline whose row is folded away; `revealed` names what was chosen, so a second choice opens it again), and printing opens it, so a printed answer carries every row.
 */
export function useFold(total: number, first: number, reveal = false, revealed: unknown = null): { limit: number; open: boolean; toggle: () => void; folds: boolean } {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (reveal) setOpen(true);
  }, [reveal, revealed]);
  useEffect(() => {
    const onPrint = () => setOpen(true);
    window.addEventListener("beforeprint", onPrint);
    return () => window.removeEventListener("beforeprint", onPrint);
  }, []);
  const folds = first < total;
  return { limit: open || !folds ? total : first, open, toggle: () => setOpen((was) => !was), folds };
}

interface Props {
  shown: number;
  total: number;
  /** What the list is of, in the plural: "activities", "days". */
  things: string;
  open: boolean;
  onToggle: () => void;
}

/** Under a folded list: how much of it is showing, and the button that shows all of it or folds it again. */
export function FoldControl({ shown, total, things, open, onToggle }: Props) {
  return (
    <p className="fold">
      {!open && <span className="fold__note">{showingFirst(shown, total, things)}</span>}
      <button type="button" className="chip fold__button" aria-expanded={open} onClick={onToggle}>
        {open ? showFewer(things) : showAll(total, things)}
      </button>
    </p>
  );
}
