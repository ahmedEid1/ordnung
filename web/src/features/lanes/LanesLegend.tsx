import type { Lane, LaneBarKind, MarkerKind } from "@/api/types";
import { LANE_BAR_KINDS } from "@/api/types";
import { cn } from "@/lib/utils";
import { MarkerGlyph } from "./LaneMarks";
import { MARKER_PRIORITY } from "./layout";
import { barKindLabel, markerKindLabel } from "./marks";

function Swatch({ kind, status, cap }: { kind: LaneBarKind; status?: string; cap?: string }) {
  return (
    <span
      aria-hidden
      className={cn("lane-bar relative inline-block h-3 w-6 shrink-0 rounded-[4px]", kind === "notice_window" && "hatch")}
      data-kind={kind}
      data-status={status ?? "ok"}
      data-cap={cap}
    />
  );
}

/** Legend for the kinds of bars and markers that are actually on the chart, plus the today line. */
export function LanesLegend({ lanes, className }: { lanes: Lane[]; className?: string }) {
  const barKinds = new Set<LaneBarKind>();
  const markerKinds = new Set<MarkerKind>();
  let endingSoon = false;
  let actNow = false;
  for (const l of lanes) {
    for (const m of l.markers) markerKinds.add(m.kind);
    for (const b of l.bars) {
      barKinds.add(b.kind);
      for (const m of b.markers) markerKinds.add(m.kind);
      if (b.kind === "validity" && b.status === "attention") endingSoon = true;
      if (b.kind === "validity" && b.status === "urgent") actNow = true;
    }
  }
  const noticeStatus = lanes.flatMap((l) => l.bars).find((b) => b.kind === "notice_window" && b.status !== "past")?.status ?? "attention";
  const item = "flex items-center gap-2";
  return (
    <div className={cn("flex flex-col gap-2 text-[12px] leading-4 text-muted", className)}>
      <h3 className="sr-only">Legend</h3>
      <ul className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {LANE_BAR_KINDS.filter((k) => barKinds.has(k)).map((k) => (
          <li key={k} className={item}>
            <Swatch kind={k} status={k === "notice_window" ? noticeStatus : "ok"} />
            {barKindLabel(k)}
          </li>
        ))}
        {endingSoon ? (
          <li className={item}>
            <Swatch kind="validity" cap="attention" />
            Ends soon
          </li>
        ) : null}
        {actNow ? (
          <li className={item}>
            <Swatch kind="validity" cap="urgent" />
            Act now
          </li>
        ) : null}
        {MARKER_PRIORITY.filter((k) => markerKinds.has(k)).map((k) => (
          <li key={k} className={item}>
            <MarkerGlyph kind={k} />
            {markerKindLabel(k)}
          </li>
        ))}
        <li className={item}>
          <span aria-hidden className="h-3.5 w-[2px] rounded-full bg-ink" />
          Today
        </li>
      </ul>
    </div>
  );
}
