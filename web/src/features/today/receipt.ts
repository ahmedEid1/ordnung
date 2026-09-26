/** "Why this date?" receipts in one shape, for to-dos (computed or stated by the letter) and contracts. */
import type { ComputationStep, Confidence, Contract, Evidence, Item } from "@/api/types";

/** A receipt in one shape, whether it comes from a to-do's computation or a contract's. */
export interface ReceiptModel {
  summary: string;
  steps: ComputationStep[];
  warnings: string[];
  confidence: Confidence;
  holidayCalendar: string | null;
  sendBy: string | null;
  dueDate: string | null;
  /** The sentence the date came from (for dates the letter states directly). */
  evidence: Evidence | null;
  /** True when the rules engine computed the date (vs. the letter stating it). */
  computed: boolean;
  /** Label of the due date when there is no send-by date ("Pay by", "Due", "On"…). */
  dueLabel: string;
}

function dueLabelFor(item: Item): string {
  switch (item.kind) {
    case "payment":
      return "Pay by";
    case "appointment":
    case "milestone":
    case "reminder":
      return "On";
    case "expiry":
      return "Expires";
    case "task":
      return "By";
    default:
      return "Due";
  }
}

/** Build the receipt for a to-do (computed receipt, or "the letter says so" with the quote). */
export function receiptForItem(item: Item): ReceiptModel {
  const c = item.computation;
  const evidence = item.evidence[0] ?? null;
  if (c) {
    return {
      summary: c.summary,
      steps: c.steps,
      warnings: c.warnings,
      confidence: c.confidence,
      holidayCalendar: c.holiday_calendar || null,
      sendBy: c.send_by ?? item.send_by,
      dueDate: c.due_date ?? item.due_date,
      evidence,
      computed: true,
      dueLabel: dueLabelFor(item),
    };
  }
  const warnings = evidence && (evidence.grounding === "unverified" || !evidence.value_consistent)
    ? ["We couldn't match this date to the letter's text exactly — please compare it with the letter."]
    : [];
  return {
    summary: evidence
      ? "The letter states this date directly — nothing had to be calculated."
      : item.origin === "manual"
        ? "You set this date yourself."
        : "This date was added without a letter, so there is no rule behind it.",
    steps: [],
    warnings,
    confidence: warnings.length ? "medium" : "high",
    holidayCalendar: null,
    sendBy: item.send_by,
    dueDate: item.due_date,
    evidence,
    computed: false,
    dueLabel: dueLabelFor(item),
  };
}

/** Build the receipt for a contract decision. */
export function receiptForContract(contract: Contract): ReceiptModel | null {
  const c = contract.computed;
  if (!c) return null;
  return {
    summary: c.summary,
    steps: c.steps,
    warnings: [...c.warnings, ...c.notes],
    confidence: c.confidence,
    holidayCalendar: null,
    sendBy: c.send_by,
    dueDate: c.cancel_by,
    evidence: contract.evidence[0] ?? null,
    computed: true,
    dueLabel: "Cancel by",
  };
}
