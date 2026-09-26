/**
 * "Why this date?" — the rules engine's receipt: a plain sentence first, the key dates, how sure
 * we are (and why), then "Show the rules" with every step, its citation and the holiday calendar.
 * Always ends with the point-of-use disclaimer (SPEC §21).
 */
import { useState, type ReactNode } from "react";
import { CalendarDays, ChevronDown, ExternalLink, HelpCircle, Mail, Quote, ShieldCheck } from "lucide-react";
import type { Area, ComputationReceipt, DateSpec } from "@/api/types";
import { useRules } from "@/api/hooks";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { ConfidenceNote } from "@/components/ui/ConfidenceNote";
import { DateText } from "@/components/ui/DateText";
import { Disclaimer, ADVICE_LINKS, type AdviceLink } from "@/components/ui/Disclaimer";
import { Popover } from "@/components/ui/Popover";
import { looksGerman } from "@/lib/format";

/** Independent advice links for high-stakes areas (tax, residence, rent, fines). */
export function adviceFor(area: Area | null | undefined): AdviceLink[] | undefined {
  switch (area) {
    case "tax":
      return ADVICE_LINKS.tax;
    case "residence":
      return ADVICE_LINKS.residence;
    case "home":
      return ADVICE_LINKS.rent;
    case "mobility":
      return ADVICE_LINKS.fines;
    default:
      return undefined;
  }
}

export interface ReceiptViewProps {
  receipt: ComputationReceipt;
  /** What the letter says (shown as the quote the date came from). */
  spec?: DateSpec | null;
  area?: Area | null;
  /** Start with the rule steps open. */
  defaultShowRules?: boolean;
}

function KeyDate({ icon: Icon, label, date, strong }: { icon: typeof Mail; label: string; date: string; strong?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <span className="flex items-center gap-2 text-[13px] text-muted">
        <Icon className="size-3.5" aria-hidden />
        {label}
      </span>
      <DateText date={date} className={cn("text-[13px]", strong ? "font-semibold text-ink" : "font-medium text-ink/85")} />
    </div>
  );
}

export function ReceiptView({ receipt, spec, area, defaultShowRules = false }: ReceiptViewProps) {
  const [showRules, setShowRules] = useState(defaultShowRules);
  const rules = useRules();
  const byId = new Map((rules.data ?? []).map((r) => [r.id, r]));
  const stepsId = "receipt-steps";

  return (
    <div className="space-y-3.5">
      <p className="text-[12px] font-semibold uppercase tracking-[0.07em] text-muted in-sheet:hidden">Why this date?</p>
      <p className="text-[14px] leading-relaxed text-ink">{receipt.summary}</p>

      {receipt.due_date || receipt.send_by || receipt.safe_date ? (
        <div className="divide-y divide-line rounded-lg border border-line bg-surface-2/50 px-3">
          {receipt.due_date ? <KeyDate icon={CalendarDays} label="Must arrive by" date={receipt.due_date} strong /> : null}
          {receipt.safe_date && receipt.safe_date !== receipt.due_date ? <KeyDate icon={ShieldCheck} label="Safe date (a working day)" date={receipt.safe_date} /> : null}
          {receipt.send_by ? <KeyDate icon={Mail} label="Post it by" date={receipt.send_by} /> : null}
        </div>
      ) : null}

      <ConfidenceNote confidence={receipt.confidence} warnings={receipt.warnings} hideWhenHigh={false} />

      {spec?.text ? (
        <figure className="rounded-lg border border-line px-3 py-2.5">
          <figcaption className="mb-1 flex items-center gap-1.5 text-[12px] font-medium text-muted">
            <Quote className="size-3.5" aria-hidden /> What the letter says{looksGerman(spec.text) ? " (in German — the sentence above says it in English)" : ""}
          </figcaption>
          <blockquote lang={looksGerman(spec.text) ? "de" : undefined} className="text-[13px] leading-relaxed text-ink">
            <span className="marker box-decoration-clone px-0.5">{spec.text}</span>
          </blockquote>
        </figure>
      ) : null}

      {receipt.steps.length ? (
        <div>
          <Button
            variant="ghost"
            size="sm"
            className="-ml-2 text-accent hover:text-accent"
            aria-expanded={showRules}
            aria-controls={stepsId}
            iconRight={ChevronDown}
            onClick={() => setShowRules((v) => !v)}
          >
            {showRules ? "Hide the rules" : "Show the rules"}
          </Button>
          {showRules ? (
            <div id={stepsId} className="mt-2 space-y-3">
              <ol className="relative space-y-3 pl-5 before:absolute before:bottom-2 before:left-[5px] before:top-2 before:w-px before:bg-line-strong">
                {receipt.steps.map((s, i) => {
                  const rule = s.rule_id ? byId.get(s.rule_id) : undefined;
                  const last = i === receipt.steps.length - 1;
                  return (
                    <li key={`${s.label}-${i}`} className="relative text-[13px]">
                      <span
                        aria-hidden
                        className={cn(
                          "absolute -left-5 top-[5px] size-[11px] rounded-full border-2",
                          last ? "border-accent bg-accent" : "border-line-strong bg-surface",
                        )}
                      />
                      <div className="flex items-baseline justify-between gap-3">
                        <span className={cn("leading-snug", last ? "font-medium text-ink" : "text-ink/90")}>{s.label}</span>
                        {s.date ? <DateText date={s.date} className="shrink-0 text-[12.5px] font-medium text-ink" /> : null}
                      </div>
                      {s.citation || rule ? (
                        <div className="mt-0.5 text-[12px] text-muted">
                          {rule?.url ? (
                            <a href={rule.url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 hover:text-accent hover:underline">
                              {s.citation ?? rule.citation}
                              <ExternalLink className="size-3" aria-hidden />
                              <span className="sr-only">(opens the law text in a new tab)</span>
                            </a>
                          ) : (
                            (s.citation ?? rule?.citation)
                          )}
                        </div>
                      ) : null}
                    </li>
                  );
                })}
              </ol>
              {receipt.holiday_calendar ? (
                <p className="flex items-start gap-2 rounded-lg bg-surface-2/60 px-3 py-2 text-[12.5px] leading-5 text-muted">
                  <CalendarDays className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                  <span>
                    Weekends and public holidays counted: <span className="font-medium text-ink/85">{receipt.holiday_calendar}</span>
                  </span>
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}

      <Disclaimer variant="block" advice={adviceFor(area)} />
    </div>
  );
}

/**
 * A "Why this date?" trigger that opens the receipt in a popover.
 *
 * @example <WhyThisDate receipt={item.computation} spec={item.date_spec} />
 */
export function WhyThisDate({
  receipt,
  spec,
  area,
  children,
  className,
}: {
  receipt: ComputationReceipt;
  spec?: DateSpec | null;
  area?: Area | null;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <Popover
      label="Why this date?"
      placement="bottom-start"
      className="w-[23rem] p-4"
      content={<ReceiptView receipt={receipt} spec={spec} area={area} />}
    >
      <button
        type="button"
        className={cn(
          "inline-flex items-center gap-1 rounded-md text-[13px] font-medium text-accent underline decoration-accent/30 underline-offset-[3px] transition-colors hover:decoration-accent",
          className,
        )}
      >
        <HelpCircle className="size-3.5" aria-hidden />
        {children ?? "Why this date?"}
      </button>
    </Popover>
  );
}
