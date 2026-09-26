/**
 * The "get advice" card of a high-stakes letter (a court order, a dismissal, a landlord's notice,
 * a rent increase, an operating-cost statement): what the letter means, the steps in order, the
 * facts Ordnung worked out from the law (time-bar, rent cap, a late statement) and free or
 * low-cost help nearby. The card comes from the backend (`DocumentDetail.advice`); nothing here is
 * computed. Urgent letters (court orders, a dismissal) are styled as a warning.
 */
import { ArrowUpRight, CircleCheck, FileSearch, Info, PenLine, Scale, TriangleAlert, type LucideIcon } from "lucide-react";
import type { AdviceFact, Document, DraftKind, LetterAdvice } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { useStartDraft } from "./actions";

const FACT_TONE: Record<AdviceFact["tone"], { box: string; icon: LucideIcon; iconClass: string; title: string }> = {
  info: { box: "border-line bg-surface-2/60", icon: Info, iconClass: "text-muted", title: "text-ink" },
  warn: { box: "border-warn/30 bg-warn-soft", icon: TriangleAlert, iconClass: "text-warn", title: "text-warn-ink" },
  good: { box: "border-ok/25 bg-ok-soft", icon: CircleCheck, iconClass: "text-ok", title: "text-ok-ink" },
};

/** The letter the card offers to draft (court orders get theirs from the verdict's main button). */
const CARD_ACTION: Partial<Record<LetterAdvice["kind"], { kind: DraftKind; label: string; icon: LucideIcon }>> = {
  landlord_notice: { kind: "objection", label: "Draft a hardship objection", icon: PenLine },
  operating_costs: { kind: "receipts_inspection", label: "Ask to see the receipts", icon: FileSearch },
};

export function LetterAdviceCard({ advice, doc }: { advice: LetterAdvice; doc: Pick<Document, "id" | "party_id" | "case_id"> }) {
  const draft = useStartDraft();
  const urgent = advice.urgent;
  const action = CARD_ACTION[advice.kind];
  const titleId = `advice-${doc.id}`;
  return (
    <section
      aria-labelledby={titleId}
      className={cn("@container overflow-hidden rounded-2xl border", urgent ? "border-warn/35 bg-warn-soft" : "border-line bg-surface shadow-[var(--shadow-card)]")}
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
          <h2 id={titleId} className="mt-0.5 text-[15.5px] font-semibold leading-snug text-ink [overflow-wrap:anywhere]">
            {advice.title}
          </h2>
          <p className="mt-1.5 text-[14px] leading-relaxed text-ink/85">{advice.summary}</p>
        </div>
      </div>

      <div className="space-y-4 px-4 pb-4 pt-3 sm:px-5 @[34rem]:pl-[68px]">
        {advice.steps.length ? (
          <div>
            <h3 className={cn("text-[12px] font-semibold uppercase tracking-[0.07em]", urgent ? "text-warn-ink/85" : "text-muted")}>What to do</h3>
            <ol className="mt-2 space-y-2">
              {advice.steps.map((s, i) => (
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
                  <span className="min-w-0 pt-px">{s}</span>
                </li>
              ))}
            </ol>
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
                    <p className="mt-0.5 text-[13px] leading-relaxed text-ink/85">{f.text}</p>
                    {f.citation ? <p className="mt-1 text-[12px] leading-4 text-muted [overflow-wrap:anywhere]">{f.citation}</p> : null}
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
                        <span className="mt-0.5 text-[12.5px] leading-snug text-muted">{h.what}</span>
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

        {action ? (
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="secondary"
              icon={action.icon}
              loading={draft.pending}
              onClick={() => draft.start(action.kind, { doc_id: doc.id, party_id: doc.party_id, case_id: doc.case_id })}
            >
              {action.label}
            </Button>
          </div>
        ) : null}
      </div>

      <p className={cn("border-t px-4 py-2 text-[12px] leading-5 text-muted sm:px-5", urgent ? "border-warn/20 bg-surface/40" : "border-line bg-surface-2/40")}>
        Not legal advice. Ordnung reads the letter and applies the law as written; only an advice service or a lawyer can check your case.
      </p>
    </section>
  );
}
