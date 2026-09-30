/**
 * The first card of a letter that waits for the person (`held`): the watched folder brought it in,
 * it is stored on this computer and nothing of it has been sent to Claude. "Keep private" keeps it
 * here (undoable from the toast); "Read it with Claude" queues it for reading — an e-mail's
 * attachments that still wait go with it. It takes the verdict card's place — and its page heading —
 * until the person answers.
 *
 * The answer's toast runs from the request's own promise, so it happens even though the card is gone
 * by then (the letter's refetch can land before the answer returns); the focus move to the card that
 * replaces this one is the page's (`onAnswered`: DocumentView moves it once that card is rendered,
 * whether that render comes before the answer returns or after).
 * While an answer runs its button keeps focus, so a failed one leaves the person where they were.
 */
import { Lock, Sparkles } from "lucide-react";
import type { DocumentDetail } from "@/api/types";
import { useKeepHeldPrivate, useReadHeld, useWaitAgain } from "@/api/hooks";
import { MEANING_ICONS } from "@/lib/copy";
import { glueText } from "@/lib/format";
import { GermanTerms } from "@/lib/germanTerms";
import { cn, plural } from "@/lib/utils";
import { FileNameText } from "@/components/ui/FileNameText";
import { toast } from "@/components/ui/Toast";
import { AnswerButton } from "@/features/inbox/AnswerButton";
import { heldOrigin } from "@/features/inbox/waiting";
import { hasLongWord } from "./verdict";

/**
 * "Not read yet" over a waiting letter's title, with the Inbox's icon for it. Its row is as tall as the
 * verdict card's badge row, so the title sits where the verdict's does (and the "How it was read" tab's).
 */
export function NotReadYet() {
  const Icon = MEANING_ICONS.notReadYet;
  return (
    <p className="flex min-h-7 items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.08em] text-accent">
      <Icon className="size-3.5 shrink-0" aria-hidden />
      Not read yet
    </p>
  );
}

/**
 * A letter's title as its page shows it: the letter's words kept whole where the line wraps (a reference,
 * "30 €", a German compound at its joints), or its file name, broken after underscores — never at the
 * hyphens inside a date or a reference (UI audit round 2: "Rechnung_2026-" / "09_FunkNetz.pdf").
 */
export function LetterTitle({ title, filename }: { title: string | null; filename: string }) {
  return title && title !== filename ? <GermanTerms text={glueText(title)} /> : <FileNameText name={filename} />;
}

/** The detail-page title size: a step smaller on phones for a title with a very long word. */
export const detailTitleSize = (title: string) => (hasLongWord(title) ? "text-detail-long" : "text-detail");

/** How many of an e-mail's attachments still wait (they are answered with it). */
export function waitingAttachments(detail: Pick<DocumentDetail, "attachments">): number {
  return detail.attachments.filter((a) => a.doc_id && a.status === "held").length;
}

export interface HeldCardProps {
  detail: DocumentDetail;
  className?: string;
  /** An answer went through (`from`: the status it answered): the card goes, and focus belongs to the one that takes its place. */
  onAnswered?: (from: DocumentDetail["document"]["status"]) => void;
}

export function HeldCard({ detail, className, onAnswered }: HeldCardProps) {
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
        onAnswered?.(doc.status);
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
        onAnswered?.(doc.status);
      })
      .catch(() => undefined);

  return (
    // named as written (the heading keeps its hyphens whole with non-breaking ones)
    <article aria-label={title} className={cn("card overflow-hidden", className)}>
      <div className="px-5 pb-5 pt-5 sm:px-6 sm:pt-6">
        <NotReadYet />
        <h1 id="held-title" className={cn("display mt-3 font-semibold text-ink outline-none hyphens-manual [overflow-wrap:anywhere]", detailTitleSize(title))}>
          <LetterTitle title={doc.title} filename={doc.filename} />
        </h1>
        {title !== doc.filename ? (
          <p className="mt-1 text-[13px] text-muted [overflow-wrap:anywhere]">
            <FileNameText name={doc.filename} />
          </p>
        ) : null}
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
