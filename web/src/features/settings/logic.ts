/** Settings (SPEC §14.8): pure helpers for reminders, AI usage and the data export. */
import type { Activity, ItemKind, LLMCallRecord, RuleInfo, UsageStats } from "@/api/types";
import { ITEM_KINDS } from "@/api/types";
import { LLM_PURPOSE_LABELS, humanize } from "@/lib/copy";

// ------------------------------------------------------------------------------------------------
// Sections
// ------------------------------------------------------------------------------------------------

export const SECTION_IDS = ["profile", "region", "reminders", "calendar", "folder", "ai", "claude", "privacy", "rules", "data"] as const;
export type SectionId = (typeof SECTION_IDS)[number];

export function parseSection(v: string | null | undefined): SectionId {
  return (SECTION_IDS as readonly string[]).includes(v ?? "") ? (v as SectionId) : "profile";
}

/** What each section is called (navigation, "unsaved changes" warnings). */
export const SECTION_LABELS: Record<SectionId, string> = {
  profile: "Profile & address",
  region: "Region & language",
  reminders: "Reminders",
  calendar: "Calendar",
  folder: "Watched folder",
  ai: "AI & models",
  claude: "Claude connection",
  privacy: "Privacy & AI usage",
  rules: "How dates are computed",
  data: "Data",
};

/**
 * Does moving from `from` to `to` leave the current settings section (another section or another
 * page)? Unsaved edits are only lost then — other query parameters (e.g. the People drawer) keep it.
 */
export function leavesSection(from: { pathname: string; search: string }, to: { pathname: string; search: string }): boolean {
  if (from.pathname !== to.pathname) return true;
  return parseSection(new URLSearchParams(from.search).get("section")) !== parseSection(new URLSearchParams(to.search).get("section"));
}

// ------------------------------------------------------------------------------------------------
// Reminders
// ------------------------------------------------------------------------------------------------

/** The reminder kinds shown in Settings, in a sensible order, with human words. */
export const REMINDER_KINDS: { kind: ItemKind; label: string; hint: string }[] = [
  { kind: "deadline", label: "Deadlines", hint: "Objections, cancellations, forms" },
  { kind: "payment", label: "Payments", hint: "Bills, fees, rent" },
  { kind: "appointment", label: "Appointments", hint: "Offices, doctors, meetings" },
  { kind: "expiry", label: "Expiry dates", hint: "Passport, residence permit, cards" },
  { kind: "task", label: "To-dos", hint: "Things to prepare or follow up" },
  { kind: "reminder", label: "Your own reminders", hint: "Reminders you added yourself" },
  { kind: "milestone", label: "Milestones", hint: "Contract ends, semester starts" },
];

export const MAX_LEAD_DAYS = 365;

/** Unique, whole, 0…365, largest first. */
export function normalizeLeadDays(days: readonly number[]): number[] {
  return [...new Set(days.filter((d) => Number.isFinite(d)).map((d) => Math.round(d)))]
    .filter((d) => d >= 0 && d <= MAX_LEAD_DAYS)
    .sort((a, b) => b - a);
}

/** "1 day", "3 days", "1 week", "2 weeks" (exact multiples of 7 read as weeks) — a lead time > 0. */
export function leadSpan(d: number): string {
  if (d % 7 === 0 && d >= 7) return d === 7 ? "1 week" : `${d / 7} weeks`;
  return d === 1 ? "1 day" : `${d} days`;
}

/** "on the day", "1 day before", "2 weeks before" (exact multiples of 7 read as weeks). */
export function leadLabel(d: number): string {
  return d === 0 ? "On the day" : `${leadSpan(d)} before`;
}

/** Why a typed lead time can't be added (null: it can). */
export function leadDaysError(text: string, existing: readonly number[]): string | null {
  const t = text.trim();
  if (!/^\d+$/.test(t)) return "Enter a number of days, like 5";
  const n = Number(t);
  if (n > MAX_LEAD_DAYS) return `Up to ${MAX_LEAD_DAYS} days`;
  if (existing.includes(n)) return `Already in the list (${leadLabel(n).toLowerCase()})`;
  return null;
}

/** Profile reminder days with every kind present (missing kinds → empty list). */
export function completeReminderDays(days: Record<string, number[]> | null | undefined): Record<ItemKind, number[]> {
  const out = {} as Record<ItemKind, number[]>;
  for (const k of ITEM_KINDS) out[k] = normalizeLeadDays(days?.[k] ?? []);
  return out;
}

export function sameReminderDays(a: Record<string, number[]>, b: Record<string, number[]>): boolean {
  return ITEM_KINDS.every((k) => (a[k] ?? []).join(",") === (b[k] ?? []).join(","));
}

// ------------------------------------------------------------------------------------------------
// AI usage
// ------------------------------------------------------------------------------------------------

export interface PurposeRow {
  purpose: string;
  label: string;
  calls: number;
  tokens: number;
  cost: number;
}

export function purposeLabel(purpose: string): string {
  return LLM_PURPOSE_LABELS[purpose] ?? humanize(purpose);
}

/** One row per purpose, most expensive first. */
export function purposeRows(usage: UsageStats | null | undefined): PurposeRow[] {
  return Object.entries(usage?.by_purpose ?? {})
    .map(([purpose, s]) => ({
      purpose,
      label: purposeLabel(purpose),
      calls: s.calls ?? 0,
      tokens: (s.input_tokens ?? 0) + (s.output_tokens ?? 0),
      cost: s.cost_usd ?? 0,
    }))
    .sort((a, b) => b.cost - a.cost || b.tokens - a.tokens);
}

/** Share of calls answered from the local cache (no call to Claude). */
export function cacheRate(usage: Pick<UsageStats, "calls" | "cache_hits"> | null | undefined): number | null {
  if (!usage || !usage.calls) return null;
  return usage.cache_hits / usage.calls;
}

/** "Sonnet", "Haiku", "Opus" from a model alias or id (`sonnet`, or a dated id the CLI reports). */
export function modelFamily(model: string): string {
  const m = /(haiku|sonnet|opus)/i.exec(model);
  return m ? m[1]!.charAt(0).toUpperCase() + m[1]!.slice(1).toLowerCase() : model;
}

/** What a call sent, in words: "2 pages of 1 letter · 2.3 KB" / "Your question and search results". */
export function sentSummary(c: Pick<LLMCallRecord, "doc_ids" | "pages_sent" | "bytes_sent" | "purpose" | "cache_hit">, fileSize: (b: number) => string): string {
  if (c.cache_hit) return "Nothing — answered from the cache on this computer";
  const parts: string[] = [];
  if (c.pages_sent) parts.push(`${c.pages_sent} ${c.pages_sent === 1 ? "page" : "pages"}`);
  if (c.doc_ids.length) parts.push(`${parts.length ? "of " : ""}${c.doc_ids.length} ${c.doc_ids.length === 1 ? "letter" : "letters"}`);
  const what = parts.join(" ");
  const size = c.bytes_sent ? fileSize(c.bytes_sent) : "";
  if (what) return [what, size].filter(Boolean).join(" · ");
  if (c.purpose === "ask") return "Your question and what Claude looked up";
  if (c.purpose === "brief" || c.purpose === "review") return "A summary of your dates and Ideas — no letters";
  return size || "Instructions only — no letters";
}

// ------------------------------------------------------------------------------------------------
// Activity
// ------------------------------------------------------------------------------------------------

/** Where an activity entry leads: its letter, its draft, or Ask for the checks of an answer. */
export function activityHref(a: Pick<Activity, "ref_type" | "ref_id">): string | null {
  if (a.ref_type === "chat") return "/ask";
  if (!a.ref_id) return null;
  if (a.ref_type === "document") return `/documents/${a.ref_id}`;
  if (a.ref_type === "draft") return `/letters/${a.ref_id}`;
  return null;
}

/** What Ask's checks did to a run of answers, folded into one row of the activity log. */
export interface AskChecks {
  /** How many answers were checked (an answer can log up to three checks). */
  answers: number;
  /** Each thing the checks did, in words ("Took out sentences or values …"), and to how many answers; newest first. */
  done: { what: string; answers: number }[];
}

/** One row of the activity log: an entry and how many identical ones came right before it. */
export interface ActivityRow {
  entry: Activity;
  /** 1, or e.g. 10 for ten "Read …" in a row (`entry` is the newest). */
  count: number;
  /** Set when the row folds several checks of Ask's answers ("Checked 12 answers in Ask"). */
  askChecks?: AskChecks;
}

/** An entry Ask's checks of an answer wrote (it leads to Ask, its `ref_id` is the answer). */
const isAskCheck = (a: Pick<Activity, "kind" | "ref_type">) => a.ref_type === "chat" && a.kind.startsWith("ask.");

const ASK_CHECK_PREFIX = /^Checked an answer in Ask:\s*/;

/** "Checked an answer in Ask: took out …" → "Took out …" (the row says which answers). */
export function askCheckWhat(message: string): string {
  const what = message.replace(ASK_CHECK_PREFIX, "").trim();
  return what.charAt(0).toUpperCase() + what.slice(1);
}

/** "Checked 12 answers in Ask" / "Checked an answer in Ask" — the message of a folded row. */
export function askChecksMessage(answers: number): string {
  return answers === 1 ? "Checked an answer in Ask" : `Checked ${answers} answers in Ask`;
}

/**
 * Runs of the same entry (same kind, message and target) become one row with a count. A run of
 * Ask's checks becomes one row whatever each check did — they alternate within an answer (up to three
 * per answer), and would push the letters read and exports out of view.
 */
export function groupActivity(list: readonly Activity[]): ActivityRow[] {
  const rows: ActivityRow[] = [];
  const checks = new Map<ActivityRow, Activity[]>(); // the Ask checks a row folds
  for (const entry of list) {
    const last = rows[rows.length - 1];
    const run = last && checks.get(last);
    if (last && run && isAskCheck(entry)) {
      run.push(entry);
      last.count += 1;
    } else if (last && !run && last.entry.kind === entry.kind && last.entry.message === entry.message && activityHref(last.entry) === activityHref(entry)) {
      last.count += 1;
    } else {
      const row: ActivityRow = { entry, count: 1 };
      rows.push(row);
      if (isAskCheck(entry)) checks.set(row, [entry]);
    }
  }
  const answer = (a: Activity) => a.ref_id ?? `#${a.id}`;
  for (const [row, run] of checks) {
    if (run.length < 2) continue; // a single check: its own message says it all
    const done = new Map<string, Set<string>>();
    for (const e of run) {
      const what = askCheckWhat(e.message);
      done.set(what, (done.get(what) ?? new Set()).add(answer(e)));
    }
    row.askChecks = { answers: new Set(run.map(answer)).size, done: [...done].map(([what, answers]) => ({ what, answers: answers.size })) };
  }
  return rows;
}

// ------------------------------------------------------------------------------------------------
// Rules ("How dates are computed")
// ------------------------------------------------------------------------------------------------

/** "§ 193 BGB; §§ 269, 270 Abs. 4 BGB" → each source on its own (a ";" inside brackets stays). */
export function splitCitation(citation: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < citation.length; i++) {
    const ch = citation[i];
    if (ch === "(") depth++;
    else if (ch === ")") depth = Math.max(0, depth - 1);
    else if (ch === ";" && depth === 0) {
      parts.push(citation.slice(start, i));
      start = i + 1;
    }
  }
  parts.push(citation.slice(start));
  return parts.map((p) => p.trim()).filter(Boolean);
}

/** Heading for rules the catalog files under no topic. */
export const OTHER_RULES_TOPIC = "More rules";

/** Rules grouped by topic, topics in catalog order (rules without one come last). */
export function groupRules<T extends Pick<RuleInfo, "topic">>(rules: readonly T[]): { topic: string; rules: T[] }[] {
  const groups = new Map<string, T[]>();
  for (const r of rules) {
    const topic = r.topic?.trim() || OTHER_RULES_TOPIC;
    groups.set(topic, [...(groups.get(topic) ?? []), r]);
  }
  const other = groups.get(OTHER_RULES_TOPIC);
  groups.delete(OTHER_RULES_TOPIC);
  if (other) groups.set(OTHER_RULES_TOPIC, other);
  return [...groups].map(([topic, list]) => ({ topic, rules: list }));
}

/** Search the rules: title, citation, summary and topic, ignoring case. */
export function matchesRule(r: Pick<RuleInfo, "title" | "citation" | "summary" | "topic">, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [r.title, r.citation, r.summary, r.topic ?? ""].some((s) => s.toLowerCase().includes(needle));
}

// ------------------------------------------------------------------------------------------------
// Export
// ------------------------------------------------------------------------------------------------

/** File name for the JSON export: `ordnung-export-2026-09-28.json`. */
export function exportFileName(today: string): string {
  return `ordnung-export-${today}.json`;
}
