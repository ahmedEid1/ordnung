/** Small non-React helpers of the Today page (kept apart so component files stay component-only). */
import { api } from "@/api/endpoints";
import type { Suggestion } from "@/api/types";
import { DRAFT_KIND_COPY } from "@/lib/copy";
import { composerHref } from "./selection";
import { contractHref } from "@/features/contracts/links";

/** The action-named primary button label ("Draft cancellation", "Check passport"…). */
export function ideaActionLabel(s: Suggestion): string | null {
  const a = s.action;
  if (!a || a.type === "none") return a?.label ?? null;
  if (a.label) return a.label;
  switch (a.type) {
    case "draft":
      return `Draft ${DRAFT_KIND_COPY[a.draft_kind ?? "general_reply"].label.toLowerCase()}`;
    case "open":
      return "Open";
    case "mark_done":
      return "Mark done";
    case "snooze":
      return "Remind me later";
  }
  return null;
}

/** Where an Idea's primary action leads (or null when it acts in place). */
export function ideaHref(s: Suggestion): string | null {
  const a = s.action;
  if (!a) return null;
  if (a.type === "draft") {
    const kind = a.draft_kind ?? "general_reply";
    if (a.target_type === "contract") return composerHref(kind, { contractId: a.target_id });
    if (a.target_type === "document") return composerHref(kind, { docId: a.target_id });
    if (a.target_type === "party") return composerHref(kind, { partyId: a.target_id });
    return composerHref(kind, {});
  }
  if (a.type === "open" && a.target_id) {
    const id = encodeURIComponent(a.target_id);
    switch (a.target_type) {
      case "document":
        return `/documents/${id}`;
      case "contract":
        return contractHref(a.target_id);
      case "party":
        return `?party=${id}`;
      case "draft":
        return `/letters/${id}`;
      default:
        return null;
    }
  }
  return null;
}

/** "Written Mon 28 Sep, 07:00" in the person's time zone (Europe/Berlin), not the browser's. */
export function writtenAt(ts: string | null | undefined, timeZone?: string): string | null {
  if (!ts) return null;
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return null;
  let parts: Intl.DateTimeFormatPart[];
  try {
    parts = new Intl.DateTimeFormat("en-US", {
      timeZone: timeZone || undefined,
      weekday: "short",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).formatToParts(d);
  } catch {
    return writtenAt(ts);
  }
  const get = (t: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === t)?.value ?? "";
  return `Written ${get("weekday")} ${get("day")} ${get("month")}, ${get("hour")}:${get("minute")}`;
}

/** Download `calendar.ics` (all open dates) — works for API URLs and mock data: URLs. */
export function downloadCalendar(): void {
  const a = document.createElement("a");
  a.href = api.calendarIcsUrl();
  a.download = "ordnung.ics";
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
