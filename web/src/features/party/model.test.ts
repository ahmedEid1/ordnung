import { describe, expect, it } from "vitest";
import type { Item } from "@/api/types";
import { item } from "@/mocks/data/helpers";
import { actionDate, asideNote, countdownMode, dateRole, identifierDisplay, identifierStyle, keepNumbersTogether, looksAbroad, partyTodos, repeatsLabel } from "./model";

const pay = (over: Partial<Item> & Pick<Item, "id">): Item => item({ kind: "payment", title: "Pay", ...over });

describe("party to-dos", () => {
  it("lists dated to-dos soonest first, then repeating ones, then undated; set-aside ones apart", () => {
    const items = [
      pay({ id: "rent", title: "Monthly rent", recurrence: { interval: 1, unit: "months", working_day: null, day_of_month: null } }),
      item({ id: "report", kind: "task", title: "Report other scholarships" }),
      pay({ id: "late", title: "Nachzahlung", due_date: "2026-10-09", send_by: "2026-10-08" }),
      pay({ id: "deposit", title: "Security deposit", due_date: "2025-10-01" }),
      pay({ id: "soon", title: "Library fee", due_date: "2026-10-02" }),
      pay({ id: "done", title: "Paid", due_date: "2026-09-01", status: "done" }),
    ];
    const { open, aside } = partyTodos(items, [{ item_id: "deposit", reason: "history", replaced_by: null }]);
    expect(open.map((i) => i.id)).toEqual(["soon", "late", "rent", "report"]);
    expect(aside.map((a) => [a.item.id, a.aside.reason])).toEqual([["deposit", "history"]]);
    expect(actionDate(items[2]!)).toBe("2026-10-08");
    // a direct debit is collected on its due date: there is nothing to send by the day before
    expect(actionDate(pay({ id: "dd", title: "Annual premium direct debit", due_date: "2026-12-01", send_by: "2026-11-30" }))).toBe("2026-12-01");
  });

  it("names each date the way Today does, and never calls past appointments or money in overdue", () => {
    expect(dateRole(pay({ id: "a", send_by: "2026-10-08", due_date: "2026-10-09" }))).toBe("Transfer by");
    expect(dateRole(pay({ id: "b", title: "Monatliche Abbuchung Deutschlandticket", due_date: "2026-10-01" }))).toBe("Collected");
    expect(dateRole(pay({ id: "c", direction: "in", due_date: "2026-10-01" }))).toBe("On");
    expect(dateRole(item({ id: "d", kind: "deadline", title: "Object", send_by: "2026-10-08" }))).toBe("Send by");
    expect(dateRole(item({ id: "e", kind: "expiry", title: "Passport", due_date: "2027-02-10" }))).toBe("Expires");
    expect(dateRole(item({ id: "f", kind: "appointment", title: "Dentist", due_date: "2026-10-08" }))).toBe("On");
    expect(countdownMode(item({ id: "g", kind: "milestone", title: "Probation ends" }))).toBe("event");
    expect(countdownMode(pay({ id: "h", direction: "in" }))).toBe("event");
    expect(countdownMode(pay({ id: "i" }))).toBe("due");
    expect(repeatsLabel({ interval: 1, unit: "months", working_day: null, day_of_month: null })).toBe("Every month");
    expect(repeatsLabel({ interval: 3, unit: "months", working_day: null, day_of_month: null })).toBe("Every 3 months");
    // the day a rule names, as the letter's page and the server say it (audit item 26: "Every month" for both)
    expect(repeatsLabel({ interval: 1, unit: "months", working_day: 3, day_of_month: null })).toBe("Every month on the 3rd working day");
    expect(repeatsLabel({ interval: 1, unit: "months", working_day: null, day_of_month: 31 })).toBe("Every month on the last day");
    expect(repeatsLabel(null)).toBeNull();
  });

  it("says why a to-do is set apart, naming the reminder that replaced it", () => {
    const docs = [{ id: "doc_rem", doc_date: "2026-09-10", received_date: null }];
    expect(asideNote({ item_id: "x", reason: "replaced", replaced_by: "doc_rem" }, docs, "2026-09-28")).toBe(
      "Replaced by the payment reminder of Thu 10 Sep — pay that one, not both.",
    );
    expect(asideNote({ item_id: "x", reason: "replaced", replaced_by: "doc_gone" }, docs, "2026-09-28")).toMatch(/^Replaced by a later payment reminder/);
    expect(asideNote({ item_id: "x", reason: "history", replaced_by: null }, docs, "2026-09-28")).toMatch(/Already in the past/);
    expect(asideNote({ item_id: "x", reason: "suspicious", replaced_by: null }, docs, "2026-09-28")).toMatch(/signs of a scam/);
  });
});

describe("party identifiers and region", () => {
  it("keeps codes whole, IBAN groups together and register numbers with their court", () => {
    expect(identifierStyle("K-7719034")).toBe("code");
    expect(identifierStyle("512 345 678")).toBe("code");
    expect(identifierStyle("Amtsgericht Beispielburg HRB 48213")).toBe("text");
    expect(identifierDisplay("K 2231 0917", "code")).toBe("K\u00a02231\u00a00917");
    expect(identifierDisplay("DE05123456000004455660", "iban")).toBe("DE05 1234 5600 0004 4556 60");
    expect(identifierDisplay("Amtsgericht Beispielburg HRB 48213", "text")).toBe("Amtsgericht Beispielburg HRB\u00a048213");
    expect(identifierDisplay("Amtsgericht Musterstadt GnR 123", "text")).toBe("Amtsgericht Musterstadt GnR\u00a0123");
    expect(keepNumbersTogether("Postfach 10 01 00 \u00b7 12345 Musterstadt")).toBe("Postfach 10\u00a001\u00a000 \u00b7 12345 Musterstadt");
  });

  it("treats a party without a Land and without a German postcode as abroad", () => {
    expect(looksAbroad({ region: null, address: "Republic of Examplia" })).toBe(true);
    expect(looksAbroad({ region: null, address: "Genossenschaftsstraße 10, 12345 Musterstadt" })).toBe(false);
    expect(looksAbroad({ region: "NW", address: "Somewhere" })).toBe(false);
    expect(looksAbroad({ region: null, address: null })).toBe(false); // unknown: nationwide holidays apply
  });
});
