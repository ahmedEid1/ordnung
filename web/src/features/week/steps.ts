/**
 * The weekly review's steps as the page shows them (the backend decides what is in each —
 * `ordnung/secretary/week.py`): a short label for tight rows, an icon, and where the full list lives.
 */
import { Archive, CalendarRange, FileSearch, Inbox, Landmark, Send, Siren, type LucideIcon } from "lucide-react";
import type { WeekEntry, WeekStep, WeeklySession } from "@/api/types";
import { contractHref } from "@/features/contracts/links";
import { MEANING_ICONS } from "@/lib/copy";
import { plural } from "@/lib/utils";

export type StepId = WeekStep["id"];

/** The page's one name — Today's prompt and its quiet link, the page and its breadcrumb, the ending
 * ("Review saved") and its messages ("Couldn't save your weekly review"). */
export const WEEKLY_REVIEW = "Weekly review";

export interface StepMeta {
  short: string;
  icon: LucideIcon;
  /** Where the rows left out of a long step are listed in full (`always`: linked whenever it has rows). */
  more: { to: string; label: string; always?: boolean };
}

export const STEP_META: Record<StepId, StepMeta> = {
  now: { short: "Now", icon: Siren, more: { to: "/timeline", label: "See everything on the timeline" } },
  new: { short: "New", icon: Inbox, more: { to: "/inbox", label: "See all in the Inbox" } },
  check: { short: "Compare", icon: FileSearch, more: { to: "/timeline", label: "See every to-do on the timeline" } },
  pay: { short: "Pay", icon: Landmark, more: { to: "/timeline", label: "See every payment on the timeline" } },
  post: { short: "Post", icon: Send, more: { to: "/letters", label: "See all your letters" } },
  // the app's "Waiting for" mark (the hourglass is a deadline's)
  waiting: { short: "Waiting", icon: MEANING_ICONS.waitingFor, more: { to: "/letters/waiting", label: "See everything you're waiting for", always: true } },
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
    case "call":
      // a promise made on the phone lives on the Waiting for page
      return "/letters/waiting";
    default:
      return entry.doc_id ? `/documents/${encodeURIComponent(entry.doc_id)}` : "/timeline";
  }
}

/** How many rows a step has (those shown and those left out). */
export function stepCount(step: Pick<WeekStep, "entries" | "more">): number {
  return step.entries.length + step.more;
}

/** "2 overdue · 22 new letters · 1 to compare · 3 to pay · 2 decisions" — what Today's prompt says is waiting. */
export function sessionHighlights(week: Pick<WeeklySession, "steps" | "overdue">): string[] {
  const count = (id: StepId) => {
    const step = week.steps.find((s) => s.id === id);
    return step ? stepCount(step) : 0;
  };
  const transfers =
    week.steps.find((s) => s.id === "pay")?.entries.filter((e) => e.date_role !== "collected" && e.date_role !== "at_appointment").length ?? 0;
  // a letter already sent is listed to keep its proof, not to post
  const toPost = week.steps.find((s) => s.id === "post")?.entries.filter((e) => e.date_role !== "sent").length ?? 0;
  const parts: string[] = [];
  if (week.overdue) parts.push(`${week.overdue} overdue`);
  if (count("new")) parts.push(plural(count("new"), "new letter"));
  // "to compare" (with the letter): Today's "Please check" card counts letters, this step to-dos too
  if (count("check")) parts.push(`${count("check")} to compare`);
  if (transfers) parts.push(`${transfers} to pay`);
  if (toPost) parts.push(`${toPost} to post`);
  if (count("decide")) parts.push(plural(count("decide"), "decision"));
  return parts;
}
