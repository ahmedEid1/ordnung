/**
 * One row of a weekly-session step: what it is, from whom, the day that matters, the amount, the
 * secretary's note and — where the person can act right here — Pay (the Pay panel) or Confirm.
 *
 * The day reads as Today words it (`ordnung/secretary/week.py`, "The day on a row"): "Transfer by …",
 * "Send by …", an appointment on its day, "Expires …", money coming in "Expected …" — and "Act today"
 * with the due date beside it once the day to post or transfer has passed.
 */
import { Link } from "react-router";
import { Check, CircleAlert, CircleCheck, Landmark, TriangleAlert, type LucideIcon } from "lucide-react";
import { useMemo } from "react";
import { useConfirmItem } from "@/api/hooks";
import type { WeekEntry } from "@/api/types";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { KindIcon, type KindSource } from "@/components/ui/KindBadge";
import { Money } from "@/components/ui/Money";
import { toast } from "@/components/ui/Toast";
import { focusAfterLeaving, focusWhenReady } from "@/features/today/focus";
import { actionFromItem } from "@/features/today/selection";
import { PayFocusProvider, PayPopover, type TopFocus } from "@/features/today/TopThree";
import { glueText } from "@/lib/format";
import { NBSP } from "@/lib/glue";
import { useFormatDate, useTodayISO } from "@/lib/today";
import { cn } from "@/lib/utils";
import type { DocumentKind, ItemKind } from "@/api/types";
import { entryHref, type StepId } from "./steps";

type Role = NonNullable<WeekEntry["date_role"]>;

/** A note is read in ink (a four-line note in red is a wall of alarm); its tone is a mark before it, and
 * the day on the row keeps its own colour. */
const NOTE_MARK: Record<WeekEntry["tone"], { icon: LucideIcon; className: string } | null> = {
  neutral: null,
  ok: { icon: CircleCheck, className: "text-ok-ink" },
  warn: { icon: CircleAlert, className: "text-warn-ink" },
  danger: { icon: TriangleAlert, className: "text-danger-ink" },
};

/** Due-like days get a countdown ("Transfer by Tue 29 Sep · tomorrow"), as Today's cards say them. */
const COUNTDOWN_PREFIX: Partial<Record<Role, string>> = {
  due: "Due",
  by: "By",
  send_by: "Send by",
  transfer_by: "Transfer by",
  pay_by: "Pay by",
  collected: "Collected",
  expected: "Expected",
  decide_by: "Decide by",
  reply_by: "Reply expected by",
  promised_by: "Promised by",
  expires: "Expires",
  at_appointment: "Pay at the appointment",
};
/** Events: past means "2 days ago", never "overdue", and never red. */
const EVENT_ROLES = new Set<Role>(["on", "collected", "expires", "at_appointment"]);
/** What someone else owes the person (money coming in, a reply, a promise made on the phone): nothing to
 * do until the day passes, so an event — and "N days overdue" in red once *Waiting for* says it is late. */
const AWAITED_ROLES = new Set<Role>(["expected", "reply_by", "promised_by"]);

/** Whether a row's day reads as an event (see `EVENT_ROLES`, `AWAITED_ROLES`). */
export function isEventDay(entry: Pick<WeekEntry, "date_role" | "overdue">): boolean {
  const role = entry.date_role;
  return role !== null && (EVENT_ROLES.has(role) || (AWAITED_ROLES.has(role) && !entry.overdue));
}
/** Things that happened: a plain date. */
const EVENT_PREFIX: Partial<Record<Role, string>> = {
  added: "Added",
  sent: "Sent",
  done: "Done",
};

/** The DOM id of a row's link (focus moves to the next one when a row leaves the step). */
export const rowLinkId = (key: string) => `week-row-${key}`;

/** A row leaves its step (confirmed, paid): the focus goes on to the row now in its place, else the step's heading. */
function focusAfterRow(step: StepId, key: string): void {
  focusAfterLeaving(
    () => Array.from(document.querySelectorAll<HTMLElement>(`[data-week-row="${step}"]`)),
    rowLinkId(key),
    `week-step-${step}`,
  );
}

function kindSource(entry: WeekEntry): KindSource {
  if (entry.ref.type === "document") return { docKind: entry.kind as DocumentKind };
  if (entry.ref.type === "contract") return { kind: "contract" };
  if (entry.ref.type === "draft") return { kind: "draft" };
  // a promise made on the phone: something to follow up, like a task
  if (entry.ref.type === "call") return { kind: "task" };
  return { kind: entry.kind as ItemKind, direction: entry.item?.direction ?? null };
}

/** "· due Wed 14 Oct": the due date beside an earlier day to act; the dot stays on the line before. */
function DueBeside({ date }: { date: string }) {
  const formatDate = useFormatDate();
  return (
    <>
      <span aria-hidden>{`${NBSP}·`}</span> <span className="whitespace-nowrap text-muted">due {formatDate(date)}</span>
    </>
  );
}

function WhenLine({ entry }: { entry: WeekEntry }) {
  const formatDate = useFormatDate();
  const role = entry.date_role;
  const time = role === "on" ? (entry.item?.due_time ?? null) : null;
  let when = null;
  if (role === "act_today") {
    // no countdown to the due date: "in 16 days" would argue with "Act today"
    when = entry.due_date ? (
      <span className="text-[13px]">
        <span className="font-medium text-danger-ink">Act today</span>{" "}
        <span className="text-muted">
          — due{" "}
          <time dateTime={entry.due_date} className="whitespace-nowrap">
            {formatDate(entry.due_date)}
          </time>
        </span>
      </span>
    ) : (
      <span className="font-medium text-danger-ink">Act today</span>
    );
  } else if (entry.date && role && (COUNTDOWN_PREFIX[role] !== undefined || role === "on")) {
    const event = isEventDay(entry);
    when = (
      <>
        <Countdown
          date={entry.date}
          prefix={COUNTDOWN_PREFIX[role]}
          showDate
          time={time}
          mode={event ? "event" : "due"}
          cap={event ? "warn" : undefined}
          className="text-[13px]"
        />
        {entry.due_date && entry.due_date !== entry.date ? <DueBeside date={entry.due_date} /> : null}
      </>
    );
  } else if (entry.date) {
    const event = role ? EVENT_PREFIX[role] : undefined;
    when = (
      <span className="text-muted">
        {event ? `${event} ` : ""}
        <span className="whitespace-nowrap">{formatDate(entry.date)}</span>
      </span>
    );
  }
  return (
    <>
      {entry.party_name ? <p className="text-[13px] leading-5 text-muted [overflow-wrap:anywhere]">{glueText(entry.party_name)}</p> : null}
      {when ? <p className="text-[13px] leading-5">{when}</p> : null}
    </>
  );
}

/** A transfer to make here (not a direct debit the sender collects, nor a fee paid at an appointment). */
export function paysHere(entry: Pick<WeekEntry, "ref" | "date_role">): boolean {
  return entry.ref.type === "item" && entry.date_role !== "collected" && entry.date_role !== "at_appointment";
}

function PayButton({ entry }: { entry: WeekEntry }) {
  const today = useTodayISO();
  const action = entry.item ? actionFromItem(entry.item, { today }) : null;
  // "Mark as paid" takes the row off the step: the focus goes on as after "Looks right", and back on Undo
  const focus = useMemo<TopFocus>(
    () => ({
      leaving: () => focusAfterRow("pay", entry.key),
      returning: () => focusWhenReady(() => document.getElementById(rowLinkId(entry.key))),
    }),
    [entry.key],
  );
  if (!action) return null;
  return (
    <PayFocusProvider value={focus}>
      <PayPopover action={action}>
        <Button size="sm" variant="secondary" icon={Landmark} aria-label={`Pay: ${entry.title}`}>
          Pay
        </Button>
      </PayPopover>
    </PayFocusProvider>
  );
}

function ConfirmButton({ entry, step }: { entry: WeekEntry; step: StepId }) {
  const confirm = useConfirmItem();
  return (
    <Button
      size="sm"
      variant="secondary"
      icon={Check}
      loading={confirm.isPending}
      // the accessible name starts with the visible words, WCAG 2.5.3; it vouches for the date only — a
      // payment's amount is compared in its Pay panel (ADR 0012, point 3)
      aria-label={`The date looks right: ${entry.title}`}
      onClick={() =>
        confirm.mutate(entry.ref.id, {
          onSuccess: () => {
            toast({ tone: "success", title: "Date confirmed", description: `${entry.title} — its date is marked as checked by you.` });
            focusAfterRow(step, entry.key);
          },
        })
      }
    >
      The date looks right
    </Button>
  );
}

/**
 * Holds a Pay button's room on a row of *Pay this week* that has none (a direct debit, a fee paid at the
 * appointment), so every amount ends at the same place — only while the rows sit beside their amounts
 * (from a 28rem row); a phone's rows stack, and nothing is held there.
 */
function PaySlot() {
  return (
    <span aria-hidden data-pay-slot className={cn(buttonVariants({ size: "sm", variant: "secondary" }), "invisible hidden @[28rem]:inline-flex")}>
      <Landmark />
      Pay
    </span>
  );
}

/** Whether "The date looks right" has a date to vouch for (an undated to-do has none: `week.py`). */
export const hasDateToConfirm = (entry: Pick<WeekEntry, "date" | "due_date">): boolean => Boolean(entry.date || entry.due_date);

export function WeekEntryRow({ entry, step }: { entry: WeekEntry; step: StepId }) {
  const paying = step === "pay";
  const pay = paying && paysHere(entry);
  const confirm = step === "check" && entry.ref.type === "item" && hasDateToConfirm(entry);
  const action = pay ? <PayButton entry={entry} /> : confirm ? <ConfirmButton entry={entry} step={step} /> : paying ? <PaySlot /> : null;
  const mark = NOTE_MARK[entry.tone];
  return (
    <div className="@container flex items-start gap-3 py-3">
      <KindIcon {...kindSource(entry)} size="sm" className="mt-0.5" />
      {/* Pay this week: every row beside its amount from a 28rem row (the amounts in one column), else stacked */}
      <div className={cn("flex min-w-0 flex-1 flex-wrap items-start gap-x-4 gap-y-2", paying && "@[28rem]:flex-nowrap")}>
        <div className={cn("min-w-0 flex-1", paying ? "basis-full @[28rem]:basis-0" : "basis-[14rem]")}>
          <Link
            id={rowLinkId(entry.key)}
            data-week-row={step}
            to={entryHref(entry)}
            className="-my-0.5 inline-block rounded py-0.5 text-[14.5px] font-medium leading-5 text-ink outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent [overflow-wrap:anywhere]"
          >
            {glueText(entry.title)}
          </Link>
          <WhenLine entry={entry} />
          {entry.note ? (
            <p data-tone={entry.tone} className="mt-0.5 flex gap-1.5 text-[13px] leading-5 text-ink/80">
              {mark ? <mark.icon aria-hidden className={cn("mt-[3px] size-3.5 shrink-0", mark.className)} /> : null}
              <span className="min-w-0">{glueText(entry.note)}</span>
            </p>
          ) : null}
        </div>
        {entry.amount !== null || action ? (
          // on a phone the button goes under the amount rather than past the card
          <div className={cn("flex min-w-0 max-w-full flex-wrap items-center gap-x-3 gap-y-2", paying && "@[28rem]:shrink-0")}>
            {entry.amount !== null ? (
              <Money
                amount={entry.amount}
                currency={entry.currency}
                tone={entry.date_role === "collected" || entry.date_role === "at_appointment" ? "muted" : "default"}
                className="text-[15px] font-semibold tabular-nums"
              />
            ) : null}
            {action}
          </div>
        ) : null}
      </div>
    </div>
  );
}
