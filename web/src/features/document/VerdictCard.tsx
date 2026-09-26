/**
 * The verdict card — the first thing on a letter: what this is, what you need to do, by when
 * (with "Why this date?"), what happens if you ignore it, and one main button.
 */
import type { ReactNode } from "react";
import { Link } from "react-router";
import {
  ArrowRight,
  CalendarPlus,
  Check,
  CircleCheckBig,
  Clock,
  Landmark,
  ListChecks,
  Mail,
  PenLine,
  Scale,
  ShieldAlert,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import type { DocumentDetail, Item, Suggestion } from "@/api/types";
import { useUpdateSuggestion } from "@/api/hooks";
import { isDirectDebit } from "@/lib/payments";
import { toast } from "@/components/ui/Toast";
import { cn } from "@/lib/utils";
import { formatDate, formatMoney, formatTime, looksGerman, urgencyOf, type Urgency } from "@/lib/format";
import { useToday } from "@/lib/today";
import { Badge } from "@/components/ui/Badge";
import { Button, buttonVariants } from "@/components/ui/Button";
import { DateText } from "@/components/ui/DateText";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { KindBadge } from "@/components/ui/KindBadge";
import { PartyChip } from "@/components/ui/PartyChip";
import { Popover } from "@/components/ui/Popover";
import { StatusPill } from "@/components/ui/StatusPill";
import {
  chooseMainAction,
  dayCountdown,
  decisionSuggestion,
  incomingMoney,
  isOpenItem,
  isOptionalObjection,
  leadsWithDecision,
  mustAct,
  needsArrivalDate,
  needsCheck,
  otherLawDeadlines,
  scamSuggestion,
  type MainAction,
} from "./verdict";
import { icsFileName, icsHref, useItemActions, useStartDraft } from "./actions";
import { KindPicker } from "./KindPicker";
import { PayPanel } from "./PayPanel";
import { GlossaryText } from "./Explained";
import { adviceFor, WhyThisDate } from "./WhyThisDate";
import { LetterText } from "@/components/ui/LetterText";

const countdownTone: Record<Urgency, string> = {
  overdue: "bg-danger text-white dark:text-canvas",
  today: "bg-danger text-white dark:text-canvas",
  soon: "bg-danger text-white dark:text-canvas",
  week: "bg-surface text-warn-ink ring-1 ring-warn/30",
  month: "bg-surface text-ink ring-1 ring-line",
  later: "bg-surface text-muted ring-1 ring-line",
  past: "bg-surface text-muted ring-1 ring-line",
};

const dateTone: Record<Urgency, string> = {
  overdue: "bg-danger-soft border-danger/20",
  today: "bg-danger-soft border-danger/20",
  soon: "bg-danger-soft border-danger/20",
  week: "bg-warn-soft border-warn/25",
  month: "bg-accent-soft/70 border-accent/15",
  later: "bg-surface-2 border-line",
  past: "bg-surface-2 border-line",
};

function Section({ label, icon: Icon, children, className }: { label: string; icon: LucideIcon; children: ReactNode; className?: string }) {
  return (
    <div className={cn("border-t border-line px-5 py-4 sm:px-6", className)}>
      {/* the card's title is the page's h1, so its sections are h2 */}
      <h2 className="mb-1.5 flex items-center gap-1.5 text-[11.5px] font-semibold uppercase tracking-[0.08em] text-muted">
        <Icon className="size-3.5" aria-hidden />
        {label}
      </h2>
      {children}
    </div>
  );
}

export interface VerdictCardProps {
  detail: DocumentDetail;
  primary: Item | null;
  /** Scroll to the "When did this letter arrive?" question. */
  onAskArrival?: () => void;
}

export function VerdictCard({ detail, primary, onAskArrival }: VerdictCardProps) {
  const doc = detail.document;
  const today = useToday();
  const scam = scamSuggestion(detail);
  const decisionIdea = decisionSuggestion(detail);
  // a price increase's special right / a notice window leads — not the new monthly fee
  const decision = !scam && leadsWithDecision(decisionIdea, primary) ? decisionIdea : null;
  const main: MainAction = decision ? { type: "decide", suggestion: decision } : chooseMainAction(detail, primary);
  const open = !decision && primary && isOpenItem(primary) ? primary : null;
  const askArrival = open ? needsArrivalDate(open, doc) : false;
  const checkDate = open ? needsCheck(open) : false;
  const isAppointment = open?.kind === "appointment";
  const debit = open ? isDirectDebit(open) : false;
  // a court order's or a dismissal's deadline isn't optional: doing nothing has consequences
  const optional = open ? isOptionalObjection(open) && !mustAct(doc) : false;
  const alsoByLaw = !scam && !decision ? otherLawDeadlines(detail.items, open) : [];
  const refund = incomingMoney(detail.items);
  const refundText = refund?.amount != null ? `${formatMoney(refund.amount, { currency: refund.currency })} comes back to you` : null;

  return (
    <article
      aria-labelledby="verdict-title"
      className={cn("card overflow-hidden", scam && "border-danger/40")}
    >
      {scam ? <div className="h-1 bg-danger" aria-hidden /> : null}
      {/* 1 — what this is */}
      <header className="px-5 pb-4 pt-5 sm:px-6 sm:pt-6">
        <p className="sr-only">What this is</p>
        <div className="flex flex-wrap items-center gap-1.5">
          <KindBadge docKind={doc.kind} />
          {!scam && doc.status !== "queued" && doc.status !== "processing" ? <KindPicker doc={doc} /> : null}
          {scam ? (
            <Badge tone="danger" icon={ShieldAlert}>
              Possible scam
            </Badge>
          ) : doc.status === "needs_review" ? (
            <StatusPill of="document" status="needs_review" />
          ) : null}
          {doc.ai_private ? <Badge tone="neutral">Private — not read by AI</Badge> : null}
        </div>
        <h1 id="verdict-title" className="display mt-3 text-[26px] font-semibold leading-[1.15] text-ink [overflow-wrap:anywhere] hyphens-auto sm:text-[29px]">
          {doc.title ?? doc.filename}
        </h1>
        <div className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-[13px] text-muted">
          {detail.party ? <PartyChip party={detail.party} /> : null}
          {/* one run of text: when it wraps, no separator is left at the start of a line */}
          {doc.doc_date || doc.received_date ? (
            <span>
              {doc.doc_date ? (
                <>
                  Letter of <DateText date={doc.doc_date} style="medium" className="text-ink/85" />
                </>
              ) : null}
              {doc.doc_date && doc.received_date ? ", " : null}
              {doc.received_date ? (
                <>
                  {doc.doc_date ? "arrived" : "Arrived"} <DateText date={doc.received_date} style="day" className="text-ink/85" />
                </>
              ) : null}
            </span>
          ) : null}
        </div>
        {doc.summary ? <p className="mt-3 text-[15px] leading-relaxed text-ink/80">{doc.summary}</p> : null}
      </header>

      {/* 2 — what you need to do */}
      <Section label="What you need to do" icon={ListChecks}>
        {scam ? (
          <p className="text-[16px] font-medium leading-snug text-danger-ink">
            Don't pay. Check with the real sender first — use contact details from an older letter, not from this one.
          </p>
        ) : decision ? (
          <>
            <p className="text-[16px] font-medium leading-snug text-ink">{decision.title}</p>
            <p className="mt-1 text-[13px] leading-relaxed text-muted">{decision.body}</p>
          </>
        ) : open && optional ? (
          <>
            <p className="flex items-start gap-2 text-[16px] font-medium leading-snug text-ink">
              <CircleCheckBig className="mt-0.5 size-[18px] shrink-0 text-ok" aria-hidden />
              <span>Nothing to do{refundText ? ` — ${refundText}` : " if the decision is right"}.</span>
            </p>
            <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink/80">
              <span className="font-medium">Only if you disagree:</span> <GlossaryText text={open.action ?? open.title} />
            </p>
          </>
        ) : open ? (
          <>
            <p className="text-[16px] font-medium leading-snug text-ink">
              {looksGerman(open.action) ? <LetterText text={open.action!} /> : <GlossaryText text={open.action ?? open.title} />}
            </p>
            {open.action && open.title !== open.action ? (
              <p className="mt-1 text-[13px] text-muted">
                <GlossaryText text={open.title} />
              </p>
            ) : null}
            {debit ? <p className="mt-1 text-[13px] text-muted">Collected automatically by direct debit — nothing to transfer.</p> : null}
            {alsoByLaw.length ? (
              <ul className="mt-3 space-y-1.5" aria-label="Also due by law">
                {alsoByLaw.map((i) => (
                  <li key={i.id} className="flex items-start gap-2 rounded-lg bg-surface-2/70 px-3 py-2 text-[13.5px] leading-snug text-ink">
                    <Scale className="mt-0.5 size-3.5 shrink-0 text-muted" aria-hidden />
                    <span className="min-w-0">
                      <span className="font-medium">Also: </span>
                      <GlossaryText text={i.title} />
                      {i.due_date ? (
                        <>
                          {" "}
                          — by <DateText date={i.due_date} style="medium" className="font-semibold" />
                        </>
                      ) : null}
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}
          </>
        ) : (
          <p className="flex items-center gap-2 text-[15px] font-medium text-ink">
            <CircleCheckBig className="size-[18px] text-ok" aria-hidden />
            {refundText ? `Nothing to do — ${refundText}.` : "Nothing right now — it's filed for your records."}
          </p>
        )}
      </Section>

      {/* 3 — by when */}
      {decision?.due_date ? (
        <Section label="Decide by" icon={Clock}>
          <div className={cn("rounded-xl border px-4 py-3.5", dateTone[urgencyOf(decision.due_date, today)])}>
            <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
              <p className="display text-[28px] font-semibold leading-none text-ink sm:text-[32px]">
                <time dateTime={decision.due_date}>{formatDate(decision.due_date, { style: "short", today })}</time>
              </p>
              <span
                className={cn(
                  "inline-flex items-center rounded-full px-2.5 py-1 text-[13px] font-semibold tabular-nums leading-4",
                  countdownTone[urgencyOf(decision.due_date, today)],
                )}
              >
                {dayCountdown(decision.due_date, today)}
              </span>
            </div>
            <p className="mt-2.5 flex items-center gap-1.5 text-[13px] text-ink/80">
              <Mail className="size-3.5 text-muted" aria-hidden />
              If you cancel by post, send it by this day so it arrives in time.
            </p>
          </div>
        </Section>
      ) : null}
      {!scam && open?.due_date ? (
        <Section label={isAppointment ? "When" : optional ? "Only if you disagree" : "By when"} icon={Clock}>
          <div className={cn("rounded-xl border px-4 py-3.5", optional ? dateTone.later : dateTone[urgencyOf(open.due_date, today)])}>
            <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
              <p className="display text-[28px] font-semibold leading-none text-ink sm:text-[32px]">
                <time dateTime={open.due_date}>{formatDate(open.due_date, { style: "short", today })}</time>
                {open.due_time ? <span className="ml-2 text-[20px] text-ink/70">{formatTime(open.due_time)}</span> : null}
              </p>
              <span
                className={cn(
                  "inline-flex items-center rounded-full px-2.5 py-1 text-[13px] font-semibold tabular-nums leading-4",
                  countdownTone[urgencyOf(open.due_date, today, isAppointment ? "event" : "due")],
                )}
              >
                {dayCountdown(open.due_date, today, isAppointment ? "event" : "due")}
              </span>
            </div>
            {debit ? (
              <p className="mt-2.5 flex items-center gap-1.5 text-[13px] text-ink/80">
                <Landmark className="size-3.5 text-muted" aria-hidden />
                Collected automatically — keep the money in your account.
              </p>
            ) : open.send_by && open.send_by !== open.due_date ? (
              <p className="mt-2.5 flex items-center gap-1.5 text-[13px] text-ink/80">
                {open.kind === "payment" ? <Landmark className="size-3.5 text-muted" aria-hidden /> : <Mail className="size-3.5 text-muted" aria-hidden />}
                {open.kind === "payment" ? "Transfer it by" : "By post, send it by"}{" "}
                <DateText date={open.send_by} className="font-semibold text-ink" />
              </p>
            ) : null}
            {checkDate ? (
              <p className="mt-2.5 flex items-start gap-1.5 text-[13px] leading-5 text-warn-ink">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                <span>We couldn't find this date in the letter — please check it below.</span>
              </p>
            ) : null}
            {askArrival ? (
              <p className="mt-2.5 flex items-start gap-1.5 text-[13px] leading-5 text-warn-ink">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                <span>
                  Counted from the letter date — the earliest possible.{" "}
                  {onAskArrival ? (
                    <button type="button" onClick={onAskArrival} className="font-semibold underline underline-offset-2 hover:no-underline">
                      Tell us when it arrived
                    </button>
                  ) : null}
                </span>
              </p>
            ) : null}
            {open.computation ? (
              <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1">
                <WhyThisDate receipt={open.computation} spec={open.date_spec} area={open.area} />
                {open.computation.confidence !== "high" ? (
                  <span className="text-[12px] text-muted">
                    {open.computation.confidence === "medium" ? "Worth a second look" : "Please check this date"}
                  </span>
                ) : null}
              </div>
            ) : null}
          </div>
        </Section>
      ) : null}

      {/* 4 — if you ignore it */}
      {scam ? (
        <Section label="If you pay" icon={TriangleAlert}>
          <p className="text-[14.5px] leading-relaxed text-ink/85">
            The money goes to an account this sender has never used before, and may be hard to get back.
          </p>
        </Section>
      ) : decision ? (
        <Section label="If you do nothing" icon={CircleCheckBig}>
          <p className="text-[14.5px] leading-relaxed text-ink/85">
            {decision.rule_id === "price_increase_right"
              ? "Nothing bad happens — the contract simply continues at the new price."
              : "Nothing bad happens — the contract simply continues."}
          </p>
        </Section>
      ) : open?.consequence ? (
        <Section label={optional ? "If you do nothing" : "If you ignore it"} icon={TriangleAlert}>
          <p className="text-[14.5px] leading-relaxed text-ink/85">
            <LetterText text={open.consequence} />
          </p>
        </Section>
      ) : null}

      <Actions detail={detail} main={main} primary={open} optional={optional} />

      {!scam && (open?.due_date || decision) ? (
        <div className="px-5 pb-4 sm:px-6">
          <Disclaimer advice={open && (open.priority === "high" || open.priority === "critical") ? adviceFor(open.area) : undefined} />
        </div>
      ) : null}
    </article>
  );
}

/** "Keep it": the person decided not to cancel — the decision Idea goes (with undo). */
function KeepButton({ suggestion }: { suggestion: Suggestion }) {
  const update = useUpdateSuggestion();
  return (
    <Button
      variant="ghost"
      icon={Check}
      loading={update.isPending}
      onClick={() =>
        update.mutate(
          { id: suggestion.id, patch: { status: "dismissed" } },
          {
            onSuccess: () =>
              toast({
                title: "Kept",
                description: "Ordnung won't remind you about this window again.",
                undo: () => update.mutate({ id: suggestion.id, patch: { status: "new" } }),
              }),
          },
        )
      }
    >
      Keep it
    </Button>
  );
}

function Actions({ detail, main, primary, optional }: { detail: DocumentDetail; main: MainAction; primary: Item | null; optional: boolean }) {
  const doc = detail.document;
  const actions = useItemActions();
  const draft = useStartDraft();

  const mainEl: ReactNode = (() => {
    switch (main.type) {
      case "decide": {
        const target = main.suggestion.action?.target_type === "contract" ? main.suggestion.action.target_id : null;
        return (
          <>
            <Button
              variant="primary"
              icon={PenLine}
              loading={draft.pending}
              onClick={() => draft.start("cancellation", { doc_id: doc.id, contract_id: target, party_id: doc.party_id, case_id: doc.case_id })}
            >
              Draft cancellation
            </Button>
            <KeepButton suggestion={main.suggestion} />
          </>
        );
      }
      case "draft":
        return (
          <Button
            variant={optional ? "secondary" : "primary"}
            icon={PenLine}
            loading={draft.pending}
            onClick={() =>
              draft.start(main.draftKind, {
                doc_id: doc.id,
                contract_id: main.item?.contract_id ?? null,
                party_id: doc.party_id,
                case_id: doc.case_id,
              })
            }
          >
            {main.label}
          </Button>
        );
      case "pay":
        return (
          <Popover label="Pay" placement="top-start" className="w-[22rem] p-4" content={(close) => <PayPanel item={main.item} doc={doc} onPaid={() => actions.markDone(main.item)} close={close} />}>
            <Button variant="primary" icon={Landmark}>
              Pay {main.item.amount != null ? formatMoney(main.item.amount, { currency: main.item.currency }) : ""}
            </Button>
          </Popover>
        );
      case "calendar":
        return (
          <a href={icsHref(main.item)} download={icsFileName(main.item)} className={buttonVariants({ variant: "primary" })}>
            <CalendarPlus aria-hidden />
            Add to calendar
          </a>
        );
      case "done":
        return (
          <Button variant="primary" icon={Check} onClick={() => actions.markDone(main.item)}>
            Mark done
          </Button>
        );
      case "scam":
        return main.realDocId ? (
          <Link to={`/documents/${main.realDocId}`} className={buttonVariants({ variant: "secondary" })}>
            Compare with your real letter
            <ArrowRight aria-hidden />
          </Link>
        ) : null;
      default:
        return null;
    }
  })();

  const showCalendar = primary?.due_date && main.type !== "calendar" && main.type !== "scam" && main.type !== "decide";
  const showDone = primary && main.type !== "done" && main.type !== "scam" && main.type !== "decide";
  if (!mainEl && !showCalendar && !showDone) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-line bg-surface-2/40 px-5 py-4 sm:px-6">
      {mainEl}
      {showCalendar && primary ? (
        <a href={icsHref(primary)} download={icsFileName(primary)} className={buttonVariants({ variant: "secondary" })}>
          <CalendarPlus aria-hidden />
          Add to calendar
        </a>
      ) : null}
      {showDone && primary ? (
        <Button variant="ghost" icon={Check} onClick={() => actions.markDone(primary)}>
          Mark done
        </Button>
      ) : null}
    </div>
  );
}
