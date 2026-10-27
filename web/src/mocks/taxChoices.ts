/**
 * The person's "For taxes" choices in the mock backend (the static demo and `?mock=1`), kept apart from the
 * letters like the API keeps them apart from Claude's reading (`tax_choices` in `meta`): "Read again" never
 * touches them, and Claude's own mark stays on the letter (`tax_relevant`).
 *
 * Made by d3-contract: every letter answers `tax_choice: null` and a PATCH that sends one answers 501 like the
 * API, until d3-tax-choice builds it. A letter deleted for good loses its choice; the trash keeps it.
 */
import type { MockDb } from "./db";

/** What a PATCH with `tax_choice` answers until d3-tax-choice builds it (as the API does). */
export const TAX_CHOICE_NOT_BUILT = "Marking a letter for taxes isn't built yet.";
/** Whether a PATCH's `tax_choice` is built here (d3-tax-choice turns it on). */
export const TAX_CHOICE_BUILT = false as boolean;

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
 * clears the choice. A body without one changes nothing here.
 */
export function patchTaxChoice(db: MockDb, docId: string, body: unknown): void {
  void db;
  void docId;
  if (body && typeof body === "object" && "tax_choice" in body) throw new TaxChoiceRefusal(501, TAX_CHOICE_NOT_BUILT);
}

/** A letter deleted for good: its choice goes with it (the trash keeps it). */
export function forgetTaxChoice(db: MockDb, docId: string): void {
  delete db.state.taxChoices[docId];
}
