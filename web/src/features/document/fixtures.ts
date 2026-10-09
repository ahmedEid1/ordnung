/**
 * Small factories for tests of the Document viewer (complete objects with sensible defaults).
 * Only imported by `*.test.ts(x)` files.
 */
import type { ComputationReceipt, Document, DocumentDetail, Item, Suggestion } from "@/api/types";

const TS = "2026-09-28T07:00:00Z";

export function makeDoc(d: Partial<Document> = {}): Document {
  return {
    id: "doc_1",
    sha256: "0".repeat(64),
    filename: "letter.pdf",
    mime: "application/pdf",
    pages: 1,
    direction: "incoming",
    source: "upload",
    status: "processed",
    error: null,
    kind: "other",
    area: "other",
    title: "A letter",
    summary: null,
    explanation: null,
    language: "de",
    doc_date: "2026-09-15",
    received_date: "2026-09-17",
    party_id: null,
    case_id: null,
    urgency: "normal",
    text_mode: "text",
    key_facts: [],
    references: [],
    warnings: [],
    tax_relevant: false,
    tax_note: null,
    tags: [],
    remedy: null,
    payment: null,
    hidden_text: false,
    ai_private: false,
    ai_processed_at: TS,
    created_at: TS,
    updated_at: TS,
    processed_at: TS,
    deleted_at: null,
    ...d,
  };
}

export function makeReceipt(r: Partial<ComputationReceipt> = {}): ComputationReceipt {
  return {
    due_date: "2026-10-21",
    send_by: null,
    safe_date: null,
    holiday_calendar: "Germany + North Rhine-Westphalia (NW)",
    summary: "One month after delivery.",
    steps: [],
    rule_ids: [],
    warnings: [],
    confidence: "high",
    ...r,
  };
}

export function makeItem(i: Partial<Item> = {}): Item {
  return {
    id: "itm_1",
    kind: "deadline",
    title: "Something to do",
    description: null,
    action: null,
    consequence: null,
    due_date: null,
    due_time: null,
    send_by: null,
    date_spec: null,
    computation: null,
    amount: null,
    currency: null,
    direction: null,
    recurrence: null,
    status: "open",
    snoozed_until: null,
    priority: "normal",
    area: "other",
    party_id: null,
    case_id: null,
    contract_id: null,
    doc_id: "doc_1",
    evidence: [],
    grounding: "verified",
    slot_key: null,
    user_modified: false,
    due_date_source: "none",
    origin: "extracted",
    location: null,
    filed_on: null,
    created_at: TS,
    updated_at: TS,
    completed_at: null,
    ...i,
  };
}

export function makeSuggestion(s: Partial<Suggestion> = {}): Suggestion {
  return {
    id: "sug_1",
    kind: "info",
    title: "An idea",
    body: "Body",
    rationale: null,
    priority: "normal",
    status: "new",
    snoozed_until: null,
    fingerprint: "fp",
    refs: [],
    action: null,
    source: "rule",
    rule_id: null,
    savings_estimate: null,
    due_date: null,
    created_at: TS,
    updated_at: TS,
    ...s,
  };
}

export function makeDetail(d: Partial<DocumentDetail> = {}): DocumentDetail {
  const document = d.document ?? makeDoc();
  return {
    document,
    advice: null,
    pages: [{ page: 1, width: 1240, height: 1754, text_source: "text" }],
    items: [],
    contracts: [],
    party: null,
    case: null,
    related: [],
    suggestions: [],
    drafts: [],
    set_aside: [],
    girocodes: [],
    attachments: [],
    attachments_more: 0,
    email: null,
    can_wait_again: false,
    proof_of: [],
    scam_signs: [],
    // as the API says: a letter that was read was given to Claude
    given_to_model: Boolean(document.ai_processed_at),
    region_suggestion: null,
    ...d,
  };
}
