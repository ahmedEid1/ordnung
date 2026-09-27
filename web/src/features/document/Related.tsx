/**
 * Context around the letter: the thread it belongs to (other letters of the same case, as a small
 * timeline), the contract it is about, letters you drafted about it, and related Ideas.
 */
import { useRef, useState } from "react";
import { Link } from "react-router";
import { AlarmClock, ArrowRight, FilePen, Layers, Lightbulb, Signature, X } from "lucide-react";
import type { Contract, Document, DocumentDetail, Draft, Item, Suggestion } from "@/api/types";
import { useUpdateSuggestion } from "@/api/hooks";
import { cn } from "@/lib/utils";
import { CONTRACT_CATEGORY_COPY, DRAFT_KIND_COPY, SUGGESTION_KIND_COPY, TONES, copyFor, documentKindLabel } from "@/lib/copy";
import { addDays } from "date-fns";
import { formatDate, toISODate } from "@/lib/format";
import { useToday } from "@/lib/today";
import { buttonVariants } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { KindBadge, KindIcon } from "@/components/ui/KindBadge";
import { Money } from "@/components/ui/Money";
import { StatusPill } from "@/components/ui/StatusPill";
import { toast } from "@/components/ui/Toast";
import { PanelSection } from "./PanelSection";
import { RefText } from "@/features/ask/RefText";
import { contractHref } from "@/features/contracts/links";
import { focusAfterLeaving, focusWhenReady } from "@/features/today/focus";
import { ideaActionLabel, ideaHref } from "@/features/today/helpers";
import { ideasForLetter, onThisLetter } from "./letter-ideas";

const docDate = (d: Document) => d.doc_date ?? d.received_date ?? d.created_at.slice(0, 10);

/** Titles and subjects wrap to two lines, the whole of it in the tooltip (UI audit round 1: cut to one line). */
const TWO_LINES = "line-clamp-2 [overflow-wrap:anywhere]";

export function ThreadSection({ detail }: { detail: DocumentDetail }) {
  const { document: doc, case: thread, related } = detail;
  if (!related.length) return null;
  const all = [...related, doc].sort((a, b) => (docDate(a) < docDate(b) ? 1 : -1));
  return (
    <PanelSection id="thread" title="Thread" icon={Layers} count={all.length} countLabel={`${all.length} letters`}>
      <div className="card overflow-hidden">
        {thread ? (
          <div className="border-b border-line px-4 py-3 sm:px-5">
            <p className="text-[14.5px] font-semibold text-ink [overflow-wrap:anywhere]">{thread.title}</p>
            {thread.summary ? <p className="mt-0.5 text-[13px] leading-5 text-muted">{thread.summary}</p> : null}
          </div>
        ) : null}
        <ol className="relative px-4 py-2 sm:px-5">
          {all.map((d, i) => {
            const current = d.id === doc.id;
            const title = d.title ?? d.filename;
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
                      // the badge sits beside the title, never inside its clamp, so a long title never hides it
                      <p className="flex min-w-0 items-start gap-2 text-[13.5px] font-semibold leading-5 text-ink">
                        <span className={cn("min-w-0", TWO_LINES)} title={title}>
                          {title}
                        </span>
                        <span className="shrink-0 rounded bg-accent-soft px-1.5 py-0.5 text-[11.5px] font-semibold leading-4 text-accent">This letter</span>
                      </p>
                    ) : (
                      <Link to={`/documents/${d.id}`} title={title} className={cn("text-[13.5px] font-medium leading-5 text-ink hover:text-accent hover:underline", TWO_LINES)}>
                        {title}
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
                {/* the name takes the room it needs; the amount goes below it when both don't fit
                    (UI audit round 1: "€156.55/month" pushed the page wider at 320 px, the name squeezed to 4 lines) */}
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                  <p lang="de" className="min-w-0 flex-[1_1_12rem] text-[14.5px] font-semibold leading-snug text-ink [overflow-wrap:anywhere] hyphens-auto">
                    {c.name}
                  </p>
                  {c.cost_amount != null ? <Money amount={c.cost_amount} currency={c.cost_currency} interval={c.cost_interval} className="shrink-0 text-[13.5px]" /> : null}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[12.5px] text-muted">
                  <KindBadge category={c.category} />
                  {comp?.send_by ? <Countdown date={comp.send_by} prefix="decide by" className="text-[12.5px]" /> : comp?.current_term_end ? <span>runs until <DateText date={comp.current_term_end} style="medium" /></span> : null}
                </div>
                {comp?.summary ? <p className="mt-1.5 text-[13px] leading-5 text-muted">{comp.summary}</p> : null}
                <Link to={contractHref(c.id)} className="mt-2 inline-flex min-h-6 items-center gap-1 text-[13px] font-semibold text-accent hover:underline">
                  Open in Contracts <ArrowRight className="size-3.5" aria-hidden />
                  <span className="sr-only"> — {c.name}</span>
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
          const subject = d.subject || k.label;
          return (
            <li key={d.id}>
              <Link to={`/letters/${d.id}`} title={subject} className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-2/50 sm:px-5">
                <span className={cn("grid size-8 shrink-0 place-items-center rounded-lg", TONES[k.tone].soft, TONES[k.tone].icon)}>
                  <k.icon className="size-4" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className={cn("block text-[13.5px] font-medium leading-5 text-ink", TWO_LINES)} lang={d.language}>
                    {subject}
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

const quiet =
  "inline-flex min-h-8 items-center gap-1.5 rounded-md px-1.5 text-[12.5px] font-medium text-muted transition-colors hover:bg-surface-2 hover:text-ink disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent";

const ideaHeadingId = (id: string) => `letter-idea-${id}`;

/** One Idea about this letter, with its action and "Remind me in a week" / "Not relevant" (both with Undo), as on Today. */
function LetterIdea({ idea, docId, items, onLeave }: { idea: Suggestion; docId: string; items: Item[]; onLeave: (id: string) => void }) {
  const update = useUpdateSuggestion();
  const today = useToday();
  const k = copyFor(SUGGESTION_KIND_COPY, idea.kind);
  const titleId = ideaHeadingId(idea.id);
  const href = ideaHref(idea);
  // an action that opens the page you are on is no action
  const action = href && href !== `/documents/${docId}` && !href.startsWith(`/documents/${docId}?`) ? ideaActionLabel(idea) : null;
  const text = (s: string) => onThisLetter(s, docId, items);

  const answer = (patch: { status: "snoozed"; snoozed_until: string } | { status: "dismissed" }, title: string) => {
    onLeave(idea.id);
    update.mutateAsync({ id: idea.id, patch }).then(
      () =>
        toast({
          title,
          description: idea.title,
          undo: async () => {
            await update.mutateAsync({ id: idea.id, patch: { status: "new", snoozed_until: null } });
            focusWhenReady(() => document.getElementById(titleId));
          },
        }),
      () => undefined, // the error toast comes from the mutation's meta
    );
  };
  const snooze = () => {
    const until = toISODate(addDays(today, 7));
    answer({ status: "snoozed", snoozed_until: until }, `I'll bring this back on ${formatDate(until, { style: "short", today })}`);
  };

  return (
    <li className="card flex gap-3 px-4 pt-3.5 pb-2 sm:px-5">
      <span className={cn("grid size-8 shrink-0 place-items-center rounded-lg", TONES[k.tone].soft, TONES[k.tone].icon)}>
        <k.icon className="size-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <h3 id={titleId} tabIndex={-1} data-letter-idea="" className="text-[14px] font-semibold leading-snug text-ink [overflow-wrap:anywhere]">
          <RefText text={text(idea.title)} />
        </h3>
        <p className="mt-1 text-[13px] leading-5 text-muted [overflow-wrap:anywhere]">
          <RefText text={text(idea.body)} />
        </p>
        {idea.rationale ? (
          <p className="mt-1.5 text-[12px] leading-5 text-muted [overflow-wrap:anywhere]">
            Why: <RefText text={text(idea.rationale)} />
          </p>
        ) : null}
        {action && href ? (
          <Link
            to={href}
            onClick={() => {
              if (idea.action?.type === "draft") update.mutate({ id: idea.id, patch: { status: "accepted" } }, { onError: () => undefined });
            }}
            aria-describedby={titleId}
            // a long action ("Send enrolment certificate to FitWell") wraps inside the card instead of widening the page
            className={buttonVariants({ variant: "soft", size: "sm", className: "mt-3 h-auto min-h-8 max-w-full whitespace-normal py-1.5 text-left" })}
          >
            {action}
          </Link>
        ) : null}
        <div className="-mx-1.5 mt-2.5 flex flex-wrap items-center gap-x-2 border-t border-line pt-1.5">
          <button type="button" onClick={snooze} disabled={update.isPending} aria-describedby={titleId} className={quiet}>
            <AlarmClock className="size-3.5" aria-hidden />
            Remind me in a week
          </button>
          <button type="button" onClick={() => answer({ status: "dismissed" }, "Idea hidden")} disabled={update.isPending} aria-describedby={titleId} className={quiet}>
            <X className="size-3.5" aria-hidden />
            Not relevant
          </button>
        </div>
      </div>
    </li>
  );
}

/**
 * Ideas about this letter (`ideasForLetter`: not the verdict again, not the calendar sweep, not
 * "Please check" for this page), each with its action, "Remind me in a week" and "Not relevant".
 * When the last one is answered the section stays, says so and takes focus.
 */
export function IdeasSection({
  suggestions,
  docId,
  items = [],
  primaryId,
}: {
  suggestions: Suggestion[];
  docId: string;
  items?: Item[];
  /** The to-do the verdict card leads with: an Idea about it alone isn't repeated here. */
  primaryId?: string | null;
}) {
  const [answered, setAnswered] = useState(false);
  const listRef = useRef<HTMLUListElement>(null);
  const list = ideasForLetter(suggestions, { docId, items, primaryId });
  if (!list.length && !answered) return null;
  const headings = () => Array.from(listRef.current?.querySelectorAll<HTMLElement>("[data-letter-idea]") ?? []);
  const onLeave = (id: string) => {
    setAnswered(true);
    focusAfterLeaving(headings, ideaHeadingId(id), "ideas-title");
  };
  return (
    <PanelSection id="ideas" title="Ideas" icon={Lightbulb}>
      {list.length ? (
        <ul ref={listRef} className="space-y-2.5">
          {list.map((s) => (
            <LetterIdea key={s.id} idea={s} docId={docId} items={items} onLeave={onLeave} />
          ))}
        </ul>
      ) : (
        <p className="card px-4 py-3.5 text-[13px] text-muted sm:px-5">Nothing else to suggest about this letter.</p>
      )}
    </PanelSection>
  );
}
