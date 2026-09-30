import { describe, expect, it } from "vitest";
import type { Draft, Item } from "@/api/types";
import {
  arrivalSavedNote,
  asideItems,
  chooseMainAction,
  consequenceWords,
  existingDraft,
  hasLongWord,
  plainLead,
  usesLaw,
  verdictWords,
  decisionSuggestion,
  incomingMoney,
  isOptionalObjection,
  isServed,
  leadsWithDecision,
  isSettled,
  isLetterSettled,
  consentDecided,
  mayNotBeOwed,
  notOwedReason,
  needsArrivalDate,
  needsCheck,
  openItemCounts,
  otherLawDeadlines,
  scamSuggestion,
  selectPrimaryItem,
  sortItems,
} from "./verdict";
import { makeDetail, makeDoc, makeItem, makeReceipt, makeSuggestion } from "./fixtures";
import { splitGlossary } from "./glossary-text";
import { isGermanText } from "./fact-text";

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
    const rent = makeItem({ id: "rent", kind: "payment", amount: 640, due_date: "2026-10-05", recurrence: { interval: 1, unit: "months", working_day: null, day_of_month: null } });
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

  it("doesn't lead with Pay for a back-payment that may not be owed (a late operating-cost statement)", () => {
    const pay = makeItem({ kind: "payment", amount: 120, due_date: "2026-09-30", computation: makeReceipt({ rule_ids: ["date_as_written", "bgb_556_3"] }) });
    expect(mayNotBeOwed(pay, null)).toBe(true);
    expect(chooseMainAction(makeDetail({ items: [pay] }), pay).type).toBe("calendar");
    // an undated one is caught by the letter's urgent card
    const undated = makeItem({ kind: "payment", amount: 120 });
    const card = { kind: "operating_costs", urgent: true } as NonNullable<Parameters<typeof mayNotBeOwed>[1]>;
    expect(mayNotBeOwed(undated, card)).toBe(true);
    expect(mayNotBeOwed(undated, { ...card, urgent: false })).toBe(false);
    expect(mayNotBeOwed(makeItem({ kind: "deadline", computation: makeReceipt({ rule_ids: ["bgb_556_3"] }) }), card)).toBe(false);
  });

  it("never says a late statement's credit or new monthly prepayment may not be owed", () => {
    const card = { kind: "operating_costs", urgent: true } as NonNullable<Parameters<typeof mayNotBeOwed>[1]>;
    const credit = makeItem({ kind: "payment", amount: 85, direction: "in", computation: makeReceipt({ rule_ids: ["bgb_556_3"] }) });
    const prepayment = makeItem({ kind: "payment", amount: 210, recurrence: { interval: 1, unit: "months", working_day: null, day_of_month: null }, computation: makeReceipt({ rule_ids: ["bgb_556_3"] }) });
    expect(notOwedReason(credit, card)).toBeNull();
    expect(notOwedReason(prepayment, card)).toBeNull();
    expect(notOwedReason(makeItem({ kind: "payment", amount: 120 }), card)).toBe("late_statement");
  });

  it("holds a rent increase's new rent until the person agrees", () => {
    const rent = makeItem({ kind: "payment", amount: 670, due_date: "2026-12-01", recurrence: { interval: 1, unit: "months", working_day: null, day_of_month: null }, computation: makeReceipt({ rule_ids: ["bgb_558b"] }) });
    expect(notOwedReason(rent, null)).toBe("consent");
    const card = { kind: "rent_increase", urgent: false } as NonNullable<Parameters<typeof mayNotBeOwed>[1]>;
    // review round 2: the note is the server's, on the new rent alone (dated or not) — never the current rent
    expect(notOwedReason(makeItem({ kind: "payment", amount: 670, computation: makeReceipt({ rule_ids: ["bgb_558b"] }) }), card)).toBe("consent");
    expect(notOwedReason(makeItem({ kind: "payment", amount: 640, recurrence: { interval: 1, unit: "months", working_day: null, day_of_month: null } }), card)).toBeNull();
    expect(notOwedReason(makeItem({ kind: "payment", amount: 30, direction: "in" }), card)).toBeNull();
    expect(chooseMainAction(makeDetail({ items: [rent] }), rent).type).toBe("calendar");
  });

  it("holds a rent increase's new rent only until the person closed the consent decision", () => {
    const rent = makeItem({ id: "rent", kind: "payment", amount: 670, recurrence: { interval: 1, unit: "months", working_day: null, day_of_month: null }, computation: makeReceipt({ rule_ids: ["bgb_558b"] }) });
    const decision = makeItem({ id: "consent", origin: "rule", computation: makeReceipt({ rule_ids: ["bgb_558b"] }) });
    expect(consentDecided([rent])).toBe(false); // no decision to-do: still hold the rent
    expect(consentDecided([rent, decision])).toBe(false);
    expect(notOwedReason(rent, null, [rent, decision])).toBe("consent");
    const done = { ...decision, status: "done" as const };
    expect(consentDecided([rent, done])).toBe(true);
    // final review 3: decided — but which way isn't known, so the new rent is owed only if they agreed, and
    // "Pay" never leads (paying it can count as agreeing, § 558b Abs. 1 BGB)
    expect(notOwedReason(rent, null, [rent, done])).toBe("if_agreed");
    const dismissed = { ...decision, status: "dismissed" as const };
    expect(consentDecided([rent, dismissed])).toBe(true);
    const dated = { ...rent, due_date: "2026-12-01" };
    for (const closed of [done, dismissed]) {
      expect(chooseMainAction(makeDetail({ items: [dated, closed] }), dated).type).toBe("calendar");
    }
    // the rent payment itself (which cites § 558b for its note) is no decision
    expect(consentDecided([{ ...rent, status: "done" as const }])).toBe(false);
  });

  it("a high-stakes letter is settled as its card says, any other once every to-do is closed", () => {
    const done = makeItem({ status: "done" });
    const card = { kind: "landlord_notice", urgent: true, handled: false } as NonNullable<Parameters<typeof isLetterSettled>[0]["advice"]>;
    expect(isLetterSettled({ advice: card, items: [done] })).toBe(false); // the paid arrears of a fristlos notice
    expect(isLetterSettled({ advice: { ...card, handled: true }, items: [makeItem({ status: "open" })] })).toBe(true);
    expect(isLetterSettled({ advice: null, items: [done] })).toBe(true);
    expect(isLetterSettled({ advice: null, items: [] })).toBe(false);
  });

  it("settles a letter once the person closed every to-do it has", () => {
    const done = makeItem({ status: "done" });
    expect(isSettled([done, makeItem({ status: "dismissed" })])).toBe(true);
    expect(isSettled([done, makeItem({ status: "open" })])).toBe(false);
    expect(isSettled([done, makeItem({ status: "missed" })])).toBe(false);
    expect(isSettled([])).toBe(false); // no to-do was ever filed (a notice without notice period)
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

  it("asks for the arrival date when the engine counted a private sender's letter from its arrival", () => {
    // read as deemed delivery, but a company's letter has none: the engine counts from arrival (§ 130 BGB)
    const spec = { type: "relative" as const, date: null, time: null, anchor: "deemed_delivery" as const, anchor_date: null, amount: 14, unit: "days" as const, delivery_rule: "de_admin_post" as const, shift_rule: "auto" as const, nature: "payment" as const, legal_basis: null, text: "" };
    const company = makeItem({ date_spec: spec, computation: makeReceipt({ rule_ids: ["private_sender_arrival", "bgb_187_1"], confidence: "low" }) });
    expect(needsArrivalDate(company, { received_date: null })).toBe(true);
    expect(needsArrivalDate(company, { received_date: "2026-09-25" })).toBe(false);
    expect(needsArrivalDate({ ...company, status: "done" }, { received_date: null })).toBe(false);
    // an authority's letter keeps its deemed delivery: nothing to ask
    const authority = { ...company, computation: makeReceipt({ rule_ids: ["posting_day", "vwvfg_41_2"] }) };
    expect(needsArrivalDate(authority, { received_date: null })).toBe(false);
  });

  it("asks for the arrival date for a private sender's letter whose date is missing too", () => {
    // the engine could compute no date (it needs the arrival day), but still says which rule it applied
    const spec = { type: "relative" as const, date: null, time: null, anchor: "deemed_delivery" as const, anchor_date: null, amount: 4, unit: "weeks" as const, delivery_rule: "de_admin_post" as const, shift_rule: "auto" as const, nature: "objection" as const, legal_basis: null, text: "" };
    const undated = makeItem({ date_spec: spec, due_date: null, send_by: null, computation: makeReceipt({ due_date: null, send_by: null, rule_ids: ["private_sender_arrival"], confidence: "low" }) });
    expect(needsArrivalDate(undated, { received_date: null })).toBe(true);
    // the rule id asks, not the stored reading: deemed delivery alone never does
    const silent = { ...undated, computation: makeReceipt({ due_date: null, send_by: null, rule_ids: [], confidence: "low" }) };
    expect(needsArrivalDate(silent, { received_date: null })).toBe(false);
  });

  it("says what saving the arrival day did, from the recomputed to-dos", () => {
    // reviewer repro: a company's letter dated Fri 18 Sep arrived Tue 22 Sep; the engine still counts
    // from Mon 21 Sep, when it would usually count as delivered — "Counting from 22 Sep" was false
    const late = { label: "It arrived on Tue 22 Sep 2026, later than …", date: "2026-09-21", rule_id: "private_sender_late_arrival", citation: null };
    const capped = makeItem({ id: "itm_a", title: "Pay the invoice", computation: makeReceipt({ rule_ids: ["private_sender_late_arrival", "bgb_187_1"], steps: [late], confidence: "medium" }) });
    const counted = makeItem({ id: "itm_b", title: "Object", computation: makeReceipt({ rule_ids: ["private_sender_arrival", "bgb_187_1"] }) });
    expect(arrivalSavedNote("2026-09-22", [counted])).toBe("Counting from Tue 22 Sep, when the letter arrived.");
    expect(arrivalSavedNote("2026-09-22", [capped])).toBe(
      "The letter arrived later than letters usually take, so to be safe we still count from Mon 21 Sep, when it would usually count as delivered. See “Why this date?”.",
    );
    expect(arrivalSavedNote("2026-09-22", [counted, capped])).toBe(
      "Counting from Tue 22 Sep, when the letter arrived — but for “Pay the invoice” the letter arrived later than letters usually take, so to be safe we still count from Mon 21 Sep, when it would usually count as delivered. See “Why this date?”.",
    );
    const other = { ...capped, id: "itm_c" };
    expect(arrivalSavedNote("2026-09-22", [counted, capped, other])).toMatch(/^Counting from Tue 22 Sep, when the letter arrived — but for 2 of these dates the letter/);
    // without the step's date: no made-up day
    const bare = { ...capped, computation: makeReceipt({ rule_ids: ["private_sender_late_arrival"] }) };
    expect(arrivalSavedNote("2026-09-22", [bare])).toContain("we still count from an earlier day, when");
  });

  it("does not ask for the arrival date when a private sender's period runs from a date the letter gives", () => {
    // "14 days from the invoice date" read with a delivery rule: the rule goes, the invoice date stays,
    // so the arrival day would change nothing (the engine says private_sender_no_delivery)
    const spec = { type: "relative" as const, date: null, time: null, anchor: "document_date" as const, anchor_date: null, amount: 14, unit: "days" as const, delivery_rule: "de_admin_post" as const, shift_rule: "auto" as const, nature: "payment" as const, legal_basis: null, text: "" };
    const invoice = makeItem({ date_spec: spec, computation: makeReceipt({ rule_ids: ["private_sender_no_delivery", "bgb_187_1"] }) });
    expect(needsArrivalDate(invoice, { received_date: null })).toBe(false);
  });

  it("asks for a court order's delivery date whatever anchor its period was read with", () => {
    const spec = { type: "relative" as const, date: null, time: null, anchor: "document_date" as const, anchor_date: null, amount: 2, unit: "weeks" as const, delivery_rule: "none" as const, shift_rule: "auto" as const, nature: "objection" as const, legal_basis: null, text: "" };
    const court = makeItem({ date_spec: spec, computation: makeReceipt({ rule_ids: ["zpo_692", "bgb_187_1", "zpo_180", "zpo_222"] }) });
    expect(needsArrivalDate(court, { received_date: null })).toBe(true);
    expect(needsArrivalDate(court, { received_date: "2026-09-25" })).toBe(false);
    expect(needsArrivalDate(makeItem({ date_spec: spec }), { received_date: null })).toBe(false);
    // any court letter whose period runs from delivery is "served", whatever kind it was filed as
    expect(isServed(makeDoc({ kind: "authority_letter" }), [court])).toBe(true);
    expect(isServed(makeDoc({ kind: "enforcement_order" }), [])).toBe(true);
    expect(isServed(makeDoc({ kind: "authority_letter" }), [makeItem({ date_spec: spec })])).toBe(false);
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

describe("UI audit round 1: which to-do the verdict leads with", () => {
  it("never leads with a to-do the server set aside (history, replaced by a reminder)", () => {
    const deposit = makeItem({ id: "deposit", kind: "payment", amount: 1560, due_date: "2025-10-01" });
    const rent = makeItem({ id: "rent", kind: "payment", amount: 640, recurrence: { interval: 1, unit: "months", working_day: null, day_of_month: null } });
    expect(selectPrimaryItem([deposit, rent])?.id).toBe("deposit");
    expect(selectPrimaryItem([deposit, rent], [{ item_id: "deposit" }])?.id).toBe("rent");
    expect(selectPrimaryItem([deposit], [{ item_id: "deposit" }])).toBeNull();
  });

  it("an invoice its payment reminder replaced opens the reminder — never Pay twice", () => {
    const invoice = makeItem({ id: "inv", kind: "payment", amount: 89.99, direction: "out", due_date: "2026-09-03" });
    const detail = makeDetail({ items: [invoice], set_aside: [{ item_id: "inv", reason: "replaced", replaced_by: "doc_reminder" }] });
    const primary = selectPrimaryItem(detail.items, detail.set_aside);
    expect(primary).toBeNull();
    expect(chooseMainAction(detail, primary)).toEqual({ type: "reminder", docId: "doc_reminder" });
    expect(asideItems(detail).map((a) => [a.item.id, a.aside.reason])).toEqual([["inv", "replaced"]]);
    // a scam letter's demand is its verdict's "Don't pay", not a quiet row
    expect(asideItems(makeDetail({ items: [invoice], set_aside: [{ item_id: "inv", reason: "suspicious", replaced_by: null }] }))).toEqual([]);
  });

  it("an archived letter whose only to-do is history offers no objection to draft", () => {
    const remedy = { type: "einspruch" as const, addressee: "Finanzamt", period_text: null, form_text: null, quote: null };
    const old = makeItem({ id: "old", due_date: "2024-05-02" });
    const detail = makeDetail({ document: makeDoc({ remedy }), items: [old], set_aside: [{ item_id: "old", reason: "history", replaced_by: null }] });
    expect(chooseMainAction(detail, selectPrimaryItem(detail.items, detail.set_aside)).type).toBe("none");
  });

  it("of two dated to-dos of one priority, a deadline or payment leads over an appointment", () => {
    const meeting = makeItem({ id: "meeting", kind: "appointment", title: "Autumn Meeting in Berlin", due_date: "2026-11-07" });
    const report = makeItem({ id: "report", kind: "deadline", title: "Submit first progress report", due_date: "2026-12-15", send_by: "2026-12-09" });
    expect(selectPrimaryItem([meeting, report])?.id).toBe("report");
    // a more important appointment still leads (the Ausländerbehörde)
    expect(selectPrimaryItem([{ ...meeting, priority: "high" }, report])?.id).toBe("meeting");
    // and a dated appointment still beats an undated task
    expect(selectPrimaryItem([meeting, makeItem({ id: "task", kind: "task" })])?.id).toBe("meeting");
  });
});

describe("UI audit round 1: the verdict leads in English", () => {
  const german = makeItem({
    kind: "payment",
    title: "Semesterbeitrag Sommersemester 2027 zahlen",
    action: "Semesterbeitrag von 312,40 € rechtzeitig überweisen",
    amount: 312.4,
    currency: "EUR",
    direction: "out",
  });

  it("an English action leads as it is, its title below", () => {
    const w = verdictWords(makeItem({ title: "Pay outstanding invoice plus reminder fee", action: "Transfer 94.99 EUR by the deadline." }));
    expect(w).toEqual({ lead: "Transfer 94.99 EUR by the deadline.", body: null, sub: "Pay outstanding invoice plus reminder fee", quote: null });
  });

  it("a German action follows an English lead as the letter's words", () => {
    const w = verdictWords(german, "Hochschule Musterstadt");
    expect(w.lead).toBe("Pay €312.40 to Hochschule Musterstadt");
    expect(w.quote).toBe("Semesterbeitrag von 312,40 € rechtzeitig überweisen");
    const withTitle = verdictWords({ ...german, title: "Pay the semester fee" });
    expect(withTitle.lead).toBe("Pay the semester fee");
    expect(withTitle.quote).toBe(german.action);
  });

  it("builds an English lead for every kind when nothing English was read", () => {
    const debit = makeItem({ kind: "payment", title: "Monatliche Abbuchung Deutschlandticket", action: "Ausreichende Kontodeckung für die monatliche SEPA-Lastschrift sicherstellen.", amount: 63, currency: "EUR", direction: "out", recurrence: { interval: 1, unit: "months", working_day: null, day_of_month: null } });
    expect(verdictWords(debit).lead).toBe("Keep €63.00 a month in your account for the direct debit");
    expect(plainLead(makeItem({ kind: "appointment" }))).toBe("Go to the appointment");
    expect(plainLead(makeItem({ kind: "payment", direction: "in", amount: 312.45, currency: "EUR" }))).toBe("€312.45 comes to you");
    expect(verdictWords(makeItem({ kind: "appointment", title: "Autumn Meeting in Berlin" })).lead).toBe("Go to: Autumn Meeting in Berlin");
  });

  it("never leaves a German verdict field without an English companion", () => {
    const fields = [
      verdictWords(german),
      verdictWords({ ...german, action: null }),
      verdictWords({ ...german, kind: "deadline", date_spec: { type: "fixed", nature: "declaration" } as Item["date_spec"] }),
      verdictWords({ ...german, action: "Bitte überweisen Sie den Betrag bis zum 15.01.2027 auf das unten genannte Konto der Hochschule." }),
    ];
    for (const w of fields) {
      expect(isGermanText(w.lead), w.lead).toBe(false);
      if (w.body) expect(isGermanText(w.body), w.body).toBe(false);
    }
  });

  it("a German consequence says in English what the letter warns of", () => {
    const c = consequenceWords("Bei späterem Zahlungseingang wird eine Säumnisgebühr von 15,00 € erhoben. Ohne fristgerechte Rückmeldung droht die Exmatrikulation (§ 51 Abs. 2 HG NRW).");
    expect(c.lead).toBe("The letter warns of a late fee and losing your place at the university.");
    expect(c.quote).toMatch(/^Bei späterem/);
    expect(consequenceWords("Geht der Betrag nicht fristgerecht ein, müssen wir die Forderung an unseren Inkassodienstleister übergeben; dadurch entstehen Ihnen weitere Kosten.").lead).toBe(
      "The letter warns of debt collection and extra costs.",
    );
    expect(consequenceWords("Andernfalls wird der Vorgang außergerichtlich weiterbearbeitet und die Sache geht an die Stelle.").lead).toBe("The letter names what happens then:");
    const english = "The contribution notice becomes final if no objection is filed in time.";
    expect(consequenceWords(english)).toEqual({ lead: english, quote: null });
  });

  it("gives very long title words the smaller headline", () => {
    expect(hasLongWord("Certificate of Enrolment (Immatrikulationsbescheinigung) for Winter Semester 2026/27")).toBe(true);
    expect(hasLongWord("1st Payment Reminder (Mahnung) – Invoice TM-2026-0048213")).toBe(false);
  });
});

describe("UI audit round 1: verdict details", () => {
  it("shows the legal disclaimer only when a law worked the date out", () => {
    const receipt = (rule_ids: string[]) => makeReceipt({ rule_ids });
    expect(usesLaw(makeItem({ kind: "expiry", title: "Passport expires", computation: receipt(["date_as_written"]) }))).toBe(false);
    expect(usesLaw(makeItem({ kind: "appointment", computation: receipt(["date_as_written", "authority_deadline"]) }))).toBe(false);
    expect(usesLaw(makeItem({ computation: receipt(["posting_day", "bgb_187_1", "postal_buffer"]) }))).toBe(true);
    expect(usesLaw(makeItem({ kind: "payment", title: "Pay the invoice", computation: receipt(["date_as_written", "bgb_675s"]) }))).toBe(true);
    // a direct debit has nothing to transfer: the bank's execution time is no law for it
    expect(usesLaw(makeItem({ kind: "payment", title: "Monthly fee", action: "Keep funds for the SEPA direct debit.", computation: receipt(["date_as_written", "bgb_675s"]) }))).toBe(false);
    expect(usesLaw(makeItem({ computation: null }))).toBe(false);
  });

  it("finds the letter the person already started (the newest of that kind)", () => {
    const older = { id: "d1", kind: "objection", status: "draft", updated_at: "2026-09-20T10:00:00Z" } as Draft;
    const newer = { id: "d2", kind: "objection", status: "sent", updated_at: "2026-09-25T10:00:00Z" } as Draft;
    const other = { id: "d3", kind: "cancellation", status: "draft", updated_at: "2026-09-26T10:00:00Z" } as Draft;
    expect(existingDraft([older, newer, other], "objection")?.id).toBe("d2");
    expect(existingDraft([other], "objection")).toBeNull();
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

describe("UI audit round 2: a law's other deadlines", () => {
  const court = makeItem({ id: "court", kind: "deadline", origin: "rule", priority: "critical", title: "Get advice now: court action against the dismissal", due_date: "2026-04-10" });
  const register = makeItem({ id: "register", kind: "deadline", origin: "rule", priority: "high", title: "Register as job-seeking", due_date: "2026-03-23" });
  const certificate = makeItem({ id: "cert", kind: "task", title: "Submit enrollment certificate each semester", due_date: "2026-10-15" });

  it("lists the law's other open deadlines, most important first", () => {
    expect(otherLawDeadlines([certificate, court, register], certificate).map((i) => i.id)).toEqual(["court", "register"]);
  });

  it("never lists one the server set aside: it is only 'Probably dealt with', never also 'N days overdue'", () => {
    const setAside = [
      { item_id: "court", reason: "history" as const, replaced_by: null },
      { item_id: "register", reason: "history" as const, replaced_by: null },
    ];
    expect(otherLawDeadlines([certificate, court, register], certificate, setAside)).toEqual([]);
    expect(otherLawDeadlines([certificate, court, register], certificate, setAside.slice(1)).map((i) => i.id)).toEqual(["court"]);
    const detail = makeDetail({ items: [certificate, court, register], set_aside: setAside });
    expect(asideItems(detail).map((a) => a.item.id)).toEqual(["court", "register"]);
  });
});
