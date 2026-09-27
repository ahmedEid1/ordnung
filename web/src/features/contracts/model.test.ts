import { describe, expect, it } from "vitest";
import type { Contract } from "@/api/types";
import { CONTRACT_REGIMES } from "@/api/types";
import { assertNoRawEnums } from "@/lib/copy";
import { CONTRACTS } from "@/mocks/data/contracts";
import { layoutLane } from "@/features/lanes/layout";
import { createTimeScale, defaultLaneRange } from "@/features/lanes/scale";
import { contractLanes, decideBy, filterByStatus, fixedCosts, isLockInDecision, isRollingContract, noticePhrase, ruleInWords, sortContracts } from "./model";
import { composerHrefFor } from "./links";

const TODAY = "2026-09-28";
const byId = (id: string) => CONTRACTS.find((c) => c.id === id)!;

describe("fixed costs", () => {
  it("sums the monthly cost of every active contract (yearly / 12, quarterly / 3)", () => {
    const costs = fixedCosts(CONTRACTS);
    // 640 + 34,99 + 48 + 29,90 + 59,90/12 + 142,86 + 63 + 4,90 + 55,08/3
    expect(costs.monthly).toBe(987);
    expect(costs.yearly).toBe(11844);
    expect(costs.counted).toBe(9);
    expect(costs.unknown).toBe(0); // the job pays you — not counted as unknown
  });

  it("sums each currency on its own (a $20 subscription is not €20 of the fixed costs)", () => {
    const cloud = { ...byId("ctr_phone"), id: "ctr_cloud", cost_amount: 20, cost_currency: "USD", cost_interval: "monthly" as const };
    const costs = fixedCosts([...CONTRACTS, cloud]);
    expect(costs.monthly).toBe(987);
    expect(costs.monthlyTotals).toEqual({ EUR: 987, USD: 20 });
    expect(costs.yearlyTotals).toEqual({ EUR: 11844, USD: 240 });
    expect(costs.counted).toBe(10);
  });

  it("ignores cancelled and ended contracts", () => {
    const list = CONTRACTS.map((c) => (c.id === "ctr_rent" ? { ...c, status: "cancelled" as const } : c));
    expect(fixedCosts(list).monthly).toBe(347);
  });
});

describe("decisions", () => {
  it("picks active contracts whose send-by date is within 60 days", () => {
    expect(decideBy(CONTRACTS, TODAY).map((c) => c.id)).toEqual(["ctr_phone"]);
    expect(decideBy(CONTRACTS, "2027-07-01").map((c) => c.id)).toEqual(["ctr_liability"]);
    expect(decideBy(CONTRACTS, "2026-10-09")).toEqual([]); // the phone's send-by has passed
  });

  it("never asks to decide on a contract that can be cancelled any month", () => {
    const rent = byId("ctr_rent");
    const rolling: Contract = {
      ...rent,
      status: "active",
      computed: { ...byId("ctr_phone").computed!, regime: "rent573c", current_term_end: null, next_renewal: null, cancel_by: "2026-10-05", send_by: "2026-09-29", earliest_exit: "2026-12-31" },
    };
    expect(isRollingContract(rolling)).toBe(true);
    expect(isLockInDecision(rolling)).toBe(false);
    expect(decideBy([rolling], TODAY)).toEqual([]);
    expect(isLockInDecision(byId("ctr_phone"))).toBe(true); // the minimum term ends
    expect(isRollingContract(byId("ctr_phone"))).toBe(false);
  });

  it("sorts cards: next action first, then by monthly cost", () => {
    // the Deutschlandticket can be cancelled any month: no date to act on, so it sorts by cost
    expect(sortContracts(CONTRACTS, TODAY).map((c) => c.id).slice(0, 4)).toEqual(["ctr_phone", "ctr_liability", "ctr_rent", "ctr_bkk"]);
    expect(filterByStatus(CONTRACTS, "cancelled")).toEqual([]);
    expect(filterByStatus(CONTRACTS, "all")).toHaveLength(CONTRACTS.length);
  });

  it("links to a pre-filled cancellation letter", () => {
    expect(composerHrefFor(byId("ctr_phone"))).toBe("/letters?kind=cancellation&contract=ctr_phone");
  });
});

describe("rules in plain words", () => {
  it("explains notice periods", () => {
    expect(noticePhrase({ notice_value: 1, notice_unit: "months" })).toBe("1 month's notice");
    expect(noticePhrase({ notice_value: 4, notice_unit: "weeks" })).toBe("4 weeks' notice");
    expect(noticePhrase({ notice_value: null, notice_unit: null })).toBeNull();
  });

  it("describes each sample contract in one sentence", () => {
    expect(ruleInWords(byId("ctr_phone"), TODAY)).toEqual({
      text: "Minimum term until 14 Nov; after that cancellable any time with 1 month's notice (phone & internet contract)",
      citation: "§ 56 TKG",
    });
    expect(ruleInWords(byId("ctr_gym"), TODAY).text).toBe("Cancellable any time with 1 month's notice (consumer contract since March 2022)");
    expect(ruleInWords(byId("ctr_rent"), TODAY).text).toMatch(/^Open-ended: notice given by the 3rd working day/);
    expect(ruleInWords(byId("ctr_liability"), TODAY).text).toBe("Renews every insurance year; cancel with 3 months' notice before the insurance year ends");
    expect(ruleInWords(byId("ctr_job"), TODAY).text).toBe("Fixed term until 31 Mar 2027; 4 weeks' notice to end it earlier");
    // "as written" without notice terms falls back to the engine's own first sentence
    expect(ruleInWords(byId("ctr_dticket"), TODAY)).toEqual({
      text: "Cancel by the 10th of a month to end it at the end of that month — next: by Sat 10 Oct for 31 Oct",
      citation: null,
    });
  });

  it("never leaks a regime code, for every regime", () => {
    for (const regime of CONTRACT_REGIMES) {
      const c: Contract = { ...byId("ctr_phone"), computed: { ...byId("ctr_phone").computed!, regime } };
      const r = ruleInWords(c, TODAY);
      assertNoRawEnums(r.text);
      if (r.citation) assertNoRawEnums(r.citation);
    }
  });
});

describe("contracts-only lanes", () => {
  const range = defaultLaneRange(TODAY);
  const lanes = contractLanes(CONTRACTS, range, TODAY);
  const lane = (id: string) => lanes.find((l) => l.id === id)!;

  it("gives every contract its own lane", () => {
    expect(lanes.map((l) => l.id)).toEqual(CONTRACTS.map((c) => c.id));
    expect(lane("ctr_phone").label).toBe("FunkNetz Allnet L");
  });

  it("draws the minimum term, what follows it and the hatched window to cancel", () => {
    const bars = lane("ctr_phone").bars;
    expect(bars.map((b) => [b.label, b.kind, b.start, b.end])).toEqual([
      ["Minimum term", "contract", "2024-11-15", "2026-11-14"],
      ["Cancellable any time", "contract", "2026-11-15", "2027-10-01"],
      ["Time to cancel", "notice_window", "2026-09-08", "2026-10-14"],
    ]);
    // what follows the minimum term has no end date: the chart never shows its drawn end as one
    expect(bars.map((b) => Boolean(b.open_end))).toEqual([false, true, false]);
    const notice = bars[2]!;
    expect(notice.status).toBe("urgent"); // send by 8 Oct is 10 days away
    expect(notice.markers).toEqual([
      { date: "2026-10-08", label: "Send by", kind: "send_by" },
      { date: "2026-10-14", label: "Must arrive by", kind: "cancel_by" },
    ]);
    expect(bars.every((b) => b.ref?.id === "ctr_phone")).toBe(true);
  });

  it("shows only the current insurance year, then the renewal", () => {
    const bars = lane("ctr_liability").bars;
    expect(bars[0]).toMatchObject({ label: "Insurance year", start: "2025-12-01", end: "2026-11-30" });
    expect(bars[1]).toMatchObject({ label: "Next insurance year", start: "2026-12-01", end: "2027-11-30" });
    expect(bars[1]!.markers).toEqual([{ date: "2026-12-01", label: "Renews", kind: "renewal" }]);
    expect(bars[2]).toMatchObject({ kind: "notice_window", start: "2027-07-26", end: "2027-08-31", status: "ok" });
  });

  it("marks fixed terms and the earliest possible end of open-ended contracts", () => {
    expect(lane("ctr_job").bars[0]).toMatchObject({ label: "Fixed term", end: "2027-03-31" });
    expect(lane("ctr_gym").bars[0]!.label).toBe("Cancellable any time");
    expect(lane("ctr_gym").markers).toEqual([{ date: "2026-10-28", label: "Earliest end (if you cancel now)", kind: "other" }]);
    expect(lane("ctr_bkk").bars[0]).toMatchObject({ label: "Open-ended", open_end: true });
    expect(lane("ctr_job").bars[0]!.open_end).toBeUndefined();
  });

  it("lays out on the chart: the notice window rides on the term bar", () => {
    const scale = createTimeScale(range.from, range.to, 1200);
    const ly = layoutLane(lane("ctr_phone"), scale, TODAY);
    expect(ly.tracks).toBe(1);
    const notice = ly.bars.find((b) => b.bar.kind === "notice_window")!;
    expect(notice.overlay).toBe(true);
    // send-by and must-arrive-by sit 6 days (15 px) apart: one mark that names both dates
    expect(ly.markers.map((m) => m.primary.marker.kind)).toEqual(["send_by", "other"]);
    expect(ly.markers[0]!.entries.map((e) => e.marker.kind)).toEqual(["send_by", "cancel_by"]);
  });
});
