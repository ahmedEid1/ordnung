/** How lane marks look and read: marker shapes, legend labels, accessible descriptions. */
import { format } from "date-fns";
import type { LaneBar, LaneBarKind, MarkerKind } from "@/api/types";
import { LANE_BAR_KIND_COPY, MARKER_KIND_COPY, copyFor } from "@/lib/copy";
import { formatDate, formatRelativeDays } from "@/lib/format";
import { markerCaption } from "./layout";
import { dayNumber } from "./scale";

export type MarkerShape = "diamond" | "circle" | "square";

export interface MarkerLook {
  shape: MarkerShape;
  hollow: boolean;
}

/**
 * Deadlines are diamonds (send-by and other deadlines filled, must-arrive-by hollow); expiries
 * squares; the rest dots. Send-by and deadline share one look — the legend names them together.
 */
export const MARKER_LOOK: Record<MarkerKind, MarkerLook> = {
  send_by: { shape: "diamond", hollow: false },
  deadline: { shape: "diamond", hollow: false },
  cancel_by: { shape: "diamond", hollow: true },
  expiry: { shape: "square", hollow: false },
  appointment: { shape: "circle", hollow: false },
  payment: { shape: "circle", hollow: false },
  renewal: { shape: "circle", hollow: true },
  other: { shape: "circle", hollow: false },
};

/** Legend / tooltip wording for marker kinds (the lanes say "Must arrive by" for cancel-by). */
export function markerKindLabel(kind: MarkerKind): string {
  if (kind === "cancel_by") return "Must arrive by";
  if (kind === "other") return "Other date";
  return copyFor(MARKER_KIND_COPY, kind).label;
}

/** Legend wording for bar kinds. */
export function barKindLabel(kind: LaneBarKind): string {
  if (kind === "period") return "Period (semester, objection time…)";
  return copyFor(LANE_BAR_KIND_COPY, kind).label;
}

/** "1 Dec 2024 – 30 Nov 2026" (years only when needed). */
export function formatRange(start: string, end: string, today: string): string {
  const sameYear = start.slice(0, 4) === end.slice(0, 4);
  const withYear = sameYear && start.slice(0, 4) === today.slice(0, 4) ? "never" : "always";
  return `${formatDate(start, { style: "day", withYear })} – ${formatDate(end, { style: "day", withYear })}`;
}

/** "June 2026" */
function monthYear(iso: string): string {
  const [y, m] = iso.split("-").map(Number);
  return format(new Date(y!, m! - 1, 1), "MMMM yyyy");
}

/** The chart's first and last day (inclusive): bars the server cut off there have no known start/end. */
export interface ChartRange {
  from: string;
  to: string;
}

/**
 * When a bar runs, in words — never a date the chart made up:
 * - "1 Dec 2024 – 30 Nov 2026";
 * - an open end: "since 1 Oct 2025 · no end date" ("from 15 Nov" when it starts later);
 * - a start or end the server cut off at the chart's edge (the bar begins exactly on its first day,
 *   or ends exactly on its last): "until 31 Mar 2027 · started before June 2026",
 *   "from 1 Oct 2025 · continues after September 2027".
 */
export function barSpan(bar: Pick<LaneBar, "start" | "end" | "open_end">, today: string, range?: ChartRange): string {
  const startCut = Boolean(range && bar.start === range.from);
  const endCut = Boolean(range && bar.end === range.to);
  const day = (iso: string) => formatDate(iso, { style: "day", today });
  const start = day(bar.start);
  const before = range ? `started before ${monthYear(range.from)}` : "";
  if (bar.open_end) {
    const since = dayNumber(bar.start) <= dayNumber(today) ? "since" : "from";
    return startCut ? `${before} · no end date` : `${since} ${start} · no end date`;
  }
  const end = day(bar.end);
  const after = range ? `continues after ${monthYear(range.to)}` : "";
  if (startCut && endCut) return `${before} · ${after}`;
  if (startCut) return `until ${end} · ${before}`;
  if (endCut) return `from ${start} · ${after}`;
  return formatRange(bar.start, bar.end, today);
}

/** What a bar's status means for its kind (upcoming, not ok, not past). */
const STATUS_WORDS: Record<LaneBarKind, { attention: string; urgent: string }> = {
  validity: { attention: "Ends soon", urgent: "Ends very soon" },
  notice_window: { attention: "Decide soon", urgent: "Act now" },
  contract: { attention: "Decide soon", urgent: "Act now" },
  period: { attention: "Due soon", urgent: "Act now" },
  event: { attention: "Coming up", urgent: "Coming up soon" },
};

const ACTION_KINDS = new Set<MarkerKind>(["send_by", "deadline", "cancel_by"]);

/**
 * Status wording for a bar, or null for plain "on track" bars — in the bar's own terms, with the
 * date to act by when the bar has one: "Ends soon — apply before 30 Nov", "Act now — send by 8 Oct".
 */
export function barStatusLabel(bar: Pick<LaneBar, "status" | "kind" | "markers">, today?: string): string | null {
  if (bar.status === "ok") return null;
  if (bar.status === "past") return bar.kind === "notice_window" ? "Closed" : "Ended";
  const words = (STATUS_WORDS[bar.kind] ?? STATUS_WORDS.event)[bar.status];
  const t = today ? dayNumber(today) : -Infinity;
  const act = bar.markers
    .filter((m) => ACTION_KINDS.has(m.kind) && m.date && dayNumber(m.date) >= t)
    .sort((a, b) => a.date.localeCompare(b.date))[0];
  if (!act) return words;
  const caption = markerCaption(act, today);
  return `${words} — ${caption.charAt(0).toLowerCase()}${caption.slice(1)}`;
}

/** Relative phrase for a marker date: "in 10 days", "3 days ago". */
export function markerWhen(date: string, today: string): string {
  return formatRelativeDays(date, today, dayNumber(date) < dayNumber(today) ? "event" : "due");
}

/**
 * Accessible name of a bar:
 * "Residence permit. Valid, 1 Dec 2024 – 30 Nov 2026. Ends soon — apply before 30 Nov. Opens the letter."
 */
export function barAriaLabel(bar: LaneBar, today: string, hint?: string | null, range?: ChartRange): string {
  const kind = copyFor(LANE_BAR_KIND_COPY, bar.kind).label;
  const status = barStatusLabel(bar, today);
  const span = barSpan(bar, today, range).replace(/ · /g, ", ");
  return [`${bar.label}.`, `${kind}, ${span}.`, status ? `${status}.` : "", hint ? `${hint}.` : ""].filter(Boolean).join(" ");
}
