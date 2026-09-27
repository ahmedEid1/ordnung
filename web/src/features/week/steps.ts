/**
 * The weekly session's steps as the page shows them (the backend decides what is in each —
 * `ordnung/secretary/week.py`): a short label for tight rows, an icon, and where the full list lives.
 */
import { Archive, CalendarRange, FileSearch, Hourglass, Inbox, Landmark, Send, type LucideIcon } from "lucide-react";
import type { WeekEntry, WeekStep, WeeklySession } from "@/api/types";
import { contractHref } from "@/features/contracts/links";
import { plural } from "@/lib/utils";

export type StepId = WeekStep["id"];

export interface StepMeta {
  short: string;
  icon: LucideIcon;
  /** Where the rows left out of a long step are listed in full. */
  more: { to: string; label: string };
}

export const STEP_META: Record<StepId, StepMeta> = {
  new: { short: "New", icon: Inbox, more: { to: "/inbox", label: "See all in the Inbox" } },
  check: { short: "Check", icon: FileSearch, more: { to: "/inbox?filter=check", label: "See all letters to check" } },
  pay: { short: "Pay", icon: Landmark, more: { to: "/timeline", label: "See every payment on the timeline" } },
  post: { short: "Post", icon: Send, more: { to: "/letters", label: "See all your letters" } },
  waiting: { short: "Waiting", icon: Hourglass, more: { to: "/timeline", label: "See the timeline" } },
  decide: { short: "Decide", icon: CalendarRange, more: { to: "/contracts", label: "See your contracts" } },
  file: { short: "File", icon: Archive, more: { to: "/inbox", label: "See all in the Inbox" } },
};

/** Where a row leads: its letter, contract or draft (a to-do opens its letter). */
export function entryHref(entry: Pick<WeekEntry, "ref" | "doc_id">): string {
  switch (entry.ref.type) {
    case "document":
      return `/documents/${encodeURIComponent(entry.ref.id)}`;
    case "contract":
      return contractHref(entry.ref.id);
    case "draft":
      return `/letters/${encodeURIComponent(entry.ref.id)}`;
    default:
      return entry.doc_id ? `/documents/${encodeURIComponent(entry.doc_id)}` : "/timeline";
  }
}

/** How many rows a step has (those shown and those left out). */
export function stepCount(step: Pick<WeekStep, "entries" | "more">): number {
  return step.entries.length + step.more;
}

/** "22 new letters · 1 to check · 3 to pay · 2 decisions" — what Today's prompt says is waiting. */
export function sessionHighlights(week: Pick<WeeklySession, "steps">): string[] {
  const count = (id: StepId) => {
    const step = week.steps.find((s) => s.id === id);
    return step ? stepCount(step) : 0;
  };
  const transfers = week.steps.find((s) => s.id === "pay")?.entries.filter((e) => e.date_role !== "collected").length ?? 0;
  const parts: string[] = [];
  if (count("new")) parts.push(plural(count("new"), "new letter"));
  if (count("check")) parts.push(`${count("check")} to check`);
  if (transfers) parts.push(`${transfers} to pay`);
  if (count("post")) parts.push(`${count("post")} to post`);
  if (count("decide")) parts.push(plural(count("decide"), "decision"));
  return parts;
}
