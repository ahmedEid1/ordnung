/**
 * The person's "For taxes" choices in the mock backend (the static demo and `?mock=1`), kept apart from the
 * letters like the API keeps them apart from Claude's reading (`tax_choices` in `meta`): "Read again" never
 * touches them, and Claude's own mark stays on the letter (`tax_relevant`).
 *
 * `PATCH /api/documents/{id}` with `tax_choice` sets (`true`/`false`) or clears (`null`) one, with the API's
 * refusals: 409 for a letter in the trash, one waiting from the folder or a proof file; 404 for no letter; 422
 * for anything but `true`, `false` or `null`. A letter deleted for good loses its choice; the trash keeps it.
 */
import type { MockDb } from "./db";

/** The API's words (`api/routes/documents.py`). */
export const IN_TRASH = "This letter is in the trash.";
export const HELD_MESSAGE = "This letter isn't read yet: choose “Read” or “Keep private” for it first (Inbox → From your folder).";
export const PROOF_FOR_TAXES = "A proof file goes with its letter: mark that letter for taxes instead.";
export const NOT_A_LETTER = "This letter doesn't exist (any more).";

/** A refusal of a tax choice as the API answers it (`{detail}` with this status). */
export class TaxChoiceRefusal extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** The person's choice for a letter (`null`: none — Claude's mark counts). */
export function taxChoiceOf(db: MockDb, docId: string): boolean | null {
  return db.state.taxChoices[docId] ?? null;
}

/**
 * `PATCH /api/documents/{id}` with a `tax_choice` in `body` (run first, before the letter's other fields): sets or
 * clears the choice, or refuses the whole PATCH as the API does. A body without one changes nothing here.
 */
export function patchTaxChoice(db: MockDb, docId: string, body: unknown): void {
  if (!body || typeof body !== "object" || !("tax_choice" in body)) return;
  const choice = (body as { tax_choice: unknown }).tax_choice;
  if (choice !== true && choice !== false && choice !== null) throw new TaxChoiceRefusal(422, "tax_choice must be true, false or null.");
  // the letter in the trash too (`db.document` leaves it out): the API answers 409 for it, not 404
  const doc = db.state.documents.find((d) => d.id === docId) ?? null;
  if (!doc) throw new TaxChoiceRefusal(404, NOT_A_LETTER);
  if (doc.deleted_at) throw new TaxChoiceRefusal(409, IN_TRASH);
  if (doc.status === "held") throw new TaxChoiceRefusal(409, HELD_MESSAGE);
  if (doc.source === "proof") throw new TaxChoiceRefusal(409, PROOF_FOR_TAXES);
  if (choice === null) delete db.state.taxChoices[docId];
  else db.state.taxChoices[docId] = choice;
}

/** A letter deleted for good: its choice goes with it (the trash keeps it). */
export function forgetTaxChoice(db: MockDb, docId: string): void {
  delete db.state.taxChoices[docId];
}
