/** Small non-React helpers of the Today page (kept apart so component files stay component-only). */
import { api } from "@/api/endpoints";
import type { Document, Party, Suggestion } from "@/api/types";
import { DRAFT_KIND_COPY } from "@/lib/copy";
import { formatDate, formatInlineText, formatTime } from "@/lib/format";
import { composerHref, type DateRole, type TodayAction } from "./selection";
import { contractHref } from "@/features/contracts/links";

// ------------------------------------------------------------------------------------------------
// Ideas
// ------------------------------------------------------------------------------------------------

const PAY = /^pay\b/i;

/** What an Idea's "open" button opens, in words ("Open letter"). */
function openLabel(targetType: string | null | undefined): string {
  if (targetType === "document") return "Open letter";
  if (targetType === "contract") return "Open contract";
  return "Open";
}

export interface IdeaActionOptions {
  /**
   * The Idea's letter has a payment the Pay panel can show (as in Top 3). Without one, an Idea's
   * "Pay" only opens the letter — and says so ("Open letter"), so "Pay" means one thing on the page.
   */
  canPay?: boolean;
}

/** The action-named primary button label ("Draft cancellation", "Check passport"…). */
export function ideaActionLabel(s: Suggestion, opts: IdeaActionOptions = {}): string | null {
  const a = s.action;
  if (!a || a.type === "none") return a?.label ?? null;
  if (a.type === "open" && a.label && PAY.test(a.label.trim()) && !opts.canPay) return openLabel(a.target_type);
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

/** The Idea asking for a sender's state (`secretary.sender_land.RULE_ID`): "Answer" opens their details at the question. */
const SENDER_LAND_RULE = "sender_land";

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
        // at the State heading, the question next (never on Yes)
        return s.rule_id === SENDER_LAND_RULE ? `?party=${id}&state=ask` : `?party=${id}`;
      case "draft":
        return `/letters/${id}`;
      default:
        return null;
    }
  }
  return null;
}

/**
 * The payment an Idea is about, when the page has it as a "Pay" action: an Idea whose button says
 * "Pay" and opens that letter gets the same Pay panel as Top 3.
 */
export function payActionFor(s: Suggestion, actions: readonly TodayAction[] | undefined): TodayAction | null {
  const a = s.action;
  if (!actions?.length || a?.type !== "open" || a.target_type !== "document" || !a.target_id) return null;
  if (!a.label || !PAY.test(a.label.trim())) return null;
  return actions.find((x) => x.verb === "pay" && x.docId === a.target_id) ?? null;
}

// ------------------------------------------------------------------------------------------------
// Coming up
// ------------------------------------------------------------------------------------------------

/**
 * What a Coming-up date means, in a word — the calendar leaf already shows the day, so the row
 * doesn't repeat it ("Transfer · Stadtwerke Musterstadt GmbH", not "Transfer by Tue 13 Oct · Stadtw…").
 */
const ROLE_WORD: Partial<Record<DateRole, string>> = {
  send_by: "Send",
  arrive_by: "Must arrive",
  transfer_by: "Transfer",
  pay_by: "Pay",
  collected: "Direct debit",
  decide_by: "Decide",
  expires: "Expires",
};

/** A Coming-up row's second line: what the date means (or the time), and who it is with. */
export function comingUpMeta(action: Pick<TodayAction, "dateRole" | "time">, party: Pick<Party, "name"> | undefined): string {
  const role = ROLE_WORD[action.dateRole];
  return [role ?? null, action.time ? formatTime(action.time) : null, party?.name ?? null].filter(Boolean).join(" · ");
}

// ------------------------------------------------------------------------------------------------
// Recent letters
// ------------------------------------------------------------------------------------------------

/** The day a recent letter is listed under: when it arrived, else its date, else when it was added. */
export function recentLetterDate(d: Pick<Document, "received_date" | "doc_date" | "created_at">): string {
  return d.received_date ?? d.doc_date ?? d.created_at.slice(0, 10);
}

/** Recent letters newest first by the day each one shows, so the list reads in order (20 Sep never above 21 Sep). */
export function sortRecentLetters<T extends Pick<Document, "id" | "received_date" | "doc_date" | "created_at">>(docs: readonly T[]): T[] {
  return [...docs].sort((a, b) => recentLetterDate(b).localeCompare(recentLetterDate(a)) || b.id.localeCompare(a.id));
}

// ------------------------------------------------------------------------------------------------
// The secretary's note
// ------------------------------------------------------------------------------------------------

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
/** "30 September", "Tuesday, 29 September 2026", "1 Oct": a day and a month name, maybe with a weekday and a year. */
const NOTE_DATE =
  /\b(?:(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?[ \u00a0]+)?(\d{1,2})\.?[ \u00a0]+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b(?:[ \u00a0]+(\d{4})\b)?/g;

/** The ISO day for a day and month: in the given year, or (without one) the year that puts it nearest today. */
function nearestDay(day: number, month: number, year: number | null, today: string): string | null {
  const iso = (y: number) => `${y}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  const at = (y: number) => Date.UTC(y, month, day);
  const valid = (y: number) => new Date(at(y)).getUTCMonth() === month;
  if (month < 0) return null;
  if (year !== null) return valid(year) ? iso(year) : null;
  const t = Date.parse(`${today}T00:00:00Z`);
  const ty = Number(today.slice(0, 4));
  if (Number.isNaN(t)) return null;
  const years = [ty, ty + 1, ty - 1].filter(valid);
  if (!years.length) return null;
  return iso(years.reduce((best, y) => (Math.abs(at(y) - t) < Math.abs(at(best) - t) ? y : best)));
}

/**
 * The note in the app's own style: every date as "Wed 30 Sep" (the model sometimes writes "30
 * September" next to "Tue 29 Sep"), money as "€94.99" (not "94,99 €"), and units kept on one line
 * ({@link formatInlineText}). A weekday that doesn't match its date is left as written.
 */
export function noteText(text: string, today: string): string {
  const dated = text.replace(NOTE_DATE, (whole: string, weekday: string | undefined, day: string, month: string, year: string | undefined) => {
    const iso = nearestDay(Number(day), MONTHS.indexOf(month.slice(0, 3).toLowerCase()), year ? Number(year) : null, today);
    if (!iso) return whole;
    const short = formatDate(iso, { style: "short", today });
    return weekday && !short.startsWith(weekday) ? whole : short;
  });
  return formatInlineText(dated, { today });
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
