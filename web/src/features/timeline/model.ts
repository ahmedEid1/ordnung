/**
 * Timeline list logic: filters, month grouping with the Today divider, status and subtitle copy.
 * Pure functions, unit-tested in `model.test.ts`.
 */
import type { Area, TimelineEntry, TimelineType } from "@/api/types";
import { AREAS, TIMELINE_TYPES } from "@/api/types";
import {
  AREA_COPY,
  CONTRACT_STATUS_COPY,
  DOCUMENT_STATUS_COPY,
  DRAFT_STATUS_COPY,
  ITEM_STATUS_COPY,
  SEND_CHANNEL_COPY,
  TIMELINE_TYPE_COPY,
  copyFor,
  type EnumCopy,
} from "@/lib/copy";
import { addToTotals, formatDate, type Totals } from "@/lib/format";
import { CircleDashed, TriangleAlert } from "lucide-react";
import { differenceInCalendarDays, parseISO } from "date-fns";

// ------------------------------------------------------------------------------------------------
// Filters (URL state: ?type=payment&area=home&with=FunkNetz&past=0)
// ------------------------------------------------------------------------------------------------

export interface TimelineFilters {
  type: TimelineType | null;
  area: Area | null;
  /** party name (entries carry `party_name`, not an id) */
  party: string | null;
  showPast: boolean;
}

export const NO_FILTERS: TimelineFilters = { type: null, area: null, party: null, showPast: true };

export function filtersFromParams(params: URLSearchParams): TimelineFilters {
  const type = params.get("type");
  const area = params.get("area");
  return {
    type: type && (TIMELINE_TYPES as readonly string[]).includes(type) ? (type as TimelineType) : null,
    area: area && (AREAS as readonly string[]).includes(area) ? (area as Area) : null,
    party: params.get("with") || null,
    showPast: params.get("past") !== "0",
  };
}

/** Write filters into a copy of `params` (other params such as `?party=` are kept). */
export function filtersToParams(f: TimelineFilters, params: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(params);
  const set = (k: string, v: string | null) => (v ? next.set(k, v) : next.delete(k));
  set("type", f.type);
  set("area", f.area);
  set("with", f.party);
  set("past", f.showPast ? null : "0");
  return next;
}

export function activeFilterCount(f: TimelineFilters): number {
  return Number(Boolean(f.type)) + Number(Boolean(f.area)) + Number(Boolean(f.party)) + Number(!f.showPast);
}

export function isPastEntry(e: Pick<TimelineEntry, "date" | "past">, today: string): boolean {
  return e.past || e.date < today;
}

export function applyFilters(entries: TimelineEntry[], f: TimelineFilters, today: string): TimelineEntry[] {
  return entries.filter(
    (e) =>
      (!f.type || e.type === f.type) &&
      (!f.area || e.area === f.area) &&
      (!f.party || e.party_name === f.party) &&
      (f.showPast || !isPastEntry(e, today)),
  );
}

export interface FilterOption<V extends string = string> {
  value: V;
  label: string;
  count: number;
}

/** Options for the filter menus — only values that occur, with counts, sorted by label. */
export function filterOptions(entries: TimelineEntry[]): {
  types: FilterOption<TimelineType>[];
  areas: FilterOption<Area>[];
  parties: FilterOption[];
} {
  const count = <K extends string>(key: (e: TimelineEntry) => K | null | undefined) => {
    const m = new Map<K, number>();
    for (const e of entries) {
      const k = key(e);
      if (k) m.set(k, (m.get(k) ?? 0) + 1);
    }
    return m;
  };
  const byLabel = (a: FilterOption, b: FilterOption) => a.label.localeCompare(b.label);
  return {
    types: [...count((e) => e.type)].map(([value, n]) => ({ value, label: typeLabel(value), count: n })).sort(byLabel),
    areas: [...count((e) => e.area)].map(([value, n]) => ({ value, label: copyFor(AREA_COPY, value).label, count: n })).sort(byLabel),
    parties: [...count((e) => e.party_name)].map(([value, n]) => ({ value, label: value, count: n })).sort(byLabel),
  };
}

/** Plural-friendly type names for the filter ("Payments", "Letters"). */
export function typeLabel(type: TimelineType): string {
  switch (type) {
    case "document":
      return "Letters received";
    case "draft":
      return "Letters you sent";
    case "task":
      return "To-dos";
    case "expiry":
      return "Expiry dates";
    default:
      return `${copyFor(TIMELINE_TYPE_COPY, type).label}s`;
  }
}

// ------------------------------------------------------------------------------------------------
// Month groups + Today divider
// ------------------------------------------------------------------------------------------------

export interface MonthGroup {
  /** "2026-10" */
  key: string;
  /** "October" */
  month: string;
  /** "2026" */
  year: string;
  entries: TimelineEntry[];
  /** index in `entries` before which the Today divider goes (null: not in this month) */
  todayIndex: number | null;
  /** sums of payment amounts still to pay (open payments), per currency */
  toPay: Totals;
  /** the whole month lies before today's month */
  past: boolean;
}

const TYPE_RANK: Partial<Record<TimelineType, number>> = { deadline: 0, payment: 1, expiry: 2, appointment: 3, contract: 4, task: 5 };

function compareEntries(a: TimelineEntry, b: TimelineEntry): number {
  return (
    a.date.localeCompare(b.date) ||
    (a.time ?? "").localeCompare(b.time ?? "") ||
    (TYPE_RANK[a.type] ?? 9) - (TYPE_RANK[b.type] ?? 9) ||
    a.title.localeCompare(b.title)
  );
}

const CLOSED = new Set(["done", "dismissed", "cancelled", "ended", "paid"]);

/**
 * Group entries by calendar month (chronological) and place the Today divider before the first
 * entry dated today or later. Today's month always gets a group (so the divider has a home), as
 * long as it lies within the entries' span or `range`.
 */
export function groupByMonth(entries: TimelineEntry[], today: string, range?: { from: string; to: string }): MonthGroup[] {
  const sorted = [...entries].sort(compareEntries);
  const todayKey = today.slice(0, 7);
  const map = new Map<string, TimelineEntry[]>();
  for (const e of sorted) {
    const k = e.date.slice(0, 7);
    map.set(k, [...(map.get(k) ?? []), e]);
  }
  const first = range?.from.slice(0, 7) ?? sorted[0]?.date.slice(0, 7);
  const last = range?.to.slice(0, 7) ?? sorted[sorted.length - 1]?.date.slice(0, 7);
  const inRange = first !== undefined && last !== undefined && first <= todayKey && todayKey <= last;
  if (!map.has(todayKey) && inRange) map.set(todayKey, []);
  const keys = [...map.keys()].sort();
  return keys.map((key) => {
    const list = map.get(key)!;
    const d = new Date(Number(key.slice(0, 4)), Number(key.slice(5, 7)) - 1, 1);
    let todayIndex: number | null = null;
    if (key === todayKey) {
      const i = list.findIndex((e) => e.date >= today);
      todayIndex = i < 0 ? list.length : i;
    }
    const toPay = list
      .filter((e) => e.type === "payment" && e.amount && !CLOSED.has(e.status ?? "") && e.date >= today)
      .reduce<Totals>((totals, e) => addToTotals(totals, e.amount ?? 0, e.currency), {});
    return {
      key,
      month: formatDate(d, { style: "month" }).split(" ")[0]!,
      year: key.slice(0, 4),
      entries: list,
      todayIndex,
      toPay,
      past: key < todayKey,
    };
  });
}

/** Among `entries`, the one a lane marker on `date` points to: same date (title match first), else the next one. */
export function entryForDate(entries: TimelineEntry[], date: string, label?: string | null): TimelineEntry | null {
  const sorted = [...entries].sort(compareEntries);
  const same = sorted.filter((e) => e.date === date);
  if (same.length) {
    const words = (label ?? "").toLowerCase().split(/\W+/).filter((w) => w.length > 3);
    return same.find((e) => words.some((w) => e.title.toLowerCase().includes(w))) ?? same[0]!;
  }
  return sorted.find((e) => e.date >= date) ?? null;
}

// ------------------------------------------------------------------------------------------------
// Copy
// ------------------------------------------------------------------------------------------------

const OVERDUE: EnumCopy = { label: "Overdue", icon: TriangleAlert, tone: "danger" };
/** An open to-do from long ago: probably done, just never marked. Quiet, not red. */
const STILL_OPEN: EnumCopy = { label: "Not marked done", icon: CircleDashed, tone: "neutral" };
const HISTORY_DAYS = 30;

/**
 * Human status for an entry, or null when there is nothing worth saying ("open", "filed",
 * "active"). Maps each entry type through its own copy table (never shows raw values).
 */
export function entryStatus(e: Pick<TimelineEntry, "type" | "status" | "date" | "past">, today: string): EnumCopy | null {
  const s = e.status;
  if (!s) return null;
  switch (e.type) {
    case "document":
      return s === "processed" ? null : copyFor(DOCUMENT_STATUS_COPY, s);
    case "draft":
      return s === "draft" ? null : copyFor(DRAFT_STATUS_COPY, s);
    case "contract":
      return s === "active" ? null : copyFor(CONTRACT_STATUS_COPY, s);
    default: {
      const late = s === "overdue" || s === "missed" || (s === "open" && isPastEntry(e, today));
      // appointments and milestones simply pass; a date long past is history, not an alarm
      if (late && (e.type === "appointment" || e.type === "milestone" || e.type === "reminder" || e.type === "expiry")) return null;
      if (late && differenceInCalendarDays(parseISO(today), parseISO(e.date)) > HISTORY_DAYS) return STILL_OPEN;
      if (late) return OVERDUE;
      if (s === "open") return null;
      return copyFor(ITEM_STATUS_COPY, s);
    }
  }
}

/** Second line of an entry: party and subtitle (send channels mapped to words), without repeats. */
export function entryMeta(e: Pick<TimelineEntry, "party_name" | "subtitle" | "time" | "type">): string {
  const parts: string[] = [];
  if (e.party_name) parts.push(e.party_name);
  let sub = e.subtitle?.trim() || null;
  if (sub && Object.prototype.hasOwnProperty.call(SEND_CHANNEL_COPY, sub)) sub = copyFor(SEND_CHANNEL_COPY, sub).label;
  if (sub && e.party_name && (sub === e.party_name || sub === `Letter from ${e.party_name}`)) sub = null;
  if (sub) parts.push(sub);
  return parts.join(" · ");
}
