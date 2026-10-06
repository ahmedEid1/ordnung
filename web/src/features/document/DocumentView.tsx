/**
 * The Document viewer (SPEC §14.3) — the trust centrepiece.
 * Desktop: page images (sticky) on the left, the panel on the right. Phones / tablets: stacked,
 * verdict first, then warnings, the pages and the rest.
 *
 * Panel order: verdict → warnings / Please check → Explained simply → To-dos & dates → Key facts →
 * the e-mail it came with / an e-mail's attachments → Thread, contract, drafts, Ideas → provenance +
 * Reprocess / Download / Delete. A letter that waits for the person (from the watched folder) shows
 * its waiting card in the verdict's place, and nothing read from it (nothing was) — only the dates the
 * person adds, as a letter Claude couldn't read does, and one that waits in the queue for Claude.
 *
 * Two tabs above the panel (`?view=trace` for the second, so it can be linked): the letter, and "How
 * this was read" — every step of its reading (`./trace`). The pages stay beside it on wide screens.
 * The letter's content is split around the pages (verdict first, then the pages on phones, then the
 * rest), so "The letter" controls two panels: its verdict and warnings, and the rest of the letter.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useSearchParams } from "react-router";
import { useMediaQuery } from "@/lib/hooks";
import { useReducedMotion } from "motion/react";
import { FileText, Route } from "lucide-react";
import type { DocumentDetail, DocumentStatus } from "@/api/types";
import { Skeleton, SkeletonCard, SkeletonText } from "@/components/ui/Skeleton";
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
import { ProcessingCard, useClaudeWait } from "./ProcessingCard";
import { HeldCard } from "./HeldCard";
import { EmailParts } from "./EmailParts";
import { TracePanel } from "./trace/TracePanel";

type DocView = "letter" | "trace";
/** The second panel of the letter tab: the rest of the letter, after the pages. */
const LETTER_MORE_PANEL = "doc-view-panel-letter-more";
const VIEW_TABS = [
  { value: "letter" as const, label: "The letter", icon: FileText, controls: [LETTER_MORE_PANEL] },
  { value: "trace" as const, label: "How it was read", icon: Route },
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
  // nothing comes for a letter that couldn't be read, or that waits for Claude until it is connected: no
  // placeholders that never fill (feature audit G15, final check F-M2)
  const claudeWait = useClaudeWait(doc);
  const reading = neverRead && doc.status !== "failed" && !claudeWait;
  const held = doc.status === "held";

  // an answer to a waiting letter ("Keep private", "Read it with Claude", "Undo “Keep private”") replaces its card with
  // another's: once the answer went through AND the letter's new state is rendered, focus moves to the page's new first
  // heading (never to the page). The two come in either order (e2e: "focus never falls to the page"):
  // - the answer's refetch is rendered after its promise resolves (the query tells its listeners a task later), so a
  //   focus moved on the next frame landed on the old heading on a busy computer, and fell to the page with it;
  // - the server says the letter changed (`document.updated`) before it replies, and the refetch that event starts can
  //   be rendered before the reply comes (a server slowed by a busy computer): the new card is on the page, the answered
  //   button gone with the old one, and the status no longer changes when the answer resolves.
  // So the card says which status it answered from, and the move waits for a rendered status other than that one.
  const answeredFrom = useRef<DocumentStatus | null>(null);
  const [answers, setAnswers] = useState(0);
  const onAnswered = useCallback((from: DocumentStatus) => {
    answeredFrom.current = from;
    setAnswers((n) => n + 1); // runs the effect below after this render, in case the new card is already there
  }, []);
  useEffect(() => {
    const from = answeredFrom.current;
    if (from === null || doc.status === from) return; // not answered, or its new state isn't rendered yet
    answeredFrom.current = null;
    const h = document.querySelector<HTMLElement>("main h1, main h2");
    if (!h) return;
    if (!h.hasAttribute("tabindex")) h.setAttribute("tabindex", "-1");
    h.focus({ preventScroll: true });
  }, [doc.status, answers]);

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
  const [view, setView] = useDocView();
  const trace = view === "trace";

  const askArrival = useCallback(() => {
    const el = document.getElementById("arrival-question");
    el?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
    el?.querySelector<HTMLInputElement>("input[type=date]")?.focus({ preventScroll: true });
  }, [reduced]);

  return (
    <EvidenceProvider anchors={anchors}>
      {/* the first row is as tall as the verdict (or waiting) card; the page viewer's spare height goes to the rest */}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.04fr)_minmax(0,1fr)] xl:grid-rows-[auto_1fr] xl:gap-x-8 xl:gap-y-6">
        <div className="min-w-0 space-y-4 xl:col-start-2 xl:row-start-1">
          <Tabs<DocView> id="doc-view" label="Show" value={view} onChange={setView} items={VIEW_TABS} fill />
          <TabPanel id="doc-view" value="trace" current={view}>
            <TracePanel detail={detail} />
          </TabPanel>
          {/* the letter's panel is its verdict (or waiting card) and warnings; the rest of the letter follows the pages */}
          <TabPanel id="doc-view" value="letter" current={view} className="space-y-4 empty:hidden">
            {busy ? <ProcessingCard doc={doc} /> : null}
            {held ? (
              <HeldCard detail={detail} onAnswered={onAnswered} />
            ) : !neverRead ? (
              <VerdictCard detail={detail} primary={primary} onAskArrival={askArrival} onAnswered={onAnswered} />
            ) : null}
            {!neverRead && !held ? <DocumentWarnings detail={detail} /> : null}
          </TabPanel>
        </div>

        {/* on phones and tablets the pages would follow a long list of steps: the trace tab leaves them out */}
        <div className={cn("min-w-0 xl:sticky xl:top-[72px] xl:col-start-1 xl:row-span-2 xl:row-start-1 xl:self-start", trace && "max-xl:hidden")}>
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

        {trace ? null : (
          <div
            role="tabpanel"
            id={LETTER_MORE_PANEL}
            aria-labelledby="doc-view-tab-letter"
            className="min-w-0 space-y-7 xl:col-start-2 xl:row-start-2"
          >
            {reading ? (
              <div className="space-y-4" aria-hidden>
                <SkeletonCard lines={3} />
                <div className="card p-5">
                  <SkeletonText lines={4} />
                </div>
              </div>
            ) : held || neverRead ? (
              // nothing read from it: only the dates the person adds
              <>
                <ItemsList items={detail.items} docId={doc.id} pages={doc.pages} letter={doc} />
                <EmailParts detail={detail} />
              </>
            ) : (
              <>
                <ExplainedSimply doc={doc} />
                <ItemsList items={detail.items} docId={doc.id} pages={doc.pages} scam={scam} setAside={detail.set_aside} documents={detail.related} letter={doc} />
                <KeyFacts doc={doc} scam={scam} girocodes={detail.girocodes} />
                <EmailParts detail={detail} />
                <ThreadSection detail={detail} />
                <ContractsSection contracts={detail.contracts} />
                <DraftsSection drafts={detail.drafts} />
                <IdeasSection suggestions={lead ? detail.suggestions.filter((s) => s.id !== lead.id) : detail.suggestions} docId={doc.id} items={detail.items} primaryId={primary?.id} />
              </>
            )}
            <DocumentFooter detail={detail} />
          </div>
        )}
      </div>
    </EvidenceProvider>
  );
}

/**
 * Loading layout matching the viewer (no layout jump when the data arrives): the view tabs' row first, as
 * tall as the tabs (UI audit round 2: the verdict moved 56 px down when they came in).
 */
export function DocumentSkeleton() {
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.04fr)_minmax(0,1fr)] xl:gap-8" aria-busy="true">
      <div className="min-w-0 space-y-4 xl:col-start-2 xl:row-start-1">
        <div aria-hidden className="flex h-10 items-center gap-2 shadow-[inset_0_-1px_0_var(--color-line)]">
          {/* each tab a half of the row on phones (the tabs fill it there), side by side from sm */}
          {["w-24", "w-32"].map((w) => (
            <span key={w} className="flex h-full items-center px-2 max-sm:flex-auto max-sm:justify-center">
              <Skeleton className={cn("h-3.5", w)} />
            </span>
          ))}
        </div>
        <SkeletonCard lines={4} />
        <SkeletonCard lines={2} />
      </div>
      <div className="card h-[60vh] animate-pulse bg-surface-2 motion-reduce:animate-none xl:col-start-1 xl:row-start-1 xl:h-[calc(100dvh-88px)]" />
    </div>
  );
}
