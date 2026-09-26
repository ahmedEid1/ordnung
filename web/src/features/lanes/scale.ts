/**
 * Date → pixel math for the life-lanes chart. Pure functions (unit-tested in `scale.test.ts`).
 *
 * Conventions
 * - Dates are ISO `YYYY-MM-DD` calendar days. We count whole days in UTC so daylight-saving
 *   changes never shift a bar by an hour's worth of pixels.
 * - The domain is inclusive: `from` starts at x = 0 and the *end* of `to` is at x = width.
 * - A day occupies `[x(day), x(day) + pxPerDay)`. Bars span from the start of their first day to
 *   the end of their last day; markers and the today line sit in the middle of their day.
 */
import { addMonths, endOfMonth, format, startOfMonth } from "date-fns";

const MS_PER_DAY = 86_400_000;
const ISO_RE = /^(\d{4})-(\d{2})-(\d{2})/;

/** Whole days since 1970-01-01 for an ISO date (timezone-independent). */
export function dayNumber(iso: string): number {
  const m = ISO_RE.exec(iso);
  if (!m) throw new RangeError(`Invalid ISO date: ${iso}`);
  return Math.round(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) / MS_PER_DAY);
}

/** Inverse of {@link dayNumber}. */
export function isoFromDayNumber(n: number): string {
  return new Date(n * MS_PER_DAY).toISOString().slice(0, 10);
}

/** Add whole days to an ISO date. */
export function addDaysISO(iso: string, days: number): string {
  return isoFromDayNumber(dayNumber(iso) + days);
}

/** Local-midnight Date for an ISO date (for date-fns formatting). */
function localDate(iso: string): Date {
  const m = ISO_RE.exec(iso);
  if (!m) throw new RangeError(`Invalid ISO date: ${iso}`);
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}

function isoOf(d: Date): string {
  return format(d, "yyyy-MM-dd");
}

export interface TimeScale {
  /** first day shown (inclusive) */
  from: string;
  /** last day shown (inclusive) */
  to: string;
  /** number of days in the domain */
  days: number;
  /** total plot width in px */
  width: number;
  pxPerDay: number;
  /** x of the *start* of a day (may be < 0 or > width for dates outside the domain) */
  x: (iso: string) => number;
  /** x of the middle of a day (markers, today line) */
  mid: (iso: string) => number;
  /** x of the *end* of a day (bar ends) */
  end: (iso: string) => number;
  /** the day under a given x (clamped to the domain) */
  dateAt: (x: number) => string;
  /** true when the day lies inside the domain */
  contains: (iso: string) => boolean;
}

/** Linear time scale over whole days, `from`..`to` inclusive mapped onto `0..width`. */
export function createTimeScale(from: string, to: string, width: number): TimeScale {
  const d0 = dayNumber(from);
  const d1 = dayNumber(to);
  if (d1 < d0) throw new RangeError(`Empty time range: ${from} – ${to}`);
  const days = d1 - d0 + 1;
  const w = Math.max(1, width);
  const pxPerDay = w / days;
  const x = (iso: string) => (dayNumber(iso) - d0) * pxPerDay;
  return {
    from,
    to,
    days,
    width: w,
    pxPerDay,
    x,
    mid: (iso) => x(iso) + pxPerDay / 2,
    end: (iso) => x(iso) + pxPerDay,
    dateAt: (px) => isoFromDayNumber(d0 + Math.min(days - 1, Math.max(0, Math.floor(px / pxPerDay)))),
    contains: (iso) => {
      const n = dayNumber(iso);
      return n >= d0 && n <= d1;
    },
  };
}

/**
 * The default window of the life lanes: from the first day of the month three months ago to the
 * last day of the month twelve months ahead (e.g. today 28 Sep 2026 → 1 Jun 2026 – 30 Sep 2027).
 */
export function defaultLaneRange(today: string, monthsBack = 3, monthsAhead = 12): { from: string; to: string } {
  const t = localDate(today);
  return {
    from: isoOf(startOfMonth(addMonths(t, -monthsBack))),
    to: isoOf(endOfMonth(addMonths(t, monthsAhead))),
  };
}

export interface MonthTick {
  /** first day of the month (ISO) */
  date: string;
  /** x of the month start (clamped to 0 for a partial first month) */
  x: number;
  /** band width in px (clipped to the domain) */
  width: number;
  /** "Oct" */
  label: string;
  /** "October 2026" (accessible name / tooltip) */
  longLabel: string;
  year: number;
  /** first month of a calendar year (draw a stronger line) */
  yearStart: boolean;
}

/** One tick per calendar month that intersects the domain. */
export function monthTicks(scale: TimeScale): MonthTick[] {
  const out: MonthTick[] = [];
  let cursor = startOfMonth(localDate(scale.from));
  const last = localDate(scale.to);
  while (cursor <= last) {
    const start = isoOf(cursor);
    const end = isoOf(endOfMonth(cursor));
    const x0 = Math.max(0, scale.x(start));
    const x1 = Math.min(scale.width, scale.end(end));
    out.push({
      date: start,
      x: x0,
      width: Math.max(0, x1 - x0),
      label: format(cursor, "MMM"),
      longLabel: format(cursor, "MMMM yyyy"),
      year: cursor.getFullYear(),
      yearStart: cursor.getMonth() === 0,
    });
    cursor = addMonths(cursor, 1);
  }
  return out;
}

export interface YearSpan {
  year: number;
  x: number;
  width: number;
}

/** Calendar-year segments of the domain (for the upper axis row). */
export function yearSpans(ticks: MonthTick[]): YearSpan[] {
  const spans: YearSpan[] = [];
  for (const t of ticks) {
    const cur = spans[spans.length - 1];
    if (cur && cur.year === t.year) cur.width = t.x + t.width - cur.x;
    else spans.push({ year: t.year, x: t.x, width: t.width });
  }
  return spans;
}

/** Number of (possibly fractional) months in the domain — used to size the plot. */
export function monthsInScale(from: string, to: string): number {
  return (dayNumber(to) - dayNumber(from) + 1) / 30.44;
}

/**
 * Plot width for a zoom level: `fit` stretches the whole domain over the available width but never
 * below `minMonthPx` per month; `detail` shows about `visibleMonths` months at once.
 */
export function plotWidth(
  from: string,
  to: string,
  available: number,
  zoom: "fit" | "detail",
  opts: { minMonthPx?: number; visibleMonths?: number } = {},
): number {
  const months = monthsInScale(from, to);
  const minMonthPx = opts.minMonthPx ?? 64;
  const avail = Math.max(0, available);
  if (zoom === "detail") {
    const perMonth = Math.max(minMonthPx * 1.8, avail / (opts.visibleMonths ?? 4));
    return Math.round(perMonth * months);
  }
  return Math.round(Math.max(avail, minMonthPx * months));
}

/** scrollLeft that puts `iso` at `ratio` (0..1) of the visible plot width. */
export function scrollLeftFor(scale: TimeScale, iso: string, visibleWidth: number, ratio = 0.22): number {
  const target = scale.mid(iso) - visibleWidth * ratio;
  return Math.max(0, Math.min(Math.max(0, scale.width - visibleWidth), Math.round(target)));
}
