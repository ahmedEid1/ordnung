import { describe, expect, it } from "vitest";
import { makeDetail, makeDoc, makeItem, makeSuggestion } from "@/features/document/fixtures";
import type { Contract } from "@/api/types";
import { filterCounts, filterDocuments, groupLetters, kindOptions, openItemsByDoc, parseFilter } from "./filters";
import { recapSentence, summarizeBatch } from "./recap";

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

  it("counts letters with something due within 14 days as needing you", () => {
    const soon = makeDetail({ document: makeDoc({ id: "soon" }), items: [makeItem({ due_date: "2026-10-05" })] });
    expect(summarizeBatch([soon], TODAY).needYouDocIds).toEqual(["soon"]);
  });

  it("writes the recap sentence", () => {
    expect(recapSentence(summarizeBatch(details, TODAY)).replace(/\u00a0/g, " ")).toBe(
      "I read 4 letters: 2 deadlines, 1 contract, €94.99/month fixed costs, 1 needs you now, 1 possible scam.",
    );
    expect(recapSentence(summarizeBatch([makeDetail()], TODAY))).toBe("I read 1 letter. Nothing needs you right now.");
  });
});
