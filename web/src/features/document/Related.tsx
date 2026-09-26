/**
 * Context around the letter: the thread it belongs to (other letters of the same case, as a small
 * timeline), the contract it is about, letters you drafted about it, and related Ideas.
 */
import { Link } from "react-router";
import { ArrowRight, FilePen, Layers, Lightbulb, Signature } from "lucide-react";
import type { Contract, Document, DocumentDetail, Draft, Suggestion } from "@/api/types";
import { cn } from "@/lib/utils";
import { CONTRACT_CATEGORY_COPY, DRAFT_KIND_COPY, SUGGESTION_KIND_COPY, TONES, copyFor, documentKindLabel } from "@/lib/copy";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { KindBadge, KindIcon } from "@/components/ui/KindBadge";
import { Money } from "@/components/ui/Money";
import { StatusPill } from "@/components/ui/StatusPill";
import { PanelSection } from "./PanelSection";
import { RefText } from "@/features/ask/RefText";

const docDate = (d: Document) => d.doc_date ?? d.received_date ?? d.created_at.slice(0, 10);

export function ThreadSection({ detail }: { detail: DocumentDetail }) {
  const { document: doc, case: thread, related } = detail;
  if (!related.length) return null;
  const all = [...related, doc].sort((a, b) => (docDate(a) < docDate(b) ? 1 : -1));
  return (
    <PanelSection id="thread" title="Thread" icon={Layers} count={all.length}>
      <div className="card overflow-hidden">
        {thread ? (
          <div className="border-b border-line px-4 py-3 sm:px-5">
            <p className="text-[14.5px] font-semibold text-ink">{thread.title}</p>
            {thread.summary ? <p className="mt-0.5 text-[13px] leading-5 text-muted">{thread.summary}</p> : null}
          </div>
        ) : null}
        <ol className="relative px-4 py-2 sm:px-5">
          {all.map((d, i) => {
            const current = d.id === doc.id;
            return (
              <li key={d.id} className="relative flex gap-3 py-2">
                {/* rail */}
                <span aria-hidden className="relative flex w-3 shrink-0 justify-center">
                  {i < all.length - 1 ? <span className="absolute left-1/2 top-5 -bottom-3 w-px -translate-x-1/2 bg-line-strong" /> : null}
                  <span className={cn("relative mt-2.5 size-2.5 rounded-full ring-2 ring-surface", current ? "bg-accent" : "bg-faint")} />
                </span>
                <div className="flex min-w-0 flex-1 items-start gap-3">
                  <KindIcon docKind={d.kind} size="sm" className="mt-0.5" />
                  <div className="min-w-0 flex-1">
                    {current ? (
                      <p className="truncate text-[13.5px] font-semibold text-ink">
                        {d.title ?? d.filename} <span className="ml-1 rounded bg-accent-soft px-1.5 py-0.5 text-[11px] font-semibold text-accent">This letter</span>
                      </p>
                    ) : (
                      <Link to={`/documents/${d.id}`} className="block truncate text-[13.5px] font-medium text-ink hover:text-accent hover:underline">
                        {d.title ?? d.filename}
                      </Link>
                    )}
                    <p className="mt-0.5 text-[12px] text-muted">
                      {documentKindLabel(d.kind)} · <DateText date={docDate(d)} style="medium" />
                    </p>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </PanelSection>
  );
}

export function ContractsSection({ contracts }: { contracts: Contract[] }) {
  if (!contracts.length) return null;
  return (
    <PanelSection id="contract" title={contracts.length === 1 ? "Contract" : "Contracts"} icon={Signature}>
      <div className="space-y-2.5">
        {contracts.map((c) => {
          const cat = copyFor(CONTRACT_CATEGORY_COPY, c.category);
          const comp = c.computed;
          return (
            <div key={c.id} className="card flex items-start gap-3 px-4 py-3.5 sm:px-5">
              <span className={cn("grid size-9 shrink-0 place-items-center rounded-lg", TONES[cat.tone].soft, TONES[cat.tone].icon)}>
                <cat.icon className="size-[18px]" aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-3">
                  <p className="text-[14.5px] font-semibold leading-snug text-ink">{c.name}</p>
                  {c.cost_amount != null ? <Money amount={c.cost_amount} currency={c.cost_currency} interval={c.cost_interval} className="text-[13.5px]" /> : null}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[12.5px] text-muted">
                  <KindBadge category={c.category} />
                  {comp?.send_by ? <Countdown date={comp.send_by} prefix="decide by" className="text-[12.5px]" /> : comp?.current_term_end ? <span>runs until <DateText date={comp.current_term_end} style="medium" /></span> : null}
                </div>
                {comp?.summary ? <p className="mt-1.5 text-[13px] leading-5 text-muted">{comp.summary}</p> : null}
                <Link to="/contracts" className="mt-2 inline-flex items-center gap-1 text-[13px] font-semibold text-accent hover:underline">
                  Open in Contracts <ArrowRight className="size-3.5" aria-hidden />
                </Link>
              </div>
            </div>
          );
        })}
      </div>
    </PanelSection>
  );
}

export function DraftsSection({ drafts }: { drafts: Draft[] }) {
  if (!drafts.length) return null;
  return (
    <PanelSection id="drafts" title="Your letters about this" icon={FilePen}>
      <ul className="card divide-y divide-line overflow-hidden">
        {drafts.map((d) => {
          const k = copyFor(DRAFT_KIND_COPY, d.kind);
          return (
            <li key={d.id}>
              <Link to={`/letters/${d.id}`} className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-2/50 sm:px-5">
                <span className={cn("grid size-8 shrink-0 place-items-center rounded-lg", TONES[k.tone].soft, TONES[k.tone].icon)}>
                  <k.icon className="size-4" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13.5px] font-medium text-ink" lang={d.language}>
                    {d.subject || k.label}
                  </span>
                  <span className="text-[12px] text-muted">
                    {k.label} · <DateText date={d.updated_at.slice(0, 10)} style="day" />
                  </span>
                </span>
                <StatusPill of="draft" status={d.status} />
              </Link>
            </li>
          );
        })}
      </ul>
    </PanelSection>
  );
}

export function IdeasSection({ suggestions }: { suggestions: Suggestion[] }) {
  const list = suggestions.filter((s) => s.kind !== "scam" && (s.status === "new" || s.status === "accepted" || s.status === "snoozed"));
  if (!list.length) return null;
  return (
    <PanelSection id="ideas" title="Ideas" icon={Lightbulb}>
      <ul className="space-y-2.5">
        {list.map((s) => {
          const k = copyFor(SUGGESTION_KIND_COPY, s.kind);
          return (
            <li key={s.id} className="card flex gap-3 px-4 py-3.5 sm:px-5">
              <span className={cn("grid size-8 shrink-0 place-items-center rounded-lg", TONES[k.tone].soft, TONES[k.tone].icon)}>
                <k.icon className="size-4" aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-[14px] font-semibold leading-snug text-ink">
                  <RefText text={s.title} />
                </p>
                <p className="mt-1 text-[13px] leading-5 text-muted">
                  <RefText text={s.body} />
                </p>
                {s.rationale ? (
                  <p className="mt-1.5 text-[12px] text-muted">
                    Why: <RefText text={s.rationale} />
                  </p>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </PanelSection>
  );
}
