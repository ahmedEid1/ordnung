/**
 * LanesChart — the year-ahead "life lanes": one row per life area (or per contract), bars for
 * validity / terms / periods, hatched notice windows, diamond send-by markers, a bold today line
 * and a month grid. Plain HTML + CSS (no chart library) for crisp control.
 *
 * - Scrolls horizontally; the lane labels stay pinned on the left (on phones they ride above each
 *   lane). Starts scrolled so that today sits near the left third.
 * - Keyboard: one tab stop; ←/→ move along a lane, ↑/↓ between lanes, Home/End, Enter opens.
 * - Every bar and marker has a tooltip and a full accessible name; a legend explains the marks.
 *
 * @example
 * <LanesChart lanes={lanes} from={range.from} to={range.to} today={today} ariaLabel="Your year ahead" />
 */
import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { useReducedMotion } from "motion/react";
import { Crosshair, Maximize2, ZoomIn } from "lucide-react";
import type { Lane } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { KindIcon } from "@/components/ui/KindBadge";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Skeleton } from "@/components/ui/Skeleton";
import { LANE_BAR_STATUS_COPY, TONES, copyFor } from "@/lib/copy";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { BarMark, MarkerCaption, MarkerMark } from "./LaneMarks";
import { LanesLegend } from "./LanesLegend";
import { layoutLane, laneStatus, nextOnLane, type LaneLayout } from "./layout";
import { markerWhen } from "./marks";
import { measureBarLabel, measureCaption } from "./measure";
import { refTarget } from "./refs";
import { createTimeScale, monthTicks, plotWidth, scrollLeftFor, yearSpans, dayNumber } from "./scale";
import type { LaneDescription, LaneSelection, LaneTarget } from "./types";
import "./lanes.css";

const LABEL_W = 232;
const AXIS_H = 46;
const COMPACT_BELOW = 640;
const COMPACT_HEADER = 32;
const MIN_LANE_H = 54;

export interface LanesChartProps {
  lanes: Lane[];
  /** first and last day shown (ISO, inclusive) */
  from: string;
  to: string;
  /** the app's today (ISO) — never the browser clock */
  today: string;
  /** accessible name of the chart */
  ariaLabel: string;
  /** heading and description shown above the chart */
  title?: ReactNode;
  description?: ReactNode;
  /** extra controls next to the zoom switch */
  actions?: ReactNode;
  /** column heading above the lane labels ("Life area", "Contract") */
  labelHeading?: string;
  /** icon / label / second line per lane */
  describeLane?: (lane: Lane) => LaneDescription | undefined;
  /** where a click leads (default: letters and contracts by their reference) */
  resolveTarget?: (sel: LaneSelection) => LaneTarget | null;
  /** click handler; default navigates to `resolveTarget(sel).href` */
  onSelect?: (sel: LaneSelection) => void;
  loading?: boolean;
  /** shown when there are no lanes */
  empty?: ReactNode;
  /** show the legend under the chart (default true) */
  legend?: boolean;
  /** content under the legend (e.g. a disclaimer) */
  footer?: ReactNode;
  className?: string;
}

/** Width of an element, tracked with a ResizeObserver (0 until measured). */
function useElementWidth(el: HTMLElement | null): number {
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const next = Math.round(entries[0]?.contentRect.width ?? 0);
      setW((prev) => (prev === next ? prev : next));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  // jsdom / very old browsers: assume a laptop-sized container
  return typeof ResizeObserver === "undefined" ? 1024 : w;
}

function defaultIcon(lane: Lane): ReactNode {
  return lane.id === "contracts" ? <KindIcon kind="contract" size="sm" /> : <KindIcon area={lane.area} size="sm" />;
}

function NextLine({ lane, today }: { lane: Lane; today: string }) {
  const next = nextOnLane(lane, today);
  if (!next) return <span className="text-muted">Nothing coming up</span>;
  const days = dayNumber(next.date) - dayNumber(today);
  const key = next.kind !== "other" && next.kind !== "renewal" && next.kind !== "payment";
  const tone = key && days <= 14 ? "text-danger-ink" : key && days <= 45 ? "text-warn-ink" : "text-muted";
  const date = formatDate(next.date, { style: "day", today });
  const joiner = /\b(by|before|until|on|expires|ends)$/i.test(next.label) ? " " : " · ";
  const text = `${next.label}${joiner}${date}${days <= 30 ? ` · ${markerWhen(next.date, today)}` : ""}`;
  return (
    <span className={cn("tabular-nums", tone)} title={text}>
      {text}
    </span>
  );
}

function StatusDot({ lane }: { lane: Lane }) {
  const s = laneStatus(lane);
  if (!s || s === "ok") return null;
  const c = copyFor(LANE_BAR_STATUS_COPY, s);
  return (
    <>
      <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", TONES[c.tone].solid)} />
      <span className="sr-only">{c.label}</span>
    </>
  );
}

interface MarkRef {
  key: string;
  x: number;
}

export function LanesChart({
  lanes,
  from,
  to,
  today,
  ariaLabel,
  title,
  description,
  actions,
  labelHeading = "Life area",
  describeLane,
  resolveTarget,
  onSelect,
  loading,
  empty,
  legend = true,
  footer,
  className,
}: LanesChartProps) {
  const navigate = useNavigate();
  const reduced = Boolean(useReducedMotion());
  const [frame, setFrame] = useState<HTMLDivElement | null>(null);
  // element as state (effects re-run when it mounts) + ref (for imperative scrolling)
  const [scroller, setScroller] = useState<HTMLDivElement | null>(null);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const attachScroller = useCallback((el: HTMLDivElement | null) => {
    scrollerRef.current = el;
    setScroller(el);
  }, []);
  const width = useElementWidth(frame);
  const compact = width > 0 && width < COMPACT_BELOW;
  const labelW = compact ? 0 : LABEL_W;
  const [zoom, setZoom] = useState<"fit" | "detail">("fit");
  const [scrolled, setScrolled] = useState(false);
  /** scroll position, so bar labels whose start is scrolled away shrink to the part in view */
  const [viewLeft, setViewLeft] = useState(0);
  const scrollFrame = useRef(0);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const hintId = useId();

  const plotW = width ? plotWidth(from, to, width - labelW, zoom, { minMonthPx: compact ? 66 : 50, visibleMonths: compact ? 3 : 5 }) : 0;
  const scale = useMemo(() => createTimeScale(from, to, plotW || 1), [from, to, plotW]);
  const ticks = useMemo(() => monthTicks(scale), [scale]);
  const years = useMemo(() => yearSpans(ticks), [ticks]);
  const layouts: LaneLayout[] = useMemo(
    () => (plotW ? lanes.map((l) => layoutLane(l, scale, today, { measure: measureBarLabel, measureCaption, minHeight: compact ? 0 : MIN_LANE_H })) : []),
    [lanes, scale, today, compact, plotW],
  );
  const scrollable = plotW > width - labelW + 1;
  const todayVisible = scale.contains(today);
  const todayX = scale.mid(today);

  // Marks per lane in x order (bars by start, markers by centre) — for arrow-key navigation.
  const marks: MarkRef[][] = useMemo(
    () =>
      layouts.map((ly) =>
        [
          ...ly.bars.map((b) => ({ key: `${ly.lane.id}|${b.key}`, x: b.x + Math.min(b.width / 2, 12) })),
          ...ly.markers.map((m) => ({ key: `${ly.lane.id}|${m.key}`, x: m.x })),
        ].sort((a, b) => a.x - b.x),
      ),
    [layouts],
  );
  const defaultKey = useMemo(() => {
    for (const list of marks) {
      if (!list.length) continue;
      return (list.find((m) => m.x >= todayX) ?? list[0]!).key;
    }
    return null;
  }, [marks, todayX]);
  const allKeys = useMemo(() => new Set(marks.flat().map((m) => m.key)), [marks]);
  const focusKey = activeKey && allKeys.has(activeKey) ? activeKey : defaultKey;

  // Start scrolled so that today sits near the left third (again when the zoom changes).
  const scrolledFor = useRef<{ el: HTMLElement; key: string } | null>(null);
  useLayoutEffect(() => {
    const el = scrollerRef.current;
    if (!el || !plotW) return;
    const key = `${zoom}|${compact}`;
    if (scrolledFor.current?.el === el && scrolledFor.current.key === key) return;
    scrolledFor.current = { el, key };
    el.scrollLeft = scrollable && todayVisible ? scrollLeftFor(scale, today, el.clientWidth - labelW) : 0;
  }, [scroller, plotW, zoom, compact, scrollable, todayVisible, scale, today, labelW]);

  const scrollToToday = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollTo?.({ left: scrollLeftFor(scale, today, el.clientWidth - labelW), behavior: reduced ? "auto" : "smooth" });
  }, [scale, today, labelW, reduced]);

  const select = useCallback(
    (sel: LaneSelection) => {
      if (onSelect) return onSelect(sel);
      const target = resolveTarget ? resolveTarget(sel) : refTarget(sel.ref);
      if (target?.href) navigate(target.href);
    },
    [onSelect, resolveTarget, navigate],
  );
  const hintFor = useCallback(
    (sel: LaneSelection) => (resolveTarget ? resolveTarget(sel) : refTarget(sel.ref))?.hint ?? null,
    [resolveTarget],
  );

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const t = e.target as HTMLElement;
    const key = t.dataset.markKey;
    if (!key) return;
    const li = Number(t.dataset.markLane);
    const list = marks[li] ?? [];
    const i = list.findIndex((m) => m.key === key);
    let next: string | undefined;
    if (e.key === "ArrowRight") next = list[i + 1]?.key;
    else if (e.key === "ArrowLeft") next = list[i - 1]?.key;
    else if (e.key === "Home") next = list[0]?.key;
    else if (e.key === "End") next = list[list.length - 1]?.key;
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const dir = e.key === "ArrowDown" ? 1 : -1;
      const x = list[i]?.x ?? 0;
      for (let l = li + dir; l >= 0 && l < marks.length; l += dir) {
        const cand = marks[l]!;
        if (!cand.length) continue;
        next = cand.reduce((best, m) => (Math.abs(m.x - x) < Math.abs(best.x - x) ? m : best)).key;
        break;
      }
    } else return;
    e.preventDefault();
    if (!next) return;
    setActiveKey(next);
    scrollerRef.current?.querySelector<HTMLElement>(`[data-mark-key="${CSS.escape(next)}"]`)?.focus();
  };

  const hasLanes = lanes.length > 0;
  const headerRow =
    title || description || actions || (hasLanes && !loading) ? (
      <div className="flex flex-col gap-3 px-4 pb-3 pt-4 sm:flex-row sm:items-end sm:px-5 sm:pt-5">
        <div className="min-w-0 flex-1">
          {title ? <h2 className="display text-[21px] font-semibold leading-tight text-ink sm:text-[23px]">{title}</h2> : null}
          {description ? <p className="mt-1 text-[13.5px] leading-snug text-muted">{description}</p> : null}
        </div>
        {hasLanes && !loading ? (
          <div className="flex flex-wrap items-center gap-2">
            {actions}
            {scrollable && todayVisible ? (
              <Button variant="ghost" size="sm" icon={Crosshair} onClick={scrollToToday}>
                Today
              </Button>
            ) : null}
            <SegmentedControl
              size="sm"
              label="Zoom"
              value={zoom}
              onChange={setZoom}
              options={[
                { value: "fit", label: "Whole year", icon: Maximize2 },
                { value: "detail", label: "Zoom in", icon: ZoomIn },
              ]}
            />
          </div>
        ) : (
          actions
        )}
      </div>
    ) : null;

  return (
    // `isolate`: the chart's own z-layers (sticky labels, today line) never paint over the app bar
    <div className={cn("card isolate overflow-hidden", className)}>
      {headerRow}
      <div ref={setFrame} className="relative border-t border-line">
        {loading ? (
          <div className="p-5">
            <div className="space-y-4" aria-hidden>
              {[0, 1, 2, 3, 4].map((i) => (
                <div key={i} className="flex items-center gap-4">
                  <Skeleton className="hidden h-9 w-44 sm:block" />
                  <Skeleton className="h-5 flex-1" />
                </div>
              ))}
            </div>
            <span role="status" className="sr-only">
              Loading your year…
            </span>
          </div>
        ) : !hasLanes ? (
          <div className="p-5">{empty ?? <p className="py-8 text-center text-sm text-muted">Nothing on your lanes yet.</p>}</div>
        ) : plotW ? (
          <div
            ref={attachScroller}
            className="overflow-x-auto overscroll-x-contain scrollbar-thin"
            style={{ scrollPaddingLeft: labelW + 16, scrollPaddingRight: 16 }}
            onScroll={(e) => {
              const left = e.currentTarget.scrollLeft;
              setScrolled(left > 2);
              cancelAnimationFrame(scrollFrame.current);
              scrollFrame.current = requestAnimationFrame(() => setViewLeft(left));
            }}
          >
            <div
              className="relative"
              style={{ width: labelW + plotW, ["--lane-label-w" as string]: `${labelW}px` }}
              role="group"
              aria-label={ariaLabel}
              aria-describedby={hintId}
              onKeyDown={onKeyDown}
            >
              <p id={hintId} className="sr-only">
                Use the arrow keys to move between bars and dates, Enter to open.
              </p>

              {/* grid, past tint, today line */}
              <div aria-hidden className="pointer-events-none absolute inset-y-0" style={{ left: labelW, width: plotW }}>
                {todayVisible ? (
                  <div className="absolute bottom-0 left-0 bg-surface-2/70 dark:bg-surface-2/60" style={{ top: AXIS_H, width: todayX }} />
                ) : null}
                {ticks.map((t) =>
                  t.x > 0 ? (
                    <div
                      key={t.date}
                      className={cn("absolute bottom-0 w-px", t.yearStart ? "top-0 bg-line-strong" : "bg-line")}
                      style={{ left: t.x, top: t.yearStart ? 0 : 20 }}
                    />
                  ) : null,
                )}
                {todayVisible ? (
                  <div data-testid="lanes-today-line" className="absolute bottom-0 z-[5] w-[2px] -translate-x-1/2 rounded-full bg-ink" style={{ left: todayX, top: 20 }} />
                ) : null}
              </div>

              {/* axis */}
              <div className="relative flex" style={{ height: AXIS_H }}>
                {!compact ? (
                  <div
                    className={cn(
                      "sticky left-0 z-30 flex shrink-0 items-end border-r border-line bg-surface px-4 pb-2.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted",
                      scrolled && "shadow-[6px_0_10px_-8px_rgb(0_0_0/0.18)]",
                    )}
                    style={{ width: labelW }}
                  >
                    {labelHeading}
                  </div>
                ) : null}
                <div className="relative shrink-0" style={{ width: plotW }} aria-hidden>
                  {years.map((y) => (
                    // the year label slides along (sticky) while its year is in view
                    <div key={y.year} className="absolute top-[5px] flex h-4" style={{ left: y.x, width: y.width }}>
                      <span className="sticky whitespace-nowrap pl-2 text-[11px] font-semibold tabular-nums tracking-wide text-muted" style={{ left: labelW }}>
                        {y.year}
                      </span>
                    </div>
                  ))}
                  {ticks.map((t) => (
                    <span
                      key={t.date}
                      className={cn(
                        "absolute bottom-[7px] -translate-x-1/2 whitespace-nowrap text-[12px] font-medium",
                        t.date.slice(0, 7) === today.slice(0, 7) ? "text-ink" : "text-muted",
                      )}
                      style={{ left: t.x + t.width / 2 }}
                    >
                      {t.width >= 30 ? t.label : t.label.slice(0, 1)}
                    </span>
                  ))}
                  {todayVisible ? (
                    <span
                      data-testid="lanes-today"
                      className="absolute top-[2px] z-20 -translate-x-1/2 whitespace-nowrap rounded-full bg-ink px-2 py-[2px] text-[10.5px] font-semibold uppercase leading-[14px] tracking-[0.06em] text-canvas shadow-[0_0_0_2px_var(--color-surface)]"
                      style={{ left: todayX }}
                    >
                      Today
                    </span>
                  ) : null}
                </div>
              </div>

              {/* lanes */}
              <div role="list" aria-label="Lanes">
                {layouts.map((ly, li) => {
                  const lane = ly.lane;
                  const desc = describeLane?.(lane);
                  const label = desc?.label ?? lane.label;
                  const icon = desc?.icon ?? defaultIcon(lane);
                  const sub = desc?.sublabel ?? <NextLine lane={lane} today={today} />;
                  const offset = compact ? COMPACT_HEADER : 0;
                  const height = ly.height + offset;
                  const railY = (ly.trackY[0] ?? 0) + offset;
                  return (
                    <div key={lane.id} role="listitem" aria-label={label} className="relative flex border-t border-line/80" style={{ height }}>
                      {!compact ? (
                        <div
                          className={cn(
                            "sticky left-0 z-30 flex shrink-0 items-center gap-2.5 border-r border-line bg-surface pl-4 pr-3",
                            scrolled && "shadow-[6px_0_10px_-8px_rgb(0_0_0/0.18)]",
                          )}
                          style={{ width: labelW }}
                        >
                          {icon}
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-1.5">
                              <span className="truncate text-[13.5px] font-semibold leading-5 text-ink" title={label}>
                                {label}
                              </span>
                              <StatusDot lane={lane} />
                            </div>
                            <div className="truncate text-[12px] leading-4">{sub}</div>
                          </div>
                        </div>
                      ) : null}
                      <div className="relative shrink-0" style={{ width: plotW }}>
                        {compact ? (
                          <div className="sticky left-0 z-30 mt-1.5 flex h-7 w-max max-w-[calc(100vw-56px)] items-center gap-2 rounded-r-lg bg-surface/95 pl-3 pr-2.5">
                            {icon}
                            <span className="whitespace-nowrap text-[13px] font-semibold text-ink">{label}</span>
                            <StatusDot lane={lane} />
                            <span className="min-w-0 truncate text-[12px]">{sub}</span>
                          </div>
                        ) : null}
                        {ly.rail ? (
                          <div aria-hidden className="absolute inset-x-0 h-px bg-line-strong" style={{ top: railY }} />
                        ) : null}
                        {ly.bars.map((b, bi) => {
                          const sel: LaneSelection = { lane, bar: b.bar, marker: null, ref: b.bar.ref, date: b.bar.end };
                          const key = `${lane.id}|${b.key}`;
                          return (
                            <BarMark
                              key={b.key}
                              placed={b}
                              trackY={(ly.trackY[b.track] ?? 0) + offset}
                              labelInset={labelW}
                              viewLeft={viewLeft}
                              reduced={reduced}
                              delay={Math.min(0.6, li * 0.05 + bi * 0.03)}
                              onSelect={() => select(sel)}
                              markKey={key}
                              laneIndex={li}
                              tabIndex={key === focusKey ? 0 : -1}
                              onActivate={setActiveKey}
                              today={today}
                              hint={hintFor(sel)}
                            />
                          );
                        })}
                        {ly.markers.map((m) => {
                          const e = m.primary;
                          const sel: LaneSelection = { lane, bar: e.bar, marker: e.marker, ref: e.bar?.ref ?? null, date: e.marker.date };
                          const key = `${lane.id}|${m.key}`;
                          return (
                            <MarkerMark
                              key={m.key}
                              placed={m}
                              trackY={(ly.trackY[m.track] ?? 0) + offset}
                              context={e.bar && e.bar.label !== label ? `${label} · ${e.bar.label}` : label}
                              onSelect={() => select(sel)}
                              markKey={key}
                              laneIndex={li}
                              tabIndex={key === focusKey ? 0 : -1}
                              onActivate={setActiveKey}
                              today={today}
                              hint={hintFor(sel)}
                            />
                          );
                        })}
                        {ly.captions.map((c) => (
                          <MarkerCaption key={c.key} caption={c} trackY={(ly.trackY[c.track] ?? 0) + offset} />
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        ) : (
          <div className="h-64" aria-hidden />
        )}
      </div>
      {legend && hasLanes && !loading ? (
        <div className="flex flex-col gap-3 border-t border-line bg-surface-2/40 px-4 py-3.5 sm:px-5">
          <LanesLegend lanes={lanes} />
          {footer}
        </div>
      ) : footer ? (
        <div className="border-t border-line px-4 py-3.5 sm:px-5">{footer}</div>
      ) : null}
    </div>
  );
}
