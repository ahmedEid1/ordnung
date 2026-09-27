import { createContext, useContext, useMemo, useRef, type RefObject } from "react";
import { Link } from "react-router";
import { CircleCheck, HandCoins, PenLine, Phone } from "lucide-react";
import { useMarkAnswered, useParties, useUpdateCall, useUpdateItem } from "@/api/hooks";
import type { Party, WaitingEntry } from "@/api/types";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { Money } from "@/components/ui/Money";
import { PartyChip } from "@/components/ui/PartyChip";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { toast } from "@/components/ui/Toast";
import { TONES, WAITING_SOURCE_COPY, WAITING_STATUS_COPY, copyFor } from "@/lib/copy";
import { usePartyDrawer } from "@/lib/party-drawer";
import { cn } from "@/lib/utils";
import { focusWhenReady } from "@/features/today/focus";
import { WAITING_GROUPS, WRAPPING_BUTTON, asksForACall, closeLabel, groupWaiting } from "./model";

const rowHeadingId = (entryId: string) => `waiting-row-${entryId}`;

/** Where focus goes when a row leaves the list (settled) or comes back (Undo) — never to <body>. */
interface RowFocus {
  leaving: (entryId: string) => void;
  returning: (entryId: string) => void;
}

const RowFocusContext = createContext<RowFocus | null>(null);

function useRowFocus(list: RefObject<HTMLElement | null>): RowFocus {
  return useMemo<RowFocus>(() => {
    const headings = () => Array.from(list.current?.querySelectorAll<HTMLElement>("[data-waiting-heading]") ?? []);
    return {
      leaving: (entryId) => {
        const id = rowHeadingId(entryId);
        const at = Math.max(
          0,
          headings().findIndex((h) => h.id === id),
        );
        // the row now in its place, else the last one, else the page heading (nothing left to wait for)
        focusWhenReady(() => {
          if (document.getElementById(id)) return null;
          const rest = headings();
          return rest[Math.min(at, rest.length - 1)] ?? document.querySelector<HTMLElement>("main h1");
        });
      },
      returning: (entryId) => focusWhenReady(() => document.getElementById(rowHeadingId(entryId))),
    };
  }, [list]);
}

function Actions({ entry }: { entry: WaitingEntry }) {
  const item = useUpdateItem();
  const call = useUpdateCall();
  const answered = useMarkAnswered();
  const drawer = usePartyDrawer();
  const focus = useContext(RowFocusContext);
  // The row leaves the list once settled, so the toast follows the promise (a `mutate` callback
  // would be dropped with the unmounted row); errors are shown by the mutation's own toast.
  const settle = (what: string) => {
    if (!entry.followup_item_id) return;
    const id = entry.followup_item_id;
    focus?.leaving(entry.id);
    item.mutateAsync({ id, patch: { status: "done" } }).then(
      () =>
        toast.success(what, {
          description: entry.title,
          undo: () => item.mutateAsync({ id, patch: { status: "open" } }).then(() => focus?.returning(entry.id)),
        }),
      () => undefined,
    );
  };
  const kept = () => {
    focus?.leaving(entry.id);
    call.mutateAsync({ id: entry.ref.id, kept: true }).then(
      () =>
        toast.success("Marked as kept", {
          description: entry.title,
          undo: () => call.mutateAsync({ id: entry.ref.id, kept: false }).then(() => focus?.returning(entry.id)),
        }),
      () => undefined,
    );
  };
  // a letter: the person's word closes it — with the letter that came (answered) or without (by phone, e-mail …)
  const closeLetter = () => {
    const draftId = entry.ref.id;
    focus?.leaving(entry.id);
    answered
      .mutateAsync({
        id: draftId,
        answered: true,
        docId: entry.status === "answered" ? (entry.answered_by?.id ?? null) : null,
      })
      .then(
        () =>
          toast.success("Marked as answered", {
            description: `${entry.title} — the follow-up is closed.`,
            undo: () => answered.mutateAsync({ id: draftId, answered: false }).then(() => focus?.returning(entry.id)),
          }),
        () => undefined,
      );
  };
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
      {entry.source === "letter" ? (
        <Button size="sm" variant="soft" icon={CircleCheck} loading={answered.isPending} onClick={closeLetter} className={WRAPPING_BUTTON}>
          <span>{closeLabel(entry)}</span>
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
      {asksForACall(entry) ? (
        // the note says "call them — and note what they say": the form, with this thread chosen
        <Button size="sm" variant="secondary" icon={Phone} onClick={() => drawer.open(entry.party_id!, { noteCall: { caseId: entry.case_id } })}>
          Note a call
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
            <h3
              id={rowHeadingId(entry.id)}
              data-waiting-heading
              tabIndex={-1}
              className="mt-0.5 text-[15px] font-semibold leading-snug text-ink outline-none [overflow-wrap:anywhere] focus-visible:rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              {entry.title}
            </h3>
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
 * and they close it — every letter can be closed, also when the answer came by phone or e-mail — or
 * say the money arrived, or the promise was kept. Focus moves to the row now in the settled one's place.
 */
export function WaitingList({ entries }: { entries: readonly WaitingEntry[] }) {
  const parties = useParties();
  const byId = useMemo(() => new Map((parties.data ?? []).map((p) => [p.id, p])), [parties.data]);
  const groups = groupWaiting(entries);
  const listRef = useRef<HTMLDivElement>(null);
  const focus = useRowFocus(listRef);
  return (
    <RowFocusContext.Provider value={focus}>
      <div ref={listRef} className="flex flex-col gap-8">
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
    </RowFocusContext.Provider>
  );
}
