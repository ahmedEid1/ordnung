import { createContext, useContext, useEffect, useId, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { motion } from "motion/react";
import { useNavigate } from "react-router";
import {
  ChartNoAxesGantt,
  Check,
  CircleCheck,
  Copy,
  FileSearch,
  FileText,
  PenLine,
  ShieldAlert,
  Signature,
  TriangleAlert,
  Wallet,
  type LucideIcon,
} from "lucide-react";
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
import { formatIban, formatMoney, urgencyOf, urgencyTone, type UrgencyTone } from "@/lib/format";
import { useTodayISO } from "@/lib/today";
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
  open: { label: "Open letter", icon: FileText },
};

/** The verb button's words: "Open" names where it goes ("Open letter", "Open contract"…). */
export function verbFor(action: Pick<TodayAction, "verb" | "docId" | "contractId">): { label: string; icon: LucideIcon } {
  if (action.verb !== "open" || action.docId) return VERB[action.verb];
  if (action.contractId) return { label: "Open contract", icon: Signature };
  return { label: "Open in Timeline", icon: ChartNoAxesGantt };
}

/**
 * The accessible name of a verb button — the verb, then what it acts on, without saying the verb
 * twice: "Pay: outstanding invoice plus reminder fee" (not "Pay: Pay outstanding…").
 */
export function verbLabel(verb: string, title: string): string {
  const first = verb.split(" ")[0]!;
  const rest = title.match(new RegExp(`^${first}\\s+(.+)$`, "i"))?.[1];
  return `${verb}: ${rest ?? title}`;
}

/** The countdown pill's first words ("Transfer by Tue 29 Sep · tomorrow"). */
const PREFIX: Record<DateRole, string | undefined> = {
  send_by: "Send by",
  pay_by: "Pay by",
  transfer_by: "Transfer by",
  collected: "Collected",
  due: "Due",
  by: "By",
  on: undefined,
  expires: "Expires",
  decide_by: "Decide by",
};

/** Appointments and money coming in are events ("2 days ago"), everything else is due. */
const modeFor = (a: Pick<TodayAction, "dateRole">) => (a.dateRole === "on" ? "event" : "due");
/** Nothing to send for events and direct debits (the bank collects them): never red. */
const capFor = (a: Pick<TodayAction, "dateRole">) => (a.dateRole === "on" || a.dateRole === "collected" ? "warn" : undefined);

/**
 * How urgent an action's date is, on the app's one urgency scale — the countdown pill and the
 * card's top edge both use it, so they always agree.
 */
export function actionTone(action: Pick<TodayAction, "actionDate" | "dateRole">, today: string): UrgencyTone {
  return urgencyTone(urgencyOf(action.actionDate, today, modeFor(action)), { cap: capFor(action) });
}

/** Countdown for an action: "Send by Thu 8 Oct · in 10 days", "Wed 14 Oct, 10:30 · in 16 days". */
export function ActionCountdown({ action, variant = "pill", className }: { action: TodayAction; variant?: "pill" | "text"; className?: string }) {
  return (
    <Countdown
      date={action.actionDate}
      prefix={PREFIX[action.dateRole]}
      showDate
      time={action.time}
      variant={variant}
      mode={modeFor(action)}
      cap={capFor(action)}
      className={className}
    />
  );
}

// ------------------------------------------------------------------------------------------------
// Focus: a card that leaves Top 3 (paid, done) or comes back (Undo)
// ------------------------------------------------------------------------------------------------

const headingId = (key: string) => `top-${key}`;

/**
 * Focus sits on nothing in particular: <body>, <main> (where a closing toast hands it back), a
 * removed node, or a toast (its Undo was just used and it is on its way out).
 */
function focusIsLost(): boolean {
  const a = document.activeElement;
  return !a || a === document.body || a.tagName === "MAIN" || !a.isConnected || Boolean(a.closest("[data-toast]"));
}

/**
 * Once `find` returns an element (checked every frame for up to `ms`), focus it — but only when
 * focus is lost by then, so someone who has moved on is not pulled back.
 */
function focusWhenReady(find: () => HTMLElement | null, ms = 5000): void {
  const until = performance.now() + ms;
  const tick = () => {
    const el = find();
    if (!el) {
      if (performance.now() < until) requestAnimationFrame(tick);
      return;
    }
    if (!focusIsLost()) return;
    if (!el.hasAttribute("tabindex")) el.tabIndex = -1;
    el.focus();
  };
  requestAnimationFrame(tick);
}

interface TopFocus {
  /** This card is about to leave: when it's gone, focus the card now in its place (or the section heading). */
  leaving: (key: string) => void;
  /** This card is coming back (Undo): focus its heading once it's there. */
  returning: (key: string) => void;
}

const TopFocusContext = createContext<TopFocus | null>(null);

function useTopFocus(list: RefObject<HTMLElement | null>): TopFocus {
  return useMemo<TopFocus>(() => {
    const headings = () => Array.from(list.current?.querySelectorAll<HTMLElement>("[data-top-heading]") ?? []);
    return {
      leaving: (key) => {
        const at = Math.max(0, headings().findIndex((h) => h.id === headingId(key)));
        focusWhenReady(() => {
          if (document.getElementById(headingId(key))) return null;
          const rest = headings();
          return rest[Math.min(at, rest.length - 1)] ?? document.getElementById("top3-title");
        });
      },
      returning: (key) => focusWhenReady(() => document.getElementById(headingId(key))),
    };
  }, [list]);
}

// ------------------------------------------------------------------------------------------------
// Pay panel
// ------------------------------------------------------------------------------------------------

/** An amount as a German banking app wants it typed: 94.99 → "94,99", 1234.5 → "1234,50". */
export function amountForTransfer(amount: number): string {
  return amount.toFixed(2).replace(".", ",");
}

/**
 * One transfer detail: its label, the full value (wrapped, never cut — every character of an IBAN
 * or a reference matters) and a copy button, which is icon-only in a narrow panel.
 */
function CopyRow({ label, value, display, copyId, ident }: { label: string; value: string; display?: string; copyId: string; ident?: boolean }) {
  const { copy, copied } = useClipboard();
  const done = copied === copyId;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 py-2">
      <dt className="text-xs font-medium text-muted">{label}</dt>
      <dd className={cn("col-start-1 text-base text-ink [overflow-wrap:anywhere]", ident && "font-ident")}>{display ?? value}</dd>
      <dd className="col-start-2 row-span-2 row-start-1">
        <button
          type="button"
          onClick={() => void copy(value, copyId)}
          className="inline-flex h-7 min-w-7 items-center justify-center gap-1 rounded-md px-2 text-xs font-medium text-accent transition-colors hover:bg-accent-soft"
          aria-label={done ? `${label} copied` : `Copy ${label}`}
        >
          {done ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
          <span aria-hidden className="hidden @[17rem]:inline">
            {done ? "Copied" : "Copy"}
          </span>
        </button>
        <span className="sr-only" aria-live="polite">
          {done ? `${label} copied` : ""}
        </span>
      </dd>
    </div>
  );
}

/** "Pay": the transfer details from the letter (copyable) and "Mark as paid" (with undo). */
function PayPanel({ action, close }: { action: TodayAction; close: () => void }) {
  const doc = useDocument(action.docId ?? undefined);
  const update = useUpdateItem();
  const navigate = useNavigate();
  const focus = useContext(TopFocusContext);
  const pay = doc.data?.document.payment;
  const item = action.item;

  const markPaid = () => {
    if (!item) return;
    update.mutate(
      { id: item.id, patch: { status: "done" } },
      {
        onSuccess: () => {
          close();
          focus?.leaving(action.key);
          toast({
            tone: "success",
            title: "Marked as paid",
            description: item.title,
            undo: async () => {
              await update.mutateAsync({ id: item.id, patch: { status: "open" } });
              focus?.returning(action.key);
            },
          });
        },
      },
    );
  };

  return (
    <div>
      <p className="eyebrow in-sheet:hidden">Pay</p>
      <p className="mt-0.5 text-sm text-muted">{action.title}</p>
      {action.amount ? <Money amount={action.amount} currency={action.currency} className="display mt-2 block text-[28px] font-semibold leading-none" /> : null}

      {action.docId && doc.isPending ? (
        <div className="mt-4 space-y-2" aria-hidden>
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
        </div>
      ) : pay && (pay.iban || pay.reference) ? (
        <dl className="@container mt-3 divide-y divide-line rounded-lg border border-line px-3">
          {pay.payee ? <CopyRow label="Recipient" value={pay.payee} copyId="payee" /> : null}
          {pay.iban ? <CopyRow label="IBAN" value={pay.iban.replace(/\s+/g, "")} display={formatIban(pay.iban)} copyId="iban" ident /> : null}
          {action.amount ? (
            <CopyRow label="Amount" value={amountForTransfer(action.amount)} display={formatMoney(action.amount, { currency: action.currency })} copyId="amount" />
          ) : null}
          {pay.reference ? <CopyRow label="Reference" value={pay.reference} copyId="reference" ident /> : null}
        </dl>
      ) : (
        <p className="mt-3 text-sm leading-relaxed text-muted">{item?.action ?? "The payment details are in the letter."}</p>
      )}

      {pay?.iban_valid === false ? (
        <p className="mt-3 flex gap-2 rounded-lg bg-danger-soft px-3 py-2.5 text-sm leading-5 text-danger-ink">
          <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          This IBAN fails its checksum. Don't pay until you've confirmed the account with the sender.
        </p>
      ) : pay?.iban_valid === true ? (
        <p className="mt-2 flex items-start gap-1.5 text-xs leading-5 text-ok-ink">
          <CircleCheck className="mt-[3px] size-3.5 shrink-0" aria-hidden />
          The IBAN's check digits are valid — that only rules out typos, not fraud.
        </p>
      ) : null}

      {/*
        stays in view at the bottom of the panel, however far its details scroll: it covers the
        panel's bottom padding (a sticky box stops at the padding edge, so it is pulled down by it)
      */}
      <div
        className={cn(
          "sticky -bottom-4 -mb-4 mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-line bg-surface py-3",
          "in-sheet:bottom-[calc(-1.25rem-env(safe-area-inset-bottom))] in-sheet:mb-[calc(-1.25rem-env(safe-area-inset-bottom))] in-sheet:pb-[calc(0.75rem+env(safe-area-inset-bottom))]",
        )}
      >
        {action.docId ? (
          <Button variant="ghost" size="sm" icon={FileText} onClick={() => navigate(actionHref(action))}>
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
  const focus = useContext(TopFocusContext);
  const verb = verbFor(action);
  const label = verbLabel(verb.label, action.title);

  if (action.verb === "pay") {
    return (
      <Popover content={(close) => <PayPanel action={action} close={close} />} className="w-[22rem]" label={label} title="Pay" placement="bottom-start">
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
            onSuccess: () => {
              focus?.leaving(action.key);
              toast({
                tone: "success",
                title: "Marked as done",
                description: item.title,
                undo: async () => {
                  await update.mutateAsync({ id: item.id, patch: { status: "open" } });
                  focus?.returning(action.key);
                },
              });
            },
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

/**
 * The card's reason, up to four lines; a longer one gets "Read more" (measured — only text that is
 * really cut offers it). The full text is always in the page for screen readers.
 */
function Reason({ children }: { children: ReactNode }) {
  const id = useId();
  const ref = useRef<HTMLParagraphElement>(null);
  const [open, setOpen] = useState(false);
  const [cut, setCut] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || open || typeof ResizeObserver === "undefined") return;
    // (the observer reports once right away, then on every resize)
    const ro = new ResizeObserver(() => setCut(el.scrollHeight > el.clientHeight + 1));
    ro.observe(el);
    return () => ro.disconnect();
  }, [open]);
  return (
    <>
      <p ref={ref} id={id} className={cn("mt-2 text-[13.5px] leading-relaxed text-muted", !open && "line-clamp-4")}>
        {children}
      </p>
      {cut || open ? (
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen(!open)}
          className="-mx-1 mt-0.5 inline-flex min-h-6 items-center self-start rounded-md px-1 text-sm font-semibold text-accent underline-offset-2 hover:underline"
        >
          {open ? "Show less" : "Read more"}
        </button>
      ) : null}
    </>
  );
}

function ActionCard({ action, index, party, today }: { action: TodayAction; index: number; party: Party | undefined; today: string }) {
  const receipt = action.item ? receiptForItem(action.item) : action.contract ? receiptForContract(action.contract) : null;
  const tone = actionTone(action, today);
  return (
    <motion.li variants={fadeUp} className="@container flex">
      <article
        aria-labelledby={headingId(action.key)}
        data-urgency={tone.level}
        className={cn(
          "card relative flex w-full flex-col overflow-hidden p-4 sm:p-5",
          // the first card leads: an accent edge that shows in dark mode too, where shadows don't
          index === 0 && "border-accent/45 shadow-[var(--shadow-pop)] dark:border-accent/55",
        )}
      >
        {/* urgency edge — the same scale and colour as the countdown pill */}
        <span aria-hidden data-part="stripe" className={cn("absolute inset-x-0 top-0 h-[3px]", tone.stripe)} />
        {/* the rank, in the corner (the list is an <ol>, so it is announced already) */}
        <span
          aria-hidden
          data-part="rank"
          className="display absolute right-4 top-4 flex h-7 items-center text-[22px] font-semibold leading-none text-faint sm:right-5 sm:top-5"
        >
          {index + 1}
        </span>
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex min-h-7 flex-wrap items-center gap-2 pr-6">
            {/* a narrow card keeps its first line for the date */}
            <span className="contents @max-[21rem]:hidden">
              {action.kind === "contract" ? (
                <KindIcon category={action.contract?.category ?? "other"} size="sm" />
              ) : (
                <KindIcon kind={action.kind} direction={action.item?.direction} size="sm" />
              )}
            </span>
            {/* one line as a pill; a long one ("Transfer by Tue 22 Sep · 6 days overdue") wraps in a narrow card */}
            <ActionCountdown action={action} className="max-w-full flex-wrap whitespace-normal rounded-[11px]" />
          </div>

          <h3 id={headingId(action.key)} data-top-heading="" className="mt-3.5 text-[16px] font-semibold leading-snug text-ink [overflow-wrap:anywhere]">
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
            <Reason>
              <LetterText text={action.reason} />
            </Reason>
          ) : null}
          {party ? (
            <div className="mt-auto pt-4">
              <PartyChip party={party} className="max-w-full" />
            </div>
          ) : null}
        </div>

        <div className="mt-3.5 flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-t border-line pt-3.5">
          <VerbButton action={action} variant={index === 0 ? "primary" : "secondary"} />
          <WhyThisDate receipt={receipt} context={action.title} />
        </div>
      </article>
    </motion.li>
  );
}

/**
 * "Top 3 this week": the three most urgent actions, each with a countdown, a reason, the
 * person/organisation, one verb button and "Why this date?". Shows "All clear until …" when
 * nothing is due. When a card leaves (paid, done) focus moves to the card now in its place.
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
  const section = useRef<HTMLElement>(null);
  const focus = useTopFocus(section);
  // the countdowns count from the app's today; so does the urgency edge
  const appToday = useTodayISO();
  return (
    <TopFocusContext.Provider value={focus}>
      <section ref={section} aria-labelledby="top3-title" className="@container">
        <SectionHeader id="top3-title" title="Top 3 this week" description={actions.length ? "The things that matter most right now — one step each." : undefined} />
        {actions.length ? (
          <motion.ol variants={stagger} initial="hidden" animate="show" className="grid grid-cols-1 gap-3 sm:gap-4 @4xl:grid-cols-3">
            {actions.map((a, i) => (
              <ActionCard key={a.key} action={a} index={i} party={a.partyId ? partyById.get(a.partyId) : undefined} today={appToday} />
            ))}
          </motion.ol>
        ) : (
          <EmptyState
            illustration="clear"
            size="sm"
            headingLevel={3}
            title={allClearTitle(next?.actionDate, today)}
            description={
              next
                ? `Nothing needs you this week. Next up: ${next.title}.`
                : "Nothing needs you right now. New letters show up here as soon as they are read."
            }
          />
        )}
      </section>
    </TopFocusContext.Provider>
  );
}
