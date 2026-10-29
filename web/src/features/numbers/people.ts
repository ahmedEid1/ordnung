/**
 * Whose a number is on My numbers (`ordnung/numbers.py`, ADR 0023): the person's own, or someone's of the household
 * the person filed letters for. The page's `household` groups, `filed_for` (a call sheet's number or a case that is
 * only one person's) and `also_for` (a number other people's letters show too) are read here, in words.
 */
import type { NumbersPage, PersonNumbers } from "@/api/types";

/** The person themself in `also_for` (as the household says "mine"). */
export const ME = "me";

/** The people of the household with a section of their own on the first tab: those with numbers or documents. */
export function peopleWithNumbers(page: NumbersPage): PersonNumbers[] {
  return page.household.filter((p) => p.about.length > 0 || p.documents.length > 0);
}

/** Each id the page names, by its name: a person of the household as typed, and "you" for the person. */
export function peopleNames(page: NumbersPage): Map<string, string> {
  return new Map([[ME, "you"], ...page.household.map((p): [string, string] => [p.id, p.name])]);
}

/**
 * The first tab: *People* once someone of the household has numbers or documents (its short label the same word,
 * so what shows is its name), else *About you*. It counts every group it lists.
 */
export function peopleTab(page: NumbersPage): { label: string; shortLabel: string; count: number } {
  const people = peopleWithNumbers(page);
  const count = page.about_you.length + page.documents.length + people.reduce((n, p) => n + p.about.length + p.documents.length, 0);
  return people.length ? { label: "People", shortLabel: "People", count } : { label: "About you", shortLabel: "You", count };
}

/** Names as a sentence lists them: "you", "you and Mia Rivera", "you, Mia Rivera and Kim Rivera". */
export function namesList(names: readonly string[]): string {
  if (names.length < 2) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** What a number other people's letters show too says: whose it is, the person checks. */
export function alsoForLine(names: readonly string[]): string {
  return `Also on letters for ${namesList(names)} — check whose it is`;
}

/** The names of `also_for`'s ids (`"me"` is "you"), in its order; an id the page doesn't name is left out. */
export function alsoForNames(ids: readonly string[] | undefined, page: NumbersPage): string[] {
  const names = peopleNames(page);
  return (ids ?? []).flatMap((id) => (names.has(id) ? [names.get(id)!] : []));
}

/** {@link alsoForLine} for `also_for`'s ids, or `null` when no one else's letters show the number. */
export function alsoForText(ids: readonly string[], page: NumbersPage): string | null {
  const names = alsoForNames(ids, page);
  return names.length ? alsoForLine(names) : null;
}

/** The name of the person of the household a call sheet's number, a case's reference or an open case is only for. */
export function filedForName(key: string, page: NumbersPage): string | undefined {
  const id = page.filed_for[key];
  return id ? page.household.find((p) => p.id === id)?.name : undefined;
}

/** Whose each row of the page is, for the rows and cards: see {@link filedForName} and {@link alsoForNames}. */
export interface Whose {
  filedFor(key: string): string | undefined;
  alsoFor(key: string): string[] | undefined;
}

export function whoseOf(page: NumbersPage): Whose {
  return {
    filedFor: (key) => filedForName(key, page),
    alsoFor: (key) => {
      const names = alsoForNames(page.also_for[key], page);
      return names.length ? names : undefined;
    },
  };
}
