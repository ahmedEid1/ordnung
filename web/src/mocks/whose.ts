/**
 * Whose an Idea, a calendar entry or the full notification is about in the mock backend (ADR 0023), the way the
 * API words it (`secretary/triggers.py`, `calendar/ics.py`, `notify/desktop.py`). Only a letter the visitor filed for
 * someone still in the household counts; a suggestion, "No, it's mine" or someone since removed never names anyone.
 * It is worked out on read: the canned Ideas keep their own titles.
 */
import type { Suggestion } from "@/api/types";
import { MEMBER_TITLES } from "./data/suggestions";
import type { MockDb } from "./db";
import { possessive } from "./household";

/**
 * Rules whose Ideas never name anyone (the API's `NEVER_NAMED`): the person's own tax return, calendar, profile and
 * move, a sender's Land, and the decision on a contract.
 */
const NEVER_NAMED = new Set(["tax_documents", "calendar_outdated", "student_permit_info", "moved_house", "sender_land", "contract_cancel_window"]);

/** The name of the person of the household each letter outside the trash is filed for, by letter id. */
export function filedNames(db: MockDb): Record<string, string> {
  const { members, links } = db.state.household;
  if (!members.length) return {};
  const names = new Map(members.map((m) => [m.id, m.name]));
  const live = new Set(db.liveDocuments().map((d) => d.id));
  return Object.fromEntries(Object.entries(links).flatMap(([doc, link]) => (live.has(doc) && names.has(link) ? [[doc, names.get(link)!]] : [])));
}

/** The letters an Idea refers to: its letters, each to-do's letter, and the letter each of the person's own letters answers. */
function lettersOf(db: MockDb, idea: Suggestion): Set<string> {
  const letters = new Set<string>();
  for (const ref of idea.refs) {
    const letter =
      ref.type === "document"
        ? ref.id
        : ref.type === "item"
          ? db.state.items.find((i) => i.id === ref.id)?.doc_id
          : ref.type === "draft"
            ? db.state.drafts.find((d) => d.id === ref.id)?.doc_id
            : null;
    if (letter) letters.add(letter);
  }
  return letters;
}

/** The person an Idea is about: every letter it refers to is filed for them (null: no letter, or not all theirs). */
function ideaMember(db: MockDb, idea: Suggestion, names: Record<string, string>): string | null {
  if (idea.source !== "rule" || NEVER_NAMED.has(idea.rule_id ?? "")) return null;
  const people = new Set([...lettersOf(db, idea)].map((letter) => names[letter] ?? null));
  if (people.size !== 1) return null;
  return [...people][0] ?? null;
}

/** An Idea's title about letters filed for `name`: its own words for a passport or permit, else "For Alex Rivera: …". */
function titleFor(idea: Suggestion, name: string): string {
  const own = MEMBER_TITLES[idea.id];
  if (own) {
    const owner = possessive(name);
    return owner ? own.possessive(owner) : `For ${name}: ${own.plain}`;
  }
  return `For ${name}: ${idea.title}`;
}

/** The Ideas as `GET /suggestions` lists them: an Idea about letters filed for someone of the household names them. */
export function nameIdeas(db: MockDb, ideas: Suggestion[]): Suggestion[] {
  const names = filedNames(db);
  if (!Object.keys(names).length) return ideas;
  return ideas.map((idea) => {
    const name = ideaMember(db, idea, names);
    return name ? { ...idea, title: titleFor(idea, name) } : idea;
  });
}
