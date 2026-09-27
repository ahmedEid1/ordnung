/**
 * One row of a weekly-session step: what it is, from whom, the day that matters, the amount, the
 * secretary's note and — where the person can act right here — Pay (the Pay panel) or Confirm.
 */
import { Link } from "react-router";
import { Check, Landmark } from "lucide-react";
import { useConfirmItem } from "@/api/hooks";
import type { WeekEntry } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { KindIcon, type KindSource } from "@/components/ui/KindBadge";
import { Money } from "@/components/ui/Money";
import { toast } from "@/components/ui/Toast";
import { actionFromItem } from "@/features/today/selection";
import { PayPopover } from "@/features/today/TopThree";
import { useFormatDate, useTodayISO } from "@/lib/today";
import { cn } from "@/lib/utils";
import type { DocumentKind, ItemKind } from "@/api/types";
import { entryHref, type StepId } from "./steps";

const NOTE_TONE: Record<WeekEntry["tone"], string> = {
  neutral: "text-ink/80",
  ok: "text-ok-ink",
  warn: "text-warn-ink",
  danger: "text-danger-ink",
};

/** Due-like days get a countdown ("pay by Tue 29 Sep · tomorrow"); past events a plain date. */
const COUNTDOWN_PREFIX: Partial<Record<NonNullable<WeekEntry["date_role"]>, string>> = {
  due: "due",
  send_by: "send by",
  pay_by: "pay by",
  collected: "collected",
  decide_by: "decide by",
  reply_by: "reply expected by",
};
const EVENT_PREFIX: Partial<Record<NonNullable<WeekEntry["date_role"]>, string>> = {
  added: "Added",
  sent: "Sent",
  done: "Done",
};

function kindSource(entry: WeekEntry): KindSource {
  if (entry.ref.type === "document") return { docKind: entry.kind as DocumentKind };
  if (entry.ref.type === "contract") return { kind: "contract" };
  if (entry.ref.type === "draft") return { kind: "draft" };
  return { kind: entry.kind as ItemKind };
}

function WhenLine({ entry }: { entry: WeekEntry }) {
  const formatDate = useFormatDate();
  const role = entry.date_role;
  const due = role ? COUNTDOWN_PREFIX[role] : undefined;
  const event = role ? EVENT_PREFIX[role] : undefined;
  return (
    <>
      {entry.party_name ? <p className="text-[13px] leading-5 text-muted [overflow-wrap:anywhere]">{entry.party_name}</p> : null}
      {entry.date && due ? (
        <p className="text-[13px] leading-5">
          <Countdown date={entry.date} prefix={due.charAt(0).toUpperCase() + due.slice(1)} mode={role === "collected" ? "event" : "due"} className="text-[13px]" />
        </p>
      ) : entry.date ? (
        <p className="text-[13px] leading-5 text-muted">
          {event ? `${event} ` : ""}
          {formatDate(entry.date)}
        </p>
      ) : null}
    </>
  );
}

function PayButton({ entry }: { entry: WeekEntry }) {
  const today = useTodayISO();
  const action = entry.item ? actionFromItem(entry.item, { today }) : null;
  if (!action) return null;
  return (
    <PayPopover action={action}>
      <Button size="sm" variant="secondary" icon={Landmark} aria-label={`Pay: ${entry.title}`}>
        Pay
      </Button>
    </PayPopover>
  );
}

function ConfirmButton({ entry }: { entry: WeekEntry }) {
  const confirm = useConfirmItem();
  return (
    <Button
      size="sm"
      variant="secondary"
      icon={Check}
      loading={confirm.isPending}
      aria-label={`Confirm: ${entry.title}`}
      onClick={() =>
        confirm.mutate(entry.ref.id, {
          onSuccess: () => toast({ tone: "success", title: "Confirmed", description: `${entry.title} — marked as checked by you.` }),
        })
      }
    >
      Looks right
    </Button>
  );
}

export function WeekEntryRow({ entry, step }: { entry: WeekEntry; step: StepId }) {
  const pay = step === "pay" && entry.ref.type === "item" && entry.date_role !== "collected";
  const confirm = step === "check" && entry.ref.type === "item";
  const action = pay ? <PayButton entry={entry} /> : confirm ? <ConfirmButton entry={entry} /> : null;
  return (
    <div className="@container flex items-start gap-3 py-3">
      <KindIcon {...kindSource(entry)} size="sm" className="mt-0.5" />
      <div className="flex min-w-0 flex-1 flex-wrap items-start gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1 basis-[14rem]">
          <Link
            to={entryHref(entry)}
            className="-my-0.5 inline-block rounded py-0.5 text-[14.5px] font-medium leading-5 text-ink outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent [overflow-wrap:anywhere]"
          >
            {entry.title}
          </Link>
          <WhenLine entry={entry} />
          {entry.note ? <p className={cn("mt-0.5 text-[13px] leading-5", NOTE_TONE[entry.tone])}>{entry.note}</p> : null}
        </div>
        {entry.amount !== null || action ? (
          <div className="flex shrink-0 items-center gap-3">
            {entry.amount !== null ? (
              <Money amount={entry.amount} currency={entry.currency} tone={entry.date_role === "collected" ? "muted" : "default"} className="text-[15px] font-semibold tabular-nums" />
            ) : null}
            {action}
          </div>
        ) : null}
      </div>
    </div>
  );
}
