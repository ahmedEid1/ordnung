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
  ListTodo,
  Scale,
  Search,
  Signature,
  UserRound,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { formatDate, formatInlineDates } from "@/lib/format";
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

function day(v: unknown): string {
  return typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) ? formatDate(v, { style: "day" }) : "…";
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

/** A human label for a tool call (without the backend's label). */
export function fallbackToolLabel(name: string, input: Record<string, unknown> = {}, titleOf?: TitleLookup): string {
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
      if (from && to) return `Listed ${scope} from ${day(from)} to ${day(to)}`;
      if (to) return `Listed ${scope} until ${day(to)}`;
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
      return from && to ? `Checked your timeline from ${day(from)} to ${day(to)}` : "Checked your timeline";
    }
    case "today":
      return "Checked today's date";
    case "get_profile":
      return "Checked your profile";
    default:
      return "Looked something up";
  }
}

/** The result next to a finished step ("Today is 2026-09-28" → "Today is 28 Sep 2026"), dates in the app's style. */
export function toolResultText(result: string): string {
  return formatInlineDates(result);
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

/** The chip text for a step: the backend label when present, else the fallback. */
export function toolLabel(step: Pick<ToolStep, "name" | "input" | "label">, titleOf?: TitleLookup): string {
  // the backend's label may carry ISO dates ("from 2026-09-28 to 2026-10-26") and straight quotes
  // ('Searched your letters for "Kündigung"'); the fallback's are curly: one style in the trace
  return step.label ? curlyQuotes(formatInlineDates(step.label)) : fallbackToolLabel(step.name, step.input, titleOf);
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
