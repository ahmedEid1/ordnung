/** One contract: what it is, what it costs, how it ends (in plain words), the dates to act by. */
import type { ReactNode } from "react";
import { Link } from "react-router";
import { FilePen, FileText, Info, TriangleAlert } from "lucide-react";
import type { Contract, Party } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { buttonVariants } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { KindIcon } from "@/components/ui/KindBadge";
import { PartyChip } from "@/components/ui/PartyChip";
import { StatusPill } from "@/components/ui/StatusPill";
import { CONTRACT_CATEGORY_COPY, copyFor } from "@/lib/copy";
import { formatIntervalSuffix, formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ContractWhy } from "./ContractWhy";
import { contractMonthlyCost, isLockInDecision, isRollingContract, ruleInWords } from "./model";
import { composerHrefFor, endingLetterLabel, offersEndingLetter } from "./links";
import { dayNumber } from "@/features/lanes/scale";

/** Regimes under which an uncancelled contract simply continues, cancellable at any time. */
const ROLLING_REGIMES = new Set(["bgb309_new", "tkg56", "stromgvv20", "sgbv175"]);

function Row({ label, children, strong }: { label: string; children: ReactNode; strong?: boolean }) {
  return (
    <div className={cn("flex items-baseline justify-between gap-3 py-1.5", strong && "font-medium")}>
      <dt className="text-[13px] text-muted">{label}</dt>
      {/* never narrower than its widest unbreakable part (a date): the label wraps instead */}
      <dd className="text-right text-[13px] text-ink">{children}</dd>
    </div>
  );
}

export function ContractCard({
  contract: c,
  party,
  today,
  selected,
}: {
  contract: Contract;
  party: Party | undefined;
  today: string;
  selected?: boolean;
}) {
  const comp = c.computed;
  const monthly = contractMonthlyCost(c);
  const rule = ruleInWords(c, today);
  const category = copyFor(CONTRACT_CATEGORY_COPY, c.category).label;
  const active = c.status === "active";
  const rolling = isRollingContract(c);
  // a rolling contract can be cancelled any month: no countdown, just when it would end
  const upcomingSend = !rolling && comp?.send_by && comp.send_by >= today ? comp.send_by : null;
  const decideSoon = Boolean(upcomingSend && isLockInDecision(c) && dayNumber(upcomingSend) - dayNumber(today) <= 60);
  const upcomingCancel = !rolling && comp?.cancel_by && comp.cancel_by >= today ? comp.cancel_by : null;
  const lowConfidence = comp?.confidence === "low";
  const titleId = `contract-${c.id}-title`;
  const isJob = c.category === "employment";
  const offerLetter = offersEndingLetter(c);
  // e.g. the broadcasting fee: say why there is nothing to cancel instead of offering a letter
  const whyNot = active && !offerLetter ? c.cancel_hint : null;

  return (
    <article
      id={`contract-${c.id}`}
      aria-labelledby={titleId}
      data-contract-id={c.id}
      className={cn(
        "card flex w-full flex-col p-4 transition-[box-shadow,border-color] duration-300 sm:p-5",
        selected && "border-accent shadow-[0_0_0_3px_color-mix(in_srgb,var(--color-accent)_22%,transparent)]",
        !active && "bg-surface/70",
      )}
    >
      <header className="flex items-start gap-3">
        <KindIcon category={c.category} size="md" title={category} />
        <div className="min-w-0 flex-1">
          <h3 id={titleId} className="text-[15px] font-semibold leading-snug text-ink">
            {c.name}
          </h3>
          <p className="mt-0.5 text-[12.5px] text-muted">{category}</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {!active ? <StatusPill of="contract" status={c.status} /> : null}
          {lowConfidence ? (
            <Badge tone="warn" icon={TriangleAlert}>
              Please check
            </Badge>
          ) : null}
        </div>
      </header>

      {c.party_id || party ? (
        <div className="mt-3">
          <PartyChip party={party ?? null} id={c.party_id} name={party?.name ?? null} />
        </div>
      ) : null}

      <div className="mt-4 flex items-baseline gap-2">
        {c.cost_amount !== null && c.cost_interval && c.cost_interval !== "once" ? (
          <>
            <span className="display text-[24px] font-semibold leading-none text-ink">{formatMoney(c.cost_amount, { currency: c.cost_currency })}</span>
            <span className="-ml-1 text-[13px] text-muted">{formatIntervalSuffix(c.cost_interval)}</span>
            {c.cost_interval !== "monthly" && monthly !== null ? (
              <span className="text-[12.5px] text-muted">≈ {formatMoney(monthly, { currency: c.cost_currency })}/month</span>
            ) : null}
          </>
        ) : isJob ? (
          <span className="text-[13px] text-muted">Pays you — not a cost</span>
        ) : (
          <span className="text-[13px] text-muted">Cost not in your letters yet</span>
        )}
      </div>

      <p className="mt-2 text-[13.5px] leading-relaxed text-ink/90">
        {rule.text}
        {rule.citation ? <span className="whitespace-nowrap text-muted"> · {rule.citation}</span> : null}
      </p>
      <ContractWhy contract={c} className="mt-1.5 self-start" />

      {rolling && comp?.cancel_by && comp.earliest_exit ? (
        <p className="mt-3 text-[13px] leading-relaxed text-ink/85" data-testid="rolling-note">
          Cancel any time — it ends <DateText date={comp.earliest_exit} className="font-medium text-ink" /> if your notice arrives by{" "}
          <DateText date={comp.cancel_by} className="font-medium text-ink" />, otherwise a month later.
        </p>
      ) : null}

      <dl className="mt-3 divide-y divide-line/80 border-y border-line/80 empty:hidden">
        {upcomingSend ? (
          <Row label="Post it by" strong>
            <Countdown date={upcomingSend} showDate />
          </Row>
        ) : null}
        {upcomingCancel ? (
          <Row label="Must arrive by">
            <Countdown date={upcomingCancel} showDate className={upcomingSend ? "font-normal" : undefined} />
          </Row>
        ) : null}
        {comp?.current_term_end ? (
          <Row label={comp.current_term_end < today ? "Term ended" : "Current term ends"}>
            <DateText date={comp.current_term_end} />
          </Row>
        ) : null}
        {comp?.next_renewal && comp.next_renewal >= today ? (
          <Row label={ROLLING_REGIMES.has(comp.regime) || !c.renewal_term_months ? "Runs on month by month from" : "Renews on"}>
            <DateText date={comp.next_renewal} />
          </Row>
        ) : null}
        {c.end_date && c.end_date !== comp?.current_term_end ? (
          <Row label={c.end_date < today ? "Ended" : "Ends"}>
            <DateText date={c.end_date} />
          </Row>
        ) : null}
        {active && !rolling && comp?.earliest_exit && comp.earliest_exit >= today && !upcomingCancel ? (
          <Row label="Earliest end if you cancel now">
            <DateText date={comp.earliest_exit} />
          </Row>
        ) : null}
        {c.customer_number ? (
          <Row label="Customer number">
            <span className="font-ident">{c.customer_number}</span>
          </Row>
        ) : null}
      </dl>

      {whyNot ? (
        <p className="mt-4 flex items-start gap-2 rounded-lg bg-surface-2/70 px-3 py-2 text-[12.5px] leading-5 text-muted" data-testid="cancel-hint">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>{whyNot}</span>
        </p>
      ) : null}

      <footer className="mt-auto flex flex-wrap items-center gap-2 pt-4">
        {offerLetter ? (
          <Link
            to={composerHrefFor(c)}
            title={isJob && c.cancel_hint ? c.cancel_hint : undefined}
            className={buttonVariants({ variant: decideSoon ? "primary" : "secondary", size: "sm" })}
          >
            <FilePen aria-hidden />
            {endingLetterLabel(c)}
            <span className="sr-only"> for {c.name}</span>
          </Link>
        ) : null}
        {c.source_doc_id ? (
          <Link to={`/documents/${encodeURIComponent(c.source_doc_id)}`} className={buttonVariants({ variant: "ghost", size: "sm" })}>
            <FileText aria-hidden />
            Open letter
            <span className="sr-only"> for {c.name}</span>
          </Link>
        ) : null}
      </footer>
    </article>
  );
}
