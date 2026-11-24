// Which screen is open, kept in the address's query string as the application already keeps a question there
// (?q=...). The browser's back button and a copied link then work without a router: ?well=AK-3 is a well's page,
// ?view=questions the questions people asked, and ?view=questions&question=<id> one of them.

export type Route =
  | { view: "home" }
  | { view: "well"; well: string }
  | { view: "questions"; question: string | null };

export const HOME: Route = { view: "home" };

export function readRoute(search: string): Route {
  const params = new URLSearchParams(search);
  const well = params.get("well")?.trim();
  if (well) return { view: "well", well };
  if (params.get("view") === "questions") return { view: "questions", question: params.get("question") || null };
  return HOME;
}

/** The query string of a screen: empty for the start. */
export function routeSearch(route: Route): string {
  if (route.view === "well") return `?${new URLSearchParams({ well: route.well })}`;
  if (route.view === "questions") {
    return `?${new URLSearchParams({ view: "questions", ...(route.question ? { question: route.question } : {}) })}`;
  }
  return "";
}

/** Opens a screen and adds it to the browser's history, marked as reached from inside the application. */
export function pushRoute(route: Route): void {
  const search = routeSearch(route);
  if (search === window.location.search) return;
  window.history.pushState({ inApp: true }, "", search || window.location.pathname);
}

/** Whether the screen before this one in the history is the application's own, so "back" stays inside it. */
export function cameFromApp(): boolean {
  return Boolean((window.history.state as { inApp?: boolean } | null)?.inApp);
}
