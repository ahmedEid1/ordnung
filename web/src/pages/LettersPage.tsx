import { useCallback, useLayoutEffect, useMemo } from "react";
import { useSearchParams } from "react-router";
import { FileCheck2, Languages, PenLine, Plus, Send, ShieldCheck } from "lucide-react";
import { useDrafts, useParties } from "@/api/hooks";
import { Page, PageHeader } from "@/components/shell/Page";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadError } from "@/components/ui/LoadError";
import { LoadingLabel, Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { DraftGroup } from "@/features/letters/DraftList";
import { LetterComposer } from "@/features/letters/LetterComposer";
import { COMPOSER_PARAMS, parsePrefill, splitDrafts } from "@/features/letters/logic";
import { PARTY_PARAM } from "@/lib/party-drawer";
import { cn } from "@/lib/utils";

const HOW = [
  { icon: PenLine, title: "Pick what you want to do", body: "Cancel a contract, object to a decision or reply to a letter." },
  // no "right next to it": a phone shows the translation behind a switch (UI audit round 1)
  { icon: Languages, title: "Ordnung drafts it in German", body: "Legal sentences come from fixed templates, with an English translation to check it against." },
  { icon: FileCheck2, title: "Checks before you send", body: "Reference, dates, addresses and placeholders are checked for you." },
  { icon: Send, title: "How and by when to send it", body: "The safest way to send it, the send-by date — and a reminder to check for a reply." },
];

/** `/letters` — drafts (in progress / sent) and the "New letter" composer (`?new=1`, `?kind=…`). */
export default function LettersPage() {
  const [params, setParams] = useSearchParams();
  const drafts = useDrafts();
  const parties = useParties();

  // Older links used `party=` for the recipient (it would also open the People drawer): read it as `to=`.
  useLayoutEffect(() => {
    const pid = params.get(PARTY_PARAM);
    if (!pid || !(params.has("kind") || params.has("new"))) return;
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete(PARTY_PARAM);
        if (!next.get("to")) next.set("to", pid);
        return next;
      },
      { replace: true },
    );
  }, [params, setParams]);

  const prefill = useMemo(() => parsePrefill(params), [params]);
  const open = Boolean(prefill) && !params.has(PARTY_PARAM);

  const openComposer = useCallback(() => setParams({ new: "1" }), [setParams]);
  const closeComposer = useCallback(
    () =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          COMPOSER_PARAMS.forEach((k) => next.delete(k));
          return next;
        },
        { replace: true },
      ),
    [setParams],
  );

  const partyMap = useMemo(() => new Map((parties.data ?? []).map((p) => [p.id, p])), [parties.data]);
  const list = useMemo(() => drafts.data ?? [], [drafts.data]);
  const { inProgress, sent } = useMemo(() => splitDrafts(list), [list]);
  const listed = !drafts.isPending && !drafts.isError && list.length > 0;
  // the empty state has its own "Write your first letter": one primary button, not two
  const empty = !drafts.isPending && !drafts.isError && list.length === 0;

  return (
    <Page title="Letters">
      <PageHeader
        title="Letters"
        description="Cancellations, objections and replies — drafted in German with an English translation, checked, and ready to send."
        actions={
          empty ? undefined : (
            <Button variant="primary" icon={Plus} onClick={openComposer}>
              New letter
            </Button>
          )
        }
      />

      {/* the "How letters work" card sits beside the list only where both have room (from 1280 px): beside a
          narrow list the rows lost their titles (UI audit round 1) */}
      <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0">
          {drafts.isPending ? (
            <div aria-busy="true">
              <LoadingLabel>Loading your letters…</LoadingLabel>
              {/* as tall as a group's heading (20 px + 10 px), so the card beside it doesn't jump */}
              <Skeleton className="mb-2.5 h-5 w-32" />
              <div className="card divide-y divide-line">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="flex items-center gap-3.5 px-5 py-4">
                    <Skeleton className="size-10 rounded-xl" />
                    <SkeletonText lines={2} className="flex-1" />
                  </div>
                ))}
              </div>
            </div>
          ) : drafts.isError ? (
            <LoadError what="your letters" error={drafts.error} onRetry={() => void drafts.refetch()} retrying={drafts.isFetching} />
          ) : list.length ? (
            <>
              <DraftGroup id="letters-open" title="In progress" drafts={inProgress} parties={partyMap} />
              <DraftGroup id="letters-sent" title="Sent" drafts={sent} parties={partyMap} />
            </>
          ) : (
            <EmptyState
              illustration="letter"
              headingLevel={2}
              title="No letters yet"
              description="When a contract needs cancelling or a decision needs an objection, Ordnung drafts the German letter for you — with a translation, checks and how to send it."
              action={
                <Button variant="primary" icon={Plus} onClick={openComposer}>
                  Write your first letter
                </Button>
              }
            />
          )}
        </div>

        {/* beside the list, its top lines up with the first card under the group heading (20 px line + 10 px);
            beside the empty state or a load error, with their top */}
        <aside aria-labelledby="letters-how" data-letters-how className={cn((listed || drafts.isPending) && "xl:pt-[1.875rem]")}>
          <Card padding="md" className="bg-surface/70">
            <h2 id="letters-how" className="mb-4 flex items-center gap-2 text-[14px] font-semibold text-ink">
              <ShieldCheck className="size-4 text-accent" aria-hidden />
              How letters work
            </h2>
            {/* under the list (below 1280 px) the steps use the width: two columns from 640 px */}
            <ol className="grid gap-4 sm:grid-cols-2 sm:gap-x-6 xl:grid-cols-1">
              {HOW.map((h, i) => (
                <li key={h.title} className="flex gap-3">
                  <span className="relative grid size-7 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
                    <h.icon className="size-3.5" aria-hidden />
                    <span className="sr-only">Step {i + 1}: </span>
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[13.5px] font-medium text-ink">{h.title}</span>
                    <span className="mt-0.5 block text-[12.5px] leading-5 text-muted">{h.body}</span>
                  </span>
                </li>
              ))}
            </ol>
            <p className="mt-5 border-t border-line pt-4 text-[12.5px] leading-5 text-muted">Nothing is ever sent for you. You print, sign or send it yourself.</p>
            <Disclaimer className="mt-3" />
          </Card>
        </aside>
      </div>

      <LetterComposer open={open} onClose={closeComposer} prefill={prefill} />
    </Page>
  );
}
