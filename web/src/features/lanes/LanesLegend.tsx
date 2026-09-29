import type { Lane, LaneBarKind, LaneBarStatus, MarkerKind } from "@/api/types";
import { LANE_BAR_KINDS } from "@/api/types";
import { cn } from "@/lib/utils";
import { MarkerGlyph } from "./LaneMarks";
import { MARKER_PRIORITY } from "./layout";
import { barKindLabel, markerKindLabel } from "./marks";

function Swatch({ kind, status, cap }: { kind: LaneBarKind; status?: string; cap?: string }) {
  return (
    <span
      aria-hidden
      className="lane-bar relative inline-block h-3 w-6 shrink-0 rounded-[4px]"
      data-kind={kind}
      data-status={status ?? "ok"}
      data-cap={cap}
    />
  );
}

/** How soon a notice window closes, as the legend says it next to its hatch colour. */
const WINDOW_STATUS: { status: Exclude<LaneBarStatus, "past">; suffix: string }[] = [
  { status: "ok", suffix: "" },
  { status: "attention", suffix: " — decide soon" },
  { status: "urgent", suffix: " — act now" },
];

/** "Other date" markers that all say when a term ends get a name that says so. */
const TERM_END = /\b(ends?|end of|earliest end)\b/i;

/**
 * Legend for the kinds of bars and markers that are actually on the chart, after the today line
 * (listed first, so it never wraps onto a line of its own). Send-by and deadline share a glyph and
 * one entry; each notice-window colour on the chart gets its own hatch swatch.
 */
export function LanesLegend({ lanes, className }: { lanes: Lane[]; className?: string }) {
  const barKinds = new Set<LaneBarKind>();
  const markerKinds = new Set<MarkerKind>();
  const windowStatuses = new Set<LaneBarStatus>();
  const otherLabels: string[] = [];
  let endingSoon = false;
  let actNow = false;
  for (const l of lanes) {
    const markers = [...l.markers, ...l.bars.flatMap((b) => b.markers)];
    for (const m of markers) {
      markerKinds.add(m.kind);
      if (m.kind === "other") otherLabels.push(m.label);
    }
    for (const b of l.bars) {
      barKinds.add(b.kind);
      if (b.kind === "notice_window" && b.status !== "past") windowStatuses.add(b.status);
      if (b.kind === "validity" && b.status === "attention") endingSoon = true;
      if (b.kind === "validity" && b.status === "urgent") actNow = true;
    }
  }
  // a chart with only closed windows still explains the hatch
  if (barKinds.has("notice_window") && !windowStatuses.size) windowStatuses.add("ok");
  const sendAndDeadline = markerKinds.has("send_by") && markerKinds.has("deadline");
  const markerLabel = (k: MarkerKind): string => {
    if (k === "send_by" && sendAndDeadline) return "Send by / deadline";
    if (k === "other" && otherLabels.length && otherLabels.every((l) => TERM_END.test(l))) return "Term ends / earliest end";
    return markerKindLabel(k);
  };
  const item = "flex items-center gap-2";
  return (
    <ul aria-label="Legend" className={cn("flex flex-wrap items-center gap-x-4 gap-y-2 text-xs leading-4 text-muted", className)}>
      <li className={item}>
        <span aria-hidden className="h-3.5 w-[2px] rounded-full bg-ink" />
        Today
      </li>
      {LANE_BAR_KINDS.filter((k) => barKinds.has(k)).flatMap((k) =>
        k === "notice_window" ? (
          WINDOW_STATUS.filter((w) => windowStatuses.has(w.status)).map((w) => (
            <li key={`${k}-${w.status}`} className={item}>
              <Swatch kind={k} status={w.status} />
              {barKindLabel(k)}
              {w.suffix}
            </li>
          ))
        ) : (
          <li key={k} className={item}>
            <Swatch kind={k} status="ok" />
            {barKindLabel(k)}
          </li>
        ),
      )}
      {endingSoon ? (
        <li className={item}>
          <Swatch kind="validity" cap="attention" />
          Ends soon
        </li>
      ) : null}
      {actNow ? (
        <li className={item}>
          <Swatch kind="validity" cap="urgent" />
          Ends very soon
        </li>
      ) : null}
      {MARKER_PRIORITY.filter((k) => markerKinds.has(k) && !(k === "deadline" && sendAndDeadline)).map((k) => (
        <li key={k} className={item}>
          <MarkerGlyph kind={k} />
          {markerLabel(k)}
        </li>
      ))}
    </ul>
  );
}
