/**
 * Ideas that came from the demo's *New mail* tray — the ones the tour's "An idea just arrived" step
 * is about, and the ones Today pins on top with a "New" badge. Pure helpers plus one hook.
 */
import { useMemo } from "react";
import { useHealth, useMailTray, useSuggestions } from "@/api/hooks";
import type { MailTrayItem, Suggestion } from "@/api/types";

/**
 * Rules whose Ideas are worth announcing: a decision, a risk or a warning. Housekeeping Ideas ("Add
 * your 27 dates to your calendar", "Please check") change whenever any letter is read, so they
 * never count as "an idea arrived".
 */
export const HEADLINE_RULES: ReadonlySet<string> = new Set([
  "price_increase_right",
  "scam_warning",
  "dunning_escalation",
  "contract_cancel_window",
  "confirm_cancellation",
  "expiry_soon",
  "passport_before_permit",
  "followup_due",
]);

/** Document ids of the letters taken out of the tray so far. */
export function openedTrayDocIds(tray: readonly MailTrayItem[] | undefined): Set<string> {
  return new Set((tray ?? []).flatMap((m) => (m.opened && m.doc_id ? [m.doc_id] : [])));
}

/** A new (not dismissed/snoozed) Idea worth announcing. */
export function isHeadlineIdea(s: Pick<Suggestion, "status" | "rule_id" | "source">): boolean {
  return s.status === "new" && (s.source === "review" || HEADLINE_RULES.has(s.rule_id ?? ""));
}

/** Headline Ideas about a letter from the tray, most important first. */
export function ideasFromNewMail(suggestions: readonly Suggestion[] | undefined, trayDocs: ReadonlySet<string>): Suggestion[] {
  if (!trayDocs.size) return [];
  const rank = { critical: 0, high: 1, normal: 2, low: 3 } as const;
  return (suggestions ?? [])
    .filter((s) => isHeadlineIdea(s) && s.refs.some((r) => r.type === "document" && trayDocs.has(r.id)))
    .sort((a, b) => rank[a.priority] - rank[b.priority] || b.created_at.localeCompare(a.created_at));
}

/** The demo's tray letters by the document they became (empty outside the demo). */
export function useTrayByDoc(): Map<string, MailTrayItem> {
  const demo = Boolean(useHealth().data?.demo);
  const tray = useMailTray(demo);
  return useMemo(
    () => new Map((demo ? tray.data ?? [] : []).flatMap((m) => (m.doc_id ? [[m.doc_id, m] as const] : []))),
    [demo, tray.data],
  );
}

/** The demo's opened tray letters (empty outside the demo). */
export function useOpenedTrayDocs(): Set<string> {
  const demo = Boolean(useHealth().data?.demo);
  const tray = useMailTray(demo);
  return useMemo(() => openedTrayDocIds(demo ? tray.data : undefined), [demo, tray.data]);
}

/**
 * Headline Ideas that came with the new mail (empty outside the demo or before a letter was
 * opened); `ready` once both the tray and the Ideas have loaded.
 */
export function useNewMailIdeas(enabled = true): { ideas: Suggestion[]; ready: boolean } {
  const demo = Boolean(useHealth().data?.demo);
  const tray = useMailTray(demo);
  const suggestions = useSuggestions();
  const ready = demo && tray.isSuccess && suggestions.isSuccess;
  const ideas = useMemo(
    () => (enabled && ready ? ideasFromNewMail(suggestions.data, openedTrayDocIds(tray.data)) : []),
    [enabled, ready, suggestions.data, tray.data],
  );
  return { ideas, ready };
}
