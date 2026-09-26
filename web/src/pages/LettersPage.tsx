import { useCallback, useLayoutEffect, useMemo } from "react";
import { useSearchParams } from "react-router";
import { FileCheck2, Languages, PenLine, Plus, Send, ShieldCheck } from "lucide-react";
import { useDrafts, useParties } from "@/api/hooks";
import { Page, PageHeader } from "@/components/shell/Page";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingLabel, Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { DraftGroup } from "@/features/letters/DraftList";
import { LetterComposer } from "@/features/letters/LetterComposer";
import { COMPOSER_PARAMS, parsePrefill } from "@/features/letters/logic";
import { PARTY_PARAM } from "@/lib/party-drawer";

const HOW = [
  { icon: PenLine, title: "Pick what you want to do", body: "Cancel a contract, object to a decision or reply to a letter." },
  { icon: Languages, title: "Ordnung drafts it in German", body: "Legal sentences come from fixed templates. An English translation sits right next to it." },
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
  const list = drafts.data ?? [];
  const inProgress = list.filter((d) => d.status !== "sent");
  const sent = list.filter((d) => d.status === "sent");

  return (
    <Page title="Letters">
      <PageHeader
        title="Letters"
        description="Cancellations, objections and replies — drafted in German with an English translation, checked, and ready to send."
        actions={
          <Button variant="primary" icon={Plus} onClick={openComposer}>
            New letter
          </Button>
        }
      />

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0">
          {drafts.isPending ? (
            <div aria-busy="true">
              <LoadingLabel>Loading your letters…</LoadingLabel>
              <Skeleton className="mb-3 h-4 w-32" />
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
            <EmptyState illustration="error" headingLevel={2} title="Couldn't load your letters" description="Is Ordnung still running on this computer?" action={<Button onClick={() => void drafts.refetch()}>Try again</Button>} />
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

        <aside aria-labelledby="letters-how" className="lg:pt-[30px]">
          <Card padding="md" className="bg-surface/70">
            <h2 id="letters-how" className="mb-4 flex items-center gap-2 text-[14px] font-semibold text-ink">
              <ShieldCheck className="size-4 text-accent" aria-hidden />
              How letters work
            </h2>
            <ol className="space-y-4">
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
