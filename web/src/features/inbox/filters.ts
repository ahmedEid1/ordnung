/**
 * Inbox list logic (pure, unit-tested): filters, month grouping, open to-dos per letter.
 */
import { differenceInCalendarDays, format, parseISO } from "date-fns";
import type { Document, DocumentKind, Item } from "@/api/types";
import { documentKindLabel } from "@/lib/copy";
import { daysUntil } from "@/lib/format";

export const INBOX_FILTERS = ["all", "check", "private"] as const;
export type InboxFilter = (typeof INBOX_FILTERS)[number];

export function parseFilter(v: string | null): InboxFilter {
  return (INBOX_FILTERS as readonly string[]).includes(v ?? "") ? (v as InboxFilter) : "all";
}

/** Letters that need the person: "Please check" (or reading failed). */
export const needsYou = (d: Document) => d.status === "needs_review" || d.status === "failed";
export const isReading = (d: Document) => d.status === "queued" || d.status === "processing";

export function matchesFilter(d: Document, filter: InboxFilter): boolean {
  if (filter === "check") return needsYou(d);
  if (filter === "private") return d.ai_private;
  return true;
}

export function filterDocuments(docs: Document[], opts: { filter: InboxFilter; kind?: DocumentKind | null }): Document[] {
  return docs.filter((d) => !d.deleted_at && matchesFilter(d, opts.filter) && (!opts.kind || d.kind === opts.kind));
}

export function filterCounts(docs: Document[]): Record<InboxFilter, number> {
  const live = docs.filter((d) => !d.deleted_at);
  return {
    all: live.length,
    check: live.filter(needsYou).length,
    private: live.filter((d) => d.ai_private).length,
  };
}

/** Kinds present in the list, as select options sorted by label. */
export function kindOptions(docs: Document[]): { value: DocumentKind; label: string; count: number }[] {
  const counts = new Map<DocumentKind, number>();
  for (const d of docs) if (d.kind) counts.set(d.kind, (counts.get(d.kind) ?? 0) + 1);
  return [...counts.entries()]
    .map(([value, count]) => ({ value, label: documentKindLabel(value), count }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** When the letter came into the inbox: its arrival date, else when it was added. */
export function inboxDate(d: Document): string {
  return d.received_date ?? d.created_at.slice(0, 10);
}

export interface LetterGroup {
  key: string;
  label: string;
  docs: Document[];
}

/**
 * Newest first, grouped: letters being read → "Last 7 days" → one group per month
 * ("August", or "December 2025" for other years).
 */
export function groupLetters(docs: Document[], today: string): LetterGroup[] {
  const t = parseISO(today);
  const sorted = [...docs].sort((a, b) => {
    const ra = Number(isReading(a));
    const rb = Number(isReading(b));
    if (ra !== rb) return rb - ra;
    const da = inboxDate(a);
    const db = inboxDate(b);
    if (da !== db) return da < db ? 1 : -1;
    return a.created_at < b.created_at ? 1 : -1;
  });
  const groups: LetterGroup[] = [];
  const byKey = new Map<string, LetterGroup>();
  for (const d of sorted) {
    let key: string;
    let label: string;
    const date = parseISO(inboxDate(d));
    if (isReading(d)) {
      key = "reading";
      label = "Being read";
    } else if (differenceInCalendarDays(t, date) < 7) {
      key = "week";
      label = "Last 7 days";
    } else {
      key = format(date, "yyyy-MM");
      label = date.getFullYear() === t.getFullYear() ? format(date, "MMMM") : format(date, "MMMM yyyy");
    }
    let g = byKey.get(key);
    if (!g) {
      g = { key, label, docs: [] };
      byKey.set(key, g);
      groups.push(g);
    }
    g.docs.push(d);
  }
  return groups;
}

export interface OpenSummary {
  count: number;
  /** earliest open dated item (send-by first) */
  next: Item | null;
}

/** Items further back than this are history, not something overdue to act on. */
export const HISTORY_DAYS = 30;

/**
 * Whether an item can be "the next thing" of a letter on `today`: money coming in, appointments and
 * milestones that have passed (they just happened), and dates long past (history) can't.
 */
export function isNextCandidate(i: Item, today?: string): boolean {
  if (i.kind === "payment" && i.direction === "in") return false;
  const d = i.send_by ?? i.due_date;
  if (!d || !today) return Boolean(d);
  if (d >= today) return true;
  if (i.kind === "appointment" || i.kind === "milestone" || i.kind === "reminder") return false;
  return daysUntil(d, today) >= -HISTORY_DAYS;
}

/** Open to-dos per letter, with the next one to act on (see {@link isNextCandidate}). */
export function openItemsByDoc(items: Item[], today?: string): Map<string, OpenSummary> {
  const out = new Map<string, OpenSummary>();
  for (const i of items) {
    if (!i.doc_id || (i.status !== "open" && i.status !== "missed")) continue;
    const s = out.get(i.doc_id) ?? { count: 0, next: null };
    s.count += 1;
    const d = i.send_by ?? i.due_date;
    const nd = s.next ? (s.next.send_by ?? s.next.due_date) : null;
    if (d && isNextCandidate(i, today) && (!nd || d < nd)) s.next = i;
    out.set(i.doc_id, s);
  }
  return out;
}
