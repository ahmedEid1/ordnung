import { describe, expect, it } from "vitest";
import type { Contract, ContractRegime } from "@/api/types";
import { CONTRACT_REGIMES } from "@/api/types";
import { assertNoRawEnums } from "@/lib/copy";
import { CONTRACTS } from "@/mocks/data/contracts";
import { contract } from "@/mocks/data/helpers";
import { layoutLane } from "@/features/lanes/layout";
import { addDaysISO, createTimeScale, defaultLaneRange } from "@/features/lanes/scale";
import {
  contractLaneNote,
  contractLanes,
  decideBy,
  filterByStatus,
  fixedCosts,
  isFixedTerm,
  isLockInDecision,
  isRollingContract,
  nextActionDate,
  noticeDayPhrase,
  noticeEditable,
  noticeFromYou,
  noticePhrase,
  pleaseCheckHint,
  ruleInWords,
  sortContracts,
  termsUnclear,
} from "./model";
import { composerHrefFor } from "./links";

const TODAY = "2026-09-28";
const byId = (id: string) => CONTRACTS.find((c) => c.id === id)!;

describe("fixed costs", () => {
  it("sums the monthly cost of every active contract (yearly / 12, quarterly / 3)", () => {
    const costs = fixedCosts(CONTRACTS);
    // 640 + 34,99 + 48 + 29,90 + 59,90/12 + 142,86 + 63 + 4,90 + 55,08/3
    expect(costs.monthly).toBe(987);
    // a year from each contract's own amount: €59.90 a year is €59.90 (not 4.99 × 12 = €59.88)
    expect(costs.yearly).toBe(11844.02);
    expect(costs.counted).toBe(9);
    expect(costs.unknown).toBe(0); // the job pays you — not counted as unknown
    expect(costs.jobs).toBe(1);
  });

  it("sums each currency on its own (a $20 subscription is not €20 of the fixed costs)", () => {
    const cloud = { ...byId("ctr_phone"), id: "ctr_cloud", cost_amount: 20, cost_currency: "USD", cost_interval: "monthly" as const };
    const costs = fixedCosts([...CONTRACTS, cloud]);
    expect(costs.monthly).toBe(987);
    expect(costs.monthlyTotals).toEqual({ EUR: 987, USD: 20 });
    expect(costs.yearlyTotals).toEqual({ EUR: 11844.02, USD: 240 });
    expect(costs.counted).toBe(10);
  });

  it("never counts a job as a cost, even when its letter names the pay", () => {
    const paid = CONTRACTS.map((c) => (c.id === "ctr_job" ? { ...c, cost_amount: 1200, cost_interval: "monthly" as const } : c));
    const costs = fixedCosts(paid);
    expect(costs.monthly).toBe(987);
    expect([costs.counted, costs.unknown, costs.jobs]).toEqual([9, 0, 1]);
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

  it("a fixed-term job its contract lets you leave earlier: its notice's date locks nothing in (migration 0004)", () => {
    // as the rules engine computes it for Sam (Mon 28 Sep 2026): four weeks to the end of October, else it
    // ends by itself on Wed 31 Mar 2027
    const job: Contract = {
      ...byId("ctr_job"),
      computed: { ...byId("ctr_job").computed!, cancel_by: "2026-10-03", safe_date: "2026-10-02", send_by: "2026-09-28", earliest_exit: "2026-10-31" },
    };
    expect(job.computed!.current_term_end).toBe("2027-03-31");
    expect(isRollingContract(job)).toBe(true);
    expect(isLockInDecision(job)).toBe(false);
    expect(decideBy([job], TODAY)).toEqual([]);
    expect(nextActionDate(job, TODAY)).toBeNull();
    expect(isFixedTerm(job)).toBe(true); // … and it still ends by itself on its date
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
    // a fixed-term job ends by itself; leaving earlier by notice needs a clause that allows it (§ 15 Abs. 4
    // TzBfG, `notice_before_end`): then the notice the contract names (at least the statutory one), or the
    // statutory one — without the clause no notice is promised, whatever period the letter names
    expect(ruleInWords(byId("ctr_job"), TODAY).text).toBe("Fixed term until 31 Mar 2027 — it ends by itself. To leave earlier: 4 weeks' notice, at least the legal minimum");
    expect(ruleInWords({ ...byId("ctr_job"), notice_value: null, notice_unit: null }, TODAY).text).toBe(
      "Fixed term until 31 Mar 2027 — it ends by itself. To leave earlier: the statutory notice",
    );
    expect(ruleInWords({ ...byId("ctr_job"), notice_before_end: false }, TODAY).text).toBe("Fixed term until 31 Mar 2027 — it ends by itself, no notice needed");
    // a current account (walkthrough of phase 2: "we couldn't compute a cancellation date")
    const giro = byId("ctr_bank");
    const account: Contract = { ...giro, computed: { ...giro.computed!, regime: "bgb675h" } };
    expect(ruleInWords(account, TODAY)).toEqual({ text: "Current account: cancellable any time, without notice", citation: "§ 675h BGB" });
    expect(ruleInWords({ ...account, notice_value: 2, notice_unit: "weeks" }, TODAY).text).toBe(
      "Current account: cancellable any time with 2 weeks' notice (at most one month counts)",
    );
    // "as written" without notice terms falls back to the engine's own first sentence
    const ticket = byId("ctr_dticket");
    const written: Contract = {
      ...ticket,
      notice_day: null,
      computed: { ...ticket.computed!, regime: "as_written", summary: "Cancel by the 10th of a month to end it at the end of that month — next: by Sat 10 Oct for 31 Oct." },
    };
    expect(ruleInWords(written, TODAY)).toEqual({
      text: "Cancel by the 10th of a month to end it at the end of that month — next: by Sat 10 Oct for 31 Oct",
      citation: null,
    });
  });

  it("reads the contract's own day of the month where the rules do: by the 10th, to the month's end (migration 0004)", () => {
    // the Deutschlandticket: "Die Kündigung muss bis zum 10. eines Monats zum Ende dieses Monats bei uns eingehen"
    const ticket: Contract = byId("ctr_dticket");
    expect(ticket.notice_day).toBe(10);
    expect(noticeDayPhrase(ticket)).toBe("by the 10th of the month, to the month's end");
    expect(ruleInWords(ticket, TODAY)).toEqual({
      text: "Cancellable by the 10th of the month, to the month's end (consumer contract since March 2022)",
      citation: "§ 309 Nr. 9 BGB",
    });
    expect([1, 2, 3, 11, 21, 22, 23, 31].map((d) => noticeDayPhrase({ ...ticket, notice_day: d })!.split(" ")[2])).toEqual([
      "1st", "2nd", "3rd", "11th", "21st", "22nd", "23rd", "31st",
    ]);
    // a notice period read with it applies too (the person's own terms clear the day), and another basis is no
    // month-end rule
    expect(noticeDayPhrase({ ...ticket, notice_value: 10, notice_unit: "days" })).toBe("with 10 days' notice by the 10th of the month, to the month's end");
    expect(ruleInWords({ ...ticket, notice_value: 10, notice_unit: "days" }, TODAY).text).toBe(
      "Cancellable with 10 days' notice by the 10th of the month, to the month's end (consumer contract since March 2022)",
    );
    // limited to a month, as the rules limit it after the first term
    expect(ruleInWords({ ...ticket, notice_value: 3, notice_unit: "months" }, TODAY).text).toBe(
      "Cancellable with 1 month's notice by the 10th of the month, to the month's end (consumer contract since March 2022)",
    );
    expect(noticeDayPhrase({ ...ticket, notice_basis: "any_time" })).toBeNull();
    const withComp = (regime: ContractRegime, extra: Partial<Contract> = {}): Contract => ({
      ...ticket,
      ...extra,
      computed: { ...ticket.computed!, regime },
    });
    expect(ruleInWords(withComp("bgb309_old"), TODAY).text).toBe("Cancellable by the 10th of the month, to the month's end (consumer contract from before March 2022)");
    expect(ruleInWords(withComp("tkg56"), TODAY).text).toBe("Cancellable by the 10th of the month, to the month's end (phone & internet contract after its minimum term)");
    expect(ruleInWords(withComp("as_written"), TODAY).text).toBe("As written in the contract: cancellable by the 10th of the month, to the month's end");
    expect(ruleInWords(withComp("as_written", { notice_value: 3, notice_unit: "months" }), TODAY).text).toBe(
      "As written in the contract: cancellable with 3 months' notice by the 10th of the month, to the month's end",
    );
    // entered on the card, the day is the person's (the API's `entered_notice`)
    const mine = { doc_id: "doc_dticket", page: null, quote: "notice by the 10th of the month, to the end of that month", grounding: "user" as const, value_consistent: true, score: 0, boxes: [] };
    expect(ruleInWords(withComp("as_written", { evidence: [mine] }), TODAY).text).toBe("As you entered it: cancellable by the 10th of the month, to the month's end");
    const inFirstTerm = withComp("bgb309_new", { initial_term_months: 12 });
    inFirstTerm.computed = { ...inFirstTerm.computed!, current_term_end: "2027-01-31" };
    expect(ruleInWords(inFirstTerm, TODAY).text).toBe(
      "Minimum term until 31 Jan 2027; after that cancellable by the 10th of the month, to the month's end (consumer contract since March 2022)",
    );
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

  it("draws no window to cancel once the cancellation was sent, only when it ends (final review)", () => {
    const phone: Contract = { ...byId("ctr_phone"), cancellation_sent: { draft_id: "drf_1", sent_on: "2026-09-28", channel: "registered_letter" } };
    const [l] = contractLanes([phone], range, TODAY);
    expect(l!.bars.map((b) => b.kind)).toEqual(["contract", "contract"]);
    expect(l!.markers).toEqual([{ date: phone.computed!.earliest_exit, label: "Ends (cancellation sent)", kind: "other" }]);
    expect(contractLaneNote(phone, TODAY)).toEqual({ text: "Cancellation sent", tone: "muted" });
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

  const unset = { cancel_by: null, send_by: null, safe_date: null, next_renewal: null, current_term_end: null, earliest_exit: null };

  it("draws a contract whose end date is only the end of its minimum term as running on, not ending", () => {
    // the demo's electricity contract: its end date is the end of the 12-month minimum term, and
    // after it the contract continues month by month (§ 309 Nr. 9 BGB) — nothing ends in 2 days
    const power = contract({
      id: "ctr_power2",
      name: "Stromliefervertrag MusterStrom Flex",
      category: "energy",
      start_date: "2025-10-01",
      initial_term_months: 12,
      renewal_term_months: 0,
      end_date: "2026-09-30",
      computed: {
        ...byId("ctr_phone").computed!,
        ...unset,
        regime: "bgb309_new",
        current_term_end: "2026-09-30",
        next_renewal: "2026-10-01",
        earliest_exit: "2026-11-02",
      },
    });
    expect(isFixedTerm(power)).toBe(false);
    const [l] = contractLanes([power], range, TODAY);
    expect(l!.bars.map((b) => [b.label, b.start, b.end])).toEqual([
      ["Minimum term", "2025-10-01", "2026-09-30"],
      ["Cancellable any time", "2026-10-01", addDaysISO(range.to, 1)],
    ]);
    expect(l!.bars.flatMap((b) => b.markers).map((m) => m.kind)).not.toContain("expiry");
    expect(l!.markers).toEqual([{ date: "2026-11-02", label: "Earliest end (if you cancel now)", kind: "other" }]);
    // under its name: when it could end at the earliest, not "Minimum term ends · in 2 days"
    expect(contractLaneNote(power, TODAY)).toEqual({ text: "Earliest end · 2 Nov", tone: "muted" });

    // a job with an end date does end by itself — the chart's own "Ends 31 Mar 2027" says so
    expect(isFixedTerm(byId("ctr_job"))).toBe(true);
    expect(contractLaneNote(byId("ctr_job"), TODAY)).toBeNull();
    // a decision to make keeps the chart's "Send by 8 Oct · in 10 days"
    expect(contractLaneNote(byId("ctr_phone"), TODAY)).toBeNull();
  });

  it("draws terms it couldn't work out as unclear, not as cancellable any time", () => {
    const giro = contract({
      id: "ctr_giro",
      name: "Girokonto Klassik",
      category: "bank",
      notice_basis: "any_time",
      cost_amount: 4.9,
      cost_interval: "monthly",
      computed: { ...byId("ctr_phone").computed!, ...unset, regime: "as_written", confidence: "low" },
    });
    expect(termsUnclear(giro)).toBe(true);
    const [l] = contractLanes([giro], range, TODAY);
    expect(l!.bars.map((b) => [b.label, b.status, b.open_end])).toEqual([["Terms unclear", "ok", true]]);
    expect(contractLaneNote(giro, TODAY)).toEqual({ text: "Check the letter", tone: "warn" });
    // sure enough of the terms, or a date worked out: not unclear
    expect(termsUnclear({ ...giro, computed: { ...giro.computed!, confidence: "medium" } })).toBe(false);
    expect(termsUnclear({ ...giro, computed: { ...giro.computed!, earliest_exit: "2026-10-31" } })).toBe(false);
  });

  it("says why it asks 'Please check', keeps the notice period correctable, and asks nothing of the person's own entry", () => {
    const base = { ...byId("ctr_phone").computed!, ...unset, regime: "as_written" as const, confidence: "low" as const };
    const giro = contract({ id: "ctr_giro", name: "Girokonto Klassik", category: "bank", computed: base });
    expect(pleaseCheckHint(giro)).toMatch(/^Ordnung couldn't work out how this contract ends/);
    const written = { ...giro, notice_value: 3, notice_unit: "months" as const, notice_basis: "end_of_month" as const, computed: { ...base, earliest_exit: "2026-12-31" } };
    expect(pleaseCheckHint(written)).toBe("Ordnung follows the notice period as written — check it against the contract");
    expect(noticeEditable(written)).toBe(true);
    expect(ruleInWords(written, TODAY).text).toBe("As written in the contract: 3 months' notice to the end of a month");
    // R2-inbox-timeline-contracts-1: saved on the card, the period is the person's
    const quote = { doc_id: "doc_bank", page: null, quote: "three months' notice to the end of a month", grounding: "user" as const, value_consistent: true, score: 0, boxes: [] };
    const entered = { ...written, evidence: [quote] };
    expect(noticeFromYou(entered)).toBe(true);
    expect(pleaseCheckHint(entered)).toBeNull();
    expect(noticeEditable(entered)).toBe(true);
    expect(ruleInWords(entered, TODAY).text).toBe("As you entered it: 3 months' notice to the end of a month");
    // a statutory rule with sure dates: nothing to enter, nothing to check
    expect(noticeEditable(byId("ctr_phone"))).toBe(false);
    // the terms a notice period can't say stay correctable, as a misreading can get them wrong (migration 0004): the
    // contract's own day of the month where the rules read it, and a fixed-term job's early notice, either way
    expect(noticeEditable(byId("ctr_dticket"))).toBe(true);
    expect(noticeEditable({ ...byId("ctr_dticket"), notice_basis: "any_time" })).toBe(false);
    const insurance = byId("ctr_liability");
    expect(noticeEditable({ ...insurance, notice_day: 10, notice_basis: "end_of_month" })).toBe(false); // § 11 VVG reads no day
    expect(noticeEditable(byId("ctr_job"))).toBe(true);
    const endsByItself: Contract = { ...byId("ctr_job"), notice_before_end: false };
    expect(noticeEditable(endsByItself)).toBe(true);
    expect(noticeEditable({ ...byId("ctr_job"), end_date: null })).toBe(false);
    expect(noticeEditable({ ...byId("ctr_dticket"), status: "cancelled" })).toBe(false);
    expect(pleaseCheckHint(byId("ctr_phone"))).toBeNull();
    expect(pleaseCheckHint({ ...byId("ctr_phone"), computed: { ...byId("ctr_phone").computed!, confidence: "low" } })).toBe(
      "Ordnung isn't sure of these dates — check them against the contract",
    );
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
