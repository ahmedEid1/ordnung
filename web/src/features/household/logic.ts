/**
 * Your household on the page (pure, unit-tested): who a letter is filed for, the Inbox's *For* choice
 * (`?for=`), the letters addressed to someone and not answered yet, and what an Undo sends back.
 *
 * The API works it all out (`GET /api/household`, ADR 0023): `filed` holds only live filings (a letter outside
 * the trash, for someone still in the list), `mine` the letters the person said are theirs, `suggested` the
 * unanswered letters whose addressee names one person. Nothing here files anything: only a press does.
 */
import type { Household, HouseholdPerson, ListedLetter } from "@/api/types";

/** The answer "No, it's mine", and the `?for=` of the person's own letters ("You"). */
export const MINE = "me";

/** What the Inbox's *For* select narrows to: null (Everyone), {@link MINE} (You), or a person's id. */
export type ForChoice = string | null;

/** One option of the *For* select (`value` "" is Everyone; `count`: the person's letters among those listed). */
export interface ForOption {
  value: string;
  label: string;
  count: number | null;
}

/** A person of the household by id (null: not, or no longer, in it). */
export function memberById(h: Household | undefined, id: string | null | undefined): HouseholdPerson | null {
  return (id && h?.members.find((m) => m.id === id)) || null;
}

/** The person a letter is filed for (null: it isn't — unanswered, the person's own, or filed for someone removed). */
export function filedMember(h: Household | undefined, docId: string): HouseholdPerson | null {
  return memberById(h, h?.filed[docId]);
}

/** A letter's answer now — a person's id, {@link MINE}, or null (not answered): what an Undo sends back. */
export function answerOf(h: Household | undefined, docId: string): string | null {
  if (!h) return null;
  return h.filed[docId] ?? (h.mine.includes(docId) ? MINE : null);
}

/** The answers of `ids` as they are now: the body of an Undo (`PATCH /api/household`'s `letters`). */
export function undoLetters(h: Household | undefined, ids: readonly string[]): Record<string, string | null> {
  return Object.fromEntries(ids.map((id) => [id, answerOf(h, id)]));
}

/** `?for=`: You, a person in the household, else Everyone (an unknown id, or a household with no people). */
export function parseFor(param: string | null, h: Household | undefined): ForChoice {
  if (!param || !h?.members.length) return null;
  if (param === MINE) return MINE;
  return memberById(h, param) ? param : null;
}

/** Whether a letter is in the *For* choice: a person's are those filed for them; You's every letter not filed for someone. */
export function matchesFor(doc: Pick<ListedLetter, "id">, choice: ForChoice, h: Household | undefined): boolean {
  if (choice == null) return true;
  if (choice === MINE) return !filedMember(h, doc.id);
  return h?.filed[doc.id] === choice;
}

/** The *For* select's options: Everyone, You, then each person with their letters among `docs`; none without people. */
export function forOptions(docs: readonly Pick<ListedLetter, "id">[], h: Household | undefined): ForOption[] {
  if (!h?.members.length) return [];
  const people = h.members.map((m) => {
    const count = docs.filter((d) => h.filed[d.id] === m.id).length;
    return { value: m.id, label: `${m.name} (${count})`, count };
  });
  return [{ value: "", label: "Everyone", count: null }, { value: MINE, label: "You", count: null }, ...people];
}

/** The letters of `docs` addressed to this person and not answered yet, in their order (*File these N*). */
export function suggestedFor<T extends Pick<ListedLetter, "id">>(docs: readonly T[], memberId: string, h: Household | undefined): T[] {
  if (!h) return [];
  return docs.filter((d) => h.suggested[d.id] === memberId);
}

/**
 * The start of a row's second line for a date from a letter filed for someone of the household: "For Alex Rivera",
 * the words Today's Coming up uses.
 */
export function forLine(name: string): string {
  return `For ${name}`;
}

/** The button that files the listed letters for a person. */
export function fileTheseLabel(n: number, name: string): string {
  return n === 1 ? `File it for ${name}` : `File these ${n} for ${name}`;
}
