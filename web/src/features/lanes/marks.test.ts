import { describe, expect, it } from "vitest";
import type { LaneBar } from "@/api/types";
import { barAriaLabel, barSpan, barStatusLabel } from "./marks";

const TODAY = "2026-09-28";
const RANGE = { from: "2026-06-01", to: "2027-09-30" };

const bar = (b: Partial<LaneBar>): LaneBar => ({
  id: "b",
  label: "Bar",
  start: "2024-12-01",
  end: "2026-11-30",
  kind: "contract",
  status: "ok",
  markers: [],
  ref: null,
  ...b,
});

describe("barSpan — when a bar runs, never with a made-up date", () => {
  it("gives both real dates, however far outside the chart they lie", () => {
    expect(barSpan(bar({ start: "2024-11-15", end: "2026-11-14" }), TODAY, RANGE)).toBe("15 Nov 2024 – 14 Nov 2026");
    expect(barSpan(bar({ start: "2025-10-01", end: "2027-12-31" }), TODAY, RANGE)).toBe("1 Oct 2025 – 31 Dec 2027");
  });

  it("says “no end date” for an open-ended bar instead of the chart's end", () => {
    expect(barSpan(bar({ start: "2025-10-01", end: "2027-10-01", open_end: true }), TODAY, RANGE)).toBe("since 1 Oct 2025 · no end date");
    // starts later: "from", not "since"
    expect(barSpan(bar({ start: "2026-11-15", end: "2027-10-01", open_end: true }), TODAY, RANGE)).toBe("from 15 Nov · no end date");
  });

  it("names a start or end the server cut off at the chart's edge instead of showing the edge as a date", () => {
    expect(barSpan(bar({ start: RANGE.from, end: "2027-03-31" }), TODAY, RANGE)).toBe("until 31 Mar 2027 · started before June 2026");
    expect(barSpan(bar({ start: "2026-08-15", end: RANGE.to }), TODAY, RANGE)).toBe("from 15 Aug · continues after September 2027");
    expect(barSpan(bar({ start: RANGE.from, end: RANGE.to }), TODAY, RANGE)).toBe("started before June 2026 · continues after September 2027");
    expect(barSpan(bar({ start: RANGE.from, end: RANGE.to, open_end: true }), TODAY, RANGE)).toBe("started before June 2026 · no end date");
  });
});

describe("barStatusLabel — the status in the bar's own terms", () => {
  it("says a permit ends soon (not “coming up”) and names the date to apply by", () => {
    const permit = bar({
      kind: "validity",
      status: "attention",
      markers: [
        { date: "2026-11-30", label: "Apply before this date (§ 81 Abs. 4 AufenthG)", kind: "deadline" },
        { date: "2026-11-30", label: "Expires", kind: "expiry" },
      ],
    });
    expect(barStatusLabel(permit, TODAY)).toBe("Ends soon — apply before 30 Nov");
    expect(barStatusLabel({ ...permit, markers: [] }, TODAY)).toBe("Ends soon");
    expect(barStatusLabel({ ...permit, status: "urgent", markers: [] }, TODAY)).toBe("Ends very soon");
  });

  it("asks to act on a closing notice window by its send-by date", () => {
    const window = bar({
      kind: "notice_window",
      status: "urgent",
      markers: [
        { date: "2026-10-08", label: "Send by", kind: "send_by" },
        { date: "2026-10-14", label: "Must arrive by", kind: "cancel_by" },
      ],
    });
    expect(barStatusLabel(window, TODAY)).toBe("Act now — send by 8 Oct");
    expect(barStatusLabel({ ...window, status: "attention" }, TODAY)).toBe("Decide soon — send by 8 Oct");
    expect(barStatusLabel({ ...window, status: "past" }, TODAY)).toBe("Closed");
    expect(barStatusLabel(bar({ status: "past" }), TODAY)).toBe("Ended");
    expect(barStatusLabel(bar({ status: "ok" }), TODAY)).toBeNull();
  });

  it("builds the accessible name from the span and status", () => {
    expect(barAriaLabel(bar({ label: "Open-ended", start: "2025-10-01", end: "2027-10-01", open_end: true }), TODAY, "Shows the contract below", RANGE)).toBe(
      "Open-ended. Contract term, since 1 Oct 2025, no end date. Shows the contract below.",
    );
  });
});
