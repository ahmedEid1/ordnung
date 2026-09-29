/**
 * Layout of one life lane: which bars share a track, which track the lane's own markers get (never
 * one where they would cover a bar), where markers sit (and which ones merge), where direct labels
 * fit. Pure functions over a {@link TimeScale}; unit-tested in `layout.test.ts`.
 */
import type { Lane, LaneBar, LaneBarStatus, MarkerKind, RefLink, TimelineMarker } from "@/api/types";
import { formatDate } from "@/lib/format";
import { dayNumber, type TimeScale } from "./scale";

/** Visual constants shared by the layout and the component. */
export const LANE_METRICS = {
  /** bar thickness (dataviz: ≤ 24 px; a bar is a button, so a full 24 px target — WCAG 2.5.8) */
  barHeight: 24,
  /** vertical pitch of one track */
  trackHeight: 32,
  /** extra room under a track for direct marker labels (12 px text) */
  captionHeight: 16,
  /** padding above the first / below the last track */
  padY: 11,
  /**
   * Markers closer than this (px) merge into one mark (one tooltip listing every date), so no two
   * markers ever overlap and each keeps a 24 px hit target (WCAG 2.5.8).
   */
  markerGap: 24,
  /** horizontal padding inside a bar around its label */
  labelPad: 8,
  /** room kept free for a caption on either side of the today line (px, beyond its 2 px) */
  todayClear: 4,
  /** captions stay this far from the right edge of the plot (px) */
  captionInset: 8,
} as const;

/** Most important first — decides the shape/colour of a merged marker and caption priority. */
export const MARKER_PRIORITY: readonly MarkerKind[] = [
  "send_by",
  "deadline",
  "cancel_by",
  "expiry",
  "appointment",
  "payment",
  "renewal",
  "other",
];

/** Marker kinds that earn a direct label ("Send by 8 Oct") when upcoming. */
const CAPTION_KINDS = new Set<MarkerKind>(["send_by", "deadline", "cancel_by", "expiry"]);

const STATUS_RANK: Record<LaneBarStatus, number> = { urgent: 3, attention: 2, ok: 1, past: 0 };

export type TextMeasure = (text: string) => number;

/** Rough width of 12 px Inter text — used when no canvas is available (tests, SSR). */
export const approxTextWidth: TextMeasure = (text) => Math.ceil(text.length * 6.4);

// ------------------------------------------------------------------------------------------------
// Bars
// ------------------------------------------------------------------------------------------------

export interface BarBox {
  /** left edge in px (clamped to the plot) */
  x: number;
  /** width in px (≥ 3) */
  width: number;
  /** the bar starts before the visible range (or exactly at its first day — clipped by the API) */
  continuesBefore: boolean;
  /** the bar ends after the visible range (or exactly on its last day) */
  continuesAfter: boolean;
}

/** Pixel box of a bar, clipped to the plot; `null` when it lies completely outside. */
export function barBox(bar: Pick<LaneBar, "start" | "end">, scale: TimeScale): BarBox | null {
  let s = dayNumber(bar.start);
  let e = dayNumber(bar.end);
  if (e < s) [s, e] = [e, s];
  const d0 = dayNumber(scale.from);
  const d1 = dayNumber(scale.to);
  if (e < d0 || s > d1) return null;
  const x0 = (Math.max(s, d0) - d0) * scale.pxPerDay;
  const x1 = (Math.min(e, d1) - d0 + 1) * scale.pxPerDay;
  return {
    x: x0,
    width: Math.max(3, x1 - x0),
    continuesBefore: s <= d0,
    continuesAfter: e >= d1,
  };
}

export interface PlacedBar extends BarBox {
  key: string;
  bar: LaneBar;
  track: number;
  /** a notice window drawn on top of the term bar of the same contract/document */
  overlay: boolean;
  /** how the label is shown: inside the bar, just after its end, or only in the tooltip */
  labelMode: "inside" | "after" | "none";
  /** px from the bar's left edge where an inside label starts (clear of leading markers) */
  labelStart: number;
  /** max width of an inside label (truncated with an ellipsis), null = full text fits */
  labelMax: number | null;
  /** free room (px) for an inside label — a sticky label may slide within it, never onto markers */
  labelRoom: number;
  /** x (px) of an "after" label */
  afterX: number;
}

const refKey = (ref: RefLink | null | undefined) => (ref ? `${ref.type}:${ref.id}` : null);

export interface Interval {
  s: number;
  e: number;
}

const overlaps = (a: Interval, b: Interval) => a.s <= b.e && b.s <= a.e;
/** Pixel extents overlap when they share more than an edge. */
const pxOverlaps = (a: Interval, b: Interval) => a.s < b.e && b.s < a.e;

/** Half a marker's hit target: a marker takes up its centre ± this (px). */
const HALF_HIT = LANE_METRICS.markerGap / 2;

/**
 * Whether a lane's own marker is a date of `bar`: of the very contract or to-do the bar stands for (the
 * same `ref`), dated within it. It then rides on the bar like the bar's own markers ({@link packLane}).
 */
function ridesOn(m: TimelineMarker, bar: LaneBar): boolean {
  const ref = refKey(m.ref);
  if (!ref || !m.date || ref !== refKey(bar.ref)) return false;
  const [first, last] = bar.start <= bar.end ? [bar.start, bar.end] : [bar.end, bar.start];
  return first <= m.date && m.date <= last;
}

/**
 * What a bar takes up on its track (px): the button as `BarMark` draws it (1 px in from each side of
 * its box), widened to the hit targets of its markers — its own, and the lane's markers that ride on it
 * ({@link ridesOn}): a marker at the bar's end reaches past it.
 */
function barFootprint(bar: LaneBar, box: BarBox, scale: TimeScale, riders: readonly TimelineMarker[]): Interval {
  let s = box.x + 1;
  let e = box.x + 1 + Math.max(3, box.width - 2);
  for (const m of [...bar.markers, ...riders.filter((r) => ridesOn(r, bar))]) {
    if (!m.date || !scale.contains(m.date)) continue;
    const x = scale.mid(m.date);
    s = Math.min(s, x - HALF_HIT);
    e = Math.max(e, x + HALF_HIT);
  }
  return { s, e };
}

/** What a track already holds: each bar's days, its footprint (px), what it stands for, and whether it rides on another bar. */
interface Slot {
  days: Interval;
  px: Interval;
  ref: string | null;
  overlay: boolean;
}

/**
 * Whether a bar clashes with what a track already holds. Bars of the same contract or to-do only when
 * their days overlap: a term and what follows it meet at the marker between them, on one row. Anything
 * else as soon as the bars or their markers' hit targets would touch — never a mark of one thing drawn
 * over another thing's bar. A bar riding on its host (a notice window) blocks by its footprint only.
 */
function clashes(o: Slot, c: Omit<Slot, "overlay">): boolean {
  if (o.ref !== null && o.ref === c.ref) return !o.overlay && overlaps(o.days, c.days);
  return pxOverlaps(o.px, c.px) || (!o.overlay && overlaps(o.days, c.days));
}

/**
 * Assign bars to tracks (rows inside a lane):
 * - term/validity/period bars go to the first track where they clash with nothing ({@link clashes});
 * - a notice window rides on the track of the bar with the same `ref` that covers it (it is drawn
 *   hatched on top of that bar); one that no bar of its contract covers still goes on that
 *   contract's track when there is room, otherwise it gets a free track like any other bar.
 */
export type PackedBar = Omit<PlacedBar, "labelMode" | "labelStart" | "labelMax" | "labelRoom" | "afterX">;

export function packBars(bars: LaneBar[], scale: TimeScale): { placed: PackedBar[]; tracks: number } {
  const { placed, rows } = packBarRows(bars, scale);
  return { placed, tracks: rows.length };
}

/** {@link packBars}, with what each track holds; `riders`: the lane's own markers (some ride on bars). */
function packBarRows(bars: LaneBar[], scale: TimeScale, riders: readonly TimelineMarker[] = []): { placed: PackedBar[]; rows: Slot[][] } {
  const visible = bars
    .map((bar, i) => ({ bar, i, box: barBox(bar, scale) }))
    .filter((b): b is { bar: LaneBar; i: number; box: BarBox } => b.box !== null);
  const base = visible.filter((b) => b.bar.kind !== "notice_window").sort((a, b) => a.bar.start.localeCompare(b.bar.start) || a.i - b.i);
  const windows = visible.filter((b) => b.bar.kind === "notice_window").sort((a, b) => a.bar.start.localeCompare(b.bar.start) || a.i - b.i);

  const rows: Slot[][] = [];
  const hosts: { track: number; ref: string | null; iv: Interval }[] = [];
  const placed: PackedBar[] = [];

  const slotOf = (bar: LaneBar, box: BarBox): Omit<Slot, "overlay"> => {
    const a = dayNumber(bar.start);
    const b = dayNumber(bar.end);
    return { days: { s: Math.min(a, b), e: Math.max(a, b) }, px: barFootprint(bar, box, scale, riders), ref: refKey(bar.ref) };
  };
  const fits = (track: number, c: Omit<Slot, "overlay">) => !rows[track]!.some((o) => clashes(o, c));
  const freeTrack = (c: Omit<Slot, "overlay">) => {
    let t = rows.findIndex((_, track) => fits(track, c));
    if (t < 0) {
      t = rows.length;
      rows.push([]);
    }
    return t;
  };

  for (const { bar, i, box } of base) {
    const slot = slotOf(bar, box);
    const track = freeTrack(slot);
    rows[track]!.push({ ...slot, overlay: false });
    hosts.push({ track, ref: slot.ref, iv: slot.days });
    placed.push({ key: `${bar.id}#${i}`, bar, track, overlay: false, ...box });
  }

  for (const { bar, i, box } of windows) {
    const slot = slotOf(bar, box);
    const { ref, days } = slot;
    // on a term bar of its own contract that it overlaps, next to no other window there, and
    // clear of every other thing's bar on that row
    const host = ref
      ? hosts.find(
          (h) =>
            h.ref === ref &&
            overlaps(h.iv, days) &&
            !rows[h.track]!.some((o) => (o.ref === ref ? o.overlay && overlaps(o.days, days) : clashes(o, slot))),
        )
      : undefined;
    // a window after the drawn term (e.g. next year's) still stays on its own contract's row
    const sameRow = !host && ref ? hosts.find((h) => h.ref === ref && fits(h.track, slot)) : undefined;
    if (host) {
      rows[host.track]!.push({ ...slot, overlay: true });
      placed.push({ key: `${bar.id}#${i}`, bar, track: host.track, overlay: true, ...box });
    } else {
      const track = sameRow ? sameRow.track : freeTrack(slot);
      rows[track]!.push({ ...slot, overlay: false });
      placed.push({ key: `${bar.id}#${i}`, bar, track, overlay: false, ...box });
    }
  }

  placed.sort((a, b) => a.track - b.track || Number(a.overlay) - Number(b.overlay) || a.x - b.x);
  return { placed, rows };
}

export interface PackedLane {
  placed: PackedBar[];
  /** the track of each of the lane's own markers, by its index in `lane.markers` (0 for one not drawn) */
  markerTracks: number[];
  /** number of tracks: bars' rows and the rows their neighbouring markers needed */
  tracks: number;
}

/**
 * Tracks for a whole lane: its bars ({@link packBars}), then its own markers — the to-dos and
 * payments of a life area, which stand for other things than its bars.
 *
 * - A marker of the very contract or to-do a bar stands for (the same `ref`), dated within that bar,
 *   is that bar's date: it sits on the bar, like the bar's own markers (the earliest end of a
 *   contract on the Contracts page).
 * - Any other marker never lands on a bar: it goes to the first track where its 24 px hit target
 *   touches no bar and no bar's marker, else to a new track below. So an appointment never covers
 *   the permit bar it happens to fall on, and a to-do's mark never merges with a bar's date.
 * - Markers closer than the marker gap merge into one mark ({@link placeMarkers}): they are placed
 *   as one run, on one track, so a merged mark is never split over two rows.
 * - A marker with no date, or one outside the range, isn't drawn and takes no room.
 */
export function packLane(lane: Pick<Lane, "bars" | "markers">, scale: TimeScale): PackedLane {
  const { placed, rows } = packBarRows(lane.bars, scale, lane.markers);
  // what each track holds, in px: its bars with their markers' hit targets (riders included)
  const taken: Interval[][] = rows.map((row) => row.map((s) => s.px));
  const markerTracks = lane.markers.map(() => 0);

  const loose: { i: number; x: number }[] = [];
  lane.markers.forEach((m, i) => {
    if (!m.date || !scale.contains(m.date)) return;
    // on its bar (the term bar rather than a notice window riding on it: the same row either way)
    const own = placed.filter((p) => ridesOn(m, p.bar)).sort((a, b) => Number(a.overlay) - Number(b.overlay))[0];
    if (own) markerTracks[i] = own.track;
    else loose.push({ i, x: scale.mid(m.date) });
  });

  loose.sort((a, b) => a.x - b.x || a.i - b.i);
  const runs: { i: number[]; first: number; last: number }[] = [];
  for (const m of loose) {
    const run = runs[runs.length - 1];
    if (run && m.x - run.last < LANE_METRICS.markerGap) {
      run.i.push(m.i);
      run.last = m.x;
    } else runs.push({ i: [m.i], first: m.x, last: m.x });
  }
  for (const run of runs) {
    const iv = { s: run.first - HALF_HIT, e: run.last + HALF_HIT };
    let t = taken.findIndex((row) => !row.some((o) => pxOverlaps(o, iv)));
    if (t < 0) {
      t = taken.length;
      taken.push([]);
    }
    taken[t]!.push(iv);
    for (const i of run.i) markerTracks[i] = t;
  }
  return { placed, markerTracks, tracks: taken.length };
}

/** The free stretches of `[lo, hi]` once the `blocked` intervals are taken out (left to right). */
export function freeSegments(lo: number, hi: number, blocked: Interval[]): Interval[] {
  const out: Interval[] = [];
  let s = lo;
  for (const b of [...blocked].sort((a, c) => a.s - c.s)) {
    if (b.e <= s) continue;
    if (b.s >= hi) break;
    if (b.s > s) out.push({ s, e: b.s });
    s = Math.max(s, b.e);
  }
  if (hi > s) out.push({ s, e: hi });
  return out;
}

/**
 * Decide where each bar's label goes, keeping clear of the markers on the bar and of a
 * notice-window overlay: inside, in the first free stretch between markers where the whole label
 * fits; else truncated (the tooltip carries the full text) in the widest free stretch when that
 * still has decent room; else right after the bar end when there is room before the next bar or
 * marker and the plot edge; else only in the tooltip. Notice windows are never truncated.
 */
export function placeBarLabels(
  placed: PackedBar[],
  scale: TimeScale,
  measure: TextMeasure = approxTextWidth,
  markers: Pick<PlacedMarker, "x" | "track">[] = [],
): PlacedBar[] {
  const pad = LANE_METRICS.labelPad;
  const clear = 9; // px kept free on either side of a marker centre
  return placed.map((p) => {
    const text = p.bar.label;
    const textW = measure(text);
    const x0 = p.x;
    const x1 = p.x + p.width;
    const onBar = markers.filter((m) => m.track === p.track && m.x > x0 - clear && m.x < x1 + clear).map((m) => m.x);
    // a faded (continuing) end keeps the label out of the fade
    const lo = x0 + (p.continuesBefore ? 20 : pad);
    const hi = x1 - (p.continuesAfter ? 20 : pad);
    const blocked: Interval[] = onBar.map((mx) => ({ s: mx - clear, e: mx + clear + 2 }));
    if (!p.overlay) {
      for (const o of placed) if (o.overlay && o.track === p.track && o.x < x1 && o.x + o.width > x0) blocked.push({ s: o.x - 4, e: o.x + o.width + 4 });
    }
    const segments = freeSegments(lo, hi, blocked);
    const chip = p.bar.kind === "notice_window" ? 12 : 0;
    const fitting = segments.find((s) => s.e - s.s >= textW + chip);
    const widest = segments.reduce<Interval | null>((best, s) => (!best || s.e - s.s > best.e - best.s ? s : best), null);
    const seg = fitting ?? widest;
    const room = seg ? seg.e - seg.s : 0;
    const base = {
      ...p,
      labelStart: seg ? Math.round(seg.s - x0) : pad,
      labelMax: null as number | null,
      labelRoom: Math.max(0, Math.floor(room)),
      afterX: 0,
    };
    if (fitting) return { ...base, labelMode: "inside" as const };
    if (!chip && !p.overlay && room >= 64) return { ...base, labelMode: "inside" as const, labelMax: Math.floor(room) };
    if (p.overlay) return { ...base, labelMode: "none" as const };
    const endMarker = onBar.some((mx) => Math.abs(x1 - mx) < 12);
    const afterX = x1 + (endMarker ? 14 : 8);
    const next = placed
      .filter((o) => o !== p && o.track === p.track && !o.overlay && o.x >= x1 - 1)
      .reduce((min, o) => Math.min(min, o.x), scale.width - LANE_METRICS.captionInset);
    const nextMarker = markers.filter((m) => m.track === p.track && m.x > afterX).reduce((min, m) => Math.min(min, m.x - clear), Infinity);
    const fits = textW <= Math.min(next, nextMarker) - afterX - 4 && !p.continuesAfter;
    return { ...base, afterX, labelMode: fits ? ("after" as const) : ("none" as const) };
  });
}

// ------------------------------------------------------------------------------------------------
// Markers
// ------------------------------------------------------------------------------------------------

export interface MarkerEntry {
  marker: TimelineMarker;
  /** the bar the marker belongs to (null for lane-level markers) */
  bar: LaneBar | null;
  past: boolean;
}

export interface PlacedMarker {
  key: string;
  track: number;
  /** centre x in px */
  x: number;
  date: string;
  /** the most important marker of the cluster (shape, colour, click target) */
  primary: MarkerEntry;
  /** every marker merged into this one, most important first */
  entries: MarkerEntry[];
  /** width (px) of the click/hover target: `markerGap` (24 px) — neighbours are at least that far apart */
  hitWidth: number;
}

export function markerRank(kind: MarkerKind): number {
  const i = MARKER_PRIORITY.indexOf(kind);
  return i < 0 ? MARKER_PRIORITY.length : i;
}

/** Sort key: upcoming before past, then by kind priority, then by date. */
function compareEntries(a: MarkerEntry, b: MarkerEntry): number {
  return Number(a.past) - Number(b.past) || markerRank(a.marker.kind) - markerRank(b.marker.kind) || a.marker.date.localeCompare(b.marker.date);
}

/**
 * Put markers on their track (a bar's markers on the bar's track, lane markers on the track
 * {@link packLane} gave them — track 0 when `laneTracks` is left out) and merge markers that would
 * sit closer than `minGap` (24 px) into one mark: it is drawn at its most important entry's date, and
 * its tooltip and accessible name list every date. So markers never cover each other and every mark
 * keeps a full 24 px hit target.
 */
export function placeMarkers(
  lane: Pick<Lane, "id" | "markers">,
  bars: Pick<PackedBar, "bar" | "track">[],
  scale: TimeScale,
  today: string,
  { laneTracks = [], minGap = LANE_METRICS.markerGap }: { laneTracks?: readonly number[]; minGap?: number } = {},
): PlacedMarker[] {
  const todayN = dayNumber(today);
  const raw: { entry: MarkerEntry; track: number; x: number }[] = [];
  const push = (marker: TimelineMarker, bar: LaneBar | null, track: number) => {
    if (!marker.date || !scale.contains(marker.date)) return;
    raw.push({ entry: { marker, bar, past: dayNumber(marker.date) < todayN }, track, x: scale.mid(marker.date) });
  };
  for (const p of bars) for (const m of p.bar.markers) push(m, p.bar, p.track);
  lane.markers.forEach((m, i) => push(m, null, laneTracks[i] ?? 0));

  interface Group {
    items: typeof raw;
    entries: MarkerEntry[];
    x: number;
  }
  const group = (items: typeof raw): Group => {
    const entries = items.map((c) => c.entry).sort(compareEntries);
    return { items, entries, x: items.find((c) => c.entry === entries[0])!.x };
  };

  const out: PlacedMarker[] = [];
  const byTrack = new Map<number, typeof raw>();
  for (const r of raw) byTrack.set(r.track, [...(byTrack.get(r.track) ?? []), r]);
  for (const [track, list] of [...byTrack.entries()].sort((a, b) => a[0] - b[0])) {
    list.sort((a, b) => a.x - b.x || compareEntries(a.entry, b.entry));
    let groups = list.map((r) => group([r]));
    // merge the closest pair of neighbours until every mark is at least `minGap` from the next
    for (;;) {
      groups.sort((a, b) => a.x - b.x);
      let at = -1;
      for (let i = 0; i + 1 < groups.length; i++) {
        const gap = groups[i + 1]!.x - groups[i]!.x;
        if (gap < minGap && (at < 0 || gap < groups[at + 1]!.x - groups[at]!.x)) at = i;
      }
      if (at < 0) break;
      const merged = group([...groups[at]!.items, ...groups[at + 1]!.items]);
      groups = [...groups.slice(0, at), merged, ...groups.slice(at + 2)];
    }
    for (const g of groups) {
      const primary = g.entries[0]!;
      out.push({
        key: `${lane.id}:${track}:${primary.marker.date}:${out.length}`,
        track,
        x: g.x,
        date: primary.marker.date,
        primary,
        entries: g.entries,
        hitWidth: minGap,
      });
    }
  }
  out.sort((a, b) => a.track - b.track || a.x - b.x);
  return out;
}

// ------------------------------------------------------------------------------------------------
// Direct labels under markers
// ------------------------------------------------------------------------------------------------

/** Short caption for a marker: "Send by 8 Oct", "Apply before 30 Nov", "Expires 10 Feb". */
export function markerCaption(marker: TimelineMarker, today?: string): string {
  const date = formatDate(marker.date, { style: "day", today });
  const cleaned = marker.label
    .replace(/\s*\([^)]*\)\s*/g, " ")
    .replace(/\s+this date\b/i, "")
    .replace(/\s+/g, " ")
    .trim();
  switch (marker.kind) {
    case "send_by":
      return `Send by ${date}`;
    case "cancel_by":
      return /arrive/i.test(cleaned) ? `Must arrive by ${date}` : `Cancel by ${date}`;
    case "expiry":
      return cleaned && cleaned.length <= 18 && !/^expires$/i.test(cleaned) ? `${cleaned} ${date}` : `Expires ${date}`;
    default:
      return cleaned && cleaned.length <= 20 ? `${cleaned} ${date}` : `Due ${date}`;
  }
}

export interface PlacedCaption {
  key: string;
  track: number;
  /** left edge in px */
  x: number;
  width: number;
  text: string;
  markerKey: string;
}

/**
 * Greedy, collision-free direct labels: upcoming send-by / deadline / must-arrive / expiry
 * markers (most important first) get a caption under the marker when it doesn't overlap
 * an already placed caption on the same track. Captions stay inside the plot (with a small inset
 * on the right) and clear of the today line. Everything else relies on the tooltip.
 */
export function placeCaptions(
  markers: PlacedMarker[],
  scale: TimeScale,
  today: string,
  measure: TextMeasure = approxTextWidth,
  opts: { maxPerTrack?: number; gap?: number } = {},
): PlacedCaption[] {
  const gap = opts.gap ?? 10;
  const maxPerTrack = opts.maxPerTrack ?? 3;
  const { todayClear, captionInset } = LANE_METRICS;
  const todayX = scale.contains(today) ? scale.mid(today) : null;
  const maxX = (width: number) => Math.max(0, scale.width - captionInset - width);
  const candidates = markers
    .filter((m) => !m.primary.past && CAPTION_KINDS.has(m.primary.marker.kind))
    .sort((a, b) => compareEntries(a.primary, b.primary) || a.x - b.x);
  const placed: PlacedCaption[] = [];
  for (const m of candidates) {
    if (placed.filter((p) => p.track === m.track).length >= maxPerTrack) continue;
    const text = markerCaption(m.primary.marker, today);
    const width = measure(text) + 4;
    // start just left of the marker and run to the right (away from the today line)
    let x = Math.max(0, Math.min(maxX(width), m.x - 6));
    // the today line (2 px wide) never cuts through a caption: move it to the marker's side of the line
    if (todayX !== null && x < todayX + 1 + todayClear && x + width > todayX - 1 - todayClear) {
      x = m.x >= todayX ? todayX + 1 + todayClear : todayX - 1 - todayClear - width;
      x = Math.max(0, Math.min(maxX(width), x));
    }
    const clash = placed.some((p) => p.track === m.track && x < p.x + p.width + gap && p.x < x + width + gap);
    if (!clash) placed.push({ key: `cap:${m.key}`, track: m.track, x, width, text, markerKey: m.key });
  }
  return placed.sort((a, b) => a.track - b.track || a.x - b.x);
}

// ------------------------------------------------------------------------------------------------
// Whole lane
// ------------------------------------------------------------------------------------------------

export interface LaneLayout {
  lane: Lane;
  /** number of tracks (≥ 1; a lane with only markers has one "rail" track) */
  tracks: number;
  bars: PlacedBar[];
  markers: PlacedMarker[];
  captions: PlacedCaption[];
  /** y offset (px) of each track's bar centre, relative to the lane top */
  trackY: number[];
  /** total lane height in px */
  height: number;
  /** true when the lane has no bars (markers sit on a hairline rail) */
  rail: boolean;
  /** tracks with no bar on them — markers only, drawn on a hairline rail (the lane's only track when it has no bars) */
  rails: number[];
}

/** Full layout of one lane (tracks, markers, captions, heights). */
export function layoutLane(
  lane: Lane,
  scale: TimeScale,
  today: string,
  opts: { measure?: TextMeasure; measureCaption?: TextMeasure; minHeight?: number; captions?: boolean } = {},
): LaneLayout {
  const measure = opts.measure ?? approxTextWidth;
  const measureCaption = opts.measureCaption ?? measure;
  const packed = packLane(lane, scale);
  const markers = placeMarkers(lane, packed.placed, scale, today, { laneTracks: packed.markerTracks });
  const bars = placeBarLabels(packed.placed, scale, measure, markers);
  const tracks = Math.max(1, packed.tracks);
  const rails = Array.from({ length: tracks }, (_, t) => t).filter((t) => !bars.some((b) => b.track === t));
  const captions = opts.captions === false ? [] : placeCaptions(markers, scale, today, measureCaption);
  const M = LANE_METRICS;
  const trackY: number[] = [];
  let y = M.padY;
  for (let t = 0; t < tracks; t++) {
    trackY.push(y + M.barHeight / 2);
    y += M.trackHeight;
    if (captions.some((c) => c.track === t)) y += M.captionHeight;
  }
  const height = Math.max(opts.minHeight ?? 0, y - (M.trackHeight - M.barHeight) + M.padY);
  return { lane, tracks, bars, markers, captions, trackY, height, rail: bars.length === 0, rails };
}

// ------------------------------------------------------------------------------------------------
// Summaries (label column, screen readers)
// ------------------------------------------------------------------------------------------------

/** The most urgent status among a lane's bars that are not in the past (null when none). */
export function laneStatus(lane: Pick<Lane, "bars">): LaneBarStatus | null {
  let best: LaneBarStatus | null = null;
  for (const b of lane.bars) {
    if (b.status === "past") continue;
    if (!best || STATUS_RANK[b.status] > STATUS_RANK[best]) best = b.status;
  }
  return best;
}

export interface NextDate {
  date: string;
  kind: MarkerKind;
  /** "Send by", "Expires", "Rent"… */
  label: string;
}

/** Bar kinds whose end is a real date to know about ("Ends 31 Mar 2027", "Valid until 10 Feb"). */
const ENDING_BARS: Record<string, string> = { validity: "Valid until", period: "Runs until", contract: "Ends" };

/**
 * The next thing on a lane from `today` on: the earliest upcoming marker (ties → most important
 * kind). Renewals are skipped — a contract that simply runs on asks nothing of you, while the
 * send-by date before it does. With no marker ahead, the end of a bar that is running now: a
 * permit's validity, a fixed-term contract, a period ("Ends 31 Mar 2027") — never an open end,
 * a bar that renews, or an end the chart only cut off (at or after `opts.to`).
 */
export function nextOnLane(lane: Pick<Lane, "bars" | "markers">, today: string, opts: { to?: string } = {}): NextDate | null {
  const t = dayNumber(today);
  const all = [...lane.markers, ...lane.bars.flatMap((b) => b.markers)].filter((m) => m.date && m.kind !== "renewal" && dayNumber(m.date) >= t);
  all.sort((a, b) => a.date.localeCompare(b.date) || markerRank(a.kind) - markerRank(b.kind));
  const m = all[0];
  if (m) return { date: m.date, kind: m.kind, label: shortMarkerLabel(m) };
  const running = lane.bars
    .filter(
      (b) =>
        b.kind in ENDING_BARS &&
        !b.open_end &&
        !b.markers.some((mk) => mk.kind === "renewal") &&
        dayNumber(b.start) <= t &&
        dayNumber(b.end) >= t &&
        (!opts.to || b.end < opts.to),
    )
    .sort((a, b) => a.end.localeCompare(b.end))[0];
  return running ? { date: running.end, kind: running.kind === "validity" ? "expiry" : "other", label: ENDING_BARS[running.kind]! } : null;
}

/** Marker label without legal citations (the label column truncates it, the tooltip has it all). */
export function shortMarkerLabel(m: TimelineMarker): string {
  if (m.kind === "send_by") return "Send by";
  const cleaned = m.label.replace(/\s*\([^)]*\)\s*/g, " ").replace(/\s+this date\b/i, "").replace(/\s+/g, " ").trim();
  if (!cleaned) return m.kind === "expiry" ? "Expires" : "Date";
  return cleaned;
}
