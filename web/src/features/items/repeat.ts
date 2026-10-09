/**
 * How a date of the person's own repeats (audit item 26): the choices "Add a date" offers, the rule each one sends
 * (`Recurrence`), the choice a stored rule is, and the words for a rule everywhere in the app. A repeating date is one
 * entry at its next date (`ordnung.recurrence`, point 1): it moves on when marked done or once its day has passed.
 *
 * `repeatLabel` says what `ordnung.recurrence.describe` says; both read `repeatLabels.json` in their tests, so the two
 * never drift apart.
 */
import { format, parseISO } from "date-fns";
import type { Item, Recurrence } from "@/api/types";
import { ordinal } from "@/features/contracts/model";
import { formatDate } from "@/lib/format";

/** What the "Repeats" select offers; `current` is a rule set some other way (every 2 weeks …), kept as it is. */
export type RepeatChoice = "never" | "month" | "working_day" | "quarter" | "half_year" | "year" | "current";

export interface RepeatOption {
  value: RepeatChoice;
  label: string;
}

/** The working days "Which working day?" offers: the 1st to the 10th, and the last (-1), as the server allows. */
export const WORKING_DAYS: readonly number[] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, -1];
/** "bis zum 3. Werktag": the usual one. */
export const DEFAULT_WORKING_DAY = 3;
/** The last working day of a month (`Recurrence.working_day`). */
const LAST = -1;
/** A day of the month past a month's end is that month's last day. */
const LAST_DAY = 31;

const MONTHS: Partial<Record<RepeatChoice, number>> = { month: 1, quarter: 3, half_year: 6 };

/** The rule a choice sends (`null`: it doesn't repeat; `current`: the date's own rule, unchanged). */
export function repeatRule(choice: RepeatChoice, workingDay: number, current: Recurrence | null = null): Recurrence | null {
  const plain = { working_day: null, day_of_month: null };
  switch (choice) {
    case "never":
      return null;
    case "current":
      return current;
    case "working_day":
      return { interval: 1, unit: "months", working_day: workingDay, day_of_month: null };
    case "year":
      return { interval: 1, unit: "years", ...plain };
    default:
      return { interval: MONTHS[choice]!, unit: "months", ...plain };
  }
}

/** The rule as the engine steps it: months (every year is every 12 months), its working day, else its day of the month. */
export function steps(r: Recurrence): { months: number | null; workingDay: number | null; day: number | null } {
  if (r.unit === "days" || r.unit === "weeks") return { months: null, workingDay: null, day: null };
  const interval = Math.max(1, r.interval);
  const workingDay = r.working_day ?? null;
  return { months: r.unit === "years" ? 12 * interval : interval, workingDay, day: workingDay === null ? (r.day_of_month ?? null) : null };
}

/** Whether two rules give the same dates, as the server's `same_rule` says: every year is every 12 months. */
export function sameRule(a: Recurrence | null | undefined, b: Recurrence | null | undefined): boolean {
  if (!a || !b) return !a && !b;
  const x = steps(a);
  const y = steps(b);
  if (x.months === null || y.months === null) return x.months === y.months && dayStep(a) === dayStep(b);
  return x.months === y.months && x.workingDay === y.workingDay && x.day === y.day;
}

/** A rule in days or weeks as days (every 2 weeks is every 14 days); `null` for a rule in months or years. */
export function dayStep(r: Recurrence): number | null {
  if (r.unit !== "days" && r.unit !== "weeks") return null;
  return Math.max(1, r.interval) * (r.unit === "weeks" ? 7 : 1);
}

/**
 * The choice a stored rule is (`startDate`: where its schedule starts, `date_spec.date`): every 12 months is every year,
 * as the server's `same_rule` says, and a day of the month that is the schedule's own day is the plain rule. Any other
 * rule (every 2 weeks, every 3 months on a working day …) is `current`, kept unless changed.
 */
export function repeatChoiceOf(rule: Recurrence | null | undefined, startDate: string | null | undefined): { choice: RepeatChoice; workingDay: number } {
  if (!rule) return { choice: "never", workingDay: DEFAULT_WORKING_DAY };
  const { months, workingDay, day } = steps(rule);
  if (months === 1 && workingDay !== null) return { choice: "working_day", workingDay };
  const startDay = startDate ? parseISO(startDate).getDate() : null;
  const plain = workingDay === null && (day === null || day === startDay);
  const choice = plain ? ({ 1: "month", 3: "quarter", 6: "half_year", 12: "year" } as Record<number, RepeatChoice>)[months ?? 0] : undefined;
  return { choice: choice ?? "current", workingDay: DEFAULT_WORKING_DAY };
}

/**
 * A rule in words, as `ordnung.recurrence.describe` says it: "every month", "every 3 months", "every month on the 3rd
 * working day", "every month on the last working day", "every month on the 1st", "every month on the last day"
 * (`capital`: "Every month …", to start a line). `null` for a date that doesn't repeat.
 */
export function repeatLabel(rule: Recurrence | null | undefined, { capital = false }: { capital?: boolean } = {}): string | null {
  if (!rule) return null;
  const unit = rule.unit.replace(/s$/, "");
  const every = rule.interval <= 1 ? `every ${unit}` : `every ${rule.interval} ${rule.unit}`;
  const { workingDay, day } = steps(rule);
  const text =
    workingDay !== null
      ? `${every} on the ${workingDay === LAST ? "last" : ordinal(workingDay)} working day`
      : day !== null
        ? `${every} on the ${day === LAST_DAY ? "last day" : ordinal(day)}`
        : every;
  return capital ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

/** "the 14th", "the 31st (or the month's last day)": a 29th to 31st falls on a shorter month's last day. */
function onDay(date: Date): string {
  return `the ${ordinal(date.getDate())}${date.getDate() > 28 ? " (or the month's last day)" : ""}`;
}

/** One choice in words, on `date`'s day ("Every 3 months on the 14th"); without a date, no day. */
export function repeatChoiceLabel(choice: RepeatChoice, date: string | null | undefined, current: Recurrence | null = null): string {
  const day = date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? parseISO(date) : null;
  switch (choice) {
    case "never":
      return "Doesn't repeat";
    case "working_day":
      return "Every month on a working day";
    case "current":
      return `${repeatLabel(current, { capital: true }) ?? "As now"} (as now)`;
    case "year":
      return day ? `Every year on ${format(day, "d MMMM")}${day.getMonth() === 1 && day.getDate() === 29 ? " (or the month's last day)" : ""}` : "Every year";
    default: {
      const every = MONTHS[choice] === 1 ? "Every month" : `Every ${MONTHS[choice]} months`;
      return day ? `${every} on ${onDay(day)}` : every;
    }
  }
}

/**
 * The "Repeats" choices for the day chosen (`date`; none yet: no "on the …"). Weekly is left out on purpose — monthly,
 * quarterly, half-yearly and yearly cover the German cadences — but a date that already repeats some other way
 * (`current`) keeps that rule as the last choice.
 */
export function repeatOptions(date: string | null | undefined, current?: Recurrence | null, startDate?: string | null): RepeatOption[] {
  const choices: RepeatChoice[] = ["never", "month", "working_day", "quarter", "half_year", "year"];
  const own = current ? repeatChoiceOf(current, startDate ?? date).choice : null;
  if (own === "current") choices.push("current");
  // the date's own choice is on its schedule's day; another one would start on the date shown
  return choices.map((value) => ({ value, label: repeatChoiceLabel(value, value === own ? (startDate ?? date) : date, current ?? null) }));
}

/**
 * "Next: Wed 4 Nov" — where a repeating to-do moved on to once marked done (`moved`, the server's answer; `before`, as it
 * was), or `null` when it closed, doesn't repeat or stayed where it was.
 */
export function nextNote(moved: Pick<Item, "status" | "recurrence" | "due_date">, before: Pick<Item, "due_date">, today?: string): string | null {
  if (moved.status !== "open" || !moved.recurrence || !moved.due_date || moved.due_date === before.due_date) return null;
  return `Next: ${formatDate(moved.due_date, { style: "short", today })}`;
}

/**
 * What a "Marked as done" or "Marked as paid" toast says: the to-do, and where a repeating one moved on to ("UStVA ·
 * Next: Wed 4 Nov", from the server's answer `moved`).
 */
export function doneLine(item: Pick<Item, "title" | "due_date">, moved: Pick<Item, "status" | "recurrence" | "due_date"> | null | undefined, today?: string): string {
  const next = moved ? nextNote(moved, item, today) : null;
  return next ? `${item.title} · ${next}` : item.title;
}
