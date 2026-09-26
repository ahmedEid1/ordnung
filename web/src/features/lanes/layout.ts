/**
 * Layout of one life lane: which bars share a track, where markers sit (and which ones merge),
 * where direct labels fit. Pure functions over a {@link TimeScale}; unit-tested in `layout.test.ts`.
 */
import type { Lane, LaneBar, LaneBarStatus, MarkerKind, RefLink, TimelineMarker } from "@/api/types";
import { formatDate } from "@/lib/format";
import { dayNumber, type TimeScale } from "./scale";

/** Visual constants shared by the layout and the component. */
export const LANE_METRICS = {
  /** bar thickness (dataviz: ≤ 24 px) */
  barHeight: 22,
  /** vertical pitch of one track */
  trackHeight: 30,
  /** extra room under a track for direct marker labels */
  captionHeight: 15,
  /** padding above the first / below the last track */
  padY: 11,
  /** markers closer than this (px) merge into one cluster */
  clusterPx: 7,
  /** horizontal padding inside a bar around its label */
  labelPad: 8,
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

interface Interval {
  s: number;
  e: number;
}

const overlaps = (a: Interval, b: Interval) => a.s <= b.e && b.s <= a.e;

/**
 * Assign bars to tracks (rows inside a lane):
 * - term/validity/period bars go to the first track where they don't overlap another bar;
 * - a notice window rides on the track of the bar with the same `ref` that covers it (it is drawn
 *   hatched on top of that bar); one that no bar of its contract covers still goes on that
 *   contract's track when there is room, otherwise it gets a free track like any other bar.
 */
export type PackedBar = Omit<PlacedBar, "labelMode" | "labelStart" | "labelMax" | "labelRoom" | "afterX">;

export function packBars(bars: LaneBar[], scale: TimeScale): { placed: PackedBar[]; tracks: number } {
  const visible = bars
    .map((bar, i) => ({ bar, i, box: barBox(bar, scale) }))
    .filter((b): b is { bar: LaneBar; i: number; box: BarBox } => b.box !== null);
  const base = visible.filter((b) => b.bar.kind !== "notice_window").sort((a, b) => a.bar.start.localeCompare(b.bar.start) || a.i - b.i);
  const windows = visible.filter((b) => b.bar.kind === "notice_window").sort((a, b) => a.bar.start.localeCompare(b.bar.start) || a.i - b.i);

  const occupied: Interval[][] = [];
  const overlays: Interval[][] = [];
  const hosts: { track: number; ref: string | null; iv: Interval }[] = [];
  const placed: PackedBar[] = [];

  const interval = (bar: LaneBar): Interval => {
    const a = dayNumber(bar.start);
    const b = dayNumber(bar.end);
    return { s: Math.min(a, b), e: Math.max(a, b) };
  };
  const freeTrack = (iv: Interval) => {
    let t = occupied.findIndex((row) => !row.some((o) => overlaps(o, iv)));
    if (t < 0) {
      t = occupied.length;
      occupied.push([]);
      overlays.push([]);
    }
    return t;
  };

  for (const { bar, i, box } of base) {
    const iv = interval(bar);
    const track = freeTrack(iv);
    occupied[track]!.push(iv);
    hosts.push({ track, ref: refKey(bar.ref), iv });
    placed.push({ key: `${bar.id}#${i}`, bar, track, overlay: false, ...box });
  }

  for (const { bar, i, box } of windows) {
    const iv = interval(bar);
    const ref = refKey(bar.ref);
    const host = ref
      ? hosts.find((h) => h.ref === ref && overlaps(h.iv, iv) && !overlays[h.track]!.some((o) => overlaps(o, iv)))
      : undefined;
    // a window after the drawn term (e.g. next year's) still stays on its own contract's row
    const sameRow = !host && ref ? hosts.find((h) => h.ref === ref && !occupied[h.track]!.some((o) => overlaps(o, iv))) : undefined;
    if (host) {
      overlays[host.track]!.push(iv);
      placed.push({ key: `${bar.id}#${i}`, bar, track: host.track, overlay: true, ...box });
    } else if (sameRow) {
      occupied[sameRow.track]!.push(iv);
      placed.push({ key: `${bar.id}#${i}`, bar, track: sameRow.track, overlay: false, ...box });
    } else {
      const track = freeTrack(iv);
      occupied[track]!.push(iv);
      placed.push({ key: `${bar.id}#${i}`, bar, track, overlay: false, ...box });
    }
  }

  placed.sort((a, b) => a.track - b.track || Number(a.overlay) - Number(b.overlay) || a.x - b.x);
  return { placed, tracks: Math.max(occupied.length, 0) };
}

/**
 * Decide where each bar's label goes, keeping clear of markers on the bar and of a notice-window
 * overlay: inside when it fits (truncated with an ellipsis when there is still decent room —
 * the tooltip carries the full text), else right after the bar end when there is room before
 * the next bar on the track, else only in the tooltip. Notice windows are never truncated.
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
    const onBar = markers.filter((m) => m.track === p.track && m.x > x0 - 2 && m.x < x1 + 2).map((m) => m.x);
    // markers hugging the start push the label to the right
    const leading = onBar.filter((mx) => mx - x0 < 18);
    const baseStart = p.continuesBefore ? 20 : pad;
    const labelStart = leading.length ? Math.max(baseStart, Math.max(...leading) - x0 + clear + 2) : baseStart;
    let limit = x1 - pad;
    for (const mx of onBar) if (mx - x0 >= 18 && mx - clear < limit) limit = mx - clear;
    if (!p.overlay) {
      for (const o of placed) if (o.overlay && o.track === p.track && o.x >= x0 && o.x < x1) limit = Math.min(limit, o.x - 4);
    }
    const chip = p.bar.kind === "notice_window" ? 12 : 0;
    const room = limit - x0 - labelStart;
    const base = { ...p, labelStart, labelMax: null as number | null, labelRoom: Math.max(0, Math.floor(room)), afterX: 0 };
    if (textW + chip <= room) return { ...base, labelMode: "inside" as const };
    if (!chip && !p.overlay && room >= 64) return { ...base, labelMode: "inside" as const, labelMax: Math.floor(room) };
    if (p.overlay) return { ...base, labelMode: "none" as const };
    const endMarker = onBar.some((mx) => x1 - mx < 12);
    const afterX = x1 + (endMarker ? 14 : 8);
    const next = placed
      .filter((o) => o !== p && o.track === p.track && !o.overlay && o.x >= x1 - 1)
      .reduce((min, o) => Math.min(min, o.x), scale.width);
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
  /** width (px) of the click/hover target: 24 px, narrowed so neighbours never overlap (≥ 12 px) */
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
 * Put markers on their track (a bar's markers on the bar's track, lane markers on track 0) and
 * merge markers that would overlap (closer than `clusterPx`) into one cluster.
 */
export function placeMarkers(
  lane: Pick<Lane, "id" | "markers">,
  bars: Pick<PackedBar, "bar" | "track">[],
  scale: TimeScale,
  today: string,
  clusterPx: number = LANE_METRICS.clusterPx,
): PlacedMarker[] {
  const todayN = dayNumber(today);
  const raw: { entry: MarkerEntry; track: number; x: number }[] = [];
  const push = (marker: TimelineMarker, bar: LaneBar | null, track: number) => {
    if (!marker.date || !scale.contains(marker.date)) return;
    raw.push({ entry: { marker, bar, past: dayNumber(marker.date) < todayN }, track, x: scale.mid(marker.date) });
  };
  for (const p of bars) for (const m of p.bar.markers) push(m, p.bar, p.track);
  for (const m of lane.markers) push(m, null, 0);

  const out: PlacedMarker[] = [];
  const byTrack = new Map<number, typeof raw>();
  for (const r of raw) byTrack.set(r.track, [...(byTrack.get(r.track) ?? []), r]);
  for (const [track, list] of [...byTrack.entries()].sort((a, b) => a[0] - b[0])) {
    list.sort((a, b) => a.x - b.x || compareEntries(a.entry, b.entry));
    let cluster: typeof raw = [];
    const flush = () => {
      if (!cluster.length) return;
      const entries = cluster.map((c) => c.entry).sort(compareEntries);
      const primary = entries[0]!;
      const anchor = cluster.find((c) => c.entry === primary)!;
      out.push({
        key: `${lane.id}:${track}:${anchor.entry.marker.date}:${out.length}`,
        track,
        x: anchor.x,
        date: primary.marker.date,
        primary,
        entries,
        hitWidth: 24,
      });
      cluster = [];
    };
    for (const r of list) {
      if (cluster.length && r.x - cluster[0]!.x >= clusterPx) flush();
      cluster.push(r);
    }
    flush();
  }
  out.sort((a, b) => a.track - b.track || a.x - b.x);
  // narrow the hit targets of close neighbours so hovering one never triggers the other
  for (let i = 0; i < out.length; i++) {
    const m = out[i]!;
    const prev = out[i - 1]?.track === m.track ? out[i - 1]!.x : -Infinity;
    const next = out[i + 1]?.track === m.track ? out[i + 1]!.x : Infinity;
    const room = Math.min(m.x - prev, next - m.x);
    m.hitWidth = Math.max(12, Math.min(24, Math.floor(room)));
  }
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
 * an already placed caption on the same track. Everything else relies on the tooltip.
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
  const candidates = markers
    .filter((m) => !m.primary.past && CAPTION_KINDS.has(m.primary.marker.kind))
    .sort((a, b) => compareEntries(a.primary, b.primary) || a.x - b.x);
  const placed: PlacedCaption[] = [];
  for (const m of candidates) {
    if (placed.filter((p) => p.track === m.track).length >= maxPerTrack) continue;
    const text = markerCaption(m.primary.marker, today);
    const width = measure(text) + 4;
    // start just left of the marker and run to the right (away from the today line)
    const x = Math.max(0, Math.min(scale.width - width, m.x - 6));
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
  const packed = packBars(lane.bars, scale);
  const markers = placeMarkers(lane, packed.placed, scale, today);
  const bars = placeBarLabels(packed.placed, scale, measure, markers);
  const tracks = Math.max(1, packed.tracks);
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
  return { lane, tracks, bars, markers, captions, trackY, height, rail: packed.tracks === 0 };
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

/**
 * The next thing on a lane from `today` on: the earliest upcoming marker (ties → most important
 * kind); if there is none, the end of a validity / period bar that is still running.
 */
export function nextOnLane(lane: Pick<Lane, "bars" | "markers">, today: string): NextDate | null {
  const t = dayNumber(today);
  const all = [...lane.markers, ...lane.bars.flatMap((b) => b.markers)].filter((m) => m.date && dayNumber(m.date) >= t);
  all.sort((a, b) => a.date.localeCompare(b.date) || markerRank(a.kind) - markerRank(b.kind));
  const m = all[0];
  if (m) return { date: m.date, kind: m.kind, label: shortMarkerLabel(m) };
  // no dated marker ahead: a running validity / period bar still says until when it lasts
  const running = lane.bars
    .filter((b) => (b.kind === "validity" || b.kind === "period") && dayNumber(b.end) >= t && dayNumber(b.start) <= t)
    .sort((a, b) => a.end.localeCompare(b.end))[0];
  return running ? { date: running.end, kind: "other", label: running.kind === "validity" ? "Valid until" : "Runs until" } : null;
}

/** Marker label without legal citations, capped for the label column. */
export function shortMarkerLabel(m: TimelineMarker): string {
  if (m.kind === "send_by") return "Send by";
  const cleaned = m.label.replace(/\s*\([^)]*\)\s*/g, " ").replace(/\s+this date\b/i, "").replace(/\s+/g, " ").trim();
  if (!cleaned) return m.kind === "expiry" ? "Expires" : "Date";
  return cleaned.length > 26 ? `${cleaned.slice(0, 25).trimEnd()}…` : cleaned;
}
