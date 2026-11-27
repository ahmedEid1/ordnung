/**
 * What the Inbox says about its filters and search (pure, unit-tested): the result line under the
 * toolbar ("3 letters match “Muster”", "Showing 4 of 22 letters", "Type one more letter to
 * search") and the empty state when nothing is left to show.
 */
import type { EmptyIllustration } from "@/components/ui/EmptyState";
import type { InboxFilter } from "./filters";
import { ROWS_STEP, count } from "./rows";

/** A search starts at this many characters. */
export const MIN_SEARCH = 2;

/**
 * Whose letters the list shows (the household's *For* select): the person's own (`mine`: every letter not filed for
 * someone), or one person's (`suggested`: their letters not filed yet, listed in the card above the list).
 */
export type InboxWho = { kind: "mine" } | { kind: "person"; name: string; suggested: number };

export interface InboxView {
  filter: InboxFilter;
  /** The picked kind as its label ("Invoice"), or null. */
  kindLabel: string | null;
  /** The search words as typed, trimmed. */
  typed: string;
  /** The search that runs ({@link MIN_SEARCH} characters or more), else "". */
  q: string;
  /** The year chosen (by the date on the letter, else the day it arrived), or null: every year. */
  year: number | null;
  /** Whose letters, or null: everyone's (also when the household has no people). */
  who: InboxWho | null;
}

/** Is the list narrowed by a filter, a kind, a year, whose letters or a search? */
export function isNarrowed(v: InboxView): boolean {
  return v.filter !== "all" || Boolean(v.kindLabel) || Boolean(v.q) || v.year != null || v.who != null;
}

export interface ResultLine {
  /** Announced (role="status"); "" while the whole inbox is shown. */
  text: string;
  /** Shown on screen too — not when an empty state already says it. */
  visible: boolean;
}

/** "1 letter not read yet matches “Wasserzähler”": the waiting letters a search found (they show above the list). */
const heldMatch = (held: number, q: string) => `${held === 1 ? "1 letter not read yet matches" : `${held} letters not read yet match`} “${q}”`;

/** "3,000 letters". */
const letters = (n: number) => `${count(n)} ${n === 1 ? "letter" : "letters"}`;

/**
 * The line under the toolbar: what the list shows now. `held`: the letters waiting from the folder that the
 * search found — listed above, in their own group, never in the list or its counts. `drawn`: the rows drawn of a
 * long list (./rows.ts): when they are fewer than its `shown` letters, a narrowed view says what it holds
 * ("136 of 3,000 letters in this view."), not "Showing 136", while 100 rows are drawn.
 */
export function resultLine(v: InboxView, shown: number, total: number, searching: boolean, held = 0, drawn = shown): ResultLine {
  if (v.typed.length > 0 && v.typed.length < MIN_SEARCH) return { text: "Type one more letter to search.", visible: true };
  if (v.q && searching) return { text: "Searching…", visible: true };
  // a view longer than the rows drawn at first ends its line with a full stop, drawn in part or whole, so the line
  // reads the same as its rows come and runs into no sentence after it; a shorter list's line is as it always was
  const stop = shown > ROWS_STEP ? "." : "";
  if (v.q) {
    if (!shown) return { text: held ? heldMatch(held, v.q) : `No letters match “${v.q}”`, visible: false };
    const also = held ? `, and ${count(held)} not read yet (above)` : "";
    return { text: `${shown === 1 ? "1 letter matches" : `${count(shown)} letters match`} “${v.q}”${also}${stop}`, visible: true };
  }
  if (isNarrowed(v)) {
    if (!shown) return { text: "No letters here", visible: false };
    return { text: drawn < shown ? `${count(shown)} of ${letters(total)} in this view.` : `Showing ${count(shown)} of ${letters(total)}${stop}`, visible: true };
  }
  return { text: "", visible: false };
}

/**
 * What the page's live line says: the line under the toolbar, and for a long list the rows drawn of it ("Showing 200
 * of 3,000 letters."), each sentence with its full stop, so the two are never read as one. `asked`: the rows asked
 * for (`Infinity` after "Show all"): once a long list is drawn whole, the whole Inbox says so too ("Showing all 3,000
 * letters."), where its line says nothing.
 */
export function announced(line: ResultLine, drawn: number, shown: number, asked = drawn): string {
  if (drawn >= shown) return !line.text && asked > ROWS_STEP && shown > ROWS_STEP ? `Showing all ${letters(shown)}.` : line.text;
  const rows = `Showing ${count(drawn)} of ${letters(shown)}.`;
  if (!line.text) return rows;
  return `${/[.!?…]$/.test(line.text) ? line.text : `${line.text}.`} ${rows}`;
}

export interface EmptyCopy {
  title: string;
  description: string;
  illustration: EmptyIllustration;
  /** `clear-search` clears only the words, `clear-filters` everything, `add` opens "Add letters". */
  action: "clear-search" | "clear-filters" | "add" | null;
}

/**
 * The empty state of a filtered list — it says which filter left it empty and how to get out (`phone`: on a paired
 * phone, where the letters are on "your computer"). `held`: waiting letters the search found — never "No letters
 * match" then: it says where they are. The all-clear of *Please check*, the explanation of *Private* and the words
 * about whose letters show only while nothing else narrows the list.
 */
export function emptyCopy(v: InboxView, phone = false, held = 0): EmptyCopy {
  const plain = !v.q && !v.kindLabel && v.year == null;
  if (v.q && held) {
    // a filter, a kind or a year narrows only the letters read: the waiting ones are in none
    const searchOnly = v.filter === "all" && !v.kindLabel && v.year == null && !v.who;
    return {
      title: heldMatch(held, v.q),
      description: `${held === 1 ? "It's" : "They're"} above, in “From your folder — not read yet”. ${searchOnly ? "No other letter matches." : "Filters are on as well — clear them to search all your letters."}`,
      illustration: "search",
      action: searchOnly ? "clear-search" : "clear-filters",
    };
  }
  if (plain && v.who && v.filter === "all") {
    if (v.who.kind === "mine") {
      return { title: "No letters for you here", description: "Every letter is filed for someone in your household.", illustration: "letter", action: "clear-filters" };
    }
    const { name, suggested } = v.who;
    return {
      title: `No letters filed for ${name}`,
      description: suggested
        ? `The letters above are addressed to ${name}. File them with one press.`
        : `Open a letter and press “Change” next to “For you” to file it for ${name}.`,
      illustration: "letter",
      action: "clear-filters",
    };
  }
  if (plain && !v.who && v.filter === "check") {
    return {
      title: "Nothing to check",
      description: "Every date and amount was found in its letter. Ordnung asks here when something doesn't add up.",
      illustration: "clear",
      action: null,
    };
  }
  if (plain && !v.who && v.filter === "private") {
    return {
      title: "No private letters",
      description: `Letters you add with “Keep private — no AI” are kept here, on ${phone ? "your" : "this"} computer only. Claude never reads them.`,
      illustration: "letter",
      action: "add",
    };
  }
  if (v.q && v.filter === "all" && !v.kindLabel && v.year == null && !v.who) {
    return {
      title: `No letters match “${v.q}”`,
      description: "Try another word — a sender, a title or an amount.",
      illustration: "search",
      action: "clear-search",
    };
  }
  // whose letters are missing, when the For choice narrows the list too
  const whose = !v.who ? "" : v.who.kind === "mine" ? " of yours" : ` for ${v.who.name}`;
  const letters = `${v.kindLabel ? `“${v.kindLabel}” letters` : "letters"}${whose}`;
  const dated = v.year != null ? ` dated ${v.year}` : "";
  const title = v.q
    ? `No letters match “${v.q}”`
    : v.filter === "check"
      ? `No ${letters}${dated} to check`
      : v.filter === "private"
        ? `No private ${letters}${dated}`
        : `No ${letters}${dated}`;
  // only the year narrows the list: that year has no letters at all
  const yearAlone = v.year != null && !v.q && !v.kindLabel && !v.who && v.filter === "all";
  return {
    title,
    description: v.q
      ? "Filters are on as well — clear them to search all your letters."
      : yearAlone
        ? "Ordnung files a letter under the year of the date on it, else the day it arrived. Choose another year, or clear the filters."
        : "Clear the filters to see all your letters.",
    illustration: "search",
    action: "clear-filters",
  };
}
