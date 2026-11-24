import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Icon } from "./Icon";

/** Where a bubble's left edge goes so that it is centred on its "i" but stays on the screen, a small margin kept. */
export function bubbleLeft(centre: number, width: number, screen: number, margin = 8): number {
  return Math.round(Math.max(margin, Math.min(centre - width / 2, screen - margin - width)));
}

/**
 * A small "i" that explains the thing beside it. The explanation shows on hover and on keyboard focus, and a
 * click or tap pins it open, so it also works on a touch screen. Esc or a click elsewhere closes it. The pointer
 * can move onto the explanation without it closing, and it never runs off the edge of the screen.
 */
export function Tip({ about, children }: { about: string; children: ReactNode }) {
  const [pinned, setPinned] = useState(false);
  const [near, setNear] = useState(false);
  const id = useId();
  const wrap = useRef<HTMLSpanElement>(null);
  const bubble = useRef<HTMLSpanElement>(null);
  const open = pinned || near;

  useEffect(() => {
    if (!open) return;
    function away(event: MouseEvent | KeyboardEvent) {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !wrap.current?.contains(event.target as Node)) {
        setPinned(false);
        setNear(false);
      }
    }
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", away);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", away);
    };
  }, [open]);

  // The explanation is placed on the screen itself, not inside whatever holds the "i": a table that scrolls
  // sideways would otherwise cut it off. It is put under the "i", and follows it when the page scrolls.
  useLayoutEffect(() => {
    const shown = bubble.current;
    const anchor = wrap.current;
    if (!open || !shown || !anchor) return;
    function place() {
      if (!shown || !anchor) return;
      shown.style.left = "0px";
      shown.style.top = "0px";
      const origin = shown.getBoundingClientRect(); // where "0, 0" falls: not always the screen's corner
      const at = anchor.getBoundingClientRect();
      const centre = at.left + at.width / 2;
      const left = bubbleLeft(centre, origin.width, document.documentElement.clientWidth);
      shown.style.left = `${left - origin.left}px`;
      shown.style.top = `${at.bottom + 8 - origin.top}px`;
      shown.style.setProperty("--arrow", `${centre - left}px`);
    }
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open]);

  return (
    <span className="tip" ref={wrap} onMouseEnter={() => setNear(true)} onMouseLeave={() => setNear(false)}>
      <button
        type="button"
        className="tip__button"
        aria-label={`What is ${about}?`}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onFocus={() => setNear(true)}
        onBlur={() => setNear(false)}
        onClick={(event) => {
          event.stopPropagation();
          setPinned((was) => !was);
        }}
      >
        <Icon name="info" size={16} />
      </button>
      {open && (
        <span role="tooltip" id={id} ref={bubble} className="tip__bubble">
          {children}
        </span>
      )}
    </span>
  );
}
