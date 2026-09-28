/**
 * Which Ideas the letter page shows under "Ideas", and how their text names this letter (UI audit
 * round 1: the letter page repeated the verdict's payment as an Idea, showed "Add your 26 dates to
 * your calendar" on every letter, and a "Please check" Idea pointed at the letter you were reading).
 */
import type { Item, Suggestion } from "@/api/types";
import { RECORD_ID_RE } from "@/lib/copy";

const LIVE: ReadonlySet<Suggestion["status"]> = new Set(["new", "accepted", "snoozed"]);

/**
 * The live Ideas about this letter:
 * - about this letter — it names the letter, or every to-do it names is one of the letter's
 *   (a sweep over all your dates, like "Add your 26 dates to your calendar", is not);
 * - not the scam warning (the verdict carries it) nor "Please check" for this letter (the page
 *   says that above, next to the to-do);
 * - not the verdict again: a rule's reminder about the verdict's to-do alone ("Pay … by Thu 1 Oct").
 */
export function ideasForLetter(
  suggestions: readonly Suggestion[],
  { docId, items, primaryId }: { docId: string; items: readonly Pick<Item, "id">[]; primaryId?: string | null },
): Suggestion[] {
  const own = new Set(items.map((i) => i.id));
  return suggestions.filter((s) => {
    if (s.kind === "scam" || !LIVE.has(s.status)) return false;
    const docs = s.refs.filter((r) => r.type === "document").map((r) => r.id);
    const todos = s.refs.filter((r) => r.type === "item").map((r) => r.id);
    const aboutLetter = docs.includes(docId) || (todos.length > 0 && todos.every((id) => own.has(id)));
    if (!aboutLetter) return false;
    if (s.rule_id === "please_check") return false;
    // a rule's reminder about the verdict's to-do alone restates it; a Weekly Ideas insight about it
    // ("you now have the certificate — send it") is new
    if (primaryId && s.source === "rule" && todos.length === 1 && todos[0] === primaryId) return false;
    return true;
  });
}

/**
 * An Idea's text on the page of the letter it is about: the letter's own id reads "this letter" and
 * its to-dos by their titles, so nothing links back to the page you are on ("The price-increase
 * letter (doc_…) shows …" → "The price-increase letter shows …"). Other records stay ids for
 * `RefText` to name and link.
 */
export function onThisLetter(text: string, docId: string, items: readonly Pick<Item, "id" | "title">[]): string {
  const titles = new Map(items.map((i) => [i.id, i.title]));
  const re = new RegExp(`\\s?\\((${RECORD_ID_RE.source})\\)|(${RECORD_ID_RE.source})`, "g");
  return text.replace(re, (all: string, inBrackets: string | undefined, _p1: string, bare: string | undefined) => {
    const id = inBrackets ?? bare ?? "";
    if (id === docId) return inBrackets ? "" : "this letter";
    const title = titles.get(id);
    if (title) return inBrackets ? ` (“${title}”)` : `“${title}”`;
    return all;
  });
}
