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

// ------------------------------------------------------------------------------------------------
// Drafts: a half-written note is never lost
// ------------------------------------------------------------------------------------------------

/**
 * Half-written call notes, one per party, kept while the app is open — and across a reload, in this
 * tab (`sessionStorage`, when the browser allows it) — so the drawer closing, a link followed from it
 * or a reload never throws away what was typed. "Save note" and "Cancel" (or "Discard") drop it.
 */
const drafts = new Map<string, CallNoteDraft>();
const STORAGE_PREFIX = "ordnung.call-draft.";

/** Something was typed (the day of the call starts as today and the thread can come chosen: those alone are nothing to keep). */
export function draftHasText(d: CallNoteDraft): boolean {
  return Boolean(d.contact.trim() || d.summary.trim() || d.promise.trim() || d.promiseDue || d.amount.trim());
}

const text = (v: unknown): string => (typeof v === "string" ? v : "");

/** The note half-written for this party, if any. */
export function loadCallDraft(partyId: string): CallNoteDraft | null {
  const kept = drafts.get(partyId);
  if (kept) return kept;
  try {
    const raw = window.sessionStorage.getItem(STORAGE_PREFIX + partyId);
    if (!raw) return null;
    const v = JSON.parse(raw) as Record<string, unknown>;
    const d: CallNoteDraft = {
      calledOn: text(v.calledOn),
      contact: text(v.contact),
      summary: text(v.summary),
      promise: text(v.promise),
      promiseDue: text(v.promiseDue),
      amount: text(v.amount),
      caseId: text(v.caseId),
    };
    if (!draftHasText(d)) return null;
    drafts.set(partyId, d);
    return d;
  } catch {
    return null; // storage blocked or unreadable: only this session's memory counts
  }
}

/** Keep the note as typed (an empty form is dropped instead). */
export function keepCallDraft(partyId: string, d: CallNoteDraft): void {
  if (!draftHasText(d)) {
    clearCallDraft(partyId);
    return;
  }
  drafts.set(partyId, d);
  try {
    window.sessionStorage.setItem(STORAGE_PREFIX + partyId, JSON.stringify(d));
  } catch {
    // storage blocked or full: the draft still survives the drawer closing
  }
}

/** The note was saved or thrown away on purpose. */
export function clearCallDraft(partyId: string): void {
  drafts.delete(partyId);
  try {
    window.sessionStorage.removeItem(STORAGE_PREFIX + partyId);
  } catch {
    // nothing kept there
  }
}

/** Tests: forget every draft. */
export function __clearCallDrafts(): void {
  for (const id of [...drafts.keys()]) clearCallDraft(id);
  try {
    for (let i = window.sessionStorage.length - 1; i >= 0; i -= 1) {
      const key = window.sessionStorage.key(i);
      if (key?.startsWith(STORAGE_PREFIX)) window.sessionStorage.removeItem(key);
    }
  } catch {
    // nothing kept there
  }
}
