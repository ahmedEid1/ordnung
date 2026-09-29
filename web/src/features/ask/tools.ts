/**
 * The visible tool trace of an Ask answer: a past-tense, human chip per tool call
 * ("Searched your letters for "Kündigung"", "Opened “Phone contract”", "Listed your open to-dos").
 * The backend sends these labels; this is the fallback (demo recordings, older messages) and it
 * mirrors `ordnung/assistant/citations.py::tool_label`.
 */
import {
  CalendarDays,
  CalendarRange,
  FileText,
  IdCard,
  ListTodo,
  Scale,
  Search,
  Signature,
  UserRound,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { formatDate, formatInlineDates, tryParseDate, type DateInput } from "@/lib/format";
import { MONTH_WORD } from "./markdown";
import MONTH_WORDS from "./monthWords.json";
import type { ToolStep } from "./stream";

export const TOOL_ICONS: Record<string, LucideIcon> = {
  search: Search,
  get_document: FileText,
  list_items: ListTodo,
  list_contracts: Signature,
  money_summary: Wallet,
  explain_date: Scale,
  get_party: Users,
  timeline: CalendarRange,
  today: CalendarDays,
  get_profile: UserRound,
  get_my_numbers: IdCard,
};

/** Resolves an id (doc_…, itm_…) to a readable title. */
export type TitleLookup = (id: string) => string | null | undefined;

/** A part of a month the check reads as its days ("Ende Januar", "mid-October"): the check's own words. */
const MONTH_PART = new RegExp(`\\b(?:${MONTH_WORDS.parts})\\s*(?:${MONTH_WORD})\\b\\.?`, "gi");

function str(v: unknown): string {
  // the model's own words: every word with a digit, and every part of a month, shows as "…" (the trace is
  // shown before the answer check, so it never shows a date or amount a letter could have put there —
  // ADR 0008); read as the check reads them: emphasis markup dropped, dashes folded ("Ende **Januar**",
  // "mid‐January")
  const s = String(v ?? "")
    .normalize("NFKC")
    .replace(/[\u2010-\u2015\u2212]/g, "-")
    .replace(/[*_`]+/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .replace(MONTH_PART, "…")
    .replace(/[^\s"“”„]*\d[^\s"“”„]*/g, "…")
    .replace(/…(?: …)+/g, "…");
  return s.length > 60 ? `${s.slice(0, 59)}…` : s;
}

/** "28 Sep" — with its year when that isn't this year ("12 Jan 2027"), as on every other page. */
function day(v: unknown, today?: DateInput): string {
  return typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) ? formatDate(v, { style: "day", today }) : "…";
}

function statusWord(v: unknown): string {
  switch (v) {
    case "done":
      return "finished ";
    case "all":
      return "";
    case "missed":
      return "missed ";
    case "snoozed":
      return "snoozed ";
    default:
      return "open ";
  }
}

/** `list_items(kind=…)` in a label, as `citations.py::_ITEM_KINDS` says it. */
const ITEM_KINDS: Record<string, string> = {
  deadline: "deadlines",
  payment: "payments",
  appointment: "appointments",
  task: "tasks",
  expiry: "expiry dates",
  reminder: "reminders",
  milestone: "milestones",
};

/**
 * A human label for a tool call (without the backend's label). With the app's `today` (`useTodayISO`) a
 * date in another year shows its year; without it no date does.
 */
export function fallbackToolLabel(name: string, input: Record<string, unknown> = {}, titleOf?: TitleLookup, today?: DateInput): string {
  const id = (input.doc_id ?? input.id ?? input.item_or_contract_id ?? input.party_id_or_name) as unknown;
  const title = typeof id === "string" ? titleOf?.(id) : null;
  switch (name) {
    case "search": {
      const q = str(input.query ?? input.q);
      return q ? `Searched your letters for “${q}”` : "Searched your letters";
    }
    case "get_document":
      return title ? `Opened “${title}”` : "Opened a letter";
    case "list_items": {
      const from = input.from ?? input.from_date;
      const to = input.to ?? input.to_date;
      // a kind filter names the kind, so two filtered calls ("open deadlines", "open payments") read apart
      const what = (typeof input.kind === "string" && ITEM_KINDS[input.kind]) || "to-dos & dates";
      const scope = `your ${statusWord(input.status)}${what}`;
      if (from && to) return `Listed ${scope} from ${day(from, today)} to ${day(to, today)}`;
      if (to) return `Listed ${scope} until ${day(to, today)}`;
      return `Listed ${scope}`;
    }
    case "list_contracts":
      return "Looked at your contracts";
    case "money_summary":
      return "Checked your money overview";
    case "explain_date":
      return title ? `Checked how “${title}” was worked out` : "Checked how a date was worked out";
    case "get_party":
      return `Looked up “${title ?? str(input.party_id_or_name ?? input.id ?? input.name)}”`;
    case "timeline": {
      const from = input.from ?? input.from_date;
      const to = input.to ?? input.to_date;
      return from && to ? `Checked your timeline from ${day(from, today)} to ${day(to, today)}` : "Checked your timeline";
    }
    case "today":
      return "Checked today's date";
    case "get_profile":
      return "Checked your profile";
    case "get_my_numbers":
      return "Looked up your numbers";
    default:
      return "Looked something up";
  }
}

/** A date written out with its year ("Thu 15 Oct 2026", "14 Nov 2026"; plain or no-break spaces). */
const DATE_WITH_YEAR =
  /\b((?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[ \u00a0])?\d{1,2}[ \u00a0](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec))[ \u00a0](\d{4})\b/g;

/**
 * "Thu 15 Oct 2026" → "Thu 15 Oct" when 2026 is the year of the app's `today`, as every other page writes
 * this year's dates (UI audit round 2: the backend's labels and the answers write dates out in full). A date
 * in another year keeps it; without `today` nothing changes. Display only: a copied answer is as stored.
 */
export function withoutThisYear(text: string, today?: DateInput): string {
  const year = today ? tryParseDate(today)?.getFullYear() : undefined;
  if (!year) return text;
  return text.replace(DATE_WITH_YEAR, (whole, date: string, y: string) => (Number(y) === year ? date : whole));
}

/**
 * The result next to a finished step, dates in the app's style. With the app's `today` this year's dates
 * leave the year out, as on every other page ("Due 2026-10-15" → "Due Thu 15 Oct"; UI audit round 2);
 * without it an ISO date gets its year ("Due Thu 15 Oct 2026").
 */
export function toolResultText(result: string, today?: DateInput): string {
  return withoutThisYear(formatInlineDates(result, today), today);
}

const SHORT_DATE = /\b(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) )?\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b(?: \d{4})?/g;

/** ``text`` with the spaces inside its dates ("Mon 28 Sep 2026") made non-breaking, so a wrapped line never splits one. */
export function unbreakDates(text: string): string {
  return text.replace(SHORT_DATE, (date) => date.replace(/ /g, "\u00a0"));
}

/** Straight double quotes around a phrase ("Kündigung") as the app writes them (“Kündigung”). */
export function curlyQuotes(text: string): string {
  return text.replace(/"([^"\n]*)"/g, "“$1”");
}

/** The chip text for a step: the backend label when present, else the fallback; `today` as for {@link toolResultText}. */
export function toolLabel(step: Pick<ToolStep, "name" | "input" | "label">, titleOf?: TitleLookup, today?: DateInput): string {
  // the backend's label may carry ISO or written-out dates ("from 2026-09-28 to Mon 26 Oct 2026") and
  // straight quotes ('Searched your letters for "Kündigung"'); the fallback's are curly: one style in the trace
  return step.label
    ? curlyQuotes(withoutThisYear(formatInlineDates(step.label, today), today))
    : fallbackToolLabel(step.name, step.input, titleOf, today);
}

/**
 * What a folded trace says: how many steps looked at the person's records — "Checked today's date"
 * is not one of them (UI audit round 1: "Looked at 2 things" when one of them was today's date).
 */
export function traceSummary(steps: readonly Pick<ToolStep, "name">[]): string {
  const n = steps.filter((s) => s.name !== "today").length;
  if (!n) return "Checked today's date";
  return n === 1 ? "Looked at 1 thing in your records" : `Looked at ${n} things in your records`;
}
