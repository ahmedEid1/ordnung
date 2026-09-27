import { describe, expect, it } from "vitest";
import type { MailTrayItem, Suggestion } from "@/api/types";
import { ideasFromNewMail, isHeadlineIdea, openedTrayDocIds } from "./newMail";

const idea = (p: Partial<Suggestion> & Pick<Suggestion, "id">): Suggestion => ({
  kind: "deadline",
  title: p.id,
  body: "",
  rationale: null,
  priority: "normal",
  status: "new",
  snoozed_until: null,
  fingerprint: p.id,
  refs: [],
  action: null,
  source: "rule",
  rule_id: null,
  savings_estimate: null,
  due_date: null,
  created_at: "2026-09-28T09:00:00Z",
  updated_at: "2026-09-28T09:00:00Z",
  ...p,
});

const tray: MailTrayItem[] = [
  { id: "tax", filename: "a.jpg", sender: "Finanzamt", subject: "Bescheid", kind_hint: "tax_assessment", photo: true, opened: true, doc_id: "doc_tax", received_date: "2026-09-17" },
  { id: "power", filename: "b.pdf", sender: "Stadtwerke", subject: "Preise", kind_hint: "price_increase", photo: false, opened: true, doc_id: "doc_power", received_date: "2026-09-26" },
  { id: "scam", filename: "c.pdf", sender: "Zahlungszentrale", subject: "Mahnung", kind_hint: "dunning", photo: false, opened: false, doc_id: null, received_date: "2026-09-28" },
];

describe("Ideas from the new mail (the tour's 'An idea just arrived')", () => {
  it("knows which letters came out of the tray", () => {
    expect([...openedTrayDocIds(tray)]).toEqual(["doc_tax", "doc_power"]);
  });

  it("counts a real decision or warning about a tray letter — never housekeeping", () => {
    const docs = openedTrayDocIds(tray);
    const price = idea({ id: "price", rule_id: "price_increase_right", refs: [{ type: "document", id: "doc_power" }] });
    const calendar = idea({ id: "cal", kind: "hygiene", rule_id: "calendar_outdated", refs: [{ type: "document", id: "doc_tax" }] });
    const older = idea({ id: "older", rule_id: "price_increase_right", refs: [{ type: "document", id: "doc_bkk" }] });
    const dismissed = idea({ id: "gone", rule_id: "scam_warning", status: "dismissed", refs: [{ type: "document", id: "doc_power" }] });
    expect(ideasFromNewMail([calendar, older, dismissed, price], docs).map((s) => s.id)).toEqual(["price"]);
    expect(isHeadlineIdea(calendar)).toBe(false);
    expect(ideasFromNewMail([price], new Set())).toEqual([]);
  });
});
