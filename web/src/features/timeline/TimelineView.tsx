/**
 * Timeline page body: the year-ahead life lanes on top, the month-by-month list below.
 * Filters live in the URL (`?area=residence&type=payment&with=…&past=0`) so Today's area tiles can
 * link straight into a filtered view; kind, area and person filter the lanes too.
 */
import { useCallback, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { Lock, Plus, X } from "lucide-react";
import { useContracts, useItems, useLanes, useParties, useTimeline } from "@/api/hooks";
import type { Item, RefLink, TimelineMarker } from "@/api/types";
import { useAddLetters } from "@/components/shell/AddLetters";
import { PageHeader } from "@/components/shell/Page";
import { Button } from "@/components/ui/Button";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadError } from "@/components/ui/LoadError";
import { SkeletonCard } from "@/components/ui/Skeleton";
import { formatDate } from "@/lib/format";
import { useTodayISO } from "@/lib/today";
import { plural } from "@/lib/utils";
import { LanesChart, defaultLaneRange, refTarget, type LaneSelection, type LaneTarget } from "@/features/lanes";
import { AddDateButton } from "@/features/items/AddDateDialog";
import { CalendarExport } from "./CalendarExport";
import { TimelineFilters } from "./TimelineFilters";
import { TimelineList } from "./TimelineList";
import {
  NO_FILTERS,
  applyFilters,
  emptyFilterHint,
  emptyLanesCopy,
  entryForDate,
  filterLanes,
  filterOptions,
  filterSummary,
  filtersFromParams,
  filtersToParams,
  groupByMonth,
  openDateCount,
  type LaneSources,
  type TimelineFilters as Filters,
} from "./model";
import { TOUR_TARGETS } from "@/features/tour/steps";
import { usePhoneCompanion } from "@/features/phone/client";
import { filesStay } from "@/features/phone/copy";
import { useStickyError } from "@/lib/hooks";

const DESCRIPTION = "Your year ahead as life lanes — permits, contracts, deadlines and study — and every date, month by month.";

/**
 * A fresh install: one clear first step instead of empty lanes, filters and a second empty list — or a date of
 * the person's own, which needs no letter (and no Claude).
 */
function FirstRun() {
  const { openPicker, uploading } = useAddLetters();
  const phone = usePhoneCompanion();
  return (
    <EmptyState
      illustration="calendar"
      title="Your year is still empty"
      description="Add a letter — a bill, a contract, a notice from an office — and Ordnung puts every deadline, payment and appointment on your lanes and here, month by month."
      action={
        <>
          <Button variant="primary" icon={Plus} onClick={openPicker} loading={uploading}>
            Add letters
          </Button>
          <AddDateButton />
        </>
      }
    >
      <p className="mt-5 inline-flex items-center gap-1.5 text-sm text-muted">
        <Lock className="size-3.5 shrink-0" aria-hidden /> {filesStay(phone)}
      </p>
    </EmptyState>
  );
}

export function TimelineView() {
  const today = useTodayISO();
  const navigate = useNavigate();
  const range = useMemo(() => defaultLaneRange(today), [today]);
  const lanesQ = useLanes(range.from, range.to);
  const timelineQ = useTimeline(range.from, range.to);
  const itemsQ = useItems();
  const contractsQ = useContracts();
  const partiesQ = useParties();
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
  const options = useMemo(() => filterOptions(entries, filters, today), [entries, filters, today]);
  const visible = useMemo(() => applyFilters(entries, filters, today), [entries, filters, today]);
  const groups = useMemo(() => groupByMonth(visible, today, range), [visible, today, range]);

  // The lanes under the same kind / area / person filters, each bar and marker judged by its own date.
  const laneSources = useMemo<LaneSources>(() => {
    const partyName = new Map((partiesQ.data ?? []).map((p) => [p.id, p.name]));
    const nameOf = (id: string | null | undefined) => (id ? (partyName.get(id) ?? null) : null);
    return {
      entries,
      contracts: new Map((contractsQ.data ?? []).map((c) => [c.id, { area: c.area, party: nameOf(c.party_id) }])),
      items: new Map((itemsQ.data ?? []).map((i) => [i.id, { kind: i.kind, area: i.area, party: nameOf(i.party_id) }])),
    };
  }, [entries, contractsQ.data, itemsQ.data, partiesQ.data]);
  const allLanes = useMemo(() => lanesQ.data ?? [], [lanesQ.data]);
  const lanes = useMemo(() => filterLanes(allLanes, filters, laneSources), [allLanes, filters, laneSources]);
  const summary = filterSummary(filters);

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
      const own = sel.marker as (TimelineMarker & { ref?: RefLink | null }) | null;
      const hit = entryForDate(pool, date, sel.marker?.label, own?.ref ?? null);
      if (!hit) return;
      if (date < today && !filters.showPast) setFilters({ ...filters, showPast: true });
      setHighlight({ id: hit.id, nonce: Date.now() });
      if (clearTimer.current) clearTimeout(clearTimer.current);
      clearTimer.current = setTimeout(() => setHighlight(null), 2600);
    },
    [itemsById, navigate, entries, filters, visible, today, setFilters],
  );

  const hrefFor = useCallback((e: (typeof entries)[number]) => refTarget(e.ref, itemsById)?.href ?? null, [itemsById]);

  // A retry of a failed load starts over as "pending" (and forgets the error): remember the error,
  // so the message stays on screen, worded the same, while "Try again" runs.
  const loaded = Boolean(lanesQ.data && timelineQ.data);
  const error = lanesQ.error ?? timelineQ.error;
  const lastError = useStickyError(error, loaded);
  const failed = !loaded && (lanesQ.isError || timelineQ.isError || lastError !== null);

  if (failed) {
    return (
      <>
        <PageHeader title="Timeline" description={DESCRIPTION} />
        <LoadError
          what="your timeline"
          error={error ?? lastError}
          onRetry={() => {
            if (!lanesQ.data) void lanesQ.refetch();
            if (!timelineQ.data) void timelineQ.refetch();
          }}
          retrying={lanesQ.isFetching || timelineQ.isFetching}
        />
      </>
    );
  }

  if (loaded && !allLanes.length && !entries.length) {
    return (
      <>
        <PageHeader title="Timeline" description={DESCRIPTION} />
        <FirstRun />
      </>
    );
  }

  const rangeText = `${formatDate(range.from, { style: "month" })} – ${formatDate(range.to, { style: "month" })}`;
  const laneFilterCount = [filters.type, filters.area, filters.party].filter(Boolean).length;
  const showAllLabel = laneFilterCount > 1 ? "Show all" : filters.area ? "Show all areas" : filters.type ? "Show all kinds" : "Show everyone";
  const openDates = openDateCount(entries);

  return (
    <>
      <PageHeader
        title="Timeline"
        description={DESCRIPTION}
        actions={
          <>
            <AddDateButton />
            {loaded && openDates > 0 ? <CalendarExport /> : null}
          </>
        }
      />

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
            !loaded ? (
              rangeText
            ) : summary ? (
              <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
                <span>
                  {/* the dot stays with the range: a wrapped line never starts with "·" */}
                  {rangeText}&nbsp;· showing {summary} only
                </span>
                <Button variant="link" size="sm" icon={X} onClick={() => setFilters({ ...filters, type: null, area: null, party: null })}>
                  {showAllLabel}
                </Button>
              </span>
            ) : (
              `${rangeText}\u00a0· ${plural(lanes.length, "lane")}`
            )
          }
          resolveTarget={resolveTarget}
          onSelect={onSelect}
          empty={
            <EmptyState
              size="sm"
              variant="plain"
              headingLevel={3}
              illustration="calendar"
              {...emptyLanesCopy(filters, visible.length)}
            />
          }
          footer={<Disclaimer />}
        />
      </section>

      {!loaded ? (
        <SkeletonCard lines={6} className="max-w-4xl" />
      ) : (
        <TimelineList
          className="max-w-4xl"
          groups={groups}
          today={today}
          hrefFor={hrefFor}
          highlight={highlight}
          scrollKey={String(filters.showPast)}
          header={
            <div className="flex flex-col gap-3 border-b border-line px-4 pb-4 pt-4 sm:px-5 sm:pt-5">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h2 id="timeline-list-title" className="display text-[21px] font-semibold leading-tight text-ink sm:text-[23px]">
                  Every date
                </h2>
                <span className="text-sm text-muted">
                  {visible.length === entries.length ? plural(entries.length, "date") : `${visible.length} of ${entries.length} dates`}
                </span>
              </div>
              {entries.length ? <TimelineFilters filters={filters} onChange={setFilters} options={options} /> : null}
            </div>
          }
          empty={
            entries.length ? (
              <EmptyState
                size="sm"
                variant="plain"
                headingLevel={3}
                illustration="search"
                title="No dates match these filters"
                description={emptyFilterHint(filters)}
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
                headingLevel={3}
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
