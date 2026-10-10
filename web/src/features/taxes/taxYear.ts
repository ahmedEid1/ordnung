/**
 * The Tax year page's logic (pure, unit-tested): a year's letters for taxes by the letter's date, the years
 * to choose from, which year to show first, and the next year's early statements.
 *
 * A letter is filed under the year of its date (else the day it arrived, {@link letterDay}) — the same rule as
 * the tax Idea's count and the export. Yearly statements for a year usually carry the next year's date, so the
 * letters for taxes dated January–May of the next year are shown (and exported) with it, to be checked.
 */
import type { Document } from "@/api/types";
import { documentKindLabel } from "@/lib/copy";
import type { LetterGroup } from "@/features/inbox/filters";
import { EARLY_UNTIL, exportable, letterDay, letterYear } from "@/features/export/selection";

/** The tax season ends with July (`TAX_SEASON_LAST_MONTH` on the server): until then the tax Idea is about last year. */
export const TAX_SEASON_LAST_MONTH = 7;
/** The tax Idea's own sentence, word for word (`secretary.triggers.tax_documents`). */
export const TAX_SEASON_SENTENCE =
  "If you have to file a return it is usually due by the end of July; filing voluntarily is possible for four years and often brings money back.";
/** The group of the next year's early letters ("Dated January–May 2026"). */
export const EARLY_GROUP = "early";

const yearOf = (iso: string) => Number(iso.slice(0, 4));
const monthOf = (iso: string) => Number(iso.slice(5, 7));

/** A letter on the Tax year page: one that can be exported and is marked as mattering for taxes. */
export const isTaxLetter = (d: Document) => exportable(d) && d.tax_relevant;

/** The letters for taxes dated in `year`, in their order. */
export function taxLetters(docs: readonly Document[], year: number): Document[] {
  return docs.filter((d) => isTaxLetter(d) && letterYear(d) === year);
}

/** The years that have letters for taxes, newest first, with how many each has. */
export function taxYears(docs: readonly Document[]): { year: number; count: number }[] {
  const counts = new Map<number, number>();
  for (const d of docs) {
    const year = isTaxLetter(d) ? letterYear(d) : null;
    if (year != null) counts.set(year, (counts.get(year) ?? 0) + 1);
  }
  return [...counts.entries()].map(([year, count]) => ({ year, count })).sort((a, b) => b.year - a.year);
}

/** Letters for taxes with no date at all: they belong to no year (and no year's export). */
export function undatedTaxLetters(docs: readonly Document[]): Document[] {
  return docs.filter((d) => isTaxLetter(d) && !letterDay(d));
}

/**
 * The year shown first: last year during the tax season (January–July) if it has letters for taxes, else this
 * year if it has any, else the newest year that has; null when there are none.
 */
export function defaultTaxYear(today: string, years: readonly number[]): number | null {
  const now = yearOf(today);
  if (monthOf(today) <= TAX_SEASON_LAST_MONTH && years.includes(now - 1)) return now - 1;
  if (years.includes(now)) return now;
  return years.length ? Math.max(...years) : null;
}

/** Whether the tax Idea would be live for `year` today (January–July, about last year). */
export function inTaxSeason(today: string, year: number): boolean {
  return monthOf(today) <= TAX_SEASON_LAST_MONTH && year === yearOf(today) - 1;
}

/** The letters for taxes dated 1 January – 31 May of the next year, once that year has begun. */
export function earlyStatements(docs: readonly Document[], year: number, today: string): Document[] {
  const from = `${year + 1}-01-01`;
  const until = `${year + 1}-${EARLY_UNTIL}`;
  if (today < from) return [];
  return docs.filter((d) => {
    const day = isTaxLetter(d) ? letterDay(d) : null;
    return day != null && day >= from && day <= until;
  });
}

const byDay = (a: Document, b: Document) => (letterDay(a) ?? "").localeCompare(letterDay(b) ?? "") || a.created_at.localeCompare(b.created_at);

/** One group per kind ("Payslip", "Insurance" …) in label order, the oldest letter first in each. */
export function groupByKind(docs: readonly Document[]): LetterGroup[] {
  const groups = new Map<string, LetterGroup>();
  for (const d of docs) {
    const kind = d.kind ?? "other";
    const group = groups.get(kind) ?? { key: `kind-${kind}`, label: documentKindLabel(kind), docs: [] };
    group.docs.push(d);
    groups.set(kind, group);
  }
  return [...groups.values()].map((g) => ({ ...g, docs: [...g.docs].sort(byDay) })).sort((a, b) => a.label.localeCompare(b.label));
}

/** The page's list: the year's letters for taxes by kind, then the next year's early ones ("Dated January–May 2026"). */
export function taxGroups(docs: readonly Document[], year: number, today: string): LetterGroup[] {
  const groups = groupByKind(taxLetters(docs, year));
  const early = earlyStatements(docs, year, today);
  if (early.length) groups.push({ key: EARLY_GROUP, label: `Dated January–May ${year + 1}`, docs: [...early].sort(byDay) });
  return groups;
}

/** A `?year=` the page can show: four digits, 1900–2100 (as the export accepts); else null. */
export function parseTaxYear(value: string | null): number | null {
  if (!value || !/^\d{4}$/.test(value)) return null;
  const year = Number(value);
  return year >= 1900 && year <= 2100 ? year : null;
}
