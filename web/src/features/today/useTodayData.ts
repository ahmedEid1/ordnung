import { useMemo } from "react";
import { useDashboard, useDocuments, useParties } from "@/api/hooks";
import type { Party } from "@/api/types";
import { useTodayISO } from "@/lib/today";
import { movingRows } from "./moving";
import { buildCandidates, calendarIdea, pickTopThree, selectIdeas, type TodayAction } from "./selection";
import { contractHref } from "@/features/contracts/links";
import { ideasFromNewMail, useOpenedTrayDocs } from "@/features/tour/newMail";

/**
 * Everything the Today page shows, derived once from `/api/dashboard`, the people & organisations
 * list, the "Please check" letters and the letters that couldn't be read. Those, the letters from the
 * watched folder and the letters in the queue (waiting for Claude, say, or being read) are `unread`:
 * nothing of them is in the dashboard, so while any are there nothing is "all clear" (UX U2, final check
 * F-M1: letters waiting for a missing or signed-out Claude stay queued — they don't fail).
 */
export function useTodayData() {
  const today = useTodayISO();
  const dashboard = useDashboard();
  const parties = useParties();
  const review = useDocuments({ status: "needs_review" });
  const failed = useDocuments({ status: "failed" });
  const allDocs = useDocuments();
  const trayDocs = useOpenedTrayDocs();
  const dash = dashboard.data;
  const reviewDocs = review.data;
  const docTitles = useMemo(() => {
    const m = new Map<string, string>();
    for (const d of [...(allDocs.data ?? []), ...(dash?.recent_documents ?? [])]) if (d.title) m.set(d.id, d.title);
    return m;
  }, [allDocs.data, dash?.recent_documents]);

  const derived = useMemo(() => {
    if (!dash) return null;
    const day = dash.today || today;
    const candidates = buildCandidates(dash, { today: day, reviewDocs: reviewDocs ?? [], docTitles });
    const top = pickTopThree(candidates);
    const topKeys = new Set(top.map((a) => a.key));
    const rest = candidates.filter((a) => !topKeys.has(a.key));
    const shownItemIds = new Set(top.flatMap((a) => (a.item ? [a.item.id] : [])));
    // Ideas that came with the demo's new mail go on top, with a "New" badge (the tour points there)
    const pinnedIds = new Set(ideasFromNewMail(dash.suggestions, trayDocs).map((s) => s.id));
    const ideas = selectIdeas(dash.suggestions, { shownItemIds, pinnedIds });
    const nextUp = [...rest].sort((a, b) => a.actionDate.localeCompare(b.actionDate))[0];
    // the moving checklist's rows have a card of their own (after the person said they moved)
    return { day, candidates, top, rest, nextUp, ideas, pinnedIds, calendar: calendarIdea(dash.suggestions), moving: movingRows(dash.suggestions) };
  }, [dash, reviewDocs, docTitles, today, trayDocs]);

  const partyById = useMemo(() => new Map<string, Party>((parties.data ?? []).map((p) => [p.id, p])), [parties.data]);

  const failedDocs = failed.data ?? [];
  const queuedDocs = useMemo(() => (allDocs.data ?? []).filter((d) => d.status === "queued" || d.status === "processing"), [allDocs.data]);
  return {
    dashboard,
    dash,
    derived,
    reviewDocs: reviewDocs ?? [],
    failedDocs,
    queuedDocs,
    unread: (dash?.waiting ?? 0) + failedDocs.length + queuedDocs.length,
    partyById,
    isPending: dashboard.isPending,
    isError: dashboard.isError && !dash,
  };
}

export type TodayData = ReturnType<typeof useTodayData>;

/** Where an action's row / "Open" leads. */
export function actionHref(a: Pick<TodayAction, "docId" | "contractId" | "source">): string {
  if (a.docId) return `/documents/${encodeURIComponent(a.docId)}`;
  if (a.contractId) return contractHref(a.contractId);
  return "/timeline";
}
