/**
 * The "get advice" card of a high-stakes letter (a court order, a dismissal, a landlord's notice,
 * a rent increase, an operating-cost statement): what the letter means, the steps in order, the
 * facts Ordnung worked out from the law (time-bar, rent cap, a late statement) and free or
 * low-cost help nearby. The card comes from the backend (`DocumentDetail.advice`); nothing here is
 * computed. Urgent letters (court orders, a dismissal) are styled as a warning. A handled card
 * (`advice.handled`: the person closed the to-dos that carry its deadline) says so and offers no letter
 * to draft; a card no to-do can close (`advice.closable`: a landlord's notice without notice period)
 * lets the person say they have dealt with it — stored as the letter's `dealt-with` tag, and undoable.
 */
import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, CircleCheck, CircleCheckBig, FileSearch, Info, PenLine, Scale, TriangleAlert, type LucideIcon } from "lucide-react";
import type { AdviceFact, Document, DraftKind, LetterAdvice } from "@/api/types";
import { useUpdateDocument } from "@/api/hooks";
import { Link } from "react-router";
import { Button, buttonVariants } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { keepCitations } from "@/lib/glue";
import { cn } from "@/lib/utils";
import { useStartDraft } from "./actions";
import { needsTypedCourt } from "@/features/letters/logic";
import { composerHref } from "@/features/today/selection";

/** The tag a letter carries once the person said they dealt with a card no to-do can close (the server's `DEALT_WITH_TAG`). */
export const DEALT_WITH_TAG = "dealt-with";

const FACT_TONE: Record<AdviceFact["tone"], { box: string; icon: LucideIcon; iconClass: string; title: string }> = {
  info: { box: "border-line bg-surface-2/60", icon: Info, iconClass: "text-muted", title: "text-ink" },
  warn: { box: "border-warn/30 bg-warn-soft", icon: TriangleAlert, iconClass: "text-warn", title: "text-warn-ink" },
  good: { box: "border-ok/25 bg-ok-soft", icon: CircleCheck, iconClass: "text-ok", title: "text-ok-ink" },
};

/** The steps a tenancy card shows before "Show all steps" (a landlord's notice has six, one of them a
 * paragraph of law): its actions and help stay in view on a phone. A court order's and a dismissal's steps
 * are each something to do within days — all shown. */
const FIRST_STEPS = 3;
const ALL_STEPS_SHOWN = new Set<LetterAdvice["kind"]>(["court_payment_order", "enforcement_order", "dismissal"]);

/**
 * How the card's letter reads (`advice.draft`, decided by the backend: none for a notice without
 * notice period, where the hardship objection doesn't apply; court orders get theirs from the verdict).
 */
const CARD_ACTION: Partial<Record<DraftKind, { label: string; icon: LucideIcon }>> = {
  objection: { label: "Draft a hardship objection", icon: PenLine },
  receipts_inspection: { label: "Ask to see the receipts", icon: FileSearch },
};

/** "I've dealt with this" on a card no to-do can close, and its undo once it is handled that way. */
function DealtWith({ advice, doc, onDone }: { advice: LetterAdvice; doc: Pick<Document, "id" | "tags">; onDone: (dealt: boolean) => void }) {
  const update = useUpdateDocument();
  const tags = doc.tags ?? [];
  const mark = (dealt: boolean) =>
    update.mutate(
      { id: doc.id, patch: { tags: dealt ? [...tags.filter((t) => t !== DEALT_WITH_TAG), DEALT_WITH_TAG] : tags.filter((t) => t !== DEALT_WITH_TAG) } },
      {
        onSuccess: () => {
          onDone(dealt);
          return dealt
            ? toast.success("Marked as dealt with", {
                description: "The card stays on the letter for reference. Nothing was sent.",
                undo: () => update.mutate({ id: doc.id, patch: { tags: tags.filter((t) => t !== DEALT_WITH_TAG) } }),
              })
            : toast.success("Back to “get advice now”");
        },
      },
    );
  if (advice.handled) {
    return tags.includes(DEALT_WITH_TAG) ? (
      <Button size="sm" variant="ghost" loading={update.isPending} onClick={() => mark(false)}>
        Not dealt with yet
      </Button>
    ) : null;
  }
  return (
    <div className="space-y-1.5">
      <p className="text-[13px] leading-snug text-ink/80">Had advice, moved out, or settled it? No to-do can close this letter — say so here. Nothing is sent.</p>
      <Button size="sm" variant="secondary" icon={CircleCheckBig} loading={update.isPending} onClick={() => mark(true)}>
        I've dealt with this
      </Button>
    </div>
  );
}

/**
 * A card title whose German term stays whole or breaks where German breaks it: "Operating-cost statement
 * (Betriebskostenabrechnung)" broke as "(Betriebskostenabrechnun" / "g)" at 320 px (review round 3 of phase 2).
 * The term in brackets is marked German (hyphenated as German, read in a German voice), and the soft hyphens
 * after the parts of a long compound let it break there even where no German hyphenation is installed.
 */
function AdviceTitle({ title }: { title: string }) {
  const found = /^(.*?)\s*\(([^()]+)\)(.*)$/.exec(title);
  if (!found) return <>{title}</>;
  const [, head, term, tail] = found;
  return (
    <>
      {head}{" "}
      <span lang="de" className="hyphens-manual">
        ({softHyphens(term!)})
      </span>
      {tail}
    </>
  );
}

/** The heads of German compounds in the card titles' terms, after which a long word may break. */
const COMPOUND_HEADS = /(Betriebskosten|Heizkosten|Nebenkosten|Vollstreckungs|Kündigungs|Kappungs|Miet|Mahn)(?=\p{Ll}{4,})/gu;

function softHyphens(term: string): string {
  return term.length < 16 ? term : term.replace(COMPOUND_HEADS, "$1\u00ad");
}

export function LetterAdviceCard({
  advice,
  doc,
  party,
}: {
  advice: LetterAdvice;
  doc: Pick<Document, "id" | "party_id" | "case_id" | "tags" | "kind" | "remedy">;
  party?: { name: string } | null;
}) {
  const draft = useStartDraft();
  const urgent = advice.urgent;
  // a handled letter has nothing left to object to in time: no letter to draft
  const draftKind = advice.handled ? null : (advice.draft ?? null);
  const action = draftKind ? CARD_ACTION[draftKind] : undefined;
  const titleId = `advice-${doc.id}`;
  const [allSteps, setAllSteps] = useState(false);
  const foldable = !ALL_STEPS_SHOWN.has(advice.kind);
  // the button the person pressed goes away once the card settles: focus follows to what replaced it
  const focusAfter = useRef<"status" | "title" | null>(null);
  const statusRef = useRef<HTMLParagraphElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const target = focusAfter.current === "status" && advice.handled ? statusRef.current : focusAfter.current === "title" && !advice.handled ? headingRef.current : null;
    if (!target) return;
    focusAfter.current = null;
    target.focus();
  }, [advice.handled]);
  return (
    <section
      id={`advice-card-${doc.id}`}
      aria-labelledby={titleId}
      className={cn("@container scroll-mt-24 overflow-hidden rounded-2xl border", urgent ? "border-warn/35 bg-warn-soft" : "border-line bg-surface shadow-[var(--shadow-card)]")}
    >
      <div className="flex gap-3 px-4 pb-1 pt-4 sm:px-5">
        <span
          className={cn(
            "grid size-9 shrink-0 place-items-center rounded-xl",
            urgent ? "bg-warn text-white dark:text-canvas" : "bg-accent-soft text-accent",
          )}
        >
          <Scale className="size-5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className={cn("text-[12px] font-semibold uppercase tracking-[0.07em]", urgent ? "text-warn-ink" : "text-muted")}>
            {urgent ? "Act now — and get advice" : "Know your rights"}
          </p>
          <h2 id={titleId} ref={headingRef} tabIndex={-1} className="mt-0.5 scroll-mt-24 text-[15.5px] font-semibold leading-snug text-ink outline-none [overflow-wrap:anywhere]">
            <AdviceTitle title={advice.title} />
          </h2>
        </div>
      </div>

      {/* the summary lines up with the steps below it: under the title on a wide card, full width on a narrow one */}
      <div className="space-y-4 px-4 pb-4 pt-2 sm:px-5 @[34rem]:pl-[68px]">
        {advice.handled ? (
          <p
            role="status"
            ref={statusRef}
            tabIndex={-1}
            className="flex scroll-mt-24 items-start gap-2 rounded-xl border border-ok/25 bg-ok-soft px-3 py-2 text-[13.5px] font-medium leading-snug text-ok-ink outline-none"
          >
            <CircleCheck className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden />
            <span>
              {doc.tags?.includes(DEALT_WITH_TAG) && advice.closable
                ? "You marked this letter as dealt with. The card stays here for reference."
                : "You've closed the to-dos that carry this letter's deadline. The card stays here for reference."}
            </span>
          </p>
        ) : null}
        <p className="text-[14px] leading-relaxed text-ink/85">{keepCitations(advice.summary)}</p>
        {advice.steps.length ? (
          <div>
            <h3 className={cn("text-[12px] font-semibold uppercase tracking-[0.07em]", urgent ? "text-warn-ink/85" : "text-muted")}>What to do</h3>
            <ol id={`advice-steps-${doc.id}`} className="mt-2 space-y-2">
              {(allSteps || !foldable ? advice.steps : advice.steps.slice(0, FIRST_STEPS)).map((s, i) => (
                <li key={s} className="flex gap-2.5 text-[13.5px] leading-snug text-ink/90">
                  <span
                    className={cn(
                      "grid size-5 shrink-0 place-items-center rounded-full text-[11px] font-bold tabular-nums",
                      urgent ? "bg-surface/80 text-warn-ink ring-1 ring-warn/30" : "bg-surface-3 text-muted",
                    )}
                    aria-hidden
                  >
                    {i + 1}
                  </span>
                  <span className="min-w-0 pt-px">{keepCitations(s)}</span>
                </li>
              ))}
            </ol>
            {foldable && advice.steps.length > FIRST_STEPS ? (
              // a long card (a landlord's notice: six steps of law) keeps its first steps and its actions in view
              <Button
                variant="link"
                size="sm"
                className="mt-1.5"
                aria-expanded={allSteps}
                aria-controls={`advice-steps-${doc.id}`}
                onClick={() => setAllSteps((v) => !v)}
              >
                {allSteps ? "Show fewer steps" : `Show all ${advice.steps.length} steps`}
              </Button>
            ) : null}
          </div>
        ) : null}

        {advice.facts.length ? (
          <ul className="space-y-2" aria-label="What Ordnung worked out">
            {advice.facts.map((f) => {
              const t = FACT_TONE[f.tone] ?? FACT_TONE.info;
              return (
                <li key={f.title} className={cn("flex gap-2.5 rounded-xl border px-3 py-2.5", t.box, urgent && f.tone === "info" && "bg-surface/70")}>
                  <t.icon className={cn("mt-0.5 size-4 shrink-0", t.iconClass)} aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className={cn("text-[13.5px] font-semibold leading-5", t.title)}>{f.title}</p>
                    <p className="mt-0.5 text-[13px] leading-relaxed text-ink/85">{keepCitations(f.text)}</p>
                    {f.citation ? <p className="mt-1 text-[12px] leading-4 text-muted">{keepCitations(f.citation)}</p> : null}
                  </div>
                </li>
              );
            })}
          </ul>
        ) : null}

        {advice.help.length ? (
          <div>
            <h3 className={cn("text-[12px] font-semibold uppercase tracking-[0.07em]", urgent ? "text-warn-ink/85" : "text-muted")}>Free or low-cost help</h3>
            <ul className="mt-2 grid gap-2 @[34rem]:grid-cols-2">
              {advice.help.map((h) => {
                const box = cn(
                  "flex h-full flex-col rounded-xl border px-3 py-2.5",
                  urgent ? "border-warn/25 bg-surface/70" : "border-line bg-surface-2/40",
                );
                return (
                  <li key={h.name} className="min-w-0">
                    {h.url ? (
                      <a
                        href={h.url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className={cn(box, "group transition-colors", urgent ? "hover:bg-surface" : "hover:border-line-strong hover:bg-surface-2/70")}
                      >
                        <span className="flex items-start gap-1 text-[13.5px] font-semibold leading-5 text-accent">
                          <span className="min-w-0 [overflow-wrap:anywhere] group-hover:underline group-hover:underline-offset-2">{h.name}</span>
                          <ArrowUpRight className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                          <span className="sr-only"> (opens in a new tab)</span>
                        </span>
                        <span className="mt-0.5 text-[12.5px] leading-snug text-muted">{keepCitations(h.what)}</span>
                      </a>
                    ) : (
                      <div className={box}>
                        <span className="text-[13.5px] font-semibold leading-5 text-ink [overflow-wrap:anywhere]">{h.name}</span>
                        <span className="mt-0.5 text-[12.5px] leading-snug text-muted">{h.what}</span>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}

        {action && draftKind ? (
          <div className="flex flex-wrap gap-2">
            {draftKind === "objection" && needsTypedCourt(doc, party) ? (
              // the letter's sender (as filed) is no court: the composer asks for the court it goes to
              <Link to={composerHref("objection", { docId: doc.id })} className={buttonVariants({ size: "sm", variant: "secondary" })}>
                <action.icon aria-hidden />
                {action.label}
              </Link>
            ) : (
              <Button
                size="sm"
                variant="secondary"
                icon={action.icon}
                loading={draft.pending}
                onClick={() => draft.start(draftKind, { doc_id: doc.id, party_id: doc.party_id, case_id: doc.case_id })}
              >
                {action.label}
              </Button>
            )}
          </div>
        ) : null}
        {advice.closable ? <DealtWith advice={advice} doc={doc} onDone={(dealt) => (focusAfter.current = dealt ? "status" : "title")} /> : null}
      </div>

      <p className={cn("border-t px-4 py-2 text-[12px] leading-5 text-muted sm:px-5", urgent ? "border-warn/20 bg-surface/40" : "border-line bg-surface-2/40")}>
        Not legal advice. Ordnung reads the letter and applies the law as written; only an advice service or a lawyer can check your case.
      </p>
    </section>
  );
}
