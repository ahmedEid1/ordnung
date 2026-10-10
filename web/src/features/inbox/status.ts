/**
 * What the Inbox says about its filters and search (pure, unit-tested): the result line under the
 * toolbar ("3 letters match “Muster”", "Showing 4 of 22 letters", "Type one more letter to
 * search") and the empty state when nothing is left to show.
 */
import type { EmptyIllustration } from "@/components/ui/EmptyState";
import { plural } from "@/lib/utils";
import type { InboxFilter } from "./filters";

/** A search starts at this many characters. */
export const MIN_SEARCH = 2;

export interface InboxView {
  filter: InboxFilter;
  /** The picked kind as its label ("Invoice"), or null. */
  kindLabel: string | null;
  /** The search words as typed, trimmed. */
  typed: string;
  /** The search that runs ({@link MIN_SEARCH} characters or more), else "". */
  q: string;
}

/** Is the list narrowed by a filter, a kind or a search? */
export function isNarrowed(v: InboxView): boolean {
  return v.filter !== "all" || Boolean(v.kindLabel) || Boolean(v.q);
}

export interface ResultLine {
  /** Announced (role="status"); "" while the whole inbox is shown. */
  text: string;
  /** Shown on screen too — not when an empty state already says it. */
  visible: boolean;
}

/** "1 letter not read yet matches “Wasserzähler”": the waiting letters a search found (they show above the list). */
const heldMatch = (held: number, q: string) => `${held === 1 ? "1 letter not read yet matches" : `${held} letters not read yet match`} “${q}”`;

/**
 * The line under the toolbar: what the list shows now. `held`: the letters waiting from the folder that the
 * search found — listed above, in their own group, never in the list or its counts.
 */
export function resultLine(v: InboxView, shown: number, total: number, searching: boolean, held = 0): ResultLine {
  if (v.typed.length > 0 && v.typed.length < MIN_SEARCH) return { text: "Type one more letter to search.", visible: true };
  if (v.q && searching) return { text: "Searching…", visible: true };
  if (v.q) {
    if (!shown) return { text: held ? heldMatch(held, v.q) : `No letters match “${v.q}”`, visible: false };
    const also = held ? `, and ${held} not read yet (above)` : "";
    return { text: `${shown === 1 ? "1 letter matches" : `${shown} letters match`} “${v.q}”${also}`, visible: true };
  }
  if (isNarrowed(v)) return { text: shown ? `Showing ${shown} of ${plural(total, "letter")}` : "No letters here", visible: shown > 0 };
  return { text: "", visible: false };
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
 * match" then: it says where they are.
 */
export function emptyCopy(v: InboxView, phone = false, held = 0): EmptyCopy {
  const plain = !v.q && !v.kindLabel;
  if (v.q && held) {
    // a filter or a kind narrows only the letters read: the waiting ones are in none
    const searchOnly = v.filter === "all" && !v.kindLabel;
    return {
      title: heldMatch(held, v.q),
      description: `${held === 1 ? "It's" : "They're"} above, in “From your folder — not read yet”. ${searchOnly ? "No other letter matches." : "Filters are on as well — clear them to search all your letters."}`,
      illustration: "search",
      action: searchOnly ? "clear-search" : "clear-filters",
    };
  }
  if (plain && v.filter === "check") {
    return {
      title: "Nothing to check",
      description: "Every date and amount was found in its letter. Ordnung asks here when something doesn't add up.",
      illustration: "clear",
      action: null,
    };
  }
  if (plain && v.filter === "private") {
    return {
      title: "No private letters",
      description: `Letters you add with “Keep private — no AI” are kept here, on ${phone ? "your" : "this"} computer only. Claude never reads them.`,
      illustration: "letter",
      action: "add",
    };
  }
  if (v.q && v.filter === "all" && !v.kindLabel) {
    return {
      title: `No letters match “${v.q}”`,
      description: "Try another word — a sender, a title or an amount.",
      illustration: "search",
      action: "clear-search",
    };
  }
  const letters = v.kindLabel ? `“${v.kindLabel}” letters` : "letters";
  const title = v.q
    ? `No letters match “${v.q}”`
    : v.filter === "check"
      ? `No ${letters} to check`
      : v.filter === "private"
        ? `No private ${letters}`
        : `No ${letters}`;
  return {
    title,
    description: v.q ? "Filters are on as well — clear them to search all your letters." : "Clear the filters to see all your letters.",
    illustration: "search",
    action: "clear-filters",
  };
}
