/**
 * "Why these dates?" for a contract: the engine's plain-words summary first, the key dates, how
 * sure we are (and why), notes (form requirements…), then "Show the rules" with every step and its
 * legal citation. Always ends with the point-of-use disclaimer (SPEC §21).
 */
import { useId, useState } from "react";
import { CalendarCheck2, CalendarClock, ChevronDown, ExternalLink, HelpCircle, Info, Mail, Recycle, Scale } from "lucide-react";
import type { Contract } from "@/api/types";
import { useRules } from "@/api/hooks";
import { Button } from "@/components/ui/Button";
import { ConfidenceNote } from "@/components/ui/ConfidenceNote";
import { DateText } from "@/components/ui/DateText";
import { ADVICE_LINKS, Disclaimer } from "@/components/ui/Disclaimer";
import { Popover } from "@/components/ui/Popover";
import { CONTRACT_REGIME_COPY, copyFor } from "@/lib/copy";
import { cn } from "@/lib/utils";
import { isRollingContract } from "./model";

function KeyDate({ icon: Icon, label, date, strong }: { icon: typeof Mail; label: string; date: string; strong?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <dt className="flex items-center gap-2 text-[13px] text-muted">
        <Icon className="size-3.5" aria-hidden />
        {label}
      </dt>
      <dd>
        <DateText date={date} className={cn("text-[13px]", strong ? "font-semibold text-ink" : "font-medium text-ink/85")} />
      </dd>
    </div>
  );
}

export function ContractWhyView({ contract }: { contract: Contract }) {
  const comp = contract.computed;
  const [showRules, setShowRules] = useState(false);
  const rules = useRules();
  const stepsId = useId();
  if (!comp) return null;
  const byId = new Map((rules.data ?? []).map((r) => [r.id, r]));
  const regime = copyFor(CONTRACT_REGIME_COPY, comp.regime);
  const advice = contract.category === "rent" ? ADVICE_LINKS.rent : contract.category === "employment" ? undefined : ADVICE_LINKS.consumer;
  const hasDates = comp.current_term_end || comp.cancel_by || comp.send_by || comp.next_renewal || comp.earliest_exit;
  const rolling = isRollingContract(contract);

  return (
    <div className="space-y-3.5">
      <div>
        <p className="text-[12px] font-semibold uppercase tracking-[0.07em] text-muted">Why these dates?</p>
        <p className="mt-0.5 text-[13px] text-muted">{contract.name}</p>
      </div>
      <p className="text-[14px] leading-relaxed text-ink">{comp.summary}</p>

      {hasDates ? (
        <dl className="divide-y divide-line rounded-lg border border-line bg-surface-2/50 px-3">
          {comp.send_by ? <KeyDate icon={Mail} label="Post it by" date={comp.send_by} strong /> : null}
          {comp.cancel_by ? <KeyDate icon={CalendarCheck2} label="Must arrive by" date={comp.cancel_by} strong={!comp.send_by} /> : null}
          {comp.safe_date && comp.safe_date !== comp.cancel_by ? <KeyDate icon={CalendarCheck2} label="Safe date (a working day)" date={comp.safe_date} /> : null}
          {comp.current_term_end ? <KeyDate icon={CalendarClock} label="Current term ends" date={comp.current_term_end} /> : null}
          {comp.next_renewal ? <KeyDate icon={Recycle} label="Renews on" date={comp.next_renewal} /> : null}
          {comp.earliest_exit && comp.earliest_exit !== comp.current_term_end ? (
            <KeyDate icon={CalendarClock} label="Earliest possible end" date={comp.earliest_exit} />
          ) : null}
        </dl>
      ) : null}

      {rolling ? (
        <p className="rounded-lg bg-surface-2/70 px-3 py-2 text-[13px] leading-5 text-ink/85">
          You can cancel this any month. Miss this date and it simply ends a month later — nothing is locked in.
        </p>
      ) : null}

      <ConfidenceNote
        confidence={comp.confidence}
        // "use the fastest channel today" is no advice for a contract you can cancel next month too
        warnings={rolling ? comp.warnings.filter((w) => !/sending time has passed/i.test(w)) : comp.warnings}
        hideWhenHigh={false}
      />

      {comp.notes.length ? (
        <ul className="space-y-1.5">
          {comp.notes.map((n) => (
            <li key={n} className="flex gap-2 text-[13px] leading-5 text-ink/90">
              <Info className="mt-0.5 size-3.5 shrink-0 text-accent" aria-hidden />
              {n}
            </li>
          ))}
        </ul>
      ) : null}

      <p className="flex items-start gap-2 text-[12.5px] leading-5 text-muted">
        <Scale className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        <span>
          Rule used: <span className="font-medium text-ink/85">{regime.label}</span>
          {"citation" in regime && comp.regime !== "as_written" ? ` · ${regime.citation}` : ""}
        </span>
      </p>

      {comp.steps.length ? (
        <div>
          <Button
            variant="link"
            size="sm"
            iconRight={ChevronDown}
            aria-expanded={showRules}
            aria-controls={stepsId}
            onClick={() => setShowRules((v) => !v)}
            className={cn("[&_svg]:transition-transform", showRules && "[&_svg]:rotate-180")}
          >
            {showRules ? "Hide the rules" : "Show the rules"}
          </Button>
          <div id={stepsId} hidden={!showRules}>
            <ol className="relative mt-3 space-y-3 pl-5 before:absolute before:bottom-1.5 before:left-[5px] before:top-1.5 before:w-px before:bg-line-strong">
              {comp.steps.map((s, i) => {
                const rule = s.rule_id ? byId.get(s.rule_id) : undefined;
                const citation = s.citation ?? rule?.citation ?? null;
                return (
                  <li key={`${s.label}-${i}`} className="relative text-[13px]">
                    <span
                      aria-hidden
                      className={cn(
                        "absolute -left-5 top-[5px] size-[11px] rounded-full border-2 border-surface",
                        i === comp.steps.length - 1 ? "bg-accent" : "bg-line-strong",
                      )}
                    />
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-ink">{s.label}</span>
                      {s.date ? <DateText date={s.date} className="shrink-0 text-[12.5px] font-medium text-ink" /> : null}
                    </div>
                    {citation ? (
                      <div className="mt-0.5 text-[12px] font-medium text-accent">
                        {rule?.url ? (
                          <a href={rule.url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 hover:underline">
                            {citation}
                            <ExternalLink className="size-3" aria-hidden />
                            <span className="sr-only">(opens the law text in a new tab)</span>
                          </a>
                        ) : (
                          citation
                        )}
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ol>
          </div>
        </div>
      ) : null}

      <Disclaimer variant="block" advice={advice} />
    </div>
  );
}

/** "Why these dates?" link that opens {@link ContractWhyView} in a popover. */
export function ContractWhy({ contract, className, label = "Why these dates?" }: { contract: Contract; className?: string; label?: string }) {
  if (!contract.computed) return null;
  return (
    <Popover
      label={`Why these dates? ${contract.name}`}
      placement="bottom-start"
      className="w-[24rem]"
      content={<ContractWhyView contract={contract} />}
    >
      <button
        type="button"
        className={cn(
          "inline-flex items-center gap-1 rounded-md text-[13px] font-medium text-accent underline decoration-accent/30 underline-offset-[3px] transition-colors hover:decoration-accent",
          className,
        )}
      >
        <HelpCircle className="size-3.5" aria-hidden />
        {label}
        <span className="sr-only"> ({contract.name})</span>
      </button>
    </Popover>
  );
}
