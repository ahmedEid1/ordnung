/**
 * Timeline list logic: filters (for the list and the lanes), month grouping with the Today divider,
 * status and subtitle copy. Pure functions, unit-tested in `model.test.ts`.
 */
import type { Area, Lane, LaneBarKind, MarkerKind, RefLink, TimelineEntry, TimelineMarker, TimelineType } from "@/api/types";
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
  /** entries this option would show together with the other filters (0: the menu greys it out) */
  count: number;
}

/**
 * Options for the filter menus: every value that occurs (plus the chosen one), sorted by label.
 * Each count is what picking that option would show together with the *other* filters — so "To-dos
 * (1)" next to a chosen person never leads to an empty list.
 */
export function filterOptions(
  entries: TimelineEntry[],
  f: TimelineFilters = NO_FILTERS,
  today = "",
): {
  types: FilterOption<TimelineType>[];
  areas: FilterOption<Area>[];
  parties: FilterOption[];
} {
  const facet = <K extends string>(key: (e: TimelineEntry) => K | null | undefined, chosen: K | null, others: TimelineFilters, label: (v: K) => string) => {
    const values = new Set<K>();
    for (const e of entries) {
      const k = key(e);
      if (k) values.add(k);
    }
    if (chosen) values.add(chosen);
    const counts = new Map<K, number>();
    for (const e of applyFilters(entries, others, today)) {
      const k = key(e);
      if (k) counts.set(k, (counts.get(k) ?? 0) + 1);
    }
    return [...values].map((value) => ({ value, label: label(value), count: counts.get(value) ?? 0 })).sort((a, b) => a.label.localeCompare(b.label));
  };
  return {
    types: facet((e) => e.type, f.type, { ...f, type: null }, typeLabel),
    areas: facet((e) => e.area, f.area, { ...f, area: null }, (a) => copyFor(AREA_COPY, a).label),
    parties: facet((e) => e.party_name, f.party, { ...f, party: null }, (p) => p),
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

/** The chosen kind, area and person in words ("Payments · Getting around"), or null when none is set. */
export function filterSummary(f: TimelineFilters): string | null {
  const parts = [f.type ? typeLabel(f.type) : null, f.area ? copyFor(AREA_COPY, f.area).label : null, f.party];
  return parts.filter(Boolean).join(" · ") || null;
}

/** What to try when the filters match nothing — naming only the filters that are set. */
export function emptyFilterHint(f: TimelineFilters): string {
  const nouns = [f.type ? "kind" : null, f.area ? "area" : null, f.party ? "person" : null].filter((x): x is string => Boolean(x));
  const last = nouns[nouns.length - 1];
  const pick = !last ? null : nouns.length > 1 ? `another ${nouns.slice(0, -1).join(", ")} or ${last}` : `another ${last === "person" ? "person or organisation" : last}`;
  if (pick) return f.showPast ? `Try ${pick}.` : `Try ${pick}, or show past dates.`;
  return f.showPast ? "Clear the filters to see every date." : "Nothing is coming up — show past dates to see earlier ones.";
}

/**
 * What the lanes say when the filters leave nothing on them — never "nothing for …" while the list
 * below has dates. `listed`: the dates the list shows with the same filters.
 */
export function emptyLanesCopy(f: TimelineFilters, listed: number): { title: string; description: string } {
  if (!filterSummary(f)) {
    return { title: "Nothing on your lanes yet", description: "Permits, contracts and deadlines appear here as letters bring them — every date is in the list below." };
  }
  if (f.type === "document" || f.type === "draft") {
    return {
      title: "Letters aren't drawn on the lanes",
      description: listed ? "They're in the list below." : f.showPast ? emptyFilterHint(f) : "Switch on “Show past” to see them in the list below.",
    };
  }
  if (listed) {
    return {
      title: listed === 1 ? "This date isn't on the lanes" : "These dates aren't on the lanes",
      description: listed === 1 ? "It's in the list below." : `All ${listed} are in the list below.`,
    };
  }
  // the lanes always show the whole year: "show past dates" wouldn't help here
  return { title: "Nothing on the lanes for these filters", description: emptyFilterHint({ ...f, showPast: true }) };
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
  /** entries of this month before today, folded away by {@link foldPast} */
  folded?: number;
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

/**
 * The groups from today on — for phones, where the list is part of the page and should start at
 * Today, not three months back. `hidden`: how many earlier entries were folded away.
 */
export function foldPast(groups: MonthGroup[]): { groups: MonthGroup[]; hidden: number } {
  let hidden = 0;
  const out: MonthGroup[] = [];
  for (const g of groups) {
    if (g.past) hidden += g.entries.length;
    else if (g.todayIndex) {
      hidden += g.todayIndex;
      out.push({ ...g, entries: g.entries.slice(g.todayIndex), todayIndex: 0, folded: g.todayIndex });
    } else out.push(g);
  }
  return { groups: out, hidden };
}

const norm = (s: string | null | undefined) => (s ?? "").trim().toLocaleLowerCase("en");
const wordsOf = (s: string) => new Set(norm(s).split(/[^\p{L}\p{N}]+/u).filter((w) => w.length > 2));

/**
 * Among `entries`, the one a lane marker on `date` points to. On that day: the same to-do or
 * contract (`ref`), else the same title, else the title that shares the largest part of its words
 * with the marker's label (never just any one word — "Monthly …" must not pick another monthly
 * bill). With nothing on that day: the next entry.
 */
export function entryForDate(entries: TimelineEntry[], date: string, label?: string | null, ref?: RefLink | null): TimelineEntry | null {
  const sorted = [...entries].sort(compareEntries);
  const same = sorted.filter((e) => e.date === date);
  if (!same.length) return sorted.find((e) => e.date >= date) ?? null;
  const byRef = ref ? same.find((e) => e.ref.type === ref.type && e.ref.id === ref.id) : undefined;
  if (byRef) return byRef;
  const want = norm(label);
  const exact = want ? same.find((e) => norm(e.title) === want) : undefined;
  if (exact || !want) return exact ?? same[0]!;
  const target = wordsOf(want);
  let best = same[0]!;
  let bestScore = 0;
  for (const e of same) {
    const own = wordsOf(e.title);
    const shared = [...own].filter((w) => target.has(w)).length;
    const score = shared / (own.size + target.size - shared || 1);
    if (score > bestScore) [best, bestScore] = [e, score];
  }
  return best;
}

// ------------------------------------------------------------------------------------------------
// The lanes under the list's filters
// ------------------------------------------------------------------------------------------------

/** A lane bar's or marker's own area and to-do/contract, where the server sends them. */
type Origin = { area?: Area | null; ref?: RefLink | null };

interface LaneFacts {
  types: ReadonlySet<TimelineType>;
  areas: ReadonlySet<Area>;
  parties: ReadonlySet<string>;
}

/** What the lanes are drawn from — to tell each bar's and marker's kind, area and person. */
export interface LaneSources {
  entries: TimelineEntry[];
  /** contracts by id: for a contract bar with no dated entry in the range */
  contracts?: ReadonlyMap<string, { area: Area; party: string | null }>;
  /** to-dos by id: for a bar whose date lies outside the range */
  items?: ReadonlyMap<string, { kind: TimelineType; area: Area; party: string | null }>;
}

const BAR_TYPE: Record<LaneBarKind, TimelineType | null> = { contract: "contract", notice_window: "contract", validity: "expiry", period: "deadline", event: null };
const MARKER_TYPE: Partial<Record<MarkerKind, TimelineType>> = { deadline: "deadline", payment: "payment", appointment: "appointment", expiry: "expiry" };
const refKey = (r: RefLink) => `${r.type}:${r.id}`;
/** The one lane that isn't an area (`views.py` LANE_ORDER): every contract, whatever its area. */
const MIXED_LANE = "contracts";

/**
 * The lanes with only the bars and markers that the list's kind, area and person filters let
 * through — each judged by the date it stands for, not by its lane (the Contracts lane holds
 * contracts of every area, the Money lane payments of every area). "Show past" doesn't apply: the
 * lanes always show the year. Lanes left empty are dropped.
 */
export function filterLanes(lanes: Lane[], f: TimelineFilters, src: LaneSources): Lane[] {
  if (!f.type && !f.area && !f.party) return lanes;
  // letters (received or sent) are records, never drawn on the lanes — even a bar that points to one
  if (f.type === "document" || f.type === "draft") return [];
  const byRef = new Map<string, TimelineEntry[]>();
  const byDay = new Map<string, TimelineEntry[]>();
  for (const e of src.entries) {
    byRef.set(refKey(e.ref), [...(byRef.get(refKey(e.ref)) ?? []), e]);
    byDay.set(e.date, [...(byDay.get(e.date) ?? []), e]);
  }
  const fromEntries = (list: TimelineEntry[] | undefined): LaneFacts | null =>
    list?.length
      ? {
          types: new Set(list.map((e) => e.type)),
          areas: new Set(list.map((e) => e.area)),
          parties: new Set(list.flatMap((e) => (e.party_name ? [e.party_name] : []))),
        }
      : null;
  const fromRef = (ref: RefLink | null | undefined): LaneFacts | null => {
    if (!ref) return null;
    const known = fromEntries(byRef.get(refKey(ref)));
    if (known) return known;
    const c = ref.type === "contract" ? src.contracts?.get(ref.id) : undefined;
    if (c) return { types: new Set(["contract"]), areas: new Set([c.area]), parties: new Set(c.party ? [c.party] : []) };
    const it = ref.type === "item" ? src.items?.get(ref.id) : undefined;
    if (it) return { types: new Set([it.kind]), areas: new Set([it.area]), parties: new Set(it.party ? [it.party] : []) };
    return null;
  };
  // the last resort: the mark's own kind, and its lane's area — unless that is the Contracts lane,
  // which holds contracts of every area (its `area` is "other")
  const guess = (lane: Lane, type: TimelineType | null | undefined, own: Origin): LaneFacts => ({
    types: new Set(type ? [type] : []),
    areas: new Set(own.area ? [own.area] : lane.id === MIXED_LANE ? [] : [lane.area]),
    parties: new Set(),
  });
  // a mark is also of its own kind: a validity bar is an expiry date even when it points to the letter
  const keep = (x: LaneFacts, kind: TimelineType | null | undefined) =>
    (!f.type || x.types.has(f.type) || kind === f.type) && (!f.area || x.areas.has(f.area)) && (!f.party || x.parties.has(f.party));

  return lanes.flatMap((lane) => {
    const bars = lane.bars.filter((bar) => keep(fromRef(bar.ref) ?? guess(lane, BAR_TYPE[bar.kind], bar as Origin), BAR_TYPE[bar.kind]));
    const markers = lane.markers.filter((m) => {
      const own = m as TimelineMarker & Origin;
      const facts = fromRef(own.ref) ?? fromEntries(byDay.get(m.date)?.filter((e) => norm(e.title) === norm(m.label))) ?? guess(lane, MARKER_TYPE[m.kind], own);
      return keep(facts, MARKER_TYPE[m.kind]);
    });
    return bars.length || markers.length ? [{ ...lane, bars, markers }] : [];
  });
}

/**
 * Open dates, as the calendar file holds them: to-dos and contract dates that aren't done,
 * dismissed or over (letters and sent letters are records, not dates to keep).
 */
export function openDateCount(entries: TimelineEntry[]): number {
  return entries.filter((e) => e.type !== "document" && e.type !== "draft" && !CLOSED.has(e.status ?? "")).length;
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

/** What the entry's date is, in a word or two: "Payment due", "Deadline", "Letter". */
export function entryRole(e: Pick<TimelineEntry, "type" | "status">): string {
  switch (e.type) {
    case "document":
      return "Letter";
    case "draft":
      return "You sent";
    case "payment":
      return CLOSED.has(e.status ?? "") ? "Payment" : "Payment due";
    default:
      return copyFor(TIMELINE_TYPE_COPY, e.type).label;
  }
}

/** A letter's summary often starts with its sender ("TechMarkt Online GmbH sent …"): drop that repeat. */
function withoutLeadingParty(sub: string, party: string): string {
  const lower = sub.toLocaleLowerCase("en");
  const name = party.toLocaleLowerCase("en");
  const lead = [name, `the ${name}`].find((p) => lower.startsWith(p) && !/[\p{L}\p{N}]/u.test(sub.charAt(p.length)));
  if (!lead) return sub;
  const rest = sub
    .slice(lead.length)
    .replace(/^\s*\([^)]*\)/, "") // "Muster BKK (statutory health insurer) informs …"
    .replace(/^[\s,:;–—-]+/, "");
  return rest ? rest.charAt(0).toLocaleUpperCase("en") + rest.slice(1) : "";
}

/** The entry's detail line (send channels mapped to words), without repeating the party. */
export function entryDetail(e: Pick<TimelineEntry, "party_name" | "subtitle">): string | null {
  let sub = e.subtitle?.trim() || null;
  if (sub && Object.prototype.hasOwnProperty.call(SEND_CHANNEL_COPY, sub)) sub = copyFor(SEND_CHANNEL_COPY, sub).label;
  if (sub && e.party_name) {
    if (sub === e.party_name || sub === `Letter from ${e.party_name}`) return null;
    sub = withoutLeadingParty(sub, e.party_name) || null;
  }
  return sub;
}

/** Second line of an entry: party and detail, without repeats. */
export function entryMeta(e: Pick<TimelineEntry, "party_name" | "subtitle" | "time" | "type">): string {
  return [e.party_name, entryDetail(e)].filter(Boolean).join(" · ");
}
