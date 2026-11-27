/**
 * A long Inbox draws the first 100 letters of a view, then 100 more or all of them as asked: drawing 3,000 rows kept a
 * slowed phone busy for 13 seconds. Filters, tabs, counts and the search still work on every letter; only the rows
 * drawn are fewer. Lists of 100 letters or fewer look as they always did.
 *
 * How many rows a view draws is kept in its history entry's own state (beside what the router keeps there), so Back,
 * Forward and a reload of that entry come back to them, while a typed address, a bookmark or any new load of the page
 * starts at 100. Not in sessionStorage by the router's location key: every page load shares the key "default", so one
 * "Show all" drew every letter on every later load. A reload keeps the rows; the place on the page comes back on Back
 * and Forward within the app (the router's own scroll restoration), not always after a reload, while the letters load.
 */
import { useEffect, useState } from "react";
import { useLocation } from "react-router";
import type { LetterGroup } from "./filters";

/** Rows drawn at first, and added by "Show 100 more". */
export const ROWS_STEP = 100;

/** A number as the Inbox writes it ("3,000"). */
export const count = (n: number): string => n.toLocaleString("en-GB");

/** A group of letters with only its first rows drawn: `count` is all of its letters, as its heading says. */
export interface DrawnGroup extends LetterGroup {
  count: number;
}

/** The groups with only the first `limit` letters, in order; a group cut short still counts all of its letters. */
export function firstRows(groups: LetterGroup[], limit: number): DrawnGroup[] {
  const out: DrawnGroup[] = [];
  let left = limit;
  for (const g of groups) {
    if (left <= 0) break;
    out.push({ ...g, docs: g.docs.length > left ? g.docs.slice(0, left) : g.docs, count: g.docs.length });
    left -= g.docs.length;
  }
  return out;
}

/** What the page's history entry keeps: the view (its tab, kind, year, person and search) and the rows it draws. */
interface Kept {
  view: string;
  rows: number;
}

const KEY = "inboxRows";

function entryState(): Record<string, unknown> {
  const state: unknown = window.history.state;
  return state && typeof state === "object" ? (state as Record<string, unknown>) : {};
}

/**
 * A new load of the page (an address typed, a bookmark, a link from elsewhere) starts at 100 whatever its entry
 * keeps: Chrome keeps the entry's state when the address typed is the one already open. This module loads with the
 * Inbox's first view in a page load, so it looks once, then; a reload and Back or Forward from another site keep them.
 */
function forgetOnNewLoad(): void {
  try {
    const load = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
    if (load?.type !== "navigate") return;
    const { [KEY]: kept, ...rest } = entryState();
    if (kept !== undefined) window.history.replaceState(rest, "");
  } catch {
    /* no timing of the load: the entry's state is all there is */
  }
}
forgetOnNewLoad();

/** The rows this history entry drew for `view`, else the first 100. */
function keptRows(view: string): number {
  try {
    const kept = entryState()[KEY] as Kept | undefined;
    return kept?.view === view && typeof kept.rows === "number" && kept.rows > ROWS_STEP ? kept.rows : ROWS_STEP;
  } catch {
    return ROWS_STEP;
  }
}

/** Keep the rows in this history entry's state, spread over what the router keeps there (its key and index). */
function keepRows(view: string, rows: number): void {
  try {
    const { [KEY]: kept, ...rest } = entryState() as Record<string, unknown> & { [KEY]?: Kept };
    if (rows <= ROWS_STEP ? kept === undefined : kept?.view === view && kept.rows === rows) return;
    window.history.replaceState(rows <= ROWS_STEP ? rest : { ...rest, [KEY]: { view, rows } satisfies Kept }, "");
  } catch {
    /* a browser that refuses: the rows are simply not kept */
  }
}

/**
 * The rows a view draws (`Infinity`: all), and a way to draw more. `view` names what the list shows (its tab, kind,
 * year, person and search): another view starts at 100 again.
 */
export function useDrawnRows(view: string): { rows: number; setRows: (rows: number) => void } {
  const [drawn, setDrawn] = useState(() => ({ view, rows: keptRows(view) }));
  // the router's entry: a link to the page already open (the sidebar's Inbox) replaces the entry's state with its
  // own and keeps the view, so the rows drawn are written into the new entry too, or a reload would draw 100
  const { key: entry } = useLocation();
  let current = drawn;
  if (drawn.view !== view) {
    current = { view, rows: ROWS_STEP };
    setDrawn(current);
  }
  useEffect(() => keepRows(current.view, current.rows), [current.view, current.rows, entry]);
  return { rows: current.rows, setRows: (rows: number) => setDrawn({ view, rows }) };
}
