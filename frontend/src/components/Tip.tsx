import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Icon } from "./Icon";

/**
 * A small "i" that explains the thing beside it. The explanation shows on hover and on keyboard focus, and a
 * click or tap pins it open, so it also works on a touch screen. Esc or a click elsewhere closes it.
 */
export function Tip({ about, children }: { about: string; children: ReactNode }) {
  const [pinned, setPinned] = useState(false);
  const [near, setNear] = useState(false);
  const id = useId();
  const wrap = useRef<HTMLSpanElement>(null);
  const open = pinned || near;

  useEffect(() => {
    if (!pinned) return;
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
  }, [pinned]);

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
        <span role="tooltip" id={id} className="tip__bubble">
          {children}
        </span>
      )}
    </span>
  );
}
