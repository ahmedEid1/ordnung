/** Call notes (Gesprächsnotizen): the form's own checks — the server checks the same again (`secretary/calls.py`). */
import { parseMoney } from "@/lib/money";

/** The largest promised amount (the server's `MAX_AMOUNT`: a typo guard). */
export const MAX_AMOUNT = 1_000_000;

/** The call-note form as typed (strings, as the inputs give them). */
export interface CallNoteDraft {
  calledOn: string;
  contact: string;
  summary: string;
  promise: string;
  promiseDue: string;
  amount: string;
  caseId: string;
}

/** What is wrong with a note before it is sent (the server says the same, and checks again). */
export function callNoteProblems(d: CallNoteDraft, today: string): Partial<Record<keyof CallNoteDraft, string>> {
  const out: Partial<Record<keyof CallNoteDraft, string>> = {};
  if (!/^\d{4}-\d{2}-\d{2}$/.test(d.calledOn)) out.calledOn = "When was the call?";
  else if (d.calledOn > today) out.calledOn = "The call can't be in the future.";
  if (!d.summary.trim()) out.summary = "Write down what was said.";
  const typed = d.amount.trim() !== "";
  const amount = promisedAmount(d);
  if (typed && amount === null) out.amount = "Type an amount in euros, like 29,90 or 1.500.";
  else if (amount !== null && amount > MAX_AMOUNT) out.amount = "Type an amount up to 1.000.000 €.";
  if ((d.promiseDue || typed) && !d.promise.trim()) out.promise = "Say what they promised, too.";
  if (d.promiseDue && d.calledOn && d.promiseDue < d.calledOn) out.promiseDue = "The promised day is before the call.";
  return out;
}

/** The promised amount as typed, German or English style ("1.500" is 1500, "1.234,56", "29,90"); `null`: none or unreadable. */
export function promisedAmount(d: Pick<CallNoteDraft, "amount">): number | null {
  return d.amount.trim() ? parseMoney(d.amount) : null;
}

/** The fields of the form in order (the first one with a problem gets focus when saving fails). */
export const CALL_FIELDS: readonly (keyof CallNoteDraft)[] = ["calledOn", "contact", "summary", "promise", "promiseDue", "amount", "caseId"];
