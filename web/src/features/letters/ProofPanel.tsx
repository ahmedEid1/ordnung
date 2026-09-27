import { useState } from "react";
import { Link } from "react-router";
import { CircleCheck, CircleDashed, Ellipsis, FileDown, Hourglass, Info, PenLine, Plus, ShieldCheck, Trash2, TriangleAlert } from "lucide-react";
import { api } from "@/api/endpoints";
import { useDraftProof, useRemoveProof, useSetTracking, useUpdateItem } from "@/api/hooks";
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
import { cn } from "@/lib/utils";
import { composerHref } from "@/features/today/selection";
import { AddProofDialog } from "./AddProofDialog";
import { TrackingField, trackingSavable } from "./TrackingField";
import { kindsIn, nachweisFileName, suggestedKind, takesTrackingNumber, waitingTitle, WAITING_TONE } from "./proof";

const WAITING_ICON = { waiting: Hourglass, overdue: TriangleAlert, answered: CircleCheck, closed: CircleCheck } as const;

/** What the letter waits for, and — once a letter answered it — the way to check and close it. */
function WaitingBox({ entry, draft }: { entry: WaitingEntry; draft: Draft }) {
  const close = useUpdateItem();
  const title = waitingTitle(entry);
  const closeFollowup = () => {
    if (!entry.followup_item_id) return;
    const id = entry.followup_item_id;
    // the box goes once it's closed: the toast follows the promise, not a `mutate` callback
    close.mutateAsync({ id, patch: { status: "done" } }).then(
      () =>
        toast.success("Follow-up closed", {
          description: "Ordnung won't remind you about this letter any more.",
          undo: () => close.mutate({ id, patch: { status: "open" } }),
        }),
      () => undefined,
    );
  };
  const reminder = entry.status === "overdue" ? composerHref("general_reply", { contractId: draft.contract_id, docId: draft.contract_id ? null : draft.doc_id, partyId: draft.contract_id || draft.doc_id ? null : draft.party_id }) : null;
  return (
    <Callout
      tone={WAITING_TONE[entry.status]}
      icon={WAITING_ICON[entry.status]}
      title={title}
      className="mb-5"
      action={
        entry.status === "answered" || reminder ? (
          <div className="flex flex-wrap gap-2">
            {entry.answered_by ? (
              <Link to={`/documents/${entry.answered_by.id}`} className={buttonVariants({ variant: "secondary", size: "sm" })}>
                Read their letter
              </Link>
            ) : null}
            {entry.status === "answered" && entry.followup_item_id ? (
              <Button size="sm" variant="primary" icon={CircleCheck} loading={close.isPending} onClick={closeFollowup}>
                It's answered — close this
              </Button>
            ) : null}
            {reminder ? (
              <Link to={reminder} className={buttonVariants({ variant: "secondary", size: "sm" })}>
                <PenLine aria-hidden />
                Write a reminder
              </Link>
            ) : null}
          </div>
        ) : undefined
      }
    >
      <p className="[overflow-wrap:anywhere]">{entry.note}</p>
    </Callout>
  );
}

/** The saved number with Change / Remove, or the field to enter it. */
function Tracking({ draft, overview }: { draft: Draft; overview: ProofOverview }) {
  const save = useSetTracking();
  const saved = overview.tracking;
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const store = (text: string | null) =>
    save.mutate(
      { id: draft.id, trackingNumber: text },
      {
        onSuccess: (next) => {
          setEditing(false);
          setValue("");
          toast.success(text ? "Tracking number saved" : "Tracking number removed", { description: next.tracking?.display ?? undefined });
        },
      },
    );

  if (saved && !editing) {
    return (
      <div>
        <h3 className="text-[13px] font-semibold text-ink">Tracking number</h3>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-ident text-[15px] tracking-wide text-ink [overflow-wrap:anywhere]">{saved.display}</span>
          <span className={cn("inline-flex items-center gap-1 text-[12.5px]", saved.checked ? "text-ok-ink" : "text-muted")}>
            {saved.checked ? <CircleCheck className="size-3.5" aria-hidden /> : <Info className="size-3.5" aria-hidden />}
            {saved.checked ? "Check digit correct" : "Not checked"}
          </span>
        </div>
        {saved.note ? <p className="mt-1 text-[12.5px] leading-5 text-muted">{saved.note}</p> : null}
        <div className="mt-2 flex flex-wrap gap-x-4">
          <Button variant="link" size="sm" onClick={() => (setValue(saved.display), setEditing(true))}>
            Change
          </Button>
          <Button variant="link" size="sm" onClick={() => store(null)} disabled={save.isPending}>
            Remove
          </Button>
        </div>
      </div>
    );
  }
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim() && trackingSavable(value)) store(value);
      }}
    >
      <TrackingField value={value} onChange={setValue} autoFocus={editing} />
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="sm" variant="soft" loading={save.isPending} disabled={!value.trim() || !trackingSavable(value)}>
          Save number
        </Button>
        {editing ? (
          <Button size="sm" variant="ghost" onClick={() => (setEditing(false), setValue(""))}>
            Cancel
          </Button>
        ) : null}
      </div>
    </form>
  );
}

/** One proof: its picture, what it is, the day it shows, and what it does and doesn't show. */
function ProofRow({ entry, onEdit, onRemove }: { entry: ProofEntry; onEdit: () => void; onRemove: () => void }) {
  const copy = copyFor(PROOF_KIND_COPY, entry.proof.kind);
  const doc = entry.document;
  // a file without a picture (an e-mail, a PDF that couldn't be drawn) shows the kind's icon instead
  const [noPicture, setNoPicture] = useState(false);
  const icon = (
    <span className={cn("grid size-12 shrink-0 place-items-center rounded-lg", TONES[copy.tone].soft, TONES[copy.tone].icon)} aria-hidden>
      <copy.icon className="size-5" />
    </span>
  );
  return (
    <li className="flex gap-3 py-3 first:pt-0 last:pb-0">
      {doc ? (
        <Link to={`/documents/${doc.id}`} className="shrink-0 self-start rounded-lg focus-visible:outline-offset-2" aria-label={`Open ${copy.label}: ${doc.filename}`}>
          {noPicture ? (
            icon
          ) : (
            <img src={api.thumbnailUrl(doc.id)} alt="" className="size-12 rounded-lg border border-line bg-surface-2 object-cover" loading="lazy" onError={() => setNoPicture(true)} />
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
              { label: "Change what it is or its day", icon: PenLine, onSelect: onEdit },
              { label: "Remove this proof", icon: Trash2, danger: true, onSelect: onRemove },
            ]}
          >
            <IconButton icon={Ellipsis} label={`Actions for ${copy.label}`} size="sm" className="-mr-1.5 -mt-1" />
          </Menu>
        </div>
        <p className="mt-0.5 text-[12.5px] leading-5 text-muted [overflow-wrap:anywhere]">
          {entry.proof.on_date ? <DateText date={entry.proof.on_date} style="short" /> : "No day given"}
          {entry.proof.note ? <span> · {entry.proof.note}</span> : null}
          {doc ? <span className="block truncate" title={doc.filename}>{doc.filename}</span> : null}
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

/** The letter's timeline: what was recorded, oldest first. */
function Timeline({ events }: { events: ProofEvent[] }) {
  return (
    <section aria-labelledby="proof-timeline">
      <h3 id="proof-timeline" className="mb-2 text-[13px] font-semibold text-ink">
        Timeline
      </h3>
      <ol className="relative ml-1.5 border-l border-line">
        {events.map((e, i) => (
          <li key={`${e.kind}-${e.date}-${i}`} className="relative pb-3 pl-4 last:pb-0">
            <span
              className={cn(
                "absolute -left-[5px] top-1.5 size-[9px] rounded-full ring-4 ring-surface",
                e.kind === "delivered" || e.kind === "answered" ? "bg-ok" : e.kind === "sent" ? "bg-accent" : "bg-faint",
              )}
              aria-hidden
            />
            <DateText date={e.date} style="short" className="block text-[12px] tabular-nums text-muted" />
            <span className="block text-[13.5px] leading-snug text-ink [overflow-wrap:anywhere]">
              {e.ref ? (
                <Link to={`/documents/${e.ref.id}`} className="inline-block min-h-6 py-0.5 underline decoration-line-strong underline-offset-2 hover:decoration-current">
                  {e.label}
                </Link>
              ) : (
                e.label
              )}
            </span>
            {e.detail ? <span className="block text-[12.5px] leading-5 text-muted [overflow-wrap:anywhere]">{e.detail}</span> : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

/**
 * "Proof of sending" on a sent letter: what it waits for, the tracking number (checked as it is
 * typed), the proofs with what each does and doesn't show, what would make it stronger, the
 * timeline and the Nachweis PDF. Proof files are private: never sent to AI.
 */
export function ProofPanel({ draft }: { draft: Draft }) {
  const q = useDraftProof(draft.id);
  const remove = useRemoveProof();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<ProofEntry | null>(null);
  const [removing, setRemoving] = useState<ProofEntry | null>(null);
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
          <div className="@container">
            <div className="grid gap-6 @[36rem]:grid-cols-[minmax(0,1fr)_minmax(0,15rem)]">
              <div className="min-w-0 space-y-5">
                {takesTrackingNumber(overview.channel) ? <Tracking draft={draft} overview={overview} /> : null}

                <section aria-labelledby="proof-list">
                  <h3 id="proof-list" className="mb-2 text-[13px] font-semibold text-ink">
                    Your proof{overview.proofs.length ? <span className="font-medium text-muted"> · {overview.proofs.length}</span> : null}
                  </h3>
                  {overview.proofs.length ? (
                    <ul className="divide-y divide-line">
                      {overview.proofs.map((p) => (
                        <ProofRow key={p.proof.id} entry={p} onEdit={() => setEditing(p)} onRemove={() => setRemoving(p)} />
                      ))}
                    </ul>
                  ) : (
                    <p className="text-[13px] leading-5 text-muted">Nothing added yet. A photo of the receipt is enough.</p>
                  )}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button size="sm" variant="soft" icon={Plus} onClick={() => setAdding(true)}>
                      Add proof
                    </Button>
                    <a href={api.proofPdfUrl(draft.id)} download={nachweisFileName(draft)} className={buttonVariants({ variant: "secondary", size: "sm" })}>
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
              <Timeline events={overview.timeline} />
            </div>
          </div>
          <p className="mt-5 flex gap-2 border-t border-line pt-4 text-[12.5px] leading-5 text-muted">
            <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            <span>{overview.caveat}</span>
          </p>

          {adding ? (
            <AddProofDialog open onClose={() => setAdding(false)} draftId={draft.id} channel={overview.channel} suggested={suggestedKind(overview.channel, kindsIn(overview))} />
          ) : null}
          {editing ? (
            <AddProofDialog key={editing.proof.id} open onClose={() => setEditing(null)} draftId={draft.id} channel={overview.channel} suggested={editing.proof.kind} editing={editing} />
          ) : null}
          <Dialog
            open={Boolean(removing)}
            onClose={() => setRemoving(null)}
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
                          toast.success("Proof removed", { description: copyFor(PROOF_KIND_COPY, removing.proof.kind).label });
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
