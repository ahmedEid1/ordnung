import { useId, useState } from "react";
import { ChevronDown, Landmark, Quote } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ConfidenceNote } from "@/components/ui/ConfidenceNote";
import { DateText } from "@/components/ui/DateText";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { GroundingBadge } from "@/components/ui/GroundingBadge";
import { Popover } from "@/components/ui/Popover";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/format";
import { useToday } from "@/lib/today";
import type { ReceiptModel } from "./receipt";

/** The popover body: plain sentence first, rules on request, disclaimer always. */
export function ReceiptView({ receipt, title }: { receipt: ReceiptModel; title?: string }) {
  const [open, setOpen] = useState(false);
  const today = useToday();
  const stepsId = useId();
  const hasRules = receipt.steps.length > 0 || Boolean(receipt.holidayCalendar);
  return (
    <div className="space-y-3.5">
      <div>
        <p className="text-[12px] font-semibold uppercase tracking-[0.07em] text-muted">Why this date?</p>
        {title ? <p className="mt-0.5 text-[13px] text-muted">{title}</p> : null}
      </div>

      {receipt.sendBy || receipt.dueDate ? (
        <dl className="grid grid-cols-2 gap-2">
          {receipt.sendBy ? (
            <div className="rounded-lg bg-surface-2 px-3 py-2">
              <dt className="text-[11.5px] font-medium text-muted">Send by</dt>
              <dd className="display text-[17px] font-semibold text-ink">{formatDate(receipt.sendBy, { style: "short", today })}</dd>
            </div>
          ) : null}
          {receipt.dueDate ? (
            <div className={cn("rounded-lg bg-surface-2 px-3 py-2", !receipt.sendBy && "col-span-2")}>
              <dt className="text-[11.5px] font-medium text-muted">{receipt.sendBy ? "Must arrive by" : receipt.dueLabel}</dt>
              <dd className="display text-[17px] font-semibold text-ink">{formatDate(receipt.dueDate, { style: "short", today })}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}

      <p className="text-[14px] leading-relaxed text-ink">{receipt.summary}</p>

      {!receipt.computed && receipt.evidence ? (
        <figure className="rounded-lg border border-line bg-surface-2/60 px-3 py-2.5">
          <blockquote lang="de" className="flex gap-2 text-[13px] leading-relaxed text-ink">
            <Quote className="mt-0.5 size-3.5 shrink-0 text-muted" aria-hidden />
            <span>
              <span className="marker px-0.5">{receipt.evidence.quote}</span>
            </span>
          </blockquote>
          <figcaption className="mt-2">
            <GroundingBadge grounding={receipt.evidence.grounding} page={receipt.evidence.page} />
          </figcaption>
        </figure>
      ) : null}

      <ConfidenceNote confidence={receipt.confidence} warnings={receipt.warnings} />

      {hasRules ? (
        <div>
          <Button
            variant="link"
            size="sm"
            iconRight={ChevronDown}
            aria-expanded={open}
            aria-controls={stepsId}
            onClick={() => setOpen((v) => !v)}
            className={cn("[&_svg]:transition-transform", open && "[&_svg]:rotate-180")}
          >
            {open ? "Hide the rules" : "Show the rules"}
          </Button>
          <div id={stepsId} hidden={!open}>
            <ol className="relative mt-3 space-y-3 pl-5 before:absolute before:bottom-1.5 before:left-[5px] before:top-1.5 before:w-px before:bg-line-strong">
              {receipt.steps.map((s, i) => (
                <li key={`${s.label}-${i}`} className="relative text-[13px]">
                  <span
                    aria-hidden
                    className={cn(
                      "absolute -left-5 top-[5px] size-[11px] rounded-full border-2 border-surface",
                      i === receipt.steps.length - 1 ? "bg-accent" : "bg-line-strong",
                    )}
                  />
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-ink">{s.label}</span>
                    {s.date ? <DateText date={s.date} className="shrink-0 text-[12.5px] font-medium text-ink" /> : null}
                  </div>
                  {s.citation ? <div className="mt-0.5 text-[12px] font-medium text-accent">{s.citation}</div> : null}
                </li>
              ))}
            </ol>
            {receipt.holidayCalendar ? (
              <p className="mt-3 flex items-start gap-1.5 text-[12px] leading-5 text-muted">
                <Landmark className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                <span>
                  Public holidays counted: <span className="text-ink">{receipt.holidayCalendar}</span>
                </span>
              </p>
            ) : null}
          </div>
        </div>
      ) : null}

      <Disclaimer variant="block" />
    </div>
  );
}

/**
 * "Why this date?" link that opens the receipt popover.
 *
 * @example <WhyThisDate receipt={receiptForItem(item)} context={item.title} />
 */
export function WhyThisDate({ receipt, context, className }: { receipt: ReceiptModel | null; context: string; className?: string }) {
  if (!receipt) return null;
  return (
    <Popover content={<ReceiptView receipt={receipt} title={context} />} className="w-[23rem]" label={`Why this date? ${context}`} placement="bottom-end">
      <Button variant="link" size="sm" className={cn("text-[13px]", className)}>
        Why this date?<span className="sr-only"> ({context})</span>
      </Button>
    </Popover>
  );
}
