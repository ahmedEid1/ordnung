/** Call notes (Gesprächsnotizen): the form's own checks — the server checks the same again (`secretary/calls.py`). */

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
  const amount = d.amount.trim() ? Number(d.amount.replace(",", ".")) : null;
  if (amount !== null && (!Number.isFinite(amount) || amount < 0)) out.amount = "Type an amount in euros, like 29.90.";
  if ((d.promiseDue || amount !== null) && !d.promise.trim()) out.promise = "Say what they promised, too.";
  if (d.promiseDue && d.calledOn && d.promiseDue < d.calledOn) out.promiseDue = "The promised day is before the call.";
  return out;
}
