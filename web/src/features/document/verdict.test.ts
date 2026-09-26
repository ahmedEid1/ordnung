import { describe, expect, it } from "vitest";
import {
  chooseMainAction,
  decisionSuggestion,
  incomingMoney,
  isOptionalObjection,
  leadsWithDecision,
  needsArrivalDate,
  needsCheck,
  openItemCounts,
  scamSuggestion,
  selectPrimaryItem,
  sortItems,
} from "./verdict";
import { makeDetail, makeDoc, makeItem, makeReceipt, makeSuggestion } from "./fixtures";
import { splitGlossary } from "./glossary-text";

describe("selectPrimaryItem — which to-do the verdict card is about", () => {
  it("returns null when nothing is open", () => {
    expect(selectPrimaryItem([])).toBeNull();
    expect(selectPrimaryItem([makeItem({ status: "done" }), makeItem({ id: "b", status: "dismissed" })])).toBeNull();
  });

  it("prefers open items over closed ones, even if the closed one is more important", () => {
    const done = makeItem({ id: "done", status: "done", priority: "critical", due_date: "2026-09-29" });
    const open = makeItem({ id: "open", priority: "low", due_date: "2026-12-01" });
    expect(selectPrimaryItem([done, open])?.id).toBe("open");
  });

  it("counts missed and snoozed items as still open", () => {
    expect(selectPrimaryItem([makeItem({ id: "m", status: "missed" })])?.id).toBe("m");
  });

  it("ranks by priority first", () => {
    const normalSoon = makeItem({ id: "soon", due_date: "2026-10-01" });
    const highLater = makeItem({ id: "high", priority: "high", due_date: "2026-11-20" });
    expect(selectPrimaryItem([normalSoon, highLater])?.id).toBe("high");
  });

  it("prefers a one-off to-do over a recurring payment of the same priority", () => {
    const rent = makeItem({ id: "rent", kind: "payment", amount: 640, due_date: "2026-10-05", recurrence: { interval: 1, unit: "months" } });
    const notice = makeItem({ id: "notice", kind: "deadline", due_date: "2026-10-31" });
    expect(selectPrimaryItem([rent, notice])?.id).toBe("notice");
  });

  it("prefers dated over undated and the earliest action date (send-by beats due date)", () => {
    const undated = makeItem({ id: "undated", kind: "task" });
    const later = makeItem({ id: "later", due_date: "2026-10-20" });
    const postEarly = makeItem({ id: "post", due_date: "2026-10-31", send_by: "2026-10-15" });
    expect(selectPrimaryItem([undated, later, postEarly])?.id).toBe("post");
    expect(selectPrimaryItem([undated, later])?.id).toBe("later");
  });

  it("breaks ties by kind: deadline before payment before appointment", () => {
    const pay = makeItem({ id: "pay", kind: "payment", due_date: "2026-10-09" });
    const appt = makeItem({ id: "appt", kind: "appointment", due_date: "2026-10-09" });
    const dl = makeItem({ id: "dl", kind: "deadline", due_date: "2026-10-09" });
    expect(selectPrimaryItem([appt, pay, dl])?.id).toBe("dl");
    expect(sortItems([appt, pay, dl]).map((i) => i.id)).toEqual(["dl", "pay", "appt"]);
  });

  it("hides dismissed items from the list but keeps done ones at the end", () => {
    const list = sortItems([makeItem({ id: "x", status: "dismissed" }), makeItem({ id: "d", status: "done" }), makeItem({ id: "o" })]);
    expect(list.map((i) => i.id)).toEqual(["o", "d"]);
  });
});

describe("chooseMainAction", () => {
  const objection = makeItem({ id: "obj", kind: "deadline", due_date: "2026-10-21", date_spec: null });

  it("offers an objection draft only for Einspruch / Widerspruch", () => {
    for (const type of ["einspruch", "widerspruch"] as const) {
      const d = makeDetail({ document: makeDoc({ remedy: { type, addressee: "Finanzamt", period_text: null, form_text: null, quote: null } }), items: [objection] });
      expect(chooseMainAction(d, objection)).toMatchObject({ type: "draft", draftKind: "objection" });
    }
    for (const type of ["klage", "unclear", "none"] as const) {
      const d = makeDetail({ document: makeDoc({ remedy: { type, addressee: null, period_text: null, form_text: null, quote: null } }), items: [objection] });
      expect(chooseMainAction(d, objection).type).toBe("calendar");
    }
  });

  it("never offers Pay for a suspected scam", () => {
    const pay = makeItem({ kind: "payment", amount: 210, due_date: "2026-10-01" });
    const scam = makeSuggestion({ kind: "scam", refs: [{ type: "document", id: "doc_1" }, { type: "document", id: "doc_real" }] });
    const d = makeDetail({ items: [pay], suggestions: [scam] });
    expect(chooseMainAction(d, pay)).toEqual({ type: "scam", realDocId: "doc_real" });
    // a dismissed scam warning no longer blocks paying
    const dismissed = makeDetail({ items: [pay], suggestions: [{ ...scam, status: "dismissed" }] });
    expect(chooseMainAction(dismissed, pay).type).toBe("pay");
  });

  it("drafts a cancellation for a notice deadline on a contract", () => {
    const notice = makeItem({ contract_id: "ctr_1", due_date: "2026-10-31", date_spec: { type: "fixed", date: "2026-10-31", time: null, anchor: null, anchor_date: null, amount: null, unit: null, delivery_rule: "none", shift_rule: "auto", nature: "notice", legal_basis: null, text: "" } });
    expect(chooseMainAction(makeDetail({ items: [notice] }), notice)).toMatchObject({ type: "draft", draftKind: "cancellation" });
  });

  it("pays payments, calendars dated to-dos, otherwise marks done", () => {
    const pay = makeItem({ kind: "payment", amount: 184.3, due_date: "2026-10-09" });
    const incoming = makeItem({ kind: "payment", amount: 324, direction: "in", due_date: "2026-10-09" });
    const appt = makeItem({ kind: "appointment", due_date: "2026-10-08" });
    const task = makeItem({ kind: "task" });
    expect(chooseMainAction(makeDetail(), pay).type).toBe("pay");
    expect(chooseMainAction(makeDetail(), incoming).type).toBe("calendar");
    expect(chooseMainAction(makeDetail(), appt).type).toBe("calendar");
    expect(chooseMainAction(makeDetail(), task).type).toBe("done");
    expect(chooseMainAction(makeDetail(), null).type).toBe("none");
  });
});

describe("what needs the person's eyes", () => {
  it("flags unverified or inconsistent evidence as Please check", () => {
    const e = { doc_id: "doc_1", page: 1, quote: "bis zum 09.10.2026", grounding: "verified" as const, value_consistent: true, score: 1, boxes: [] };
    expect(needsCheck(makeItem({ evidence: [e] }))).toBe(false);
    expect(needsCheck(makeItem({ grounding: "unverified" }))).toBe(true);
    expect(needsCheck(makeItem({ evidence: [{ ...e, value_consistent: false }] }))).toBe(true);
    expect(needsCheck(makeItem({ grounding: "user", evidence: [{ ...e, grounding: "unverified" }] }))).toBe(false);
    expect(needsCheck(makeItem({ grounding: "unverified", status: "done" }))).toBe(false);
  });

  it("asks for the arrival date when a period starts on receipt and we fell back to the letter date", () => {
    const spec = { type: "relative" as const, date: null, time: null, anchor: "receipt" as const, anchor_date: null, amount: 1, unit: "weeks" as const, delivery_rule: "none" as const, shift_rule: "auto" as const, nature: "payment" as const, legal_basis: null, text: "" };
    const it1 = makeItem({ date_spec: spec, computation: makeReceipt({ rule_ids: ["receipt_fallback", "bgb188_weeks"] }) });
    expect(needsArrivalDate(it1, { received_date: null })).toBe(true);
    expect(needsArrivalDate(it1, { received_date: "2026-09-25" })).toBe(true);
    const confirmed = { ...it1, computation: makeReceipt({ rule_ids: ["receipt_user", "bgb188_weeks"] }) };
    expect(needsArrivalDate(confirmed, { received_date: "2026-09-25" })).toBe(false);
    expect(needsArrivalDate(makeItem(), { received_date: null })).toBe(false);
  });

  it("finds the active scam warning", () => {
    expect(scamSuggestion(makeDetail({ suggestions: [makeSuggestion({ kind: "saving" })] }))).toBeNull();
    expect(scamSuggestion(makeDetail({ suggestions: [makeSuggestion({ kind: "scam" })] }))?.kind).toBe("scam");
  });

  it("counts the open to-dos that deleting would remove", () => {
    const items = [makeItem({ kind: "payment" }), makeItem({ kind: "deadline" }), makeItem({ kind: "payment" }), makeItem({ kind: "task", status: "done" })];
    expect(openItemCounts(items)).toEqual([
      { kind: "deadline", count: 1 },
      { kind: "payment", count: 2 },
    ]);
  });
});

describe("glossary terms in explanations", () => {
  it("marks the first occurrence and notices an existing translation", () => {
    const segs = splitGlossary("You can file an Einspruch (objection). The Einspruch is free; see the Bescheid.");
    expect(segs.filter((s) => s.type === "term").map((s) => s.type === "term" && [s.term, s.explained])).toEqual([
      ["Einspruch", true],
      ["Bescheid", false],
    ]);
    expect(segs.map((s) => s.text).join("")).toBe("You can file an Einspruch (objection). The Einspruch is free; see the Bescheid.");
  });

  it("never adds a translation the text already gives", () => {
    const explained = (text: string) => splitGlossary(text).flatMap((s) => (s.type === "term" ? [s.explained] : []));
    expect(explained("File an objection (Einspruch) in writing")).toEqual([true]);
    expect(explained("Increased advance payment (Abschlag)")).toEqual([true]);
    expect(explained("Your contract as a working student (Werkstudent)")).toEqual([true]);
    expect(explained("You can file an Einspruch within a month")).toEqual([false]);
  });

  it("does not match inside longer words", () => {
    expect(splitGlossary("Einspruchsfrist").every((s) => s.type === "text")).toBe(true);
  });
});

describe("dayCountdown", () => {
  it("is precise in days for legal deadlines", async () => {
    const { dayCountdown } = await import("./verdict");
    expect(dayCountdown("2026-10-21", "2026-09-28")).toBe("in 23 days");
    expect(dayCountdown("2026-09-29", "2026-09-28")).toBe("tomorrow");
    expect(dayCountdown("2026-09-28", "2026-09-28")).toBe("today");
    expect(dayCountdown("2026-09-26", "2026-09-28")).toBe("2 days overdue");
    expect(dayCountdown("2026-09-26", "2026-09-28", "event")).toBe("2 days ago");
    expect(dayCountdown("2027-06-01", "2026-09-28")).toBe("in 8 months");
  });
});

describe("the verdict leads with the decision that matters", () => {
  const decision = makeSuggestion({
    id: "sug_price",
    kind: "deadline",
    rule_id: "price_increase_right",
    title: "Stadtwerke raises prices: +€70.20/year extra cost — you may cancel until Sat 31 Oct",
    due_date: "2026-10-26",
    action: { type: "draft", draft_kind: "cancellation", target_type: "contract", target_id: "ctr_power", label: "Draft cancellation" },
  });
  const abschlag = makeItem({ id: "abschlag", kind: "payment", title: "Increased advance payment (Abschlag)", amount: 54, due_date: "2026-11-15", send_by: "2026-11-12" });

  it("a price increase's special right leads, not the new monthly instalment", () => {
    const detail = makeDetail({ items: [abschlag], suggestions: [decision] });
    expect(decisionSuggestion(detail)?.id).toBe("sug_price");
    expect(leadsWithDecision(decision, selectPrimaryItem(detail.items))).toBe(true);
  });

  it("a one-off to-do due before the decision still comes first", () => {
    const fine = makeItem({ id: "fine", kind: "payment", amount: 30, due_date: "2026-10-01" });
    expect(leadsWithDecision(decision, fine)).toBe(false);
  });

  it("never offers Pay for a direct debit", () => {
    const debit = makeItem({ id: "fee", kind: "payment", amount: 34.99, due_date: "2026-10-01", action: "Ensure sufficient funds for the monthly SEPA direct debit of 34.99 €." });
    expect(chooseMainAction(makeDetail({ items: [debit] }), debit).type).not.toBe("pay");
  });

  it("a refund is never 'what you need to do'", () => {
    const refund = makeItem({ id: "refund", kind: "payment", direction: "in", amount: 312.45, due_date: "2026-10-15" });
    const objection = makeItem({ id: "obj", kind: "deadline", due_date: "2026-10-21", date_spec: { ...makeItem().date_spec!, nature: "objection" } });
    expect(selectPrimaryItem([refund])).toBeNull();
    expect(incomingMoney([refund, objection])?.id).toBe("refund");
    expect(isOptionalObjection(objection)).toBe(true);
  });
});
