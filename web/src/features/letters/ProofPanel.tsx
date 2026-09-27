import { useRef, useState } from "react";
import { Link } from "react-router";
import { CalendarClock, CircleCheck, CircleDashed, CircleHelp, Ellipsis, FileDown, Hourglass, Info, PenLine, Plus, ShieldCheck, Trash2, TriangleAlert, Undo2 } from "lucide-react";
import { api } from "@/api/endpoints";
import { useDraftProof, useMarkAnswered, useRemoveProof, useSetTracking } from "@/api/hooks";
import type { Draft, ProofEntry, ProofEvent, ProofOverview, WaitingEntry } from "@/api/types";
import { Button, IconButton, buttonVariants } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Card, CardHeader } from "@/components/ui/Card";
import { DateText } from "@/components/ui/DateText";
import { Dialog } from "@/components/ui/Dialog";
import { LoadError } from "@/components/ui/LoadError";
import { Menu } from "@/components/ui/Menu";
import { SkeletonText } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { PROOF_KIND_COPY, TONES, copyFor } from "@/lib/copy";
import { displayTracking } from "@/lib/tracking";
import { cn } from "@/lib/utils";
import { composerHref } from "@/features/today/selection";
import { focusWhenReady } from "@/features/today/focus";
import { WRAPPING_BUTTON, closeLabel } from "@/features/waiting/model";
import { AddProofDialog } from "./AddProofDialog";
import { TrackingField, trackingSavable } from "./TrackingField";
import { hasPicture, kindsIn, proofFileHref, nachweisFileName, startWith, suggestedKind, takesTrackingNumber, waitingTitle, WAITING_TONE } from "./proof";

const WAITING_ICON = {
  waiting: Hourglass,
  overdue: TriangleAlert,
  answered: CircleCheck,
  closed: CircleCheck,
} as const;
const BOX_ID = "proof-waiting";
const LIST_ID = "proof-list";
const TRACKING_INPUT = "proof-tracking-input";
const TRACKING_CHANGE = "proof-tracking-change";

/** Focus an element by id once it's there (the control that was used has just gone); `always`: even if focus
 * is still on the control that was used (it stays, but what it does changed). */
const focusId = (id: string, always = false) => focusWhenReady(() => document.getElementById(id), 5000, { always });

/**
 * What the letter waits for, and the way to close it: the letter that came is the answer, or it was
 * answered another way (phone, e-mail …). Closing is the person's word, with Undo.
 */
function WaitingBox({ entry, draft }: { entry: WaitingEntry; draft: Draft }) {
  const answered = useMarkAnswered();
  const title = waitingTitle(entry);
  const set = (value: boolean) => {
    const docId = entry.status === "answered" ? (entry.answered_by?.id ?? null) : null;
    // the box changes once saved (its buttons go): the toast follows the promise, focus the box
    answered.mutateAsync({ id: draft.id, answered: value, docId }).then(
      () => {
        focusId(BOX_ID, true);
        if (value)
          toast.success("Marked as answered", {
            description: "The follow-up is closed — Ordnung won't remind you about this letter.",
            undo: () => answered.mutateAsync({ id: draft.id, answered: false }).then(() => focusId(BOX_ID, true)),
          });
        else
          toast.success("Waiting for an answer again", {
            description: "The follow-up is open again.",
          });
      },
      () => undefined,
    );
  };
  const reminder =
    entry.status === "overdue"
      ? composerHref("general_reply", {
          contractId: draft.contract_id,
          docId: draft.contract_id ? null : draft.doc_id,
          partyId: draft.contract_id || draft.doc_id ? null : draft.party_id,
        })
      : null;
  const open = entry.status !== "closed";
  return (
    <div id={BOX_ID} tabIndex={-1} className="mb-5 rounded-xl outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
      <Callout
        tone={WAITING_TONE[entry.status]}
        icon={WAITING_ICON[entry.status]}
        title={title}
        action={
          <div className="flex min-w-0 flex-wrap gap-2">
            {entry.answered_by && open ? (
              <Link to={`/documents/${entry.answered_by.id}`} className={buttonVariants({ variant: "secondary", size: "sm" })}>
                Read their letter
              </Link>
            ) : null}
            {open ? (
              <Button size="sm" variant={entry.status === "answered" ? "primary" : "soft"} icon={CircleCheck} loading={answered.isPending} onClick={() => set(true)} className={WRAPPING_BUTTON}>
                <span>{closeLabel(entry)}</span>
              </Button>
            ) : draft.answered_on ? (
              <Button size="sm" variant="secondary" icon={Undo2} loading={answered.isPending} onClick={() => set(false)}>
                Not answered after all
              </Button>
            ) : null}
            {reminder ? (
              <Link to={reminder} className={buttonVariants({ variant: "secondary", size: "sm" })}>
                <PenLine aria-hidden />
                Write a reminder
              </Link>
            ) : null}
          </div>
        }
      >
        <p className="[overflow-wrap:anywhere]">{entry.note}</p>
      </Callout>
    </div>
  );
}

/** The saved number with Change / Remove (with Undo), or the field to enter it. */
function Tracking({ draft, overview }: { draft: Draft; overview: ProofOverview }) {
  const save = useSetTracking();
  const saved = overview.tracking;
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [tried, setTried] = useState(false);
  const store = (text: string | null, then?: () => void) =>
    save.mutate(
      { id: draft.id, trackingNumber: text },
      {
        onSuccess: (next) => {
          setEditing(false);
          setValue("");
          setTried(false);
          then?.();
          if (text) {
            focusId(TRACKING_CHANGE);
            toast.success("Tracking number saved", {
              description: next.tracking ? displayTracking(next.tracking.number) : undefined,
            });
          }
        },
      },
    );
  const remove = () => {
    if (!saved) return;
    const previous = saved.number;
    store(null, () => {
      focusId(TRACKING_INPUT);
      toast.success("Tracking number removed", {
        description: displayTracking(previous),
        undo: () => store(previous),
      });
    });
  };

  if (saved && !editing) {
    return (
      <div>
        <h3 className="text-[13px] font-semibold text-ink">Tracking number</h3>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
          {/* plain spaces (it copies cleanly), never broken inside the number */}
          <span className="font-ident whitespace-nowrap text-[15px] tracking-wide text-ink">{displayTracking(saved.number)}</span>
          <span className={cn("inline-flex items-center gap-1 text-[12.5px]", saved.checked ? "text-ok-ink" : "text-muted")}>
            {saved.checked ? <CircleCheck className="size-3.5" aria-hidden /> : <Info className="size-3.5" aria-hidden />}
            {saved.checked ? "Check digit correct" : "Not checked"}
          </span>
        </div>
        {saved.note ? <p className="mt-1 text-[12.5px] leading-5 text-muted">{saved.note}</p> : null}
        <div className="mt-2 flex flex-wrap gap-x-4">
          <Button id={TRACKING_CHANGE} variant="link" size="sm" onClick={() => (setValue(displayTracking(saved.number)), setEditing(true))}>
            Change
          </Button>
          <Button variant="link" size="sm" onClick={remove} disabled={save.isPending}>
            Remove
          </Button>
        </div>
      </div>
    );
  }
  const cancel = () => {
    setEditing(false);
    setValue("");
    setTried(false);
    focusId(TRACKING_CHANGE);
  };
  return (
    <form
      className="flex flex-col gap-2"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        setTried(true);
        if (value.trim() && trackingSavable(value)) store(value);
        else document.getElementById(TRACKING_INPUT)?.focus();
      }}
    >
      <TrackingField id={TRACKING_INPUT} value={value} onChange={setValue} autoFocus={editing} showError={tried} required />
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="sm" variant="soft" loading={save.isPending}>
          Save number
        </Button>
        {editing ? (
          <Button size="sm" variant="ghost" onClick={cancel}>
            Cancel
          </Button>
        ) : null}
      </div>
    </form>
  );
}

/** One proof: its picture (or its kind's icon), what it is, the day it shows, and what it does and doesn't show. */
function ProofRow({ entry, onEdit, onRemove }: { entry: ProofEntry; onEdit: () => void; onRemove: () => void }) {
  const copy = copyFor(PROOF_KIND_COPY, entry.proof.kind);
  const doc = entry.document;
  // a file without a picture (an e-mail, a text file, a PDF that couldn't be drawn) shows the kind's icon
  const [broken, setBroken] = useState(false);
  const icon = (
    <span className={cn("grid size-12 shrink-0 place-items-center rounded-lg", TONES[copy.tone].soft, TONES[copy.tone].icon)} aria-hidden>
      <copy.icon className="size-5" />
    </span>
  );
  return (
    <li className="flex gap-3 py-3 first:pt-0 last:pb-0">
      {doc ? (
        <Link to={proofFileHref(entry.proof.draft_id, doc.id)} className="shrink-0 self-start rounded-lg focus-visible:outline-offset-2" aria-label={`Open ${copy.label}: ${doc.filename}`}>
          {broken || !hasPicture(doc) ? (
            icon
          ) : (
            <img src={api.thumbnailUrl(doc.id)} alt="" className="size-12 rounded-lg border border-line bg-surface-2 object-cover" loading="lazy" onError={() => setBroken(true)} />
          )}
        </Link>
      ) : (
        icon
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-2">
          <p className="min-w-0 flex-1 text-[14px] font-medium leading-snug text-ink">{copy.label}</p>
          <Menu
            label="Proof actions"
            heading={copy.label}
            items={[
              {
                label: "Change what it is or its day",
                icon: PenLine,
                onSelect: onEdit,
              },
              {
                label: "Remove this proof",
                icon: Trash2,
                danger: true,
                onSelect: onRemove,
              },
            ]}
          >
            <IconButton icon={Ellipsis} label={`Actions for ${copy.label}`} size="sm" className="-mr-1.5 -mt-1" />
          </Menu>
        </div>
        <p className="mt-0.5 text-[12.5px] leading-5 text-muted [overflow-wrap:anywhere]">
          {entry.proof.on_date ? <DateText date={entry.proof.on_date} style="short" /> : "No day given"}
          {entry.proof.note ? <span> · {entry.proof.note}</span> : null}
          {doc ? (
            <span className="block truncate" title={doc.filename}>
              {doc.filename}
            </span>
          ) : null}
        </p>
        <dl className="mt-1.5 space-y-0.5 text-[12.5px] leading-5">
          <div>
            <dt className="inline font-medium text-ink/85">Shows: </dt>
            <dd className="inline text-muted">{entry.shows}</dd>
          </div>
          <div>
            <dt className="inline font-medium text-ink/85">Doesn't show: </dt>
            <dd className="inline text-muted">{entry.does_not_show}</dd>
          </div>
        </dl>
      </div>
    </li>
  );
}

function EventLabel({ e, draftId }: { e: ProofEvent; draftId: string }) {
  // a proof opens with its letter; their letter (an answer, a possible one) in the Inbox's viewer
  const href = e.ref ? (e.kind === "proof" || e.kind === "delivered" ? proofFileHref(draftId, e.ref.id) : `/documents/${e.ref.id}`) : null;
  return (
    <span className="block text-[13.5px] leading-snug text-ink [overflow-wrap:anywhere]">
      {href ? (
        <Link to={href} className="inline-block min-h-6 py-0.5 underline decoration-line-strong underline-offset-2 hover:decoration-current">
          {e.label}
        </Link>
      ) : (
        e.label
      )}
    </span>
  );
}

/**
 * The letter's timeline: what was recorded, oldest first. A letter that may be the answer is marked as
 * a question; proofs without a day are listed apart (never on the day they were added).
 */
function Timeline({ events, draftId }: { events: ProofEvent[]; draftId: string }) {
  const dated = events.filter((e) => e.date);
  const undated = events.filter((e) => !e.date);
  return (
    <section aria-labelledby="proof-timeline">
      <h3 id="proof-timeline" className="mb-2 text-[13px] font-semibold text-ink">
        Timeline
      </h3>
      <ol className="relative ml-1.5 border-l border-line">
        {dated.map((e, i) => (
          <li key={`${e.kind}-${e.date}-${i}`} className="relative pb-3 pl-4 last:pb-0">
            {e.kind === "possible_answer" ? (
              <CircleHelp className="absolute -left-[7px] top-1 size-3.5 rounded-full bg-surface text-warn" aria-hidden />
            ) : (
              <span
                className={cn(
                  "absolute -left-[5px] top-1.5 size-[9px] rounded-full ring-4 ring-surface",
                  e.kind === "delivered" || e.kind === "answered" ? "bg-ok" : e.kind === "sent" ? "bg-accent" : "bg-faint",
                )}
                aria-hidden
              />
            )}
            <DateText date={e.date} style="short" className="block text-[12px] tabular-nums text-muted" />
            <EventLabel e={e} draftId={draftId} />
            {e.detail ? <span className="block text-[12.5px] leading-5 text-muted [overflow-wrap:anywhere]">{e.detail}</span> : null}
          </li>
        ))}
      </ol>
      {undated.length ? (
        <>
          <h4 className="mb-1.5 mt-4 text-[12.5px] font-semibold text-ink">No day given</h4>
          <ul className="space-y-2">
            {undated.map((e, i) => (
              <li key={`${e.kind}-${e.added_on}-${i}`} className="text-[13px]">
                <EventLabel e={e} draftId={draftId} />
                <span className="block text-[12px] text-muted">
                  Added <DateText date={e.added_on} style="short" /> — not placed on the timeline
                </span>
                {e.detail ? <span className="block text-[12.5px] leading-5 text-muted [overflow-wrap:anywhere]">{e.detail}</span> : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}

/**
 * "Proof of sending" on a sent letter: what it waits for (and "I got an answer"), the tracking number
 * (checked as it is typed), the proofs with what each does and doesn't show, days that contradict the
 * sending day, what would make it stronger, the timeline and the Nachweis PDF. Proof files are
 * private: never sent to AI (a file already in Ordnung is said to be so when it is added).
 */
export function ProofPanel({ draft, onChangeSending }: { draft: Draft; onChangeSending?: () => void }) {
  const q = useDraftProof(draft.id);
  const remove = useRemoveProof();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<ProofEntry | null>(null);
  const [removing, setRemoving] = useState<ProofEntry | null>(null);
  // a removed proof's row (and the menu that opened the dialog) is gone: focus returns to the list's heading
  const listHeading = useRef<HTMLHeadingElement>(null);
  const overview = q.data;

  return (
    <Card as="section" aria-labelledby="proof-title" padding="md">
      <CardHeader title={<span id="proof-title">Proof of sending</span>} icon={ShieldCheck} level={2} />
      {q.isPending ? (
        <div aria-busy="true">
          <SkeletonText lines={4} />
        </div>
      ) : q.isError || !overview ? (
        <LoadError what="the proof of this letter" variant="plain" size="sm" headingLevel={3} error={q.error} onRetry={() => void q.refetch()} retrying={q.isFetching} />
      ) : (
        <>
          {overview.waiting ? <WaitingBox entry={overview.waiting} draft={draft} /> : null}
          {overview.conflicts.length ? (
            <Callout
              tone="warn"
              icon={CalendarClock}
              title="These days don't match"
              className="mb-5"
              action={
                onChangeSending ? (
                  <Button size="sm" variant="secondary" icon={PenLine} onClick={onChangeSending}>
                    Change the sending day
                  </Button>
                ) : undefined
              }
            >
              <ul className="space-y-1 [overflow-wrap:anywhere]">
                {overview.conflicts.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
              <p className="mt-1 text-[13px] text-muted">To correct a proof's day, use its menu (⋯ → Change what it is or its day).</p>
            </Callout>
          ) : null}
          <div className="@container">
            <div className="grid gap-6 @[36rem]:grid-cols-[minmax(0,1fr)_minmax(0,15rem)]">
              <div className="min-w-0 space-y-5">
                {takesTrackingNumber(overview.channel) ? <Tracking draft={draft} overview={overview} /> : null}

                <section aria-labelledby={LIST_ID}>
                  <h3 id={LIST_ID} ref={listHeading} tabIndex={-1} className="mb-2 text-[13px] font-semibold text-ink outline-none">
                    Your proof
                    {overview.proofs.length ? <span className="font-medium text-muted"> · {overview.proofs.length}</span> : null}
                  </h3>
                  {overview.proofs.length ? (
                    <ul className="divide-y divide-line">
                      {overview.proofs.map((p) => (
                        <ProofRow key={p.proof.id} entry={p} onEdit={() => setEditing(p)} onRemove={() => setRemoving(p)} />
                      ))}
                    </ul>
                  ) : (
                    <p className="text-[13px] leading-5 text-muted">{`Nothing added yet${startWith(overview.channel) ? ` — start with ${startWith(overview.channel)}` : ""}.`}</p>
                  )}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button size="sm" variant="soft" icon={Plus} onClick={() => setAdding(true)}>
                      Add proof
                    </Button>
                    <a
                      href={api.proofPdfUrl(draft.id)}
                      download={nachweisFileName(draft)}
                      className={buttonVariants({
                        variant: "secondary",
                        size: "sm",
                      })}
                    >
                      <FileDown aria-hidden />
                      Download Nachweis (PDF)
                    </a>
                  </div>
                </section>

                <section aria-labelledby="proof-missing">
                  <h3 id="proof-missing" className="mb-1.5 text-[13px] font-semibold text-ink">
                    What would make it stronger
                  </h3>
                  {overview.missing.length ? (
                    <ul className="space-y-1.5">
                      {overview.missing.map((m) => (
                        <li key={m} className="flex gap-2 text-[13px] leading-5 text-ink/90">
                          <CircleDashed className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
                          <span className="min-w-0 [overflow-wrap:anywhere]">{m}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="flex gap-2 text-[13px] leading-5 text-muted">
                      <CircleCheck className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden />
                      You've kept what Ordnung suggests for a letter sent this way.
                    </p>
                  )}
                </section>
              </div>
              <Timeline events={overview.timeline} draftId={draft.id} />
            </div>
          </div>
          <p className="mt-5 flex gap-2 border-t border-line pt-4 text-[12.5px] leading-5 text-muted">
            <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            <span>{overview.caveat}</span>
          </p>

          {adding ? (
            <AddProofDialog
              open
              onClose={() => setAdding(false)}
              draftId={draft.id}
              channel={overview.channel}
              sentOn={draft.sent_at?.slice(0, 10) ?? null}
              suggested={suggestedKind(overview.channel, kindsIn(overview))}
            />
          ) : null}
          {editing ? (
            <AddProofDialog
              key={editing.proof.id}
              open
              onClose={() => setEditing(null)}
              draftId={draft.id}
              channel={overview.channel}
              sentOn={draft.sent_at?.slice(0, 10) ?? null}
              suggested={editing.proof.kind}
              editing={editing}
            />
          ) : null}
          <Dialog
            open={Boolean(removing)}
            onClose={() => setRemoving(null)}
            returnFocus={listHeading}
            size="sm"
            title="Remove this proof?"
            description={removing?.document?.source === "proof" ? "Its file is deleted from Ordnung for good." : "The file stays in Ordnung; only the link to this letter goes."}
            footer={
              <>
                <Button onClick={() => setRemoving(null)}>Keep it</Button>
                <Button
                  variant="danger"
                  icon={Trash2}
                  loading={remove.isPending}
                  onClick={() =>
                    removing &&
                    remove.mutate(
                      { id: draft.id, proofId: removing.proof.id },
                      {
                        onSuccess: () => {
                          toast.success("Proof removed", {
                            description: copyFor(PROOF_KIND_COPY, removing.proof.kind).label,
                          });
                          setRemoving(null);
                        },
                      },
                    )
                  }
                >
                  Remove
                </Button>
              </>
            }
          />
        </>
      )}
    </Card>
  );
}
