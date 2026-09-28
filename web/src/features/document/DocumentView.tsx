/**
 * The Document viewer (SPEC §14.3) — the trust centrepiece.
 * Desktop: page images (sticky) on the left, the panel on the right. Phones / tablets: stacked,
 * verdict first, then warnings, the pages and the rest.
 *
 * Panel order: verdict → warnings / Please check → Explained simply → To-dos & dates → Key facts →
 * Thread, contract, drafts, Ideas → provenance + Reprocess / Download / Delete.
 */
import { useCallback, useEffect, useMemo } from "react";
import { useLocation } from "react-router";
import { useMediaQuery } from "@/lib/hooks";
import { useReducedMotion } from "motion/react";
import type { DocumentDetail } from "@/api/types";
import { SkeletonCard, SkeletonText } from "@/components/ui/Skeleton";
import { EvidenceProvider } from "./EvidenceContext";
import { collectAnchors } from "./evidence";
import { decisionSuggestion, leadsWithDecision, selectPrimaryItem, scamSuggestion } from "./verdict";
import { PageViewer } from "./PageViewer";
import { VerdictCard } from "./VerdictCard";
import { DocumentWarnings } from "./Warnings";
import { ExplainedSimply } from "./Explained";
import { ItemsList } from "./ItemsList";
import { KeyFacts } from "./KeyFacts";
import { ContractsSection, DraftsSection, IdeasSection, ThreadSection } from "./Related";
import { DocumentFooter } from "./DocumentFooter";
import { ProcessingCard } from "./ProcessingCard";

export function DocumentView({ detail }: { detail: DocumentDetail }) {
  const doc = detail.document;
  const reduced = useReducedMotion();
  const anchors = useMemo(() => collectAnchors(detail), [detail]);
  // never a to-do the server set aside (an invoice its reminder replaced, a date long past when it was read)
  const primary = useMemo(() => selectPrimaryItem(detail.items, detail.set_aside), [detail.items, detail.set_aside]);
  // from xl the pages sit in a sticky column beside the panel; below, in the page's own column
  const column = useMediaQuery("(min-width: 1280px)");
  // the decision the verdict card leads with isn't repeated under "Ideas"
  const lead = useMemo(() => {
    const decision = decisionSuggestion(detail);
    return leadsWithDecision(decision, primary) ? decision : null;
  }, [detail, primary]);
  const scam = Boolean(scamSuggestion(detail));
  const busy = doc.status === "queued" || doc.status === "processing" || doc.status === "failed";
  const neverRead = busy && !doc.kind && !doc.title;

  // opened for its advice card ("Open the letter's card" in the composer): scroll to it and focus its title
  // (review round 3 of phase 2: the page opened at its top, focus on <main>, the card 1250 px below)
  const location = useLocation();
  const toCard = (location.state as { focus?: string } | null)?.focus === "advice" && !neverRead;
  useEffect(() => {
    if (!toCard) return;
    const frame = window.requestAnimationFrame(() => {
      document.getElementById(`advice-card-${doc.id}`)?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
      document.getElementById(`advice-${doc.id}`)?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [toCard, doc.id, reduced]);

  const askArrival = useCallback(() => {
    const el = document.getElementById("arrival-question");
    el?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
    el?.querySelector<HTMLInputElement>("input[type=date]")?.focus({ preventScroll: true });
  }, [reduced]);

  return (
    <EvidenceProvider anchors={anchors}>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.04fr)_minmax(0,1fr)] xl:gap-x-8 xl:gap-y-6">
        <div className="min-w-0 space-y-4 xl:col-start-2 xl:row-start-1">
          {busy ? <ProcessingCard doc={doc} /> : null}
          {!neverRead ? <VerdictCard detail={detail} primary={primary} onAskArrival={askArrival} /> : null}
          {!neverRead ? <DocumentWarnings detail={detail} /> : null}
        </div>

        <div className="min-w-0 xl:sticky xl:top-[72px] xl:col-start-1 xl:row-span-2 xl:row-start-1 xl:self-start">
          <PageViewer
            docId={doc.id}
            pages={detail.pages}
            pageCount={doc.pages}
            photo={doc.text_mode === "vision"}
            // below xl one page at a time and no scroll box of its own (a swipe scrolled only the box); the
            // sticky column is as tall as the screen at most — shorter when the pages are (a passport photo)
            paged={!column}
            className="xl:max-h-[calc(100dvh-88px)]"
          />
        </div>

        <div className="min-w-0 space-y-7 xl:col-start-2 xl:row-start-2">
          {neverRead ? (
            <div className="space-y-4" aria-hidden>
              <SkeletonCard lines={3} />
              <div className="card p-5">
                <SkeletonText lines={4} />
              </div>
            </div>
          ) : (
            <>
              <ExplainedSimply doc={doc} />
              <ItemsList items={detail.items} docId={doc.id} pages={doc.pages} scam={scam} />
              <KeyFacts doc={doc} scam={scam} girocodes={detail.girocodes} />
              <ThreadSection detail={detail} />
              <ContractsSection contracts={detail.contracts} />
              <DraftsSection drafts={detail.drafts} />
              <IdeasSection suggestions={lead ? detail.suggestions.filter((s) => s.id !== lead.id) : detail.suggestions} docId={doc.id} items={detail.items} primaryId={primary?.id} />
            </>
          )}
          <DocumentFooter detail={detail} />
        </div>
      </div>
    </EvidenceProvider>
  );
}

/** Loading layout matching the viewer (no layout jump when the data arrives). */
export function DocumentSkeleton() {
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.04fr)_minmax(0,1fr)] xl:gap-8" aria-busy="true">
      <div className="space-y-4 xl:col-start-2 xl:row-start-1">
        <SkeletonCard lines={4} />
        <SkeletonCard lines={2} />
      </div>
      <div className="card h-[60vh] animate-pulse bg-surface-2 motion-reduce:animate-none xl:col-start-1 xl:row-start-1 xl:h-[calc(100dvh-88px)]" />
    </div>
  );
}
