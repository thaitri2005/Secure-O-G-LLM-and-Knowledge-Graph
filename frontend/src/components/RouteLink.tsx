import type { MouseEvent, ReactNode } from "react";
import { routeSearch, type Route } from "../lib/route";

/**
 * A link to another screen of the application. It is a real link, so it can be copied or opened in a new tab; a
 * plain click opens the screen in place.
 */
export function RouteLink({ to, onGo, className, children, label }: {
  to: Route;
  onGo: (route: Route) => void;
  className?: string;
  children: ReactNode;
  label?: string;
}) {
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onGo(to);
  }
  return (
    <a href={routeSearch(to) || "./"} className={className ?? "link"} aria-label={label} onClick={follow}>
      {children}
    </a>
  );
}
