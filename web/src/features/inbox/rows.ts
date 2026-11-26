/**
 * A long Inbox draws the first 100 letters of a view, then 100 more or all of them as asked: drawing 3,000 rows kept a
 * slowed phone busy for 13 seconds. Filters, tabs, counts and the search still work on every letter; only the rows
 * drawn are fewer. Lists of 100 letters or fewer look as they always did.
 */
import { useState } from "react";
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

/**
 * The rows a view draws (`Infinity`: all), and a way to draw more. `view` names what the list shows (its tab, kind,
 * year, person and search): another view starts at 100 again.
 */
export function useDrawnRows(view: string): { rows: number; setRows: (rows: number) => void } {
  const [drawn, setDrawn] = useState(() => ({ view, rows: ROWS_STEP }));
  let current = drawn;
  if (drawn.view !== view) {
    current = { view, rows: ROWS_STEP };
    setDrawn(current);
  }
  return { rows: current.rows, setRows: (rows: number) => setDrawn({ view, rows }) };
}
