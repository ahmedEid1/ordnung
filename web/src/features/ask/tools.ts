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

function str(v: unknown): string {
  const s = String(v ?? "")
    .replace(/\s+/g, " ")
    .trim();
  return s.length > 60 ? `${s.slice(0, 59)}…` : s;
}

function day(v: unknown): string {
  return typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) ? formatDate(v, { style: "day" }) : str(v);
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
      const scope = `your ${statusWord(input.status)}to-dos & dates`;
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

/** The chip text for a step: the backend label when present, else the fallback. */
export function toolLabel(step: Pick<ToolStep, "name" | "input" | "label">, titleOf?: TitleLookup): string {
  // the backend's label may carry ISO dates ("from 2026-09-28 to 2026-10-26")
  return step.label ? formatInlineDates(step.label) : fallbackToolLabel(step.name, step.input, titleOf);
}
