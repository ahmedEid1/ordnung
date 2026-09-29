import type {
  ComputationReceipt,
  ComputationStep,
  Contract,
  DateSpec,
  Document,
  Evidence,
  Grounding,
  Item,
  KeyFact,
  Suggestion,
} from "@/api/types";
import { sha, ts } from "./constants";

/** Evidence stub; page + boxes are resolved against the rendered letter at mock start-up. */
export function ev(doc_id: string, quote: string, grounding: Grounding = "verified", page: number | null = null): Evidence {
  return { doc_id, page, quote, grounding, value_consistent: true, score: grounding === "unverified" ? 0.4 : 0.97, boxes: [] };
}

export function fact(label: string, value: string, evidence: Evidence | null = null): KeyFact {
  return { label, value, evidence };
}

export function step(label: string, date: string | null, rule_id: string | null = null, citation: string | null = null): ComputationStep {
  return { label, date, rule_id, citation };
}

export function receipt(r: Partial<ComputationReceipt> & Pick<ComputationReceipt, "due_date" | "summary">): ComputationReceipt {
  return {
    send_by: null,
    safe_date: null,
    holiday_calendar: "Germany + North Rhine-Westphalia (NW)",
    steps: [],
    rule_ids: [],
    warnings: [],
    confidence: "high",
    ...r,
  };
}

export function spec(s: Partial<DateSpec>): DateSpec {
  return {
    type: "fixed",
    date: null,
    time: null,
    anchor: null,
    anchor_date: null,
    amount: null,
    unit: null,
    delivery_rule: "none",
    shift_rule: "auto",
    nature: "other",
    legal_basis: null,
    text: "",
    ...s,
  };
}

type DocInput = Pick<Document, "id" | "filename" | "title"> & Partial<Document>;

export function doc(d: DocInput): Document {
  const created = d.created_at ?? ts(d.received_date ?? d.doc_date ?? "2026-09-01", "18:10");
  return {
    sha256: sha(d.id),
    mime: d.filename.endsWith(".pdf") ? "application/pdf" : "image/jpeg",
    pages: 1,
    direction: "incoming",
    source: "upload",
    status: "processed",
    error: null,
    kind: "other",
    area: "other",
    summary: null,
    explanation: null,
    language: "de",
    doc_date: null,
    received_date: null,
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
    ai_processed_at: created,
    created_at: created,
    updated_at: created,
    processed_at: created,
    deleted_at: null,
    ...d,
  };
}

type ItemInput = Pick<Item, "id" | "kind" | "title"> & Partial<Item>;

export function item(i: ItemInput): Item {
  const created = i.created_at ?? ts("2026-09-10", "18:12");
  return {
    description: null,
    action: null,
    consequence: null,
    due_date: null,
    due_time: null,
    send_by: null,
    date_spec: null,
    computation: null,
    amount: null,
    currency: i.amount != null ? "EUR" : null,
    direction: i.kind === "payment" ? "out" : null,
    recurrence: null,
    status: "open",
    snoozed_until: null,
    priority: "normal",
    area: "other",
    party_id: null,
    case_id: null,
    contract_id: null,
    doc_id: null,
    evidence: [],
    grounding: i.evidence?.[0]?.grounding ?? "verified",
    slot_key: `slot_${i.id}`,
    user_modified: false,
    due_date_source: i.computation ? "computed" : i.due_date ? "fixed" : "none",
    origin: "extracted",
    location: null,
    filed_on: null,
    created_at: created,
    updated_at: created,
    completed_at: null,
    ...i,
  };
}

type ContractInput = Pick<Contract, "id" | "name" | "category"> & Partial<Contract>;

export function contract(c: ContractInput): Contract {
  return {
    party_id: null,
    case_id: null,
    customer_number: null,
    concluded_date: null,
    start_date: null,
    initial_term_months: null,
    renewal_term_months: null,
    notice_value: null,
    notice_unit: null,
    notice_basis: null,
    notice_day: null,
    notice_before_end: false,
    end_date: null,
    is_basic_supply: false,
    cost_amount: null,
    cost_currency: "EUR",
    cost_interval: null,
    is_consumer: true,
    status: "active",
    computed: null,
    source_doc_id: null,
    evidence: [],
    area: "other",
    cancellable: true,
    cancel_hint: null,
    cancellation_sent: null,
    created_at: ts("2026-01-10"),
    updated_at: ts("2026-09-20"),
    ...c,
  };
}

type SuggestionInput = Pick<Suggestion, "id" | "kind" | "title" | "body"> & Partial<Suggestion>;

export function idea(s: SuggestionInput): Suggestion {
  return {
    rationale: null,
    priority: "normal",
    status: "new",
    snoozed_until: null,
    fingerprint: `fp_${s.id}`,
    refs: [],
    action: null,
    source: "rule",
    rule_id: null,
    savings_estimate: null,
    due_date: null,
    created_at: ts("2026-09-27", "07:00"),
    updated_at: ts("2026-09-27", "07:00"),
    ...s,
  };
}
