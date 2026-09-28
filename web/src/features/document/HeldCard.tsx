/**
 * The first card of a letter that waits for the person (`held`): the watched folder brought it in,
 * it is stored on this computer and nothing of it has been sent to Claude. "Keep private" keeps it
 * here (undoable from the toast); "Read it with Claude" queues it for reading — an e-mail's
 * attachments that still wait go with it. It takes the verdict card's place — and its page heading —
 * until the person answers.
 *
 * The answer's toast and the focus move run from the request's own promise, so they happen even
 * though the card is gone by then (the letter's refetch can land before the answer returns). While an
 * answer runs its button keeps focus, so a failed one leaves the person where they were.
 */
import { Hourglass, Lock, Sparkles } from "lucide-react";
import type { DocumentDetail } from "@/api/types";
import { useKeepHeldPrivate, useReadHeld, useWaitAgain } from "@/api/hooks";
import { cn, plural } from "@/lib/utils";
import { toast } from "@/components/ui/Toast";
import { AnswerButton } from "@/features/inbox/AnswerButton";
import { heldOrigin } from "@/features/inbox/waiting";

/** Once answered the card goes: focus moves to the page's new first heading (never to the page). */
export function focusFirstHeading() {
  requestAnimationFrame(() => {
    const h = document.querySelector<HTMLElement>("main h1, main h2");
    if (!h) return;
    if (!h.hasAttribute("tabindex")) h.setAttribute("tabindex", "-1");
    h.focus({ preventScroll: true });
  });
}

/** How many of an e-mail's attachments still wait (they are answered with it). */
export function waitingAttachments(detail: Pick<DocumentDetail, "attachments">): number {
  return detail.attachments.filter((a) => a.doc_id && a.status === "held").length;
}

export function HeldCard({ detail, className }: { detail: DocumentDetail; className?: string }) {
  const doc = detail.document;
  const read = useReadHeld();
  const keep = useKeepHeldPrivate();
  const wait = useWaitAgain();
  const busy = read.isPending || keep.isPending;
  const attached = waitingAttachments(detail);
  const title = doc.title ?? doc.filename;

  const readIt = () =>
    read
      .mutateAsync([doc.id])
      .then(() => {
        toast.success("Claude is reading it", { description: "You'll see every step here." });
        focusFirstHeading();
      })
      .catch(() => undefined); // the request's own error toast says what went wrong

  const keepIt = () =>
    keep
      .mutateAsync([doc.id])
      .then((res) => {
        const ids = res.documents.map((d) => d.id);
        toast.success("Kept private", {
          description: "It stays on this computer and is never sent to Claude — nothing in it was read.",
          undo: ids.length
            ? () =>
                wait
                  .mutateAsync(ids)
                  .then(() => void toast({ title: "It's back with the letters not read yet", tone: "info" }))
                  .catch(() => undefined)
            : undefined,
        });
        focusFirstHeading();
      })
      .catch(() => undefined);

  return (
    <article aria-labelledby="held-title" className={cn("card overflow-hidden", className)}>
      <div className="px-5 pb-5 pt-5 sm:px-6 sm:pt-6">
        <p className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.08em] text-accent">
          <Hourglass className="size-3.5" aria-hidden />
          Not read yet
        </p>
        <h1 id="held-title" className="display mt-2 text-[24px] font-semibold leading-[1.2] text-ink outline-none [overflow-wrap:anywhere] sm:text-[27px]">
          {title}
        </h1>
        {title !== doc.filename ? <p className="mt-1 text-[13px] text-muted [overflow-wrap:anywhere]">{doc.filename}</p> : null}
        <p className="mt-3 text-[15px] leading-relaxed text-ink/85">
          {heldOrigin(doc, detail.email)} It is stored on this computer and has not been sent to Claude.
        </p>
        <p className="mt-2 text-[13.5px] leading-relaxed text-muted">
          Let Claude read it to have its dates, amounts and deadlines filed — every fact is checked against the page. Or keep it private: it stays searchable here and is
          never sent, but nothing in it is read.
          {attached === 1 ? " Its attachment that waits goes with it." : attached > 1 ? ` Its ${plural(attached, "attachment")} that wait go with it.` : ""}
        </p>
        {/* the same order as the Inbox's group (the main answer last); phones: the two share the row */}
        <div className="mt-4 flex w-full gap-2 sm:w-auto">
          <AnswerButton icon={Lock} busy={keep.isPending} blocked={busy} onClick={keepIt} className="max-sm:flex-1">
            Keep private
          </AnswerButton>
          <AnswerButton variant="primary" icon={Sparkles} busy={read.isPending} blocked={busy} onClick={readIt} className="max-sm:flex-1">
            <span>
              Read it <span className="max-sm:sr-only">with Claude</span>
            </span>
          </AnswerButton>
        </div>
      </div>
    </article>
  );
}
