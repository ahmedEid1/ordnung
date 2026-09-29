/** The interactive marks of a lane: bars, markers (with tooltips) and direct captions. */
import { motion } from "motion/react";
import type { LaneBar } from "@/api/types";
import { Tooltip } from "@/components/ui/Tooltip";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/format";
import { LANE_METRICS, type PlacedBar, type PlacedCaption, type PlacedMarker } from "./layout";
import { MARKER_LOOK, barAriaLabel, barSpan, barStatusLabel, markerWhen, type ChartRange } from "./marks";
import { LANE_BAR_KIND_COPY, copyFor } from "@/lib/copy";

const H = LANE_METRICS.barHeight;
/** A label scrolled partly out of view needs at least this much room to stay readable. */
const MIN_LABEL_ROOM = 44;

interface MarkCommon {
  markKey: string;
  /** keyboard row (a track of a lane) the mark belongs to */
  row: number;
  tabIndex: number;
  onActivate: (key: string) => void;
  today: string;
  /** "Opens the letter" … */
  hint: string | null;
}

/** A small shape like the ones on the chart (legend, tooltips). */
export function MarkerGlyph({ kind, past, className }: { kind: keyof typeof MARKER_LOOK; past?: boolean; className?: string }) {
  const look = MARKER_LOOK[kind];
  return (
    <span
      aria-hidden
      className={cn("lane-marker inline-block shrink-0", className)}
      data-kind={kind}
      data-shape={look.shape}
      data-hollow={look.hollow || undefined}
      data-past={past || undefined}
    />
  );
}

/** Only validity bars (permit, passport…) get a warm / red "ends soon" end cap. */
function capFor(bar: LaneBar, p: PlacedBar): "attention" | "urgent" | undefined {
  if (bar.kind !== "validity" || p.continuesAfter) return undefined;
  return bar.status === "attention" || bar.status === "urgent" ? bar.status : undefined;
}

export function BarMark({
  placed,
  trackY,
  labelInset,
  viewLeft = 0,
  scrolls = true,
  range,
  reduced,
  delay,
  onSelect,
  ...common
}: MarkCommon & {
  placed: PlacedBar;
  trackY: number;
  /** the chart's first and last day — a bar cut off there has no known start or end */
  range?: ChartRange;
  /** px the sticky label column covers (sticky offset of the label inside long bars) */
  labelInset: number;
  /** horizontal scroll of the chart (plot px scrolled out of view on the left) */
  viewLeft?: number;
  /** the chart scrolls sideways (zoomed in): the label slides along; otherwise it stays put */
  scrolls?: boolean;
  reduced: boolean;
  delay: number;
  onSelect: () => void;
}) {
  const { bar } = placed;
  const status = barStatusLabel(bar, common.today);
  // When the start of the bar is scrolled away the sticky label slides along; it gets only the
  // room left in view (truncated), and none at all when that is too little — never a cut-off word.
  const hidden = Math.max(0, viewLeft + LANE_METRICS.labelPad - (placed.x + 1 + placed.labelStart));
  const roomInView = placed.labelRoom - hidden;
  const showInside = placed.labelMode === "inside" && (hidden === 0 || roomInView >= MIN_LABEL_ROOM);
  const labelMax = hidden > 0 ? Math.min(placed.labelMax ?? Infinity, roomInView) : placed.labelMax;
  const kind = copyFor(LANE_BAR_KIND_COPY, bar.kind).label;
  const hatched = bar.kind === "notice_window";
  const tip = (
    <div className="space-y-0.5">
      <div className="font-semibold">{bar.label}</div>
      <div className="opacity-85">
        {kind} · {barSpan(bar, common.today, range)}
      </div>
      {status ? <div className="font-medium">{status}</div> : null}
      {common.hint ? <div className="pt-0.5 opacity-70">{common.hint}</div> : null}
    </div>
  );
  return (
    <>
      <Tooltip content={tip} delay={120}>
        <motion.button
          type="button"
          data-mark-key={common.markKey}
          data-mark-row={common.row}
          tabIndex={common.tabIndex}
          onFocus={() => common.onActivate(common.markKey)}
          onClick={onSelect}
          aria-label={barAriaLabel(bar, common.today, common.hint, range)}
          data-kind={bar.kind}
          data-status={bar.status}
          data-overlay={placed.overlay || undefined}
          data-before={placed.continuesBefore || undefined}
          data-after={placed.continuesAfter || undefined}
          data-cap={capFor(bar, placed)}
          className={cn(
            "lane-bar absolute flex items-center overflow-visible whitespace-nowrap text-left text-xs font-medium leading-none",
            placed.continuesBefore ? "rounded-r-md" : placed.continuesAfter ? "rounded-l-md" : "rounded-md",
            placed.continuesBefore && placed.continuesAfter && "rounded-none",
          )}
          style={{
            left: placed.x + 1,
            width: Math.max(3, placed.width - 2),
            top: trackY - H / 2,
            height: H,
            zIndex: placed.overlay ? 12 : 10,
            paddingLeft: placed.labelStart,
          }}
          initial={reduced ? false : { opacity: 0, clipPath: "inset(0 100% 0 0)" }}
          animate={reduced ? undefined : { opacity: 1, clipPath: "inset(0 0% 0 0)", transitionEnd: { clipPath: "none" } }}
          transition={{ duration: 0.55, delay, ease: [0.2, 0.8, 0.2, 1] }}
        >
          {showInside ? (
            // The label slides (sticky) while the bar start is scrolled away, but only within the
            // free room computed by the layout — never onto markers.
            <span className="pointer-events-none relative flex h-full items-center" style={{ width: placed.labelRoom }}>
              <span
                className={cn(
                  scrolls && "sticky",
                  (labelMax !== null || hidden > 0) && "truncate",
                  hatched ? "rounded-[4px] bg-surface/90 px-1.5 py-[3px] text-ink" : bar.status === "past" ? "text-muted" : "text-ink",
                )}
                style={{ left: scrolls ? labelInset + LANE_METRICS.labelPad : undefined, maxWidth: labelMax ?? undefined }}
              >
                {bar.label}
              </span>
            </span>
          ) : null}
        </motion.button>
      </Tooltip>
      {placed.labelMode === "after" ? (
        <span
          aria-hidden
          className="pointer-events-none absolute z-10 whitespace-nowrap text-xs font-medium leading-none text-muted"
          style={{ left: placed.afterX, top: trackY - 6 }}
        >
          {bar.label}
        </span>
      ) : null}
    </>
  );
}

export function MarkerMark({
  placed,
  trackY,
  context,
  onSelect,
  ...common
}: MarkCommon & {
  placed: PlacedMarker;
  trackY: number;
  /** bar or lane label, shown as the tooltip heading */
  context: string;
  onSelect: () => void;
}) {
  const { primary, entries } = placed;
  const look = MARKER_LOOK[primary.marker.kind] ?? MARKER_LOOK.other;
  // several dates merged into this mark: the next one peeks out behind it
  const stacked = entries[1] ?? null;
  const stackLook = stacked ? (MARKER_LOOK[stacked.marker.kind] ?? MARKER_LOOK.other) : null;
  const lines = entries.map((e) => {
    const date = formatDate(e.marker.date, { style: "short", today: common.today });
    return { e, text: `${e.marker.label} · ${date}`, when: markerWhen(e.marker.date, common.today) };
  });
  // a merged mark names every date it stands for
  const aria = `${lines.map((l) => `${l.text}, ${l.when}`).join("; ")}. ${context}.${common.hint ? ` ${common.hint}.` : ""}`;
  const tip = (
    <div className="space-y-1">
      <div className="text-[11.5px] font-medium opacity-75">{context}</div>
      {lines.map((l, i) => (
        <div key={i} className="flex items-center gap-2">
          <MarkerGlyph kind={l.e.marker.kind} past={l.e.past} className="scale-90" />
          <span>
            <span className="font-semibold">{l.text}</span>
            <span className="opacity-75"> · {l.when}</span>
          </span>
        </div>
      ))}
      {common.hint ? <div className="pt-0.5 opacity-70">{common.hint}</div> : null}
    </div>
  );
  return (
    <Tooltip content={tip} delay={80}>
      <button
        type="button"
        data-mark-key={common.markKey}
        data-mark-row={common.row}
        data-mark-date={placed.date}
        tabIndex={common.tabIndex}
        onFocus={() => common.onActivate(common.markKey)}
        onClick={onSelect}
        aria-label={aria}
        className="lane-mark absolute z-20 grid h-6 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full"
        style={{ left: placed.x, top: trackY, width: placed.hitWidth }}
      >
        {stacked && stackLook ? (
          <span
            aria-hidden
            className="lane-marker lane-mark-stack"
            data-kind={stacked.marker.kind}
            data-shape={stackLook.shape}
            data-hollow={stackLook.hollow || undefined}
            data-past={stacked.past || undefined}
          />
        ) : null}
        <span
          aria-hidden
          className="lane-marker"
          data-kind={primary.marker.kind}
          data-shape={look.shape}
          data-hollow={look.hollow || undefined}
          data-past={primary.past || undefined}
        />
      </button>
    </Tooltip>
  );
}

export function MarkerCaption({ caption, trackY }: { caption: PlacedCaption; trackY: number }) {
  return (
    <span
      aria-hidden
      data-testid="lanes-caption"
      className="pointer-events-none absolute z-20 whitespace-nowrap text-center text-xs font-semibold leading-[14px] text-ink"
      style={{ left: caption.x, width: caption.width, top: trackY + H / 2 + 3 }}
    >
      {caption.text}
    </span>
  );
}
