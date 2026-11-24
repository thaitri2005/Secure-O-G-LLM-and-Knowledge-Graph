import type { KeyboardEvent } from "react";

export interface TabItem<T extends string> {
  id: T;
  label: string;
  /** How many things the tab holds, shown beside its name. */
  count?: number;
}

interface Props<T extends string> {
  /** What the tabs are of, for a screen reader. */
  label: string;
  /** The start of each tab's and each panel's id: tab "tab-text" controls panel "panel-text". */
  ids?: [string, string];
  tabs: TabItem<T>[];
  selected: T;
  onSelect: (id: T) => void;
}

/**
 * A row of tabs that works the way tabs do everywhere: Tab reaches the open one, the arrow keys (and Home and End)
 * move between them, and the panel below can be reached with Tab.
 */
export function TabList<T extends string>({ label, ids = ["tab", "panel"], tabs, selected, onSelect }: Props<T>) {
  function onKey(event: KeyboardEvent<HTMLDivElement>) {
    const at = tabs.findIndex((tab) => tab.id === selected);
    const last = tabs.length - 1;
    const to = { ArrowRight: at === last ? 0 : at + 1, ArrowLeft: at === 0 ? last : at - 1, Home: 0, End: last }[event.key];
    if (to === undefined) return;
    event.preventDefault();
    onSelect(tabs[to].id);
    document.getElementById(`${ids[0]}-${tabs[to].id}`)?.focus();
  }
  return (
    <div className="tabs" role="tablist" aria-label={label} onKeyDown={onKey}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          id={`${ids[0]}-${tab.id}`}
          aria-selected={selected === tab.id}
          aria-controls={`${ids[1]}-${tab.id}`}
          aria-label={tab.count === undefined ? undefined : `${tab.label} ${tab.count}`}
          tabIndex={selected === tab.id ? 0 : -1}
          className="tabs__tab"
          onClick={() => onSelect(tab.id)}
        >
          {tab.label}{tab.count === undefined ? null : <> <span className="tabs__count">{tab.count}</span></>}
        </button>
      ))}
    </div>
  );
}
