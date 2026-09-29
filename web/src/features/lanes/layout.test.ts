import { describe, expect, it } from "vitest";
import type { Lane, LaneBar, TimelineMarker } from "@/api/types";
import type { MarkerEntry } from "./layout";
import {
  LANE_METRICS,
  approxTextWidth,
  barBox,
  laneStatus,
  layoutLane,
  markerCaption,
  nextOnLane,
  packBars,
  packLane,
  placeBarLabels,
  placeCaptions,
  freeSegments,
  placeMarkers,
} from "./layout";
import { addDaysISO, createTimeScale, dayNumber } from "./scale";
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

  it("keeps the next thing's bar clear of a bar's end marker; a term and what follows it share the row", () => {
    // two permits back to back: the first one's "Expires" mark (24 px wide) would cover the next one's start
    const permits = packBars(
      [
        bar({ id: "old", kind: "validity", start: "2026-06-01", end: "2026-11-30", ref: { type: "item", id: "a" }, markers: [mk("2026-11-30", "Expires", "expiry")] }),
        bar({ id: "new", kind: "validity", start: "2026-12-01", end: "2027-11-30", ref: { type: "item", id: "b" } }),
      ],
      scale,
    );
    expect(permits.placed.map((p) => [p.bar.id, p.track])).toEqual([
      ["old", 0],
      ["new", 1],
    ]);
    // one contract: its minimum term ends where "cancellable any time" begins — one row, the mark between them
    const ref = { type: "contract", id: "ctr_phone" };
    const phone = packBars(
      [
        bar({ id: "term", start: "2026-06-01", end: "2026-11-14", ref, markers: [mk("2026-11-14", "Minimum term ends", "other")] }),
        bar({ id: "after", start: "2026-11-15", end: TO, ref, open_end: true }),
      ],
      scale,
    );
    expect(phone.tracks).toBe(1);
  });
});

describe("packLane (the lane's own markers)", () => {
  // the demo's Residence permit lane (prompt 11): the permit, and the extension appointment with its fee
  // and the to-do "Cancel appointment if you cannot attend" dated on it
  const permit = bar({
    id: "permit",
    label: "Residence permit",
    kind: "validity",
    status: "attention",
    start: "2026-09-16",
    end: "2026-11-30",
    ref: { type: "item", id: "itm_permit" },
    markers: [mk("2026-11-30", "Apply before this date (§ 81 Abs. 4 AufenthG)", "deadline"), mk("2026-11-30", "Expires", "expiry")],
  });
  const own = (date: string, label: string, kind: TimelineMarker["kind"], id: string): TimelineMarker => ({ ...mk(date, label, kind), ref: { type: "item", id } });
  const residence = lane(
    [permit],
    [
      own("2026-10-14", "Extension fee", "payment", "itm_fee"),
      own("2026-10-14", "Residence permit extension appointment", "appointment", "itm_appt"),
      own("2026-10-19", "Cancel appointment if you cannot attend", "deadline", "itm_cancel"),
    ],
    "residence",
  );

  it("never draws a to-do over another thing's bar: the appointment's dates get a row of their own", () => {
    const packed = packLane(residence, scale);
    expect(packed.placed.map((p) => p.track)).toEqual([0]);
    expect(packed.markerTracks).toEqual([1, 1, 1]);
    expect(packed.tracks).toBe(2);
    const ly = layoutLane(residence, scale, TODAY);
    expect(ly.tracks).toBe(2);
    expect(ly.rails).toEqual([1]);
    expect(ly.rail).toBe(false);
    // the permit's button: nothing but its own "apply before / expires" mark on it, its centre free
    const p = ly.bars[0]!;
    const onBar = ly.markers.filter((m) => m.track === p.track && m.x + m.hitWidth / 2 > p.x && m.x - m.hitWidth / 2 < p.x + p.width);
    expect(onBar.flatMap((m) => m.entries.map((e) => e.bar?.id))).toEqual(["permit", "permit"]);
    const centre = p.x + p.width / 2;
    expect(onBar.every((m) => Math.abs(m.x - centre) >= m.hitWidth / 2)).toBe(true);
    // and with the to-dos off it, its label fits inside
    expect(p.labelMode).toBe("inside");
  });

  it("keeps a lane's marker on a bar's row when it touches no bar there", () => {
    const later = lane([permit], [own("2027-02-10", "Passport expires", "expiry", "itm_pass")]);
    expect(packLane(later, scale)).toMatchObject({ markerTracks: [0], tracks: 1 });
    expect(layoutLane(later, scale, TODAY).rails).toEqual([]);
  });

  it("keeps a lane's marker clear of a bar's own markers: never one mark of two things", () => {
    // 3 Dec is 6 px after the permit's end mark — it would merge into it; 20 Dec is 40 px away
    const near = packLane(lane([permit], [own("2026-12-03", "Pay the fee", "payment", "itm_x")]), scale);
    expect(near.markerTracks).toEqual([1]);
    const far = packLane(lane([permit], [own("2026-12-20", "Pay the fee", "payment", "itm_x")]), scale);
    expect(far.markerTracks).toEqual([0]);
  });

  it("places markers that merge into one mark as one run, on one row", () => {
    // 9 Oct lies on the bar; 19 Oct alone would fit after it, but the two are 20 px apart: one mark
    const l = lane(
      [bar({ id: "b", start: "2026-06-01", end: "2026-10-10" })],
      [own("2026-10-09", "Appointment", "appointment", "itm_a"), own("2026-10-19", "Send the form", "deadline", "itm_b")],
    );
    const packed = packLane(l, scale);
    expect(packed.markerTracks).toEqual([1, 1]);
    const ms = placeMarkers(l, packed.placed, scale, TODAY, { laneTracks: packed.markerTracks });
    expect(ms.filter((m) => m.track === 1).map((m) => m.entries.length)).toEqual([2]);
  });

  it("puts a marker of the very contract a bar stands for, dated on it, on that bar", () => {
    const ref = { type: "contract", id: "ctr_gym" };
    const gym = lane(
      [bar({ id: "any", label: "Cancellable any time", start: "2026-06-01", end: TO, ref, open_end: true })],
      [{ ...mk("2026-10-28", "Earliest end (if you cancel now)", "other"), ref }, own("2026-10-28", "Pay the gym", "payment", "itm_gym")],
    );
    // the contract's own date rides on it; a to-do of the same day stands for something else
    expect(packLane(gym, scale).markerTracks).toEqual([0, 1]);
  });

  it("keeps the next thing's bar clear of a date riding on a bar's end", () => {
    const ref = { type: "contract", id: "ctr_gym" };
    const l = lane(
      [
        bar({ id: "gym", start: "2026-06-01", end: "2026-10-28", ref }),
        bar({ id: "next", start: "2026-10-29", end: "2027-03-31", ref: { type: "item", id: "itm_next" } }),
      ],
      [{ ...mk("2026-10-28", "Earliest end (if you cancel now)", "other"), ref }],
    );
    const packed = packLane(l, scale);
    const track = Object.fromEntries(packed.placed.map((p) => [p.bar.id, p.track]));
    expect(track).toEqual({ gym: 0, next: 1 });
    expect(packed.markerTracks).toEqual([0]);
    // without the rider, the two bars meet on one row
    expect(packBars(l.bars, scale).tracks).toBe(1);
  });

  it("gives a marker with no date, or one outside the range, no room", () => {
    const l = lane([permit], [own("", "No date yet", "other", "itm_n"), own("2028-01-01", "Far away", "other", "itm_f")]);
    expect(packLane(l, scale)).toMatchObject({ markerTracks: [0, 0], tracks: 1 });
    expect(layoutLane(l, scale, TODAY).markers.flatMap((m) => m.entries.map((e) => e.marker.label))).not.toContain("No date yet");
  });

  it("gives a lane of markers only one rail track, as before", () => {
    const packed = packLane(lane([], [own("2026-10-05", "Rent", "payment", "itm_r"), own("2027-03-01", "Rent", "payment", "itm_r2")]), scale);
    expect(packed).toMatchObject({ placed: [], markerTracks: [0, 0], tracks: 1 });
  });

  it("never lets a mark cover another thing's bar, nor two bars overlap, whatever the kinds, at any width", () => {
    // a small deterministic generator: bars of every kind (some of one contract), their markers, the lane's to-dos
    let seed = 7;
    const rand = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
    const day = (lo: number, hi: number) => addDaysISO(FROM, Math.floor(lo + rand() * (hi - lo)));
    const kinds: LaneBar["kind"][] = ["contract", "validity", "period", "notice_window", "event"];
    const markerKinds: TimelineMarker["kind"][] = ["send_by", "deadline", "cancel_by", "expiry", "appointment", "payment", "renewal", "other"];
    for (let n = 0; n < 300; n++) {
      const refs = ["contract:a", "contract:b", "item:c", "item:d"];
      const bars: LaneBar[] = [];
      for (let b = 0; b < 1 + Math.floor(rand() * 5); b++) {
        // often right after the bar before (back to back, as a permit and the next one), else anywhere
        const prev = bars[bars.length - 1];
        const start = prev && rand() < 0.5 ? addDaysISO(prev.end, 1 + Math.floor(rand() * 4)) : day(-60, 450);
        const end = addDaysISO(start, Math.floor(rand() * 200));
        const [type, id] = refs[Math.floor(rand() * refs.length)]!.split(":") as [string, string];
        const inside = Array.from({ length: Math.floor(rand() * 3) }, () =>
          mk(addDaysISO(start, Math.floor(rand() * (dayNumber(end) - dayNumber(start) + 1))), "Date", markerKinds[Math.floor(rand() * markerKinds.length)]!),
        );
        // most bars have a date at their end (expires, renews, must arrive by), some the day after (a renewal)
        if (rand() < 0.6) inside.push(mk(rand() < 0.8 ? end : addDaysISO(end, 1), "End", markerKinds[Math.floor(rand() * markerKinds.length)]!));
        bars.push(bar({ id: `b${b}`, start, end, kind: kinds[Math.floor(rand() * kinds.length)]!, ref: { type, id }, markers: inside }));
      }
      const loose = Array.from({ length: Math.floor(rand() * 6) }, (_, i): TimelineMarker => {
        const kind = markerKinds[Math.floor(rand() * markerKinds.length)]!;
        if (rand() < 0.2) return own("", "Undated", "other", `itm_u${i}`);
        // some of them the very contract's or to-do's a bar stands for (on its bar when dated on it), often at its end
        if (rand() < 0.3) {
          const b = bars[Math.floor(rand() * bars.length)]!;
          return { ...mk(rand() < 0.5 ? b.end : day(-10, 500), `Its date ${i}`, kind), ref: b.ref };
        }
        return own(day(-10, 500), `To-do ${i}`, kind, `itm_${i}`);
      });
      const l = lane(bars, loose);
      for (const width of [320, 974, 4000]) {
        const sc = createTimeScale(FROM, TO, width);
        const ly = layoutLane(l, sc, TODAY);
        const drawn = (p: (typeof ly.bars)[number]) => ({ s: p.x + 1, e: p.x + 1 + Math.max(3, p.width - 2) });
        const key = (r: { type: string; id: string } | null | undefined) => (r ? `${r.type}:${r.id}` : null);
        // a date of the bar itself, or of the contract or to-do it stands for
        const belongs = (e: MarkerEntry, p: (typeof ly.bars)[number]) => {
          const k = key(e.bar ? e.bar.ref : e.marker.ref);
          return e.bar === p.bar || (k !== null && k === key(p.bar.ref));
        };
        for (const m of ly.markers) {
          for (const p of ly.bars.filter((b) => b.track === m.track)) {
            const d = drawn(p);
            if (m.x + m.hitWidth / 2 <= d.s || m.x - m.hitWidth / 2 >= d.e) continue;
            const foreign = m.entries.filter((e) => !belongs(e, p)).map((e) => e.marker.label);
            expect(foreign, `lane ${n} @ ${width}px: drawn over ${p.bar.id} (${p.bar.start} – ${p.bar.end})`).toEqual([]);
          }
        }
        // bars on one row: of one thing, their days never overlap (a notice window rides on its host); of two, not even their marks touch
        for (const a of ly.bars) {
          for (const b of ly.bars) {
            if (a === b || a.track !== b.track || a.overlay || b.overlay || a.x > b.x) continue;
            const same = a.bar.ref?.id === b.bar.ref?.id && a.bar.ref?.type === b.bar.ref?.type;
            if (same) expect(a.bar.end < b.bar.start || b.bar.end < a.bar.start, `lane ${n} @ ${width}px: ${a.bar.id} and ${b.bar.id}`).toBe(true);
            else expect(drawn(a).e <= drawn(b).s, `lane ${n} @ ${width}px: ${a.bar.id} and ${b.bar.id} overlap`).toBe(true);
          }
        }
        // marks on one row keep their 24 px apart
        for (const t of new Set(ly.markers.map((m) => m.track))) {
          const xs = ly.markers.filter((m) => m.track === t).map((m) => m.x);
          for (let i = 1; i < xs.length; i++) expect(xs[i]! - xs[i - 1]!).toBeGreaterThanOrEqual(LANE_METRICS.markerGap);
        }
      }
    }
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

  it("merges markers closer than 24 px into one mark, keeps the others apart, puts lane markers on track 0 and skips dates outside the range", () => {
    const l = lane(
      [],
      [mk("2026-10-05", "Rent", "payment"), mk("2026-10-09", "Utility back payment", "payment"), mk("2026-10-20", "Fee", "payment"), mk("2028-01-01", "Far away", "other")],
    );
    const ms = placeMarkers(l, [], scale, TODAY);
    // 5 and 9 Oct are 8 px apart: one mark (drawn at the first), its tooltip lists both
    expect(ms.map((m) => m.entries.map((e) => e.marker.label))).toEqual([["Rent", "Utility back payment"], ["Fee"]]);
    expect(ms.every((m) => m.track === 0)).toBe(true);
    expect(ms[0]!.x).toBe(scale.mid("2026-10-05"));
    expect(ms[1]!.x - ms[0]!.x).toBe(30);
  });

  it("keeps merging until every mark on a track is at least 24 px from the next — a chain never overlaps", () => {
    // a date every 5 days (10 px): pairwise close, so they collapse into marks ≥ 24 px apart
    const dates = ["2026-10-01", "2026-10-06", "2026-10-11", "2026-10-16", "2026-10-21", "2026-10-26"];
    const ms = placeMarkers(lane([], dates.map((d, i) => mk(d, `Date ${i}`, i === 3 ? "deadline" : "payment"))), [], scale, TODAY);
    for (let i = 1; i < ms.length; i++) expect(ms[i]!.x - ms[i - 1]!.x).toBeGreaterThanOrEqual(LANE_METRICS.markerGap);
    expect(ms.flatMap((m) => m.entries)).toHaveLength(dates.length);
    // the deadline is the most important entry of its mark and decides where it is drawn
    const withDeadline = ms.find((m) => m.entries.some((e) => e.marker.kind === "deadline"))!;
    expect(withDeadline.primary.marker.kind).toBe("deadline");
    expect(withDeadline.x).toBe(scale.mid("2026-10-16"));
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

  it("truncates in the widest free stretch (the tooltip carries the text) when no stretch between markers fits it", () => {
    // the semester's own date on it (a lane's other dates get a row of their own: packLane)
    const l = lane([
      bar({
        id: "ws",
        label: "Winter semester 2026/27 at the University of Musterstadt",
        kind: "period",
        start: "2026-10-01",
        end: "2027-03-31",
        markers: [mk("2026-12-15", "Lectures pause", "other")],
      }),
    ]);
    const { placed } = packBars(l.bars, scale);
    const markers = placeMarkers(l, placed, scale, TODAY);
    const [p] = placeBarLabels(placed, scale, approxTextWidth, markers);
    expect(p!.labelMode).toBe("inside");
    expect(p!.labelMax).not.toBeNull();
    // 1 Oct – 15 Dec is narrower than 15 Dec – 31 Mar: the label goes after the marker, clear of it
    expect(p!.x + p!.labelStart).toBeGreaterThan(markers[0]!.x + 9);
    expect(p!.x + p!.labelStart + p!.labelMax!).toBeLessThanOrEqual(p!.x + p!.width - LANE_METRICS.labelPad);
  });

  it("puts a label that doesn't fit before a marker into the free stretch after it, instead of dropping it", () => {
    // a work contract with a marker a little way in: "Be…" before it, the whole label after it
    const l = lane([
      bar({ id: "job", label: "Befristeter Arbeitsvertrag", start: "2026-06-01", end: "2027-03-31", markers: [mk("2026-06-20", "Probation ends", "other")] }),
    ]);
    const { placed } = packBars(l.bars, scale);
    const markers = placeMarkers(l, placed, scale, TODAY);
    const [p] = placeBarLabels(placed, scale, approxTextWidth, markers);
    expect(p!.labelMode).toBe("inside");
    expect(p!.labelMax).toBeNull();
    expect(p!.x + p!.labelStart).toBeGreaterThan(markers[0]!.x);
  });

  it("finds the free stretches between blocked intervals", () => {
    expect(freeSegments(0, 100, [{ s: 20, e: 30 }, { s: 50, e: 60 }])).toEqual([
      { s: 0, e: 20 },
      { s: 30, e: 50 },
      { s: 60, e: 100 },
    ]);
    expect(freeSegments(10, 50, [{ s: 0, e: 15 }, { s: 45, e: 90 }])).toEqual([{ s: 15, e: 45 }]);
    expect(freeSegments(10, 50, [{ s: 0, e: 90 }])).toEqual([]);
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

  it("keeps captions inside the plot (with an inset on the right) and clear of the today line", () => {
    const todayX = scale.mid(TODAY);
    // due two days after today: the caption would start 2 px left of the marker, across the line
    const soon = placeCaptions(placeMarkers(lane([], [mk("2026-09-30", "Ends", "expiry")]), [], scale, TODAY), scale, TODAY);
    expect(soon).toHaveLength(1);
    expect(soon[0]!.x).toBeGreaterThanOrEqual(todayX + 1 + LANE_METRICS.todayClear);
    // the last day of the range: the caption ends 8 px before the plot's right edge
    const last = placeCaptions(placeMarkers(lane([], [mk("2027-09-29", "Send by", "send_by")]), [], scale, TODAY), scale, TODAY);
    expect(last[0]!.x + last[0]!.width).toBeLessThanOrEqual(scale.width - LANE_METRICS.captionInset);
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
      kind: "expiry",
      label: "Valid until",
    });
  });

  it("names the next date to act on: renewals are skipped, a fixed term's end counts, open or cut-off ends never do", () => {
    const ref = { type: "contract", id: "ctr" };
    // the Contracts lane: a contract that runs on (renewal on 1 Oct) and a send-by date on 8 Oct
    const contracts = lane([
      bar({ id: "power", start: "2025-10-01", end: "2026-09-30", markers: [mk("2026-10-01", "Continues · cancel any time", "renewal")] }),
      bar({ id: "phone", start: "2026-09-08", end: "2026-10-14", kind: "notice_window", ref, markers: [mk("2026-10-08", "Send by", "send_by")] }),
    ]);
    expect(nextOnLane(contracts, TODAY)).toEqual({ date: "2026-10-08", kind: "send_by", label: "Send by" });
    // the Work lane: a fixed-term contract with no markers still says when it ends
    expect(nextOnLane(lane([bar({ id: "job", start: "2025-04-01", end: "2027-03-31" })]), TODAY)).toEqual({ date: "2027-03-31", kind: "other", label: "Ends" });
    // no end date, an end the chart cut off, or a term that renews: nothing to say
    expect(nextOnLane(lane([bar({ id: "rent", start: "2025-10-01", end: "2027-10-01", open_end: true })]), TODAY)).toBeNull();
    expect(nextOnLane(lane([bar({ id: "gym", start: "2026-06-01", end: TO })]), TODAY, { to: TO })).toBeNull();
    expect(nextOnLane(lane([bar({ id: "ins", start: "2025-12-01", end: "2026-11-30", markers: [mk("2026-12-01", "Renews", "renewal")] })]), TODAY)).toBeNull();
  });

  it("keeps the whole marker label (the label column truncates it, not the text)", () => {
    const long = mk("2026-10-02", "Return overdue library items to the Stadtbibliothek (§ 5 Benutzungsordnung)", "deadline");
    expect(nextOnLane(lane([], [long]), TODAY)?.label).toBe("Return overdue library items to the Stadtbibliothek");
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
  it("are always 24 px wide and never overlap: close neighbours become one mark", () => {
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
    // send-by and must-arrive-by are 12 px apart: one mark, drawn at the send-by date
    expect(ms).toHaveLength(2);
    const [window, fee] = ms;
    expect(window!.entries.map((e) => e.marker.kind)).toEqual(["send_by", "cancel_by"]);
    expect(window!.x).toBe(scale.mid("2026-10-08"));
    expect(ms.every((m) => m.hitWidth === 24)).toBe(true);
    expect(window!.x + window!.hitWidth / 2).toBeLessThanOrEqual(fee!.x - fee!.hitWidth / 2);
  });
});
