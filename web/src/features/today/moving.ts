/**
 * The moving checklist's rules on the web side (`secretary.moving` on the server): which Ideas are its rows,
 * their order, the letter a row may already have, and whether a move the person told still has its checklist.
 * A move is only ever told by the person (Settings → Profile → "I moved"); nothing here sets one.
 */
import { addDays, format, parseISO } from "date-fns";
import type { Draft, Priority, Profile, Suggestion } from "@/api/types";
import { daysUntil, formatDate } from "@/lib/format";

/** The rule id of the checklist's rows (`secretary.moving.RULE_ID`). */
export const MOVING_RULE = "moved_house";
/** How many rows the card shows before "Show N more". */
export const MOVING_SHOWN = 5;
/** The checklist ends this many days after the move, and a move may be told this far back (the API's window). */
export const MOVE_WINDOW_DAYS = 180;
/** How far ahead a move may be told. */
export const MOVE_AHEAD_DAYS = 90;
/** The card's id: "Open your moving checklist" links to it (`/#moving-checklist`). */
export const MOVING_CHECKLIST_ID = "moving-checklist";

const WEIGHT: Record<Priority, number> = { low: 0, normal: 1, high: 2, critical: 3 };

/** The checklist's rows among Today's Ideas: new `moved_house` ones, registering first (it is `high`), then by title. */
export function movingRows(suggestions: readonly Suggestion[]): Suggestion[] {
  return suggestions
    .filter((s) => s.rule_id === MOVING_RULE && s.status === "new")
    .sort((a, b) => WEIGHT[b.priority] - WEIGHT[a.priority] || a.title.localeCompare(b.title));
}

/**
 * The unsent new-address letter to a row's sender, started since the row came (newest first): "Write the letter"
 * then opens it instead of a second one. `null` for a row about no sender, or when there is none.
 */
export function openDraftFor(row: Suggestion, drafts: readonly Draft[] | undefined): Draft | null {
  const party = row.action?.target_type === "party" ? row.action.target_id : null;
  if (!party || !drafts) return null;
  const since = row.created_at;
  return (
    drafts
      .filter((d) => d.kind === "address_change" && d.party_id === party && d.status !== "sent" && d.created_at >= since)
      .sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null
  );
}

/** Whether the move the profile holds still has its checklist: told, and at most six months ago. */
export function moveStanding(profile: Pick<Profile, "moved_on"> | undefined, today: string): boolean {
  const moved = profile?.moved_on;
  return Boolean(moved) && -daysUntil(moved!, today) <= MOVE_WINDOW_DAYS;
}

/** The days the "Moved in on" field takes: six months back to three ahead (the API refuses others). */
export function moveDayRange(today: string): { min: string; max: string } {
  const t = parseISO(today);
  return { min: format(addDays(t, -MOVE_WINDOW_DAYS), "yyyy-MM-dd"), max: format(addDays(t, MOVE_AHEAD_DAYS), "yyyy-MM-dd") };
}

/** What is wrong with the "Moved in on" day (`null`: nothing). */
export function moveDayError(day: string, today: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return "Enter the day you moved in.";
  const { min, max } = moveDayRange(today);
  if (day < min || day > max) return "Ordnung's moving checklist is for a move in the last six months or the next three — check the day.";
  return null;
}

/** "You moved in on Thu 1 Oct." (the year only when it isn't this year's); a move ahead: "You move in on …". */
export function movedLine(movedOn: string, today: string): string {
  return `${movedOn > today ? "You move in on" : "You moved in on"} ${formatDate(movedOn, { style: "short", today })}.`;
}
