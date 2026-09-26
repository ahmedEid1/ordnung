/** How lane marks look and read: marker shapes, legend labels, accessible descriptions. */
import type { LaneBar, LaneBarKind, MarkerKind } from "@/api/types";
import { LANE_BAR_KIND_COPY, LANE_BAR_STATUS_COPY, MARKER_KIND_COPY, copyFor } from "@/lib/copy";
import { formatDate, formatRelativeDays } from "@/lib/format";
import { dayNumber } from "./scale";

export type MarkerShape = "diamond" | "circle" | "square";

export interface MarkerLook {
  shape: MarkerShape;
  hollow: boolean;
}

/** Deadlines are diamonds (send-by filled, must-arrive-by hollow); expiries squares; the rest dots. */
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

/** Status wording for a bar, or null for plain "on track" bars. */
export function barStatusLabel(bar: Pick<LaneBar, "status">): string | null {
  if (bar.status === "ok") return null;
  return copyFor(LANE_BAR_STATUS_COPY, bar.status).label;
}

/** Relative phrase for a marker date: "in 10 days", "3 days ago". */
export function markerWhen(date: string, today: string): string {
  return formatRelativeDays(date, today, dayNumber(date) < dayNumber(today) ? "event" : "due");
}

/** Accessible name of a bar: "Residence permit. Valid, 1 Dec 2024 – 30 Nov 2026. Coming up. Opens the letter." */
export function barAriaLabel(bar: LaneBar, today: string, hint?: string | null): string {
  const kind = copyFor(LANE_BAR_KIND_COPY, bar.kind).label;
  const status = barStatusLabel(bar);
  return [`${bar.label}.`, `${kind}, ${formatRange(bar.start, bar.end, today)}.`, status ? `${status}.` : "", hint ? `${hint}.` : ""]
    .filter(Boolean)
    .join(" ");
}
