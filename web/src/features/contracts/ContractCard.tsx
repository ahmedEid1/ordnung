/** One contract: what it is, what it costs, how it ends (in plain words), the dates to act by. */
import { useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { FilePen, FileSearch, FileText, Info, Pencil, TriangleAlert } from "lucide-react";
import type { Contract, Party } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { KindIcon } from "@/components/ui/KindBadge";
import { Money } from "@/components/ui/Money";
import { PartyChip } from "@/components/ui/PartyChip";
import { StatusPill } from "@/components/ui/StatusPill";
import { CONTRACT_CATEGORY_COPY, copyFor } from "@/lib/copy";
import { formatMoney, protectRefs } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ContractWhy } from "./ContractWhy";
import { CONTINUES_MONTHLY, contractMonthlyCost, isFixedTerm, isLockInDecision, isRollingContract, ruleInWords, termsUnclear } from "./model";
import { composerHrefFor, endingLetterLabel, offersEndingLetter } from "./links";
import { NoticePeriodForm } from "./NoticePeriodForm";
import { dayNumber } from "@/features/lanes/scale";
import { focusWhenReady } from "@/features/today/focus";

/**
 * A label and its value on one line; when both don't fit (a narrow card, a long label) the value
 * moves under the label, still flush right — the label is never squeezed into "Send / by", and a
 * long countdown wraps inside the value, never past the card.
 */
function Row({ label, children, strong }: { label: string; children: ReactNode; strong?: boolean }) {
  return (
    <div className={cn("flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-1.5", strong && "font-medium")}>
      <dt className="min-w-0 text-[13px] text-muted">{label}</dt>
      <dd className="ml-auto min-w-0 max-w-full text-right text-[13px] text-ink">{children}</dd>
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
  const fixedTerm = active && isFixedTerm(c);
  const unclear = termsUnclear(c);
  // a rolling contract can be cancelled any month: no countdown, just when it would end
  const upcomingSend = !rolling && comp?.send_by && comp.send_by >= today ? comp.send_by : null;
  const decideSoon = Boolean(upcomingSend && isLockInDecision(c) && dayNumber(upcomingSend) - dayNumber(today) <= 60);
  const upcomingCancel = !rolling && comp?.cancel_by && comp.cancel_by >= today ? comp.cancel_by : null;
  const termEnd = comp?.current_term_end ?? null;
  // the earliest end, unless a row already says it (the end of the term, a fixed end date)
  const earliest =
    active && comp?.earliest_exit && comp.earliest_exit >= today && !upcomingCancel && comp.earliest_exit !== termEnd && comp.earliest_exit !== c.end_date
      ? comp.earliest_exit
      : null;
  const rollingArriveBy = rolling && comp?.cancel_by && comp.cancel_by >= today ? comp.cancel_by : null;
  const lowConfidence = comp?.confidence === "low";
  const titleId = `contract-${c.id}-title`;
  const isJob = c.category === "employment";
  const offerLetter = offersEndingLetter(c);
  // e.g. the broadcasting fee: say why there is nothing to cancel instead of offering a letter
  const whyNot = active && !offerLetter ? c.cancel_hint : null;
  const hasCost = c.cost_amount !== null && Boolean(c.cost_interval) && c.cost_interval !== "once";
  // terms we couldn't work out: the notice period can be entered here, and the engine redoes the dates
  const [editingNotice, setEditingNotice] = useState(false);
  const cardRef = useRef<HTMLElement>(null);
  const noticeButtonRef = useRef<HTMLButtonElement>(null);
  const closeNotice = (saved: Contract | null) => {
    setEditingNotice(false);
    // back to the button — or, when the dates are known now and it is gone, to the card itself
    requestAnimationFrame(() => (saved && !termsUnclear(saved) ? cardRef.current : noticeButtonRef.current)?.focus());
  };
  // Undo in the toast: the button is back once the old terms are, and takes the focus the toast had
  const noticeUndone = () => focusWhenReady(() => noticeButtonRef.current);

  return (
    <article
      ref={cardRef}
      id={`contract-${c.id}`}
      aria-labelledby={titleId}
      data-contract-id={c.id}
      // focusable from script only: a contract picked in the chart takes the focus with it
      tabIndex={-1}
      className={cn(
        "card flex w-full min-w-0 flex-col p-4 transition-[box-shadow,border-color] duration-300 sm:p-5",
        selected && "border-accent shadow-[0_0_0_3px_color-mix(in_srgb,var(--color-accent)_22%,transparent)]",
        !active && "bg-surface/70",
      )}
    >
      <header className="flex items-start gap-3">
        <KindIcon category={c.category} size="md" title={category} />
        <div className="min-w-0 flex-1">
          {/* a flat number ("Wohnung 05-2-03") never breaks at its hyphens */}
          <h3 id={titleId} className="text-[15px] font-semibold leading-snug text-ink">
            {protectRefs(c.name)}
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
        <div className="mt-3 min-w-0">
          <PartyChip party={party ?? null} id={c.party_id} name={party?.name ?? null} />
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        {hasCost ? (
          <>
            <Money
              amount={c.cost_amount}
              currency={c.cost_currency}
              interval={c.cost_interval}
              className="display text-[24px] font-semibold leading-none"
              intervalClassName="font-sans text-[13px]"
            />
            {c.cost_interval !== "monthly" && monthly !== null ? (
              <span className="whitespace-nowrap text-[12.5px] text-muted">≈ {formatMoney(monthly, { currency: c.cost_currency })}/month</span>
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

      <dl className="mt-3 divide-y divide-line/80 border-y border-line/80 empty:hidden">
        {upcomingSend ? (
          <Row label="Send by" strong>
            {/* the key date stays ink however far out it is (a grey "in 11 months" reads as done) */}
            <Countdown date={upcomingSend} showDate inkLater />
          </Row>
        ) : null}
        {upcomingCancel ? (
          <Row label="Must arrive by">
            <Countdown date={upcomingCancel} showDate inkLater className={upcomingSend ? "font-normal" : undefined} />
          </Row>
        ) : null}
        {termEnd ? (
          <Row label={termEnd < today ? "Term ended" : fixedTerm ? "Ends" : "Current term ends"}>
            <DateText date={termEnd} />
          </Row>
        ) : null}
        {comp?.next_renewal && comp.next_renewal >= today ? (
          <Row label={CONTINUES_MONTHLY.has(comp.regime) || !c.renewal_term_months ? "Then monthly from" : "Renews on"}>
            <DateText date={comp.next_renewal} />
          </Row>
        ) : null}
        {c.end_date && c.end_date !== termEnd ? (
          <Row label={c.end_date < today ? "Ended" : "Ends"}>
            <DateText date={c.end_date} />
          </Row>
        ) : null}
        {earliest ? (
          <Row label="Earliest end if you cancel now">
            <DateText date={earliest} />
          </Row>
        ) : null}
        {rollingArriveBy ? (
          <Row label="Notice must arrive by">
            <DateText date={rollingArriveBy} />
          </Row>
        ) : null}
        {c.customer_number ? (
          <Row label="Customer number">
            <span className="font-ident">{c.customer_number}</span>
          </Row>
        ) : null}
      </dl>

      {rollingArriveBy ? (
        <p className="mt-2 text-[12.5px] leading-5 text-muted" data-testid="rolling-note">
          You can cancel any month — a notice that arrives later ends it a month later.
        </p>
      ) : null}

      {whyNot ? (
        <p className="mt-4 flex items-start gap-2 rounded-lg bg-surface-2/70 px-3 py-2 text-[12.5px] leading-5 text-muted" data-testid="cancel-hint">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>{whyNot}</span>
        </p>
      ) : null}

      {/* (stays while saving, even once the saved terms have made the dates known) */}
      {editingNotice ? <NoticePeriodForm contract={c} onClose={closeNotice} onUndone={noticeUndone} /> : null}

      <footer className="mt-auto flex flex-wrap items-center gap-2 pt-4">
        {unclear && c.source_doc_id ? (
          // the notice period isn't in the letter we read: checking it comes first
          <Link to={`/documents/${encodeURIComponent(c.source_doc_id)}`} className={buttonVariants({ variant: "secondary", size: "sm" })}>
            <FileSearch aria-hidden />
            Check the letter
            <span className="sr-only"> for {c.name}</span>
          </Link>
        ) : null}
        {unclear && !editingNotice ? (
          <Button ref={noticeButtonRef} size="sm" icon={Pencil} onClick={() => setEditingNotice(true)}>
            {c.notice_value ? "Change notice period" : "Add notice period"}
            <span className="sr-only"> for {c.name}</span>
          </Button>
        ) : null}
        {offerLetter ? (
          <Link
            to={composerHrefFor(c)}
            title={isJob && c.cancel_hint ? c.cancel_hint : undefined}
            className={buttonVariants({ variant: decideSoon ? "primary" : unclear ? "ghost" : "secondary", size: "sm" })}
          >
            <FilePen aria-hidden />
            {endingLetterLabel(c)}
            <span className="sr-only"> for {c.name}</span>
          </Link>
        ) : null}
        {c.source_doc_id && !unclear ? (
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
