import { useMemo } from "react";
import { Link } from "react-router";
import { CircleCheck, HandCoins, PenLine } from "lucide-react";
import { useParties, useUpdateCall, useUpdateItem } from "@/api/hooks";
import type { Party, WaitingEntry } from "@/api/types";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { Money } from "@/components/ui/Money";
import { PartyChip } from "@/components/ui/PartyChip";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { toast } from "@/components/ui/Toast";
import { TONES, WAITING_SOURCE_COPY, WAITING_STATUS_COPY, copyFor } from "@/lib/copy";
import { cn } from "@/lib/utils";
import { WAITING_GROUPS, groupWaiting } from "./model";

function Actions({ entry }: { entry: WaitingEntry }) {
  const item = useUpdateItem();
  const call = useUpdateCall();
  // The row leaves the list once settled, so the toast follows the promise (a `mutate` callback
  // would be dropped with the unmounted row); errors are shown by the mutation's own toast.
  const settle = (what: string) => {
    if (!entry.followup_item_id) return;
    const id = entry.followup_item_id;
    item.mutateAsync({ id, patch: { status: "done" } }).then(
      () => toast.success(what, { description: entry.title, undo: () => item.mutate({ id, patch: { status: "open" } }) }),
      () => undefined,
    );
  };
  const kept = () =>
    call.mutateAsync({ id: entry.ref.id, kept: true }).then(
      () => toast.success("Marked as kept", { description: entry.title, undo: () => call.mutate({ id: entry.ref.id, kept: false }) }),
      () => undefined,
    );
  const link = (to: string, label: string, icon?: typeof PenLine) => {
    const Icon = icon;
    return (
      <Link to={to} className={buttonVariants({ variant: "secondary", size: "sm" })}>
        {Icon ? <Icon aria-hidden /> : null}
        {label}
      </Link>
    );
  };
  return (
    <div className="mt-2.5 flex flex-wrap gap-2">
      {entry.answered_by ? link(`/documents/${entry.answered_by.id}`, "Read their letter") : null}
      {entry.source === "letter" ? link(`/letters/${entry.ref.id}`, "Open your letter") : null}
      {entry.source === "money" && entry.doc_id ? link(`/documents/${entry.doc_id}`, "Open the letter") : null}
      {entry.source === "letter" && entry.status === "answered" && entry.followup_item_id ? (
        <Button size="sm" variant="soft" icon={CircleCheck} loading={item.isPending} onClick={() => settle("Follow-up closed")}>
          It's answered — close this
        </Button>
      ) : null}
      {entry.source === "money" ? (
        <Button size="sm" variant="soft" icon={HandCoins} loading={item.isPending} onClick={() => settle("Marked as received")}>
          It arrived
        </Button>
      ) : null}
      {entry.source === "call" ? (
        <Button size="sm" variant="soft" icon={CircleCheck} loading={call.isPending} onClick={kept}>
          They kept it
        </Button>
      ) : null}
    </div>
  );
}

/** One thing waited for: what, from whom, since and until when, what Ordnung knows, and what to do. */
function Row({ entry, party }: { entry: WaitingEntry; party: Party | null }) {
  const source = copyFor(WAITING_SOURCE_COPY, entry.source);
  const status = copyFor(WAITING_STATUS_COPY, entry.status);
  const tone = TONES[entry.status === "overdue" ? "danger" : entry.status === "answered" ? "ok" : source.tone];
  return (
    <li className="flex gap-3 px-4 py-4 sm:px-5">
      <span className={cn("grid size-9 shrink-0 place-items-center rounded-xl", tone.soft, tone.icon)} aria-hidden>
        <source.icon className="size-[18px]" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-[12px] font-medium text-muted">
              {source.label}
              <span className="sr-only"> · {status.label}</span>
            </p>
            <h3 className="mt-0.5 text-[15px] font-semibold leading-snug text-ink [overflow-wrap:anywhere]">{entry.title}</h3>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 sm:flex-col sm:items-end sm:gap-1">
            {entry.amount != null ? <Money amount={entry.amount} currency={entry.currency} className="text-[15px]" /> : null}
            {entry.status === "answered" && entry.answered_on ? (
              <span className="text-[12.5px] text-ok-ink">
                Letter of <DateText date={entry.answered_on} style="short" />
              </span>
            ) : entry.expected_by ? (
              <Countdown date={entry.expected_by} showDate className="text-[12.5px]" />
            ) : (
              <span className="text-[12.5px] text-muted">No day given</span>
            )}
          </div>
        </div>
        <div className="mt-1.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted">
          {party ? <PartyChip party={party} /> : entry.party_name ? <span className="font-medium text-ink/85">{entry.party_name}</span> : null}
          <span lang={entry.source === "letter" ? "de" : undefined} className="min-w-0 [overflow-wrap:anywhere]">
            {entry.about}
          </span>
        </div>
        <p className="mt-1.5 text-[13px] leading-5 text-ink/85 [overflow-wrap:anywhere]">{entry.note}</p>
        <Actions entry={entry} />
      </div>
    </li>
  );
}

/**
 * "Waiting for": replies to letters the person sent, money a letter promised and callbacks promised
 * on the phone, grouped overdue → waiting → answered. Nothing is closed for them: an answer is named,
 * and they close it (or say the money arrived, or the promise was kept).
 */
export function WaitingList({ entries }: { entries: readonly WaitingEntry[] }) {
  const parties = useParties();
  const byId = useMemo(() => new Map((parties.data ?? []).map((p) => [p.id, p])), [parties.data]);
  const groups = groupWaiting(entries);
  return (
    <div className="flex flex-col gap-8">
      {WAITING_GROUPS.filter((g) => groups[g.status].length).map((g) => (
        <section key={g.status} aria-labelledby={`waiting-${g.status}`}>
          <SectionHeader id={`waiting-${g.status}`} title={g.title} count={groups[g.status].length} description={g.description} />
          <ul className="card divide-y divide-line">
            {groups[g.status].map((e) => (
              <Row key={e.id} entry={e} party={e.party_id ? (byId.get(e.party_id) ?? null) : null} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
