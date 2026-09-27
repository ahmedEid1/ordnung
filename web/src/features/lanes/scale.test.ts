import { describe, expect, it } from "vitest";
import {
  addDaysISO,
  createTimeScale,
  dayNumber,
  defaultLaneRange,
  isoFromDayNumber,
  monthTicks,
  monthsInScale,
  plotWidth,
  scrollLeftFor,
  yearSpans,
} from "./scale";

describe("day arithmetic", () => {
  it("counts whole days, unaffected by daylight-saving changes", () => {
    // Europe switches to winter time on 25 Oct 2026 — still exactly one day apart
    expect(dayNumber("2026-10-26") - dayNumber("2026-10-25")).toBe(1);
    expect(dayNumber("2026-03-30") - dayNumber("2026-03-29")).toBe(1);
    expect(dayNumber("1970-01-01")).toBe(0);
    expect(isoFromDayNumber(dayNumber("2027-02-28") + 1)).toBe("2027-03-01");
    expect(addDaysISO("2026-12-31", 1)).toBe("2027-01-01");
    expect(addDaysISO("2026-10-08", -30)).toBe("2026-09-08");
  });

  it("rejects malformed dates", () => {
    expect(() => dayNumber("08.10.2026")).toThrow(RangeError);
    expect(() => createTimeScale("2026-02-01", "2026-01-01", 100)).toThrow(RangeError);
  });
});

describe("createTimeScale (date → x)", () => {
  // 1–30 Sep 2026 = 30 days over 300 px → 10 px per day
  const s = createTimeScale("2026-09-01", "2026-09-30", 300);

  it("maps the inclusive domain onto 0..width", () => {
    expect(s.days).toBe(30);
    expect(s.pxPerDay).toBe(10);
    expect(s.x("2026-09-01")).toBe(0);
    expect(s.end("2026-09-30")).toBe(300);
    expect(s.x("2026-09-16")).toBe(150);
  });

  it("puts markers in the middle of their day and bar ends at the end of the day", () => {
    expect(s.mid("2026-09-01")).toBe(5);
    expect(s.mid("2026-09-28")).toBe(275);
    expect(s.end("2026-09-10")).toBe(100);
  });

  it("extrapolates outside the domain and inverts x back to a date (clamped)", () => {
    expect(s.x("2026-08-31")).toBe(-10);
    expect(s.x("2026-10-01")).toBe(300);
    expect(s.dateAt(0)).toBe("2026-09-01");
    expect(s.dateAt(155)).toBe("2026-09-16");
    expect(s.dateAt(-40)).toBe("2026-09-01");
    expect(s.dateAt(10_000)).toBe("2026-09-30");
    expect(s.contains("2026-09-30")).toBe(true);
    expect(s.contains("2026-10-01")).toBe(false);
  });

  it("is linear: equal day spans get equal widths anywhere on the axis", () => {
    const y = createTimeScale("2026-06-01", "2027-09-30", 1600);
    const a = y.x("2026-07-10") - y.x("2026-07-01");
    const b = y.x("2027-05-10") - y.x("2027-05-01");
    expect(a).toBeCloseTo(b, 9);
    expect(y.end("2027-09-30")).toBeCloseTo(1600, 9);
  });
});

describe("default range and month grid", () => {
  it("runs from three months back to twelve months ahead (whole months)", () => {
    expect(defaultLaneRange("2026-09-28")).toEqual({ from: "2026-06-01", to: "2027-09-30" });
    expect(defaultLaneRange("2026-01-15")).toEqual({ from: "2025-10-01", to: "2027-01-31" });
  });

  it("creates one tick per month whose bands tile the plot exactly", () => {
    const { from, to } = defaultLaneRange("2026-09-28");
    const s = createTimeScale(from, to, 1600);
    const ticks = monthTicks(s);
    expect(ticks).toHaveLength(16);
    expect(ticks[0]).toMatchObject({ date: "2026-06-01", x: 0, label: "Jun", longLabel: "June 2026", yearStart: false });
    expect(ticks[7]).toMatchObject({ date: "2027-01-01", label: "Jan", yearStart: true, year: 2027 });
    const total = ticks.reduce((sum, t) => sum + t.width, 0);
    expect(total).toBeCloseTo(1600, 6);
    for (let i = 1; i < ticks.length; i++) expect(ticks[i]!.x).toBeCloseTo(ticks[i - 1]!.x + ticks[i - 1]!.width, 6);
    // a 31-day month is wider than a 28-day one
    const feb = ticks.find((t) => t.date === "2027-02-01")!;
    const mar = ticks.find((t) => t.date === "2027-03-01")!;
    expect(mar.width / feb.width).toBeCloseTo(31 / 28, 6);
    expect(yearSpans(ticks).map((y) => y.year)).toEqual([2026, 2027]);
  });

  it("clips a partial first month to the domain", () => {
    const s = createTimeScale("2026-09-15", "2026-10-31", 470);
    const [sep, oct] = monthTicks(s);
    expect(sep).toMatchObject({ date: "2026-09-01", x: 0 });
    expect(sep!.width).toBeCloseTo(160, 6); // 16 days × 10 px
    expect(oct!.x).toBeCloseTo(160, 6);
  });
});

describe("plot sizing and initial scroll", () => {
  const range = { from: "2026-06-01", to: "2027-09-30" };

  it("fits every month into the available width — “Fit all” never scrolls", () => {
    expect(monthsInScale(range.from, range.to)).toBeCloseTo(16, 0);
    expect(plotWidth(range.from, range.to, 1000, "fit", { minMonthPx: 50 })).toBe(1000);
    // a tablet-sized plot (16 months in 470 px): narrow months, but no scrolling
    expect(plotWidth(range.from, range.to, 470.6, "fit", { minMonthPx: 90 })).toBe(470);
    expect(plotWidth(range.from, range.to, 360, "fit", { minMonthPx: 66 })).toBe(360);
  });

  it("zooms in to show about a handful of months at once, never narrower than the minimum per month", () => {
    const w = plotWidth(range.from, range.to, 900, "detail", { visibleMonths: 5 });
    expect(w / monthsInScale(range.from, range.to)).toBeCloseTo(180, 0);
    const phone = plotWidth(range.from, range.to, 300, "detail", { minMonthPx: 66, visibleMonths: 4.5 });
    expect(phone / monthsInScale(range.from, range.to)).toBeCloseTo(66.7, 0);
    // never narrower than the whole range fitted
    expect(plotWidth("2026-09-01", "2026-10-31", 900, "detail", { visibleMonths: 5 })).toBe(900);
  });

  it("scrolls so that today sits near the left third, clamped to the content", () => {
    const s = createTimeScale(range.from, range.to, 1600);
    const left = scrollLeftFor(s, "2026-09-28", 400, 0.25);
    expect(s.mid("2026-09-28") - left).toBeCloseTo(100, 0);
    expect(scrollLeftFor(s, "2026-06-02", 400)).toBe(0);
    expect(scrollLeftFor(s, "2027-09-29", 400)).toBe(1200);
  });
});
