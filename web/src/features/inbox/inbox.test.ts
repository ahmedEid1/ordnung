import { describe, expect, it } from "vitest";
import { makeDetail, makeDoc, makeItem, makeSuggestion } from "@/features/document/fixtures";
import type { Contract } from "@/api/types";
import { filterCounts, filterDocuments, groupLetters, inboxDateInfo, kindOptions, openItemsByDoc, parseFilter, pinJustRead } from "./filters";
import { dueSoon, recapSentence, recapTitle, summarizeBatch } from "./recap";

const TODAY = "2026-09-28";

describe("inbox filters", () => {
  const docs = [
    makeDoc({ id: "a", kind: "tax_assessment", received_date: "2026-09-28" }),
    makeDoc({ id: "b", kind: "fine", status: "needs_review", received_date: "2026-09-25" }),
    makeDoc({ id: "c", kind: "invoice", ai_private: true, received_date: "2026-08-20" }),
    makeDoc({ id: "d", kind: "invoice", status: "failed", received_date: "2025-12-02" }),
    makeDoc({ id: "e", kind: "invoice", deleted_at: "2026-09-01T10:00:00Z" }),
  ];

  it("filters by Please check / Private / kind and ignores trashed letters", () => {
    expect(filterDocuments(docs, { filter: "all" }).map((d) => d.id)).toEqual(["a", "b", "c", "d"]);
    expect(filterDocuments(docs, { filter: "check" }).map((d) => d.id)).toEqual(["b", "d"]);
    expect(filterDocuments(docs, { filter: "private" }).map((d) => d.id)).toEqual(["c"]);
    expect(filterDocuments(docs, { filter: "all", kind: "invoice" }).map((d) => d.id)).toEqual(["c", "d"]);
    expect(filterCounts(docs)).toEqual({ all: 4, check: 2, private: 1 });
  });

  it("parses the filter from the URL safely", () => {
    expect(parseFilter("check")).toBe("check");
    expect(parseFilter("needs_review")).toBe("all");
    expect(parseFilter(null)).toBe("all");
  });

  it("offers only kinds that exist, with human labels", () => {
    const opts = kindOptions(docs);
    expect(opts.map((o) => o.label)).toEqual(["Fine", "Invoice", "Tax assessment"]);
    expect(opts.find((o) => o.value === "invoice")?.count).toBe(3);
  });

  it("groups newest first: being read, this week, then months", () => {
    const reading = makeDoc({ id: "r", status: "processing", received_date: "2026-09-28", kind: null });
    const groups = groupLetters([...docs.slice(0, 4), reading], TODAY);
    expect(groups.map((g) => [g.label, g.docs.map((d) => d.id)])).toEqual([
      ["Being read", ["r"]],
      ["Last 7 days", ["a", "b"]],
      ["August", ["c"]],
      ["December 2025", ["d"]],
    ]);
  });

  it("pins letters read from New mail on top ('Just read'), after the ones being read", () => {
    const reading = makeDoc({ id: "r", status: "processing", received_date: "2026-09-28", kind: null });
    const groups = groupLetters([...docs.slice(0, 4), reading], TODAY);
    // "c" arrived in August, but it just came out of the New-mail tray
    expect(pinJustRead(groups, new Set(["c", "r", "gone"])).map((g) => [g.label, g.docs.map((d) => d.id)])).toEqual([
      ["Being read", ["r"]],
      ["Just read", ["c"]],
      ["Last 7 days", ["a", "b"]],
      ["December 2025", ["d"]],
    ]);
    expect(pinJustRead(groups.slice(1), new Set(["a"])).map((g) => g.label)).toEqual(["Just read", "Last 7 days", "August", "December 2025"]);
    // nothing to pin: the very same groups
    expect(pinJustRead(groups, new Set())).toBe(groups);
    expect(pinJustRead(groups, new Set(["r", "zzz"]))).toBe(groups);
  });

  it("dates a row by its arrival (the grouping date) and keeps the letter's own date aside", () => {
    expect(inboxDateInfo(makeDoc({ received_date: "2026-09-02", doc_date: "2026-08-31" }))).toEqual({ date: "2026-09-02", verb: "Arrived", docDate: "2026-08-31" });
    expect(inboxDateInfo(makeDoc({ received_date: "2026-09-02", doc_date: "2026-09-02" }))).toEqual({ date: "2026-09-02", verb: "Arrived", docDate: null });
    expect(inboxDateInfo(makeDoc({ received_date: null, doc_date: null, created_at: "2026-09-26T08:00:00Z" }))).toEqual({ date: "2026-09-26", verb: "Added", docDate: null });
    // review round 2: a court order's day is the one it was delivered, as everywhere else
    expect(inboxDateInfo(makeDoc({ kind: "court_payment_order", received_date: "2026-09-24", doc_date: "2026-09-21" })).verb).toBe("Delivered");
    // review round 3 of phase 2: a letter of another kind whose to-do counts from formal service, as its page says
    const served = openItemsByDoc([
      makeItem({ id: "s", doc_id: "v", computation: { due_date: "2026-10-08", rule_ids: ["zpo_180", "zpo_222"], steps: [], warnings: [], summary: "", confidence: "medium", send_by: null, safe_date: null, holiday_calendar: "" } }),
    ]).get("v");
    expect(served?.served).toBe(true);
    expect(inboxDateInfo(makeDoc({ kind: "authority_letter", received_date: "2026-09-24" }), served?.served).verb).toBe("Delivered");
    expect(inboxDateInfo(makeDoc({ kind: "authority_letter", received_date: "2026-09-24" })).verb).toBe("Arrived");
  });

  it("counts open to-dos per letter and finds the next one", () => {
    const m = openItemsByDoc([
      makeItem({ id: "1", doc_id: "a", due_date: "2026-10-21", send_by: "2026-10-15" }),
      makeItem({ id: "2", doc_id: "a", due_date: "2026-10-10" }),
      makeItem({ id: "3", doc_id: "a", status: "done", due_date: "2026-09-29" }),
      makeItem({ id: "4", doc_id: null }),
    ]);
    expect(m.get("a")).toMatchObject({ count: 2, next: { id: "2" } });
    expect(m.size).toBe(1);
  });
});

describe("batch recap", () => {
  const contract = { id: "ctr_1", status: "active", cost_amount: 34.99, cost_interval: "monthly" } as Contract;
  const details = [
    makeDetail({
      document: makeDoc({ id: "tax" }),
      items: [makeItem({ kind: "deadline", due_date: "2026-10-21", send_by: "2026-10-15" })],
    }),
    makeDetail({
      document: makeDoc({ id: "power" }),
      items: [
        makeItem({ id: "n", kind: "deadline", due_date: "2026-10-31", contract_id: "ctr_power" }),
        makeItem({ id: "p", kind: "payment", amount: 55, due_date: "2026-11-15", recurrence: { interval: 1, unit: "months" }, contract_id: "ctr_power" }),
      ],
    }),
    makeDetail({
      document: makeDoc({ id: "scam", status: "needs_review" }),
      suggestions: [makeSuggestion({ kind: "scam" })],
    }),
    makeDetail({ document: makeDoc({ id: "phone" }), contracts: [contract], items: [makeItem({ kind: "payment", amount: 60, recurrence: { interval: 1, unit: "years" } })] }),
  ];

  it("summarises deadlines, contracts, fixed costs, what needs you and scams", () => {
    const r = summarizeBatch(details, TODAY);
    expect(r).toMatchObject({ letters: 4, deadlines: 2, contracts: 1, needYou: 1, scams: 1, scamDocId: "scam", needYouDocIds: ["scam"] });
    // 55 €/month (power) + 34,99 € (phone contract) + 60 €/year = 5 €/month
    expect(r.fixedCostsMonthly).toBeCloseTo(94.99, 2);
  });

  it("counts as 'need you now' exactly the letters its tile leads to (Please check), and what is due soon apart", () => {
    const soon = makeDetail({ document: makeDoc({ id: "soon" }), items: [makeItem({ due_date: "2026-10-20" }), makeItem({ id: "i2", send_by: "2026-10-05", due_date: "2026-10-09" })] });
    const later = makeDetail({ document: makeDoc({ id: "later" }), items: [makeItem({ due_date: "2026-11-30" })] });
    const check = makeDetail({ document: makeDoc({ id: "check", status: "needs_review" }) });
    const failed = makeDetail({ document: makeDoc({ id: "failed", status: "failed" }) });
    const batch = [soon, later, check, failed];
    const r = summarizeBatch(batch, TODAY);
    // the tile opens /inbox?filter=check: the same letters the filter lists
    const listed = filterDocuments(batch.map((d) => d.document), { filter: "check" }).map((d) => d.id);
    expect(r.needYouDocIds).toEqual(listed);
    expect(r).toMatchObject({ needYou: 2, dueSoon: 1, dueSoonDocIds: ["soon"] });
    // the earliest open date (send-by before due) — shown on the letter in the recap
    expect(dueSoon(soon, TODAY)).toBe("2026-10-05");
    expect(dueSoon(later, TODAY)).toBeNull();
    expect(recapSentence(r)).toBe("I read 4 letters: 3 deadlines, 2 need you now, 1 due within 2 weeks.");
  });

  it("titles the recap with the letters that couldn't be read", () => {
    expect(recapTitle(3, 0)).toBe("I read 3 letters");
    expect(recapTitle(3, 1)).toBe("I read 2 of 3 letters");
    expect(recapTitle(2, 2)).toBe("I couldn't read 2 letters");
  });

  it("writes the recap sentence", () => {
    expect(recapSentence(summarizeBatch(details, TODAY)).replace(/\u00a0/g, " ")).toBe(
      "I read 4 letters: 2 deadlines, 1 contract, €94.99/month fixed costs, 1 needs you now, 1 possible scam.",
    );
    expect(recapSentence(summarizeBatch([makeDetail()], TODAY))).toBe("I read 1 letter. Nothing needs you right now.");
  });
});
