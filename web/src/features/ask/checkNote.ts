/**
 * The note Ordnung's answer check appends to an Ask answer (`ordnung/assistant/support.py`,
 * ADR 0008): a last paragraph that starts with `Checked by Ordnung:` and says how many sentences
 * were left out because their date or amount could not be matched to the records they cite, and
 * that values in “quotation marks” are quoted from a letter, not confirmed.
 *
 * The note is part of the stored answer text (so a reloaded conversation shows it too); the UI
 * splits it off and shows it as a note under the answer instead of as a paragraph of it.
 */
export const CHECK_NOTE_PREFIX = "Checked by Ordnung:";

export interface SplitAnswer {
  /** the answer without the note */
  body: string;
  /** the note's text without its prefix, or null */
  note: string | null;
}

/** Split the check note off the end of an answer (only a whole last paragraph counts). */
export function splitCheckNote(text: string): SplitAnswer {
  const at = text.lastIndexOf(CHECK_NOTE_PREFIX);
  if (at < 0) return { body: text, note: null };
  const before = text.slice(0, at);
  const note = text.slice(at + CHECK_NOTE_PREFIX.length).trim();
  // the note is its own last paragraph: at the very start, or after a blank line, and one line long
  if ((before.trim() && !/\n\s*\n\s*$/.test(before)) || !note || note.includes("\n")) return { body: text, note: null };
  return { body: before.trimEnd(), note };
}
