/**
 * The Document viewer (SPEC §14.3) — the trust centrepiece.
 * Desktop: page images (sticky) on the left, the panel on the right. Phones / tablets: stacked,
 * verdict first, then warnings, the pages and the rest.
 *
 * Panel order: verdict → warnings / Please check → Explained simply → To-dos & dates → Key facts →
 * Thread, contract, drafts, Ideas → provenance + Reprocess / Download / Delete.
 *
 * Two tabs above the panel (`?view=trace` for the second, so it can be linked): the letter, and "How
 * this was read" — every step of its reading (`./trace`). The pages stay beside it on wide screens.
 * The letter's content is split around the pages (verdict first, then the pages on phones, then the
 * rest), so "The letter" controls two panels: its verdict and warnings, and the rest of the letter.
 */
import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";
import { useReducedMotion } from "motion/react";
import { FileText, Route } from "lucide-react";
import type { DocumentDetail } from "@/api/types";
import { SkeletonCard, SkeletonText } from "@/components/ui/Skeleton";
import { TabPanel, Tabs } from "@/components/ui/Tabs";
import { cn } from "@/lib/utils";
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
import { TracePanel } from "./trace/TracePanel";

type DocView = "letter" | "trace";
/** The second panel of the letter tab: the rest of the letter, after the pages. */
const LETTER_MORE_PANEL = "doc-view-panel-letter-more";
const VIEW_TABS = [
  { value: "letter" as const, label: "The letter", icon: FileText, controls: [LETTER_MORE_PANEL] },
  { value: "trace" as const, label: "How this was read", shortLabel: "How it was read", icon: Route },
];

/** The tab shown (`?view=trace`), kept in the address without adding a history entry per switch. */
function useDocView(): [DocView, (view: DocView) => void] {
  const [params, setParams] = useSearchParams();
  const view: DocView = params.get("view") === "trace" ? "trace" : "letter";
  const setView = useCallback(
    (next: DocView) =>
      setParams(
        (prev) => {
          const out = new URLSearchParams(prev);
          if (next === "trace") out.set("view", "trace");
          else out.delete("view");
          return out;
        },
        { replace: true },
      ),
    [setParams],
  );
  return [view, setView];
}

export function DocumentView({ detail }: { detail: DocumentDetail }) {
  const doc = detail.document;
  const reduced = useReducedMotion();
  const anchors = useMemo(() => collectAnchors(detail), [detail]);
  const primary = useMemo(() => selectPrimaryItem(detail.items), [detail.items]);
  // the decision the verdict card leads with isn't repeated under "Ideas"
  const lead = useMemo(() => {
    const decision = decisionSuggestion(detail);
    return leadsWithDecision(decision, primary) ? decision : null;
  }, [detail, primary]);
  const scam = Boolean(scamSuggestion(detail));
  const busy = doc.status === "queued" || doc.status === "processing" || doc.status === "failed";
  const neverRead = busy && !doc.kind && !doc.title;
  const [view, setView] = useDocView();
  const trace = view === "trace";

  const askArrival = useCallback(() => {
    const el = document.getElementById("arrival-question");
    el?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
    el?.querySelector<HTMLInputElement>("input[type=date]")?.focus({ preventScroll: true });
  }, [reduced]);

  return (
    <EvidenceProvider anchors={anchors}>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.04fr)_minmax(0,1fr)] xl:gap-x-8 xl:gap-y-6">
        <div className="min-w-0 space-y-4 xl:col-start-2 xl:row-start-1">
          <Tabs<DocView> id="doc-view" label="Show" value={view} onChange={setView} items={VIEW_TABS} fill />
          <TabPanel id="doc-view" value="trace" current={view}>
            <TracePanel detail={detail} />
          </TabPanel>
          {/* the letter's panel is its verdict and warnings; the rest of the letter follows the pages */}
          <TabPanel id="doc-view" value="letter" current={view} className="space-y-4 empty:hidden">
            {busy ? <ProcessingCard doc={doc} /> : null}
            {!neverRead ? <VerdictCard detail={detail} primary={primary} onAskArrival={askArrival} /> : null}
            {!neverRead ? <DocumentWarnings detail={detail} /> : null}
          </TabPanel>
        </div>

        {/* on phones and tablets the pages would follow a long list of steps: the trace tab leaves them out */}
        <div className={cn("min-w-0 xl:sticky xl:top-[72px] xl:col-start-1 xl:row-span-2 xl:row-start-1 xl:self-start", trace && "max-xl:hidden")}>
          <PageViewer
            docId={doc.id}
            pages={detail.pages}
            pageCount={doc.pages}
            photo={doc.text_mode === "vision"}
            className="max-h-[78vh] xl:h-[calc(100dvh-88px)] xl:max-h-none"
          />
        </div>

        {trace ? null : (
          <div
            role="tabpanel"
            id={LETTER_MORE_PANEL}
            aria-labelledby="doc-view-tab-letter"
            className="min-w-0 space-y-7 xl:col-start-2 xl:row-start-2"
          >
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
                <ItemsList items={detail.items} docId={doc.id} />
                <KeyFacts doc={doc} scam={scam} />
                <ThreadSection detail={detail} />
                <ContractsSection contracts={detail.contracts} />
                <DraftsSection drafts={detail.drafts} />
                <IdeasSection suggestions={lead ? detail.suggestions.filter((s) => s.id !== lead.id) : detail.suggestions} />
              </>
            )}
            <DocumentFooter detail={detail} />
          </div>
        )}
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
