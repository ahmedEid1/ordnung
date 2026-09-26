import { motion } from "motion/react";
import { useNavigate } from "react-router";
import { Check, CircleCheck, Copy, ExternalLink, FileSearch, FolderOpen, PenLine, TriangleAlert, Wallet, type LucideIcon } from "lucide-react";
import { useDocument, useUpdateItem } from "@/api/hooks";
import type { Party } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { Button, type ButtonVariant } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { EmptyState } from "@/components/ui/EmptyState";
import { KindIcon } from "@/components/ui/KindBadge";
import { Money } from "@/components/ui/Money";
import { PartyChip } from "@/components/ui/PartyChip";
import { Popover } from "@/components/ui/Popover";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { formatIban, formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useClipboard } from "./clipboard";
import { fadeUp, stagger } from "./motion";
import { allClearTitle, composerHref, type ActionVerb, type DateRole, type TodayAction } from "./selection";
import { actionHref } from "./useTodayData";
import { receiptForContract, receiptForItem } from "./receipt";
import { WhyThisDate } from "./WhyThisDate";
import { LetterText } from "@/components/ui/LetterText";

const VERB: Record<ActionVerb, { label: string; icon: LucideIcon }> = {
  pay: { label: "Pay", icon: Wallet },
  draft: { label: "Draft letter", icon: PenLine },
  done: { label: "Mark done", icon: Check },
  check: { label: "Check", icon: FileSearch },
  open: { label: "Open", icon: FolderOpen },
};

const PREFIX: Record<DateRole, string | undefined> = {
  send_by: "send by",
  pay_by: "pay by",
  transfer_by: "transfer by",
  collected: "collected",
  due: "due",
  by: "by",
  on: undefined,
  expires: "expires",
  decide_by: "decide by",
};

/** Countdown for an action: "send by Thu 8 Oct · in 10 days", "Wed 14 Oct, 10:30 · in 16 days". */
export function ActionCountdown({ action, variant = "pill", className }: { action: TodayAction; variant?: "pill" | "text"; className?: string }) {
  return (
    <Countdown
      date={action.actionDate}
      prefix={PREFIX[action.dateRole]}
      showDate
      time={action.time}
      variant={variant}
      mode={action.dateRole === "on" ? "event" : "due"}
      className={className}
    />
  );
}

// ------------------------------------------------------------------------------------------------
// Pay panel
// ------------------------------------------------------------------------------------------------

function CopyRow({ label, value, display, copyId, mono }: { label: string; value: string; display?: string; copyId: string; mono?: boolean }) {
  const { copy, copied } = useClipboard();
  const done = copied === copyId;
  return (
    <div className="flex items-center gap-3 py-2">
      <div className="min-w-0 flex-1">
        <dt className="text-[11.5px] font-medium text-muted">{label}</dt>
        <dd className={cn("truncate text-[14px] text-ink", mono && "font-ident")}>{display ?? value}</dd>
      </div>
      <button
        type="button"
        onClick={() => void copy(value, copyId)}
        className="inline-flex h-7 shrink-0 items-center gap-1 rounded-md px-2 text-[12px] font-medium text-accent transition-colors hover:bg-accent-soft"
        aria-label={done ? `${label} copied` : `Copy ${label}`}
      >
        {done ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
        <span aria-hidden>{done ? "Copied" : "Copy"}</span>
      </button>
      <span className="sr-only" aria-live="polite">
        {done ? `${label} copied` : ""}
      </span>
    </div>
  );
}

/** "Pay": the transfer details from the letter (copyable) and "Mark as paid" (with undo). */
function PayPanel({ action, close }: { action: TodayAction; close: () => void }) {
  const doc = useDocument(action.docId ?? undefined);
  const update = useUpdateItem();
  const navigate = useNavigate();
  const pay = doc.data?.document.payment;
  const item = action.item;

  const markPaid = () => {
    if (!item) return;
    update.mutate(
      { id: item.id, patch: { status: "done" } },
      {
        onSuccess: () => {
          close();
          toast({
            tone: "success",
            title: "Marked as paid",
            description: item.title,
            undo: async () => {
              await update.mutateAsync({ id: item.id, patch: { status: "open" } });
            },
          });
        },
      },
    );
  };

  return (
    <div>
      <p className="text-[12px] font-semibold uppercase tracking-[0.07em] text-muted">Pay</p>
      <p className="mt-0.5 text-[13px] text-muted">{action.title}</p>
      {action.amount ? <Money amount={action.amount} currency={action.currency} className="display mt-2 block text-[28px] font-semibold leading-none" /> : null}

      {action.docId && doc.isPending ? (
        <div className="mt-4 space-y-2" aria-hidden>
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
        </div>
      ) : pay && (pay.iban || pay.reference) ? (
        <dl className="mt-3 divide-y divide-line rounded-lg border border-line px-3">
          {pay.payee ? <CopyRow label="Recipient" value={pay.payee} copyId="payee" /> : null}
          {pay.iban ? <CopyRow label="IBAN" value={pay.iban.replace(/\s+/g, "")} display={formatIban(pay.iban)} copyId="iban" mono /> : null}
          {action.amount ? <CopyRow label="Amount" value={formatMoney(action.amount, { currency: action.currency }).replace(/\s*€/, "").trim()} display={formatMoney(action.amount, { currency: action.currency })} copyId="amount" /> : null}
          {pay.reference ? <CopyRow label="Reference" value={pay.reference} copyId="reference" mono /> : null}
        </dl>
      ) : (
        <p className="mt-3 text-[13px] leading-relaxed text-muted">{item?.action ?? "The payment details are in the letter."}</p>
      )}

      {pay?.iban_valid === true ? (
        <p className="mt-2 flex items-center gap-1.5 text-[12px] text-ok-ink">
          <CircleCheck className="size-3.5" aria-hidden /> IBAN checksum is valid. No warning does not mean it is safe.
        </p>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        {action.docId ? (
          <Button variant="ghost" size="sm" icon={ExternalLink} onClick={() => navigate(actionHref(action))}>
            Open letter
          </Button>
        ) : (
          <span />
        )}
        {item ? (
          <Button variant="primary" size="sm" icon={Check} onClick={markPaid} loading={update.isPending}>
            Mark as paid
          </Button>
        ) : null}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
// Verb button
// ------------------------------------------------------------------------------------------------

function VerbButton({ action, variant }: { action: TodayAction; variant: ButtonVariant }) {
  const navigate = useNavigate();
  const update = useUpdateItem();
  const verb = VERB[action.verb];
  const label = `${verb.label}: ${action.title}`;

  if (action.verb === "pay") {
    return (
      <Popover content={(close) => <PayPanel action={action} close={close} />} className="w-[22rem]" label={label} placement="bottom-start">
        <Button variant={variant} size="sm" icon={verb.icon} aria-label={label}>
          {verb.label}
        </Button>
      </Popover>
    );
  }

  const onClick = () => {
    switch (action.verb) {
      case "draft":
        navigate(composerHref(action.draftKind ?? "general_reply", { contractId: action.contractId, docId: action.contractId ? null : action.docId, partyId: null }));
        return;
      case "done": {
        const item = action.item;
        if (!item) return;
        update.mutate(
          { id: item.id, patch: { status: "done" } },
          {
            onSuccess: () =>
              toast({
                tone: "success",
                title: "Marked as done",
                description: item.title,
                undo: async () => {
                  await update.mutateAsync({ id: item.id, patch: { status: "open" } });
                },
              }),
          },
        );
        return;
      }
      default:
        navigate(actionHref(action));
    }
  };

  return (
    <Button variant={variant} size="sm" icon={verb.icon} onClick={onClick} loading={update.isPending} aria-label={label}>
      {verb.label}
    </Button>
  );
}

// ------------------------------------------------------------------------------------------------
// Card
// ------------------------------------------------------------------------------------------------

function ActionCard({ action, index, party }: { action: TodayAction; index: number; party: Party | undefined }) {
  const receipt = action.item ? receiptForItem(action.item) : action.contract ? receiptForContract(action.contract) : null;
  const urgent = action.daysLeft <= 1;
  return (
    <motion.li variants={fadeUp} className="@container flex">
      <article
        aria-labelledby={`top-${action.key}`}
        className={cn(
          "card group relative flex w-full flex-col overflow-hidden p-4 sm:p-5 @xl:flex-row @xl:gap-6",
          index === 0 && "border-line-strong/80 shadow-[var(--shadow-pop)]",
        )}
      >
        {/* urgency edge */}
        <span
          aria-hidden
          className={cn(
            "absolute inset-x-0 top-0 h-[3px]",
            action.daysLeft < 0 || urgent ? "bg-danger" : action.daysLeft <= 3 ? "bg-k-payment" : action.daysLeft <= 7 ? "bg-warn/70" : "bg-line-strong",
          )}
        />
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center gap-2">
            {action.kind === "contract" ? <KindIcon category={action.contract?.category ?? "other"} size="sm" /> : <KindIcon kind={action.kind} size="sm" />}
            <ActionCountdown action={action} />
            <span aria-hidden className="display ml-auto pl-2 text-[22px] font-semibold leading-none text-line-strong @xl:hidden">
              {index + 1}
            </span>
          </div>

          <h3 id={`top-${action.key}`} className="mt-3.5 text-[16px] font-semibold leading-snug text-ink">
            {action.title}
          </h3>
          {action.amount ? (
            <Money amount={action.amount} currency={action.currency} className="display mt-1 text-[22px] font-semibold leading-tight" />
          ) : null}
          {action.needsCheck ? (
            <Badge tone="warn" icon={TriangleAlert} className="mt-2 self-start">
              Please check
            </Badge>
          ) : null}
          {action.reason ? (
            <p className="mt-2 line-clamp-2 text-[13.5px] leading-relaxed text-muted">
              <LetterText text={action.reason} />
            </p>
          ) : null}
          {party ? (
            <div className="mt-auto pt-4">
              <PartyChip party={party} className="max-w-full" />
            </div>
          ) : null}
        </div>

        <div className="mt-3.5 flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-t border-line pt-3.5 @xl:mt-0 @xl:w-40 @xl:shrink-0 @xl:flex-col @xl:flex-nowrap @xl:items-start @xl:justify-center @xl:border-l @xl:border-t-0 @xl:pl-6 @xl:pt-0">
          <span aria-hidden className="display hidden text-[26px] font-semibold leading-none text-line-strong @xl:mb-auto @xl:block">
            {index + 1}
          </span>
          <VerbButton action={action} variant={index === 0 ? "primary" : "secondary"} />
          <WhyThisDate receipt={receipt} context={action.title} />
        </div>
      </article>
    </motion.li>
  );
}

/**
 * "Top 3 this week": the three most urgent actions, each with a countdown, a one-line reason, the
 * person/organisation, one verb button and "Why this date?". Shows "All clear until …" when
 * nothing is due.
 */
export function TopThree({
  actions,
  next,
  partyById,
  today,
}: {
  actions: TodayAction[];
  next: TodayAction | undefined;
  partyById: Map<string, Party>;
  today: string;
}) {
  return (
    <section aria-labelledby="top3-title" className="@container">
      <SectionHeader id="top3-title" title="Top 3 this week" description={actions.length ? "The things that matter most right now — one step each." : undefined} />
      {actions.length ? (
        <motion.ol variants={stagger} initial="hidden" animate="show" className="grid grid-cols-1 gap-3 sm:gap-4 @4xl:grid-cols-3">
          {actions.map((a, i) => (
            <ActionCard key={a.key} action={a} index={i} party={a.partyId ? partyById.get(a.partyId) : undefined} />
          ))}
        </motion.ol>
      ) : (
        <EmptyState
          illustration="clear"
          size="sm"
          title={allClearTitle(next?.actionDate, today)}
          description={
            next
              ? `Nothing needs you this week. Next up: ${next.title}.`
              : "Nothing needs you right now. New letters show up here as soon as they are read."
          }
        />
      )}
    </section>
  );
}
