/** "Waiting for": how the page groups what the server works out (`secretary/waiting.py`). */
import type { WaitingEntry, WaitingStatus } from "@/api/types";

export type ListedStatus = Exclude<WaitingStatus, "closed">;

/** The groups of the page, in order, with what each asks of the person. */
export const WAITING_GROUPS: { status: ListedStatus; title: string; description: string }[] = [
  { status: "overdue", title: "Overdue", description: "The day has passed and nothing linked to it has come. Chase it." },
  { status: "waiting", title: "Waiting", description: "Ordnung reminds you when the day comes." },
  { status: "answered", title: "A letter may have answered", description: "Check it — then close it here." },
];

/** Split entries by status, keeping the server's order within each (closed ones are never listed). */
export function groupWaiting(entries: readonly WaitingEntry[]): Record<ListedStatus, WaitingEntry[]> {
  const out: Record<ListedStatus, WaitingEntry[]> = { overdue: [], waiting: [], answered: [] };
  for (const e of entries) if (e.status !== "closed") out[e.status].push(e);
  return out;
}

/** "3 waiting · 1 overdue" for the Letters page's link (empty when there is nothing). */
export function waitingSummary(entries: readonly WaitingEntry[]): { count: number; overdue: number } {
  const open = entries.filter((e) => e.status !== "closed");
  return { count: open.length, overdue: open.filter((e) => e.status === "overdue").length };
}
