import { useEffect, useState, type RefObject } from "react";
import { stickyTop } from "./fold";

/** Whether the window matches a media query; false where the browser cannot say. */
export function useMedia(query: string): boolean {
  const [matches, setMatches] = useState(() => (typeof window.matchMedia === "function" ? window.matchMedia(query).matches : false));
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(query);
    const onChange = () => setMatches(media.matches);
    onChange();
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

/** One column below this width: the same breakpoint the stylesheet uses. */
export const NARROW = "(max-width: 62rem)";

/**
 * Keeps a column in view while the taller column beside it scrolls. The stylesheet makes it sticky; this tells it
 * where to stick (--stick), which depends on its own height and on the question box above it. `whenever` names
 * what is drawn, so a column that appears later is picked up.
 */
export function useStickyColumn(column: RefObject<HTMLElement | null>, whenever: unknown = null): void {
  useEffect(() => {
    const element = column.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const hero = document.querySelector<HTMLElement>(".hero");
    const update = () => {
      const under = hero && !hero.hidden && getComputedStyle(hero).position === "sticky" ? hero.offsetHeight : 0;
      element.style.setProperty("--stick", `${stickyTop(element.offsetHeight, window.innerHeight, under + 16)}px`);
      // Things scrolled into view must clear the question box that stays at the top.
      document.documentElement.style.setProperty("--under-hero", `${under + 16}px`);
    };
    const observer = new ResizeObserver(update);
    observer.observe(element);
    if (hero) observer.observe(hero);
    window.addEventListener("resize", update);
    update();
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [column, whenever]);
}
