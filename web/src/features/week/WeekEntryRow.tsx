/**
 * One row of a weekly-session step: what it is, from whom, the day that matters, the amount, the
 * secretary's note and — where the person can act right here — Pay (the Pay panel) or Confirm.
 *
 * The day reads as Today words it (`ordnung/secretary/week.py`, "The day on a row"): "Transfer by …",
 * "Send by …", an appointment on its day, "Expires …", money coming in "Expected …" — and "Act today"
 * with the due date beside it once the day to post or transfer has passed.
 */
import { Link } from "react-router";
import { Check, Landmark } from "lucide-react";
import { useMemo } from "react";
import { useConfirmItem } from "@/api/hooks";
import type { WeekEntry } from "@/api/types";
import { Button } from "@/components/ui/Button";
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

const NOTE_TONE: Record<WeekEntry["tone"], string> = {
  neutral: "text-ink/80",
  ok: "text-ok-ink",
  warn: "text-warn-ink",
  danger: "text-danger-ink",
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
/** Events: past means "2 days ago", never "overdue", and never red (money coming in is one). */
const EVENT_ROLES = new Set<Role>(["on", "collected", "expires", "at_appointment", "expected"]);
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
    const event = EVENT_ROLES.has(role);
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

export function WeekEntryRow({ entry, step }: { entry: WeekEntry; step: StepId }) {
  const pay = step === "pay" && paysHere(entry);
  const confirm = step === "check" && entry.ref.type === "item";
  const action = pay ? <PayButton entry={entry} /> : confirm ? <ConfirmButton entry={entry} step={step} /> : null;
  return (
    <div className="@container flex items-start gap-3 py-3">
      <KindIcon {...kindSource(entry)} size="sm" className="mt-0.5" />
      <div className="flex min-w-0 flex-1 flex-wrap items-start gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1 basis-[14rem]">
          <Link
            id={rowLinkId(entry.key)}
            data-week-row={step}
            to={entryHref(entry)}
            className="-my-0.5 inline-block rounded py-0.5 text-[14.5px] font-medium leading-5 text-ink outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent [overflow-wrap:anywhere]"
          >
            {glueText(entry.title)}
          </Link>
          <WhenLine entry={entry} />
          {entry.note ? <p className={cn("mt-0.5 text-[13px] leading-5", NOTE_TONE[entry.tone])}>{glueText(entry.note)}</p> : null}
        </div>
        {entry.amount !== null || action ? (
          // on a phone the button goes under the amount rather than past the card
          <div className="flex min-w-0 max-w-full flex-wrap items-center gap-x-3 gap-y-2">
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
