/**
 * The first card of a letter that waits for the person (`held`): the watched folder brought it in,
 * it is stored on this computer and nothing of it has been sent to Claude. "Read it with Claude"
 * queues it for reading (an e-mail's waiting attachments with it); "Keep private" keeps it here for
 * good. It takes the verdict card's place — and its page heading — until the person answers.
 */
import { Hourglass, Lock, Sparkles } from "lucide-react";
import type { DocumentDetail } from "@/api/types";
import { useKeepHeldPrivate, useReadHeld } from "@/api/hooks";
import { cn, plural } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { heldOrigin } from "@/features/inbox/waiting";

/** Once answered the card goes: focus moves to the page's new first heading (never to the page). */
function focusFirstHeading() {
  requestAnimationFrame(() => {
    const h = document.querySelector<HTMLElement>("main h1, main h2");
    if (!h) return;
    if (!h.hasAttribute("tabindex")) h.setAttribute("tabindex", "-1");
    h.focus({ preventScroll: true });
  });
}

export function HeldCard({ detail, className }: { detail: DocumentDetail; className?: string }) {
  const doc = detail.document;
  const read = useReadHeld();
  const keep = useKeepHeldPrivate();
  const busy = read.isPending || keep.isPending;
  const waitingAttachments = detail.attachments.filter((a) => a.doc_id && a.outcome === "added").length;

  return (
    <article aria-labelledby="held-title" className={cn("card overflow-hidden", className)}>
      <div className="px-5 pb-5 pt-5 sm:px-6 sm:pt-6">
        <p className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.08em] text-accent">
          <Hourglass className="size-3.5" aria-hidden />
          Waiting for you
        </p>
        <h1 id="held-title" className="display mt-2 text-[24px] font-semibold leading-[1.2] text-ink [overflow-wrap:anywhere] sm:text-[27px]">
          {doc.filename}
        </h1>
        <p className="mt-3 text-[15px] leading-relaxed text-ink/85">
          {heldOrigin(doc, detail.email)} It is stored on this computer and has not been sent to Claude.
        </p>
        <p className="mt-2 text-[13.5px] leading-relaxed text-muted">
          Let Claude read it to have its dates, amounts and deadlines filed — every fact is checked against the page. Or keep it private: it stays searchable here and is
          never sent.
          {waitingAttachments === 1 ? " Its attachment goes with it." : waitingAttachments > 1 ? ` Its ${plural(waitingAttachments, "attachment")} go with it.` : ""}
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            variant="primary"
            icon={Sparkles}
            loading={read.isPending}
            disabled={busy && !read.isPending}
            onClick={() =>
              read.mutate([doc.id], {
                onSuccess: () => {
                  toast.success("Claude is reading it", { description: "You'll see every step here." });
                  focusFirstHeading();
                },
              })
            }
          >
            Read it with Claude
          </Button>
          <Button
            icon={Lock}
            loading={keep.isPending}
            disabled={busy && !keep.isPending}
            onClick={() =>
              keep.mutate([doc.id], {
                onSuccess: () => {
                  toast.success("Kept private", { description: "It stays on this computer and is never sent to Claude." });
                  focusFirstHeading();
                },
              })
            }
          >
            Keep private
          </Button>
        </div>
      </div>
    </article>
  );
}
