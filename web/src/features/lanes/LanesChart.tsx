/**
 * LanesChart — the year-ahead "life lanes": one row per life area (or per contract), bars for
 * validity / terms / periods, hatched notice windows, diamond send-by markers, a bold today line
 * and a month grid. Plain HTML + CSS (no chart library) for crisp control.
 *
 * - "Fit all" puts every month into the width (the default on wider screens); "Zoom in" scrolls
 *   horizontally (the default on phones), with soft edges where there is more to see. The lane
 *   labels stay pinned on the left (on phones they ride above each lane, name and next date on
 *   two lines). Zoomed in, it starts scrolled so that today sits near the left third.
 * - Keyboard: one tab stop; ←/→ move along a row, ↑/↓ between rows (every bar row of every lane),
 *   Home/End, Enter opens.
 * - Every bar and marker has a tooltip and a full accessible name; a legend explains the marks.
 *
 * @example
 * <LanesChart lanes={lanes} from={range.from} to={range.to} today={today} ariaLabel="Your year ahead" />
 */
import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { useReducedMotion } from "motion/react";
import { Crosshair, Maximize2, ZoomIn } from "lucide-react";
import type { Lane, MarkerKind } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { KindIcon } from "@/components/ui/KindBadge";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Skeleton } from "@/components/ui/Skeleton";
import { LANE_BAR_STATUS_COPY, TONES, copyFor } from "@/lib/copy";
import { formatDate, urgencyOf, urgencyTone } from "@/lib/format";
import { cn } from "@/lib/utils";
import { BarMark, MarkerCaption, MarkerMark } from "./LaneMarks";
import { LanesLegend } from "./LanesLegend";
import { layoutLane, laneStatus, nextOnLane, type LaneLayout } from "./layout";
import { markerWhen } from "./marks";
import { measureBarLabel, measureCaption, measureLine } from "./measure";
import { refTarget } from "./refs";
import { createTimeScale, monthTicks, monthsInScale, plotWidth, scrollLeftFor, yearSpans, dayNumber } from "./scale";
import type { LaneDescription, LaneSelection, LaneTarget } from "./types";
import "./lanes.css";

/** The label column: about a quarter of the chart, 200–320 px. */
const LABEL_MIN = 200;
const LABEL_MAX = 320;
const LABEL_SHARE = 0.24;
const AXIS_H = 46;
const COMPACT_BELOW = 640;
/** the label above a lane on phones: name, then the next date (two lines) */
const COMPACT_HEADER = 48;
const MIN_LANE_H = 54;
/** "Fit all" is the default when every month gets at least this much room (its three-letter name) */
const FIT_MIN_MONTH_PX = 32;

type Zoom = "fit" | "detail";

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
  /** level of the title's heading (default 2; 3 under a page section's h2) */
  headingLevel?: 2 | 3;
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
  /** what screen readers hear while loading (default "Loading your year…") */
  loadingLabel?: string;
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

/** Width of the pinned label column for a chart `width` px wide. */
export function labelColumnWidth(width: number): number {
  return Math.min(LABEL_MAX, Math.max(LABEL_MIN, Math.round(width * LABEL_SHARE)));
}

function defaultIcon(lane: Lane): ReactNode {
  return lane.id === "contracts" ? <KindIcon kind="contract" size="sm" /> : <KindIcon area={lane.area} size="sm" />;
}

/** Dates you act on get the full urgency scale; appointments, payments and other dates never turn red. */
const ACT_BY = new Set<MarkerKind>(["send_by", "deadline", "cancel_by", "expiry"]);

/**
 * The label column's second line: "Send by 8 Oct", "Return library items · 2 Oct · in 4 days",
 * coloured by the app's urgency scale. How soon ("in 4 days") only within a week, and only when
 * the whole line fits `room` px — the label truncates, the date never does. The full line is the
 * title.
 */
function NextLine({ lane, today, to, room }: { lane: Lane; today: string; to: string; room: number }) {
  const next = nextOnLane(lane, today, { to });
  if (!next) return <span className="truncate text-muted">Nothing coming up</span>;
  const tone = urgencyTone(urgencyOf(next.date, today), { cap: ACT_BY.has(next.kind) ? undefined : "warn" });
  const date = formatDate(next.date, { style: "day", today });
  const joiner = /\b(by|before|until|on|expires|ends)$/i.test(next.label) ? " " : " · ";
  const soon = dayNumber(next.date) - dayNumber(today) <= 7 ? ` · ${markerWhen(next.date, today)}` : "";
  const full = `${next.label}${joiner}${date}${soon}`;
  const when = soon && measureLine(full) <= room ? soon : "";
  return (
    <span className={cn("flex min-w-0 tabular-nums", tone.text)} title={full}>
      <span className="truncate">{next.label}</span>
      <span data-testid="lanes-next-date" className="shrink-0 whitespace-pre">
        {joiner}
        {date}
        {when}
      </span>
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
  headingLevel = 2,
  actions,
  labelHeading = "Life area",
  describeLane,
  resolveTarget,
  onSelect,
  loading,
  loadingLabel = "Loading your year…",
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
  const labelW = compact ? 0 : labelColumnWidth(width);
  // wide enough for every month to keep its name: start with all months in view; phones start
  // zoomed in (16 months in 350 px is only an overview)
  const [zoomChoice, setZoom] = useState<Zoom | null>(null);
  const fitsAll = (width - labelW) / monthsInScale(from, to) >= FIT_MIN_MONTH_PX;
  const zoom: Zoom = zoomChoice ?? (fitsAll ? "fit" : "detail");
  /** what lies beyond the visible part: soft edges (and the label column's shadow) say so */
  const [edges, setEdges] = useState({ left: false, right: false });
  /** scroll position, so bar labels whose start is scrolled away shrink to the part in view */
  const [viewLeft, setViewLeft] = useState(0);
  const scrollFrame = useRef(0);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const hintId = useId();

  // zoomed in: about 80–95 px a month on phones and tablets, five months at once on wider screens
  const plotW = width
    ? plotWidth(from, to, width - labelW, zoom, compact ? { minMonthPx: 66, visibleMonths: Math.max(4.5, width / 95) } : { minMonthPx: 90, visibleMonths: 5 })
    : 0;
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
  const range = useMemo(() => ({ from, to }), [from, to]);

  // Rows for arrow-key navigation: every track of every lane (a contract each on the Contracts
  // page), its bars and markers in x order (bars by their start, markers by their centre).
  const { rows, rowOf } = useMemo(() => {
    const rows: MarkRef[][] = [];
    const rowOf = new Map<string, number>();
    for (const ly of layouts) {
      for (let t = 0; t < ly.tracks; t++) {
        const row = [
          ...ly.bars.filter((b) => b.track === t).map((b) => ({ key: `${ly.lane.id}|${b.key}`, x: b.x + Math.min(b.width / 2, 12) })),
          ...ly.markers.filter((m) => m.track === t).map((m) => ({ key: `${ly.lane.id}|${m.key}`, x: m.x })),
        ].sort((a, b) => a.x - b.x);
        if (!row.length) continue;
        for (const m of row) rowOf.set(m.key, rows.length);
        rows.push(row);
      }
    }
    return { rows, rowOf };
  }, [layouts]);
  const defaultKey = useMemo(() => {
    const first = rows[0];
    return first ? (first.find((m) => m.x >= todayX) ?? first[0]!).key : null;
  }, [rows, todayX]);
  const focusKey = activeKey && rowOf.has(activeKey) ? activeKey : defaultKey;

  const updateEdges = useCallback((el: HTMLElement) => {
    const left = el.scrollLeft > 2;
    const right = el.scrollLeft + el.clientWidth < el.scrollWidth - 2;
    setEdges((prev) => (prev.left === left && prev.right === right ? prev : { left, right }));
  }, []);

  // Start scrolled so that today sits near the left third (again when the zoom changes).
  const scrolledFor = useRef<{ el: HTMLElement; key: string } | null>(null);
  useLayoutEffect(() => {
    const el = scrollerRef.current;
    if (!el || !plotW) return;
    const key = `${zoom}|${compact}`;
    if (scrolledFor.current?.el !== el || scrolledFor.current.key !== key) {
      scrolledFor.current = { el, key };
      el.scrollLeft = scrollable && todayVisible ? scrollLeftFor(scale, today, el.clientWidth - labelW) : 0;
      setViewLeft(el.scrollLeft);
    }
    updateEdges(el);
  }, [scroller, plotW, zoom, compact, scrollable, todayVisible, scale, today, labelW, updateEdges]);

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
    const key = (e.target as HTMLElement).dataset.markKey;
    if (!key) return;
    const ri = rowOf.get(key) ?? 0;
    const list = rows[ri] ?? [];
    const i = list.findIndex((m) => m.key === key);
    let next: string | undefined;
    if (e.key === "ArrowRight") next = list[i + 1]?.key;
    else if (e.key === "ArrowLeft") next = list[i - 1]?.key;
    else if (e.key === "Home") next = list[0]?.key;
    else if (e.key === "End") next = list[list.length - 1]?.key;
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const x = list[i]?.x ?? 0;
      const cand = rows[ri + (e.key === "ArrowDown" ? 1 : -1)];
      next = cand?.reduce((best, m) => (Math.abs(m.x - x) < Math.abs(best.x - x) ? m : best)).key;
    } else return;
    e.preventDefault();
    if (!next) return;
    setActiveKey(next);
    scrollerRef.current?.querySelector<HTMLElement>(`[data-mark-key="${CSS.escape(next)}"]`)?.focus();
  };

  // The year label slides along (sticky) while its year is in view; it steps past the TODAY pill
  // instead of hiding under it (and hides only when there is no room left in its year).
  const pillHalf = (measureCaption("TODAY") * 1.08 + 16) / 2;
  const yearLabels = years.map((y) => {
    const textW = measureCaption(String(y.year)) + 2;
    const pad = 8;
    const pos = Math.max(y.x, Math.min(viewLeft, y.x + y.width - textW - pad));
    const s = pos + pad;
    let shift = 0;
    let hidden = false;
    if (todayVisible && s < todayX + pillHalf + 4 && s + textW > todayX - pillHalf - 4) {
      const after = todayX + pillHalf + 6;
      if (after + textW <= y.x + y.width - 2) shift = after - s;
      else hidden = true;
    }
    return { ...y, pad: pad + shift, hidden };
  });

  const hasLanes = lanes.length > 0;
  const Heading = headingLevel === 3 ? "h3" : "h2";
  const headerRow =
    title || description || actions || (hasLanes && !loading) ? (
      <div className="flex flex-col gap-3 px-4 pb-3 pt-4 sm:flex-row sm:items-end sm:px-5 sm:pt-5">
        <div className="min-w-0 flex-1">
          {title ? <Heading className="display text-[21px] font-semibold leading-tight text-ink sm:text-[23px]">{title}</Heading> : null}
          {description ? <p className="mt-1 text-[13.5px] leading-snug text-muted">{description}</p> : null}
        </div>
        {hasLanes && !loading ? (
          <div className="flex flex-wrap items-center gap-2">
            {actions}
            {scrollable && todayVisible ? (
              <Button variant="ghost" size="sm" icon={Crosshair} onClick={scrollToToday} title="Jump to today">
                {/* icon only on the narrowest phones (the name stays for screen readers) */}
                <span className="max-[359px]:sr-only">Jump to today</span>
              </Button>
            ) : null}
            <SegmentedControl
              size="sm"
              label="Zoom"
              value={zoom}
              onChange={setZoom}
              options={[
                { value: "fit", label: "Fit all", icon: Maximize2 },
                { value: "detail", label: "Zoom in", icon: ZoomIn },
              ]}
            />
          </div>
        ) : (
          actions
        )}
      </div>
    ) : null;

  const columnShadow = edges.left && "shadow-[6px_0_10px_-8px_rgb(0_0_0/0.18)]";

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
              {loadingLabel}
            </span>
          </div>
        ) : !hasLanes ? (
          <div className="p-5">{empty ?? <p className="py-8 text-center text-base text-muted">Nothing on your lanes yet.</p>}</div>
        ) : plotW ? (
          <>
            <div
              ref={attachScroller}
              data-testid="lanes-scroller"
              className="overflow-x-auto overscroll-x-contain scrollbar-thin"
              style={{ scrollPaddingLeft: labelW + 16, scrollPaddingRight: 16 }}
              onScroll={(e) => {
                const el = e.currentTarget;
                updateEdges(el);
                cancelAnimationFrame(scrollFrame.current);
                scrollFrame.current = requestAnimationFrame(() => setViewLeft(el.scrollLeft));
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
                        "sticky left-0 z-30 flex shrink-0 items-end border-r border-line bg-surface px-4 pb-2.5 text-xs font-semibold uppercase tracking-[0.08em] text-muted",
                        columnShadow,
                      )}
                      style={{ width: labelW }}
                    >
                      {labelHeading}
                    </div>
                  ) : null}
                  <div className="relative shrink-0" style={{ width: plotW }} aria-hidden>
                    {yearLabels.map((y) => (
                      <div key={y.year} className="absolute top-[3px] flex h-[18px]" style={{ left: y.x, width: y.width }}>
                        <span
                          data-testid="lanes-year"
                          className={cn("whitespace-nowrap text-xs font-semibold leading-[18px] tabular-nums tracking-wide text-muted", scrollable && "sticky", y.hidden && "invisible")}
                          style={{ left: labelW, paddingLeft: y.pad }}
                        >
                          {y.year}
                        </span>
                      </div>
                    ))}
                    {ticks.map((t) => (
                      <span
                        key={t.date}
                        className={cn(
                          "absolute bottom-[7px] -translate-x-1/2 whitespace-nowrap text-xs font-medium",
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
                        className="absolute top-[3px] z-20 -translate-x-1/2 whitespace-nowrap rounded-full bg-ink px-2 py-[2px] text-xs font-semibold uppercase leading-[14px] tracking-[0.06em] text-canvas shadow-[0_0_0_2px_var(--color-surface)]"
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
                    // room for the second line: the label column (or the pinned label on phones) minus its icon and padding
                    const room = compact ? Math.max(160, width - 12) - 58 : labelW - 66;
                    const sub = desc?.sublabel ?? <NextLine lane={lane} today={today} to={to} room={room} />;
                    const offset = compact ? COMPACT_HEADER : 0;
                    const height = ly.height + offset;
                    const railY = (ly.trackY[0] ?? 0) + offset;
                    const common = (key: string) => ({
                      markKey: key,
                      row: rowOf.get(key) ?? 0,
                      tabIndex: key === focusKey ? 0 : -1,
                      onActivate: setActiveKey,
                      today,
                    });
                    return (
                      <div key={lane.id} role="listitem" aria-label={label} className="relative flex border-t border-line/80" style={{ height }}>
                        {!compact ? (
                          <div
                            className={cn("sticky left-0 z-30 flex shrink-0 items-center gap-2.5 border-r border-line bg-surface pl-4 pr-3", columnShadow)}
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
                              <div className="flex min-w-0 text-xs leading-4">{sub}</div>
                            </div>
                          </div>
                        ) : null}
                        <div className="relative shrink-0" style={{ width: plotW }}>
                          {compact ? (
                            // the lane's name and next date, pinned to the left edge while the lane scrolls;
                            // never wider than the chart (the name truncates, the date stays)
                            <div
                              data-testid="lanes-compact-label"
                              className="sticky left-0 z-30 mt-1 flex w-max items-center gap-2 rounded-r-lg bg-surface/95 py-1 pl-3 pr-2.5"
                              style={{ maxWidth: Math.max(160, width - 12) }}
                            >
                              {icon}
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-1.5">
                                  <span className="truncate text-[13px] font-semibold leading-5 text-ink" title={label}>
                                    {label}
                                  </span>
                                  <StatusDot lane={lane} />
                                </div>
                                <div className="flex min-w-0 text-xs leading-4">{sub}</div>
                              </div>
                            </div>
                          ) : null}
                          {ly.rail ? <div aria-hidden className="absolute inset-x-0 h-px bg-line-strong" style={{ top: railY }} /> : null}
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
                                scrolls={scrollable}
                                range={range}
                                reduced={reduced}
                                delay={Math.min(0.6, li * 0.05 + bi * 0.03)}
                                onSelect={() => select(sel)}
                                hint={hintFor(sel)}
                                {...common(key)}
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
                                hint={hintFor(sel)}
                                {...common(key)}
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
            {/* soft edges where the zoomed-in chart has more to show (below the pinned lane labels) */}
            {scrollable ? (
              <>
                <div
                  aria-hidden
                  data-testid="lanes-fade-left"
                  data-shown={edges.left || undefined}
                  className={cn(
                    "pointer-events-none absolute inset-y-0 z-[25] w-6 bg-linear-to-r from-surface to-transparent transition-opacity duration-150",
                    edges.left ? "opacity-100" : "opacity-0",
                  )}
                  style={{ left: labelW }}
                />
                <div
                  aria-hidden
                  data-testid="lanes-fade-right"
                  data-shown={edges.right || undefined}
                  className={cn(
                    "pointer-events-none absolute inset-y-0 right-0 z-[25] w-8 bg-linear-to-l from-surface to-transparent transition-opacity duration-150",
                    edges.right ? "opacity-100" : "opacity-0",
                  )}
                />
              </>
            ) : null}
          </>
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
