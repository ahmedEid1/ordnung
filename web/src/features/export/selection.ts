/**
 * Export letters: which letters a choice takes, the link's query and the ZIP's name (pure, unit-tested).
 *
 * The server decides what goes into the ZIP (`ordnung.letters_zip.matches` / `zip_name`); this mirrors it so
 * the dialog can say how many letters the ZIP will hold before the person clicks. Both test suites read
 * `selection-cases.json`, so the two can't drift apart.
 */
import type { Document, LettersZipParams } from "@/api/types";

/** What the person chose: a year (by the letter's date), `until` a day of the next year, only letters for taxes, one sender. */
export interface ExportChoice {
  year?: number | null;
  until?: string | null;
  tax?: boolean;
  party_id?: string | null;
}

/** The last day of the next year whose letters a tax year also takes ("05-31": statements dated January–May). */
export const EARLY_UNTIL = "05-31";

/** `${year + 1}-05-31`: the `until` of a tax year's early statements. */
export function earlyUntil(year: number): string {
  return `${year + 1}-${EARLY_UNTIL}`;
}

/** A `YYYY-MM-DD` day (or the day of an ISO timestamp) if it is a real one, as the server reads it; else null. */
export function parseDay(value: string | null | undefined): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value ?? "");
  if (!m) return null;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const date = new Date(Date.UTC(y, mo - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === mo - 1 && date.getUTCDate() === d && y >= 1 ? m[0].slice(0, 10) : null;
}

/** The day a letter is filed under by year: the date printed on it, else the day it arrived (`letter_day` on the server). */
export function letterDay(d: Pick<Document, "doc_date" | "received_date">): string | null {
  return parseDay(d.doc_date) ?? parseDay(d.received_date);
}

/** The year of {@link letterDay} (null: the letter has no date). */
export function letterYear(d: Pick<Document, "doc_date" | "received_date">): number | null {
  const day = letterDay(d);
  return day ? Number(day.slice(0, 4)) : null;
}

/** A letter that can be exported at all: not in the trash, not waiting to be read (held), not a proof file. */
export function exportable(d: Document): boolean {
  return !d.deleted_at && d.status !== "held" && d.source !== "proof";
}

/** Whether `d` belongs in the export `c` describes. */
export function matchesChoice(d: Document, c: ExportChoice): boolean {
  if (!exportable(d)) return false;
  if (c.tax && !d.tax_relevant) return false;
  if (c.party_id && d.party_id !== c.party_id) return false;
  if (c.year == null) return true;
  const day = letterDay(d);
  if (!day) return false;
  const year = Number(day.slice(0, 4));
  if (year === c.year) return true;
  return Boolean(c.until) && year === c.year + 1 && day <= c.until!;
}

/** The letters of `docs` the export takes, in their order. */
export function selectForExport(docs: readonly Document[], c: ExportChoice): Document[] {
  return docs.filter((d) => matchesChoice(d, c));
}

/** The link's query: only what narrows the export (`until` only with a year, `tax` only when on). */
export function exportQuery(c: ExportChoice): LettersZipParams {
  const q: LettersZipParams = {};
  if (c.year != null) q.year = c.year;
  if (c.year != null && c.until) q.until = c.until;
  if (c.tax) q.tax = true;
  if (c.party_id) q.party_id = c.party_id;
  return q;
}

/** `ordnung-letters[-for-taxes][-<year>|-<today>].zip`, the name the server gives the download. */
export function zipName(c: ExportChoice, today: string): string {
  return `ordnung-letters${c.tax ? "-for-taxes" : ""}-${c.year != null ? c.year : today}.zip`;
}
