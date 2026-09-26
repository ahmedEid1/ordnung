/**
 * Timeline page body: the year-ahead life lanes on top, the month-by-month list below.
 * Filters live in the URL (`?area=residence&type=payment&with=…&past=0`) so Today's area tiles can
 * link straight into a filtered view.
 */
import { useCallback, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { X } from "lucide-react";
import { useItems, useLanes, useTimeline } from "@/api/hooks";
import type { Item } from "@/api/types";
import { PageHeader } from "@/components/shell/Page";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { EmptyState } from "@/components/ui/EmptyState";
import { SkeletonCard } from "@/components/ui/Skeleton";
import { AREA_COPY, copyFor } from "@/lib/copy";
import { formatDate } from "@/lib/format";
import { useTodayISO } from "@/lib/today";
import { plural } from "@/lib/utils";
import { LanesChart, defaultLaneRange, refTarget, type LaneSelection, type LaneTarget } from "@/features/lanes";
import { CalendarExport } from "./CalendarExport";
import { TimelineFilters } from "./TimelineFilters";
import { TimelineList } from "./TimelineList";
import { NO_FILTERS, applyFilters, entryForDate, filterOptions, filtersFromParams, filtersToParams, groupByMonth, type TimelineFilters as Filters } from "./model";
import { TOUR_TARGETS } from "@/features/tour/steps";

export function TimelineView() {
  const today = useTodayISO();
  const navigate = useNavigate();
  const range = useMemo(() => defaultLaneRange(today), [today]);
  const lanesQ = useLanes(range.from, range.to);
  const timelineQ = useTimeline(range.from, range.to);
  const itemsQ = useItems();
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => filtersFromParams(params), [params]);
  const [highlight, setHighlight] = useState<{ id: string; nonce: number } | null>(null);
  const clearTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const setFilters = useCallback(
    (f: Filters) => setParams((prev) => filtersToParams(f, prev), { replace: true, preventScrollReset: true }),
    [setParams],
  );

  const itemsById = useMemo(() => new Map<string, Item>((itemsQ.data ?? []).map((i) => [i.id, i])), [itemsQ.data]);
  const entries = useMemo(() => timelineQ.data ?? [], [timelineQ.data]);
  const options = useMemo(() => filterOptions(entries), [entries]);
  const visible = useMemo(() => applyFilters(entries, filters, today), [entries, filters, today]);
  const groups = useMemo(() => groupByMonth(visible, today, range), [visible, today, range]);

  const allLanes = useMemo(() => lanesQ.data ?? [], [lanesQ.data]);
  const lanes = useMemo(() => (filters.area ? allLanes.filter((l) => l.area === filters.area) : allLanes), [allLanes, filters.area]);

  const resolveTarget = useCallback(
    (sel: LaneSelection): LaneTarget | null => refTarget(sel.ref, itemsById) ?? (sel.marker ? { hint: "Shows it in the list below" } : null),
    [itemsById],
  );

  const onSelect = useCallback(
    (sel: LaneSelection) => {
      const target = refTarget(sel.ref, itemsById);
      if (target) {
        navigate(target.href);
        return;
      }
      // No page of its own (e.g. a payment marker): show the matching entry in the list below.
      const date = sel.marker?.date ?? sel.date;
      const pool = date < today && !filters.showPast ? applyFilters(entries, { ...filters, showPast: true }, today) : visible;
      const hit = entryForDate(pool, date, sel.marker?.label);
      if (!hit) return;
      if (date < today && !filters.showPast) setFilters({ ...filters, showPast: true });
      setHighlight({ id: hit.id, nonce: Date.now() });
      if (clearTimer.current) clearTimeout(clearTimer.current);
      clearTimer.current = setTimeout(() => setHighlight(null), 2600);
    },
    [itemsById, navigate, entries, filters, visible, today, setFilters],
  );

  const hrefFor = useCallback((e: (typeof entries)[number]) => refTarget(e.ref, itemsById)?.href ?? null, [itemsById]);

  const areaLabel = filters.area ? copyFor(AREA_COPY, filters.area).label : null;
  const rangeText = `${formatDate(range.from, { style: "month" })} – ${formatDate(range.to, { style: "month" })}`;
  const failed = (lanesQ.isError && !lanesQ.data) || (timelineQ.isError && !timelineQ.data);

  return (
    <>
      <PageHeader
        title="Timeline"
        description="Your year ahead as life lanes — permits, contracts, deadlines and study — and every date, month by month."
        actions={<CalendarExport />}
      />

      {failed ? (
        <Callout
          tone="danger"
          title="Couldn't load your timeline"
          className="mb-6"
          action={
            <Button
              size="sm"
              onClick={() => {
                void lanesQ.refetch();
                void timelineQ.refetch();
              }}
            >
              Try again
            </Button>
          }
        >
          Your letters are safe — the app just couldn't reach its local server.
        </Callout>
      ) : null}

      <section aria-label="Your year ahead" data-tour={TOUR_TARGETS.timelineLanes} className="mb-8">
        <LanesChart
          lanes={lanes}
          from={range.from}
          to={range.to}
          today={today}
          loading={lanesQ.isPending}
          ariaLabel="Your year ahead, one lane per area of life"
          title="Your year ahead"
          description={
            areaLabel ? (
              <span className="inline-flex flex-wrap items-center gap-2">
                <span>
                  {rangeText} · showing {areaLabel} only
                </span>
                <Button variant="link" size="sm" icon={X} className="text-[13px]" onClick={() => setFilters({ ...filters, area: null })}>
                  Show all areas
                </Button>
              </span>
            ) : (
              `${rangeText} · ${plural(lanes.length, "lane")}`
            )
          }
          resolveTarget={resolveTarget}
          onSelect={onSelect}
          empty={
            <EmptyState
              size="sm"
              variant="plain"
              illustration="calendar"
              title={areaLabel ? `Nothing for ${areaLabel} in this year` : "Your year is still empty"}
              description={areaLabel ? "Try another area — or show all." : "Add letters and Ordnung fills in permits, contracts and deadlines here."}
            />
          }
          footer={<Disclaimer />}
        />
      </section>

      {timelineQ.isPending ? (
        <SkeletonCard lines={6} />
      ) : (
        <TimelineList
          groups={groups}
          today={today}
          hrefFor={hrefFor}
          highlight={highlight}
          scrollKey={String(filters.showPast)}
          header={
            <div className="flex flex-col gap-3 border-b border-line px-4 pb-4 pt-4 sm:px-5 sm:pt-5">
              <div className="flex items-baseline gap-3">
                <h2 id="timeline-list-title" className="display text-[21px] font-semibold leading-tight text-ink sm:text-[23px]">
                  Every date
                </h2>
                <span className="text-[13px] text-muted">
                  {visible.length === entries.length ? plural(entries.length, "date") : `${visible.length} of ${entries.length} dates`}
                </span>
              </div>
              <TimelineFilters filters={filters} onChange={setFilters} options={options} />
            </div>
          }
          empty={
            entries.length ? (
              <EmptyState
                size="sm"
                variant="plain"
                illustration="search"
                title="No dates match these filters"
                description="Try another kind or area, or show past dates."
                action={
                  <Button size="sm" onClick={() => setFilters(NO_FILTERS)}>
                    Clear filters
                  </Button>
                }
              />
            ) : (
              <EmptyState
                size="sm"
                variant="plain"
                illustration="calendar"
                title="No dates yet"
                description="Add letters and every deadline, payment and appointment shows up here, month by month."
              />
            )
          }
        />
      )}
    </>
  );
}
