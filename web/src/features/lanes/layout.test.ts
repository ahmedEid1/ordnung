import { describe, expect, it } from "vitest";
import type { Lane, LaneBar, TimelineMarker } from "@/api/types";
import {
  LANE_METRICS,
  approxTextWidth,
  barBox,
  laneStatus,
  layoutLane,
  markerCaption,
  nextOnLane,
  packBars,
  placeBarLabels,
  placeCaptions,
  placeMarkers,
} from "./layout";
import { createTimeScale } from "./scale";
import { refTarget } from "./refs";

// 1 Jun 2026 – 30 Sep 2027 is 487 days; 974 px → exactly 2 px per day
const FROM = "2026-06-01";
const TO = "2027-09-30";
const TODAY = "2026-09-28";
const scale = createTimeScale(FROM, TO, 974);

const mk = (date: string, label: string, kind: TimelineMarker["kind"]): TimelineMarker => ({ date, label, kind });
const bar = (b: Partial<LaneBar> & Pick<LaneBar, "id" | "start" | "end">): LaneBar => ({
  label: b.id,
  kind: "contract",
  status: "ok",
  markers: [],
  ref: null,
  ...b,
});
const lane = (bars: LaneBar[], markers: TimelineMarker[] = [], id = "l"): Lane => ({ id, label: id, area: "home", bars, markers });

describe("barBox", () => {
  it("spans from the start of the first day to the end of the last day", () => {
    const b = barBox({ start: "2026-06-11", end: "2026-06-20" }, scale)!;
    expect(b.x).toBe(20);
    expect(b.width).toBe(20);
    expect(b.continuesBefore).toBe(false);
    expect(b.continuesAfter).toBe(false);
  });

  it("clips bars that run past the range and flags the continuation", () => {
    const passport = barBox({ start: "2017-02-11", end: "2027-02-10" }, scale)!;
    expect(passport.x).toBe(0);
    expect(passport.continuesBefore).toBe(true);
    expect(passport.width).toBe(scale.end("2027-02-10"));
    const lease = barBox({ start: "2026-09-01", end: "2027-12-31" }, scale)!;
    expect(lease.x + lease.width).toBe(974);
    expect(lease.continuesAfter).toBe(true);
    // a bar the API already clipped to the first day also reads as "continues"
    expect(barBox({ start: FROM, end: "2026-07-01" }, scale)!.continuesBefore).toBe(true);
  });

  it("drops bars completely outside the range and keeps tiny bars visible", () => {
    expect(barBox({ start: "2025-01-01", end: "2026-05-31" }, scale)).toBeNull();
    expect(barBox({ start: "2027-10-01", end: "2027-12-01" }, scale)).toBeNull();
    expect(barBox({ start: "2026-10-01", end: "2026-10-01" }, scale)!.width).toBe(3);
  });
});

describe("packBars (tracks)", () => {
  it("keeps sequential bars on one track and stacks overlapping ones", () => {
    const { placed, tracks } = packBars(
      [
        bar({ id: "a", start: "2026-06-01", end: "2026-11-30" }),
        bar({ id: "b", start: "2026-12-01", end: "2027-11-30" }),
        bar({ id: "c", start: "2026-10-01", end: "2027-02-10" }),
      ],
      scale,
    );
    expect(tracks).toBe(2);
    const track = Object.fromEntries(placed.map((p) => [p.bar.id, p.track]));
    expect(track).toEqual({ a: 0, b: 0, c: 1 });
  });

  it("draws a notice window on top of the term bar of the same contract", () => {
    const ref = { type: "contract", id: "ctr_phone" };
    const { placed, tracks } = packBars(
      [
        bar({ id: "term", start: "2024-11-15", end: "2026-11-14", ref }),
        bar({ id: "notice", start: "2026-09-08", end: "2026-10-14", kind: "notice_window", ref }),
        bar({ id: "other", start: "2026-06-01", end: "2027-01-01", ref: { type: "contract", id: "ctr_x" } }),
        bar({ id: "notice2", start: "2026-12-01", end: "2026-12-20", kind: "notice_window", ref: { type: "document", id: "doc_y" } }),
      ],
      scale,
    );
    const by = Object.fromEntries(placed.map((p) => [p.bar.id, p]));
    expect(by.notice!.overlay).toBe(true);
    expect(by.notice!.track).toBe(by.term!.track);
    expect(by.other!.track).not.toBe(by.term!.track);
    // no matching term bar → a notice window gets its own free slot
    expect(by.notice2!.overlay).toBe(false);
    expect(tracks).toBe(2);
  });
});

describe("packBars (one row per contract)", () => {
  it("keeps next year's notice window on its own contract's row, not on a free one", () => {
    const liability = { type: "contract", id: "ctr_liability" };
    const { placed } = packBars(
      [
        bar({ id: "power", start: "2025-10-01", end: "2026-09-30", ref: { type: "contract", id: "ctr_power" } }),
        bar({ id: "insurance-year", start: "2025-12-01", end: "2026-11-30", ref: liability }),
        bar({ id: "window", start: "2027-07-26", end: "2027-08-31", kind: "notice_window", ref: liability }),
      ],
      scale,
    );
    const by = Object.fromEntries(placed.map((p) => [p.bar.id, p]));
    expect(by.window!.track).toBe(by["insurance-year"]!.track);
    expect(by.window!.track).not.toBe(by.power!.track);
  });
});

describe("placeMarkers", () => {
  it("centres a marker in its day on the track of its bar", () => {
    const l = lane([bar({ id: "w", start: "2026-09-08", end: "2026-10-14", kind: "notice_window", markers: [mk("2026-10-08", "Send by", "send_by")] })]);
    const { placed } = packBars(l.bars, scale);
    const [m] = placeMarkers(l, placed, scale, TODAY);
    expect(m!.x).toBe(scale.mid("2026-10-08"));
    expect(m!.x).toBe((129 + 0.5) * 2); // 8 Oct is day 129 of the range
    expect(m!.track).toBe(0);
    expect(m!.primary.bar?.id).toBe("w");
  });

  it("merges markers on the same date and puts the most important one on top", () => {
    const l = lane([
      bar({
        id: "permit",
        start: "2024-12-01",
        end: "2026-11-30",
        kind: "validity",
        markers: [mk("2026-11-30", "Expires", "expiry"), mk("2026-11-30", "Apply before this date (§ 81 Abs. 4 AufenthG)", "deadline")],
      }),
    ]);
    const { placed } = packBars(l.bars, scale);
    const ms = placeMarkers(l, placed, scale, TODAY);
    expect(ms).toHaveLength(1);
    expect(ms[0]!.entries).toHaveLength(2);
    expect(ms[0]!.primary.marker.kind).toBe("deadline");
  });

  it("keeps markers a few days apart separate, puts lane markers on track 0 and skips dates outside the range", () => {
    const l = lane([], [mk("2026-10-05", "Rent", "payment"), mk("2026-10-09", "Utility back payment", "payment"), mk("2028-01-01", "Far away", "other")]);
    const ms = placeMarkers(l, [], scale, TODAY);
    expect(ms.map((m) => m.primary.marker.label)).toEqual(["Rent", "Utility back payment"]);
    expect(ms.every((m) => m.track === 0)).toBe(true);
    expect(ms[1]!.x - ms[0]!.x).toBe(8);
  });

  it("marks past markers so they can be drawn muted", () => {
    const ms = placeMarkers(lane([], [mk("2026-09-01", "Paid", "payment"), mk("2026-09-28", "Today", "appointment")]), [], scale, TODAY);
    expect(ms.map((m) => m.primary.past)).toEqual([true, false]);
  });
});

describe("labels", () => {
  it("puts a label inside a bar when it fits and keeps it clear of markers at the start", () => {
    const l = lane([
      bar({ id: "renewed", label: "Insurance year (renewed)", start: "2026-12-01", end: "2027-11-30", markers: [mk("2026-12-01", "Renews", "renewal")] }),
    ]);
    const { placed } = packBars(l.bars, scale);
    const markers = placeMarkers(l, placed, scale, TODAY);
    const [p] = placeBarLabels(placed, scale, approxTextWidth, markers);
    expect(p!.labelMode).toBe("inside");
    expect(p!.labelStart).toBeGreaterThan(LANE_METRICS.labelPad); // pushed right of the "Renews" ring
    expect(p!.labelMax).toBeNull();
  });

  it("moves a label after a short bar, or leaves it to the tooltip when there is no room", () => {
    const { placed } = packBars(
      [
        bar({ id: "tax", label: "Objection period", kind: "notice_window", start: "2026-09-21", end: "2026-10-21" }),
        bar({ id: "tight", label: "A long label that cannot fit", start: "2027-01-01", end: "2027-01-10" }),
        bar({ id: "next", label: "x", start: "2027-01-12", end: "2027-09-30" }),
      ],
      scale,
    );
    const labels = Object.fromEntries(placeBarLabels(placed, scale).map((p) => [p.bar.id, p]));
    expect(labels.tax!.labelMode).toBe("after");
    expect(labels.tax!.afterX).toBeGreaterThan(labels.tax!.x + labels.tax!.width);
    expect(labels.tight!.labelMode).toBe("none");
  });

  it("truncates (with the tooltip carrying the text) when a marker cuts a long bar short", () => {
    const l = lane([
      bar({ id: "ws", label: "Winter semester 2026/27 at the University of Musterstadt", kind: "period", start: "2026-10-01", end: "2027-03-31" }),
    ], [mk("2026-12-15", "Scholarship report", "deadline")]);
    const { placed } = packBars(l.bars, scale);
    const markers = placeMarkers(l, placed, scale, TODAY);
    const [p] = placeBarLabels(placed, scale, approxTextWidth, markers);
    expect(p!.labelMode).toBe("inside");
    expect(p!.labelMax).not.toBeNull();
    expect(p!.x + p!.labelStart + p!.labelMax!).toBeLessThan(markers[0]!.x);
  });

  it("captions upcoming deadlines without overlaps, most important first", () => {
    const l = lane([
      bar({
        id: "w",
        start: "2026-09-08",
        end: "2026-10-14",
        kind: "notice_window",
        markers: [mk("2026-10-08", "Send by", "send_by"), mk("2026-10-14", "Must arrive by", "cancel_by")],
      }),
    ]);
    const { placed } = packBars(l.bars, scale);
    const caps = placeCaptions(placeMarkers(l, placed, scale, TODAY), scale, TODAY);
    // 6 days apart = 12 px: both captions would collide → only "Send by" gets one
    expect(caps.map((c) => c.text)).toEqual(["Send by 8 Oct"]);
    for (const c of caps) {
      expect(c.x).toBeGreaterThanOrEqual(0);
      expect(c.x + c.width).toBeLessThanOrEqual(scale.width);
    }
  });

  it("writes short captions for marker kinds", () => {
    expect(markerCaption(mk("2026-11-30", "Apply before this date (§ 81 Abs. 4 AufenthG)", "deadline"), TODAY)).toBe("Apply before 30 Nov");
    expect(markerCaption(mk("2027-02-10", "Passport expires", "expiry"), TODAY)).toBe("Passport expires 10 Feb 2027");
    expect(markerCaption(mk("2026-10-14", "Must arrive by", "cancel_by"), TODAY)).toBe("Must arrive by 14 Oct");
  });
});

describe("whole lane", () => {
  it("sizes a lane by its tracks and caption rows", () => {
    const one = layoutLane(lane([bar({ id: "a", start: "2026-06-01", end: "2026-12-01" })]), scale, TODAY);
    const two = layoutLane(
      lane([bar({ id: "a", start: "2026-06-01", end: "2026-12-01" }), bar({ id: "b", start: "2026-07-01", end: "2026-08-01" })]),
      scale,
      TODAY,
    );
    const captioned = layoutLane(
      lane([bar({ id: "a", start: "2026-06-01", end: "2026-12-01", markers: [mk("2026-11-01", "Send by", "send_by")] })]),
      scale,
      TODAY,
    );
    expect(one.tracks).toBe(1);
    expect(two.tracks).toBe(2);
    expect(two.height - one.height).toBe(LANE_METRICS.trackHeight);
    expect(captioned.height - one.height).toBe(LANE_METRICS.captionHeight);
    expect(two.trackY[1]! - two.trackY[0]!).toBe(LANE_METRICS.trackHeight);
  });

  it("gives marker-only lanes a rail", () => {
    const ly = layoutLane(lane([], [mk("2026-10-05", "Rent", "payment")]), scale, TODAY);
    expect(ly.rail).toBe(true);
    expect(ly.tracks).toBe(1);
  });

  it("summarises status and the next date", () => {
    const l = lane(
      [
        bar({ id: "old", start: "2026-01-01", end: "2026-07-01", status: "past" }),
        bar({ id: "p", start: "2026-06-01", end: "2026-11-30", kind: "validity", status: "attention", markers: [mk("2026-11-30", "Expires", "expiry")] }),
      ],
      [mk("2026-10-14", "Appointment 10:30", "appointment"), mk("2026-09-01", "Past", "payment")],
    );
    expect(laneStatus(l)).toBe("attention");
    expect(nextOnLane(l, TODAY)).toEqual({ date: "2026-10-14", kind: "appointment", label: "Appointment 10:30" });
    expect(nextOnLane(lane([bar({ id: "v", start: "2026-01-01", end: "2027-02-10", kind: "validity" })]), TODAY)).toEqual({
      date: "2027-02-10",
      kind: "other",
      label: "Valid until",
    });
    expect(nextOnLane(lane([bar({ id: "c", start: "2026-01-01", end: "2027-12-31" })]), TODAY)).toBeNull();
  });
});

describe("refTarget", () => {
  it("links letters, contracts and to-dos (via their letter)", () => {
    expect(refTarget({ type: "document", id: "doc_abh" })?.href).toBe("/documents/doc_abh");
    expect(refTarget({ type: "contract", id: "ctr_phone" })?.href).toBe("/contracts?contract=ctr_phone");
    const items = new Map([["itm_1", { doc_id: "doc_tax", contract_id: null }], ["itm_2", { doc_id: null, contract_id: "ctr_gym" }]]);
    expect(refTarget({ type: "item", id: "itm_1" }, items)?.href).toBe("/documents/doc_tax");
    expect(refTarget({ type: "item", id: "itm_2" }, items)?.href).toBe("/contracts?contract=ctr_gym");
    expect(refTarget({ type: "item", id: "itm_unknown" }, items)).toBeNull();
    expect(refTarget(null)).toBeNull();
  });
});

describe("marker hit targets", () => {
  it("are 24 px wide, narrowed between close neighbours so they never overlap", () => {
    const l = lane([
      bar({
        id: "w",
        start: "2026-09-08",
        end: "2026-10-14",
        kind: "notice_window",
        markers: [mk("2026-10-08", "Send by", "send_by"), mk("2026-10-14", "Must arrive by", "cancel_by")],
      }),
    ], [mk("2027-01-15", "Semester fee", "payment")]);
    const { placed } = packBars(l.bars, scale);
    const ms = placeMarkers(l, placed, scale, TODAY);
    const [send, cancel, fee] = ms;
    expect(cancel!.x - send!.x).toBe(12);
    expect(send!.hitWidth).toBe(12);
    expect(cancel!.hitWidth).toBe(12);
    expect(send!.x + send!.hitWidth / 2).toBeLessThanOrEqual(cancel!.x - cancel!.hitWidth / 2);
    expect(fee!.hitWidth).toBe(24);
  });
});
