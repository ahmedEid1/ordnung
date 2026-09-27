import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { ArrowLeft, Download, Lock, Trash2 } from "lucide-react";
import { api } from "@/api/endpoints";
import { useRemoveProof } from "@/api/hooks";
import type { DocumentDetail } from "@/api/types";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Dialog } from "@/components/ui/Dialog";
import { toast } from "@/components/ui/Toast";
import { PROOF_KIND_COPY, TONES, copyFor } from "@/lib/copy";
import { cn } from "@/lib/utils";
import { hasPicture } from "./proof";

/**
 * A proof file opened on its own (`/letters/:id/proofs/:docId`): it belongs to the letter it proves,
 * never to the Inbox — so this says what it is and for which letter, shows the
 * file, and removes it as a proof (not as "a letter"). Proof files are never read by AI, so there is no
 * kind, no "what you need to do" and no evidence here.
 */
export function ProofFileView({ detail, draftId }: { detail: DocumentDetail; draftId?: string }) {
  const doc = detail.document;
  const link = detail.proof_of.find((l) => l.draft_id === draftId) ?? detail.proof_of[0]!;
  const copy = copyFor(PROOF_KIND_COPY, link.kind);
  const remove = useRemoveProof();
  const navigate = useNavigate();
  const [confirm, setConfirm] = useState(false);
  const pages = Math.max(1, detail.pages.length || doc.pages);
  const letterHref = `/letters/${link.draft_id}`;
  return (
    <div className="mx-auto max-w-3xl">
      <header className="mb-5 flex min-w-0 gap-3">
        <span className={cn("grid size-11 shrink-0 place-items-center rounded-xl", TONES[copy.tone].soft, TONES[copy.tone].icon)} aria-hidden>
          <copy.icon className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium text-muted">Proof of sending</p>
          <h1 className="display mt-0.5 text-[24px] font-semibold leading-tight text-ink [overflow-wrap:anywhere] sm:text-[28px]">{copy.label}</h1>
          <p className="mt-1.5 text-[14px] text-ink/85 [overflow-wrap:anywhere]">
            For your letter{" "}
            <Link to={letterHref} className="font-medium underline decoration-line-strong underline-offset-2 hover:decoration-current" lang="de">
              {link.subject || "Your letter"}
            </Link>
            {detail.proof_of.length > 1 ? <span className="text-muted"> and {detail.proof_of.length - 1} more</span> : null}
          </p>
          <p className="mt-1 flex items-center gap-1.5 text-[13px] text-muted">
            <Lock className="size-3.5 shrink-0" aria-hidden />
            {doc.ai_private ? "Kept private — never sent to AI." : "This file was in Ordnung before it became a proof, and AI has read it."}
          </p>
        </div>
      </header>

      <div className="mb-5 flex flex-wrap gap-2">
        <Link to={letterHref} className={buttonVariants({ variant: "secondary", size: "sm" })}>
          <ArrowLeft aria-hidden />
          Back to the letter
        </Link>
        <a href={api.fileUrl(doc.id)} download={doc.filename} className={buttonVariants({ variant: "secondary", size: "sm" })}>
          <Download aria-hidden />
          Download the file
        </a>
        <Button size="sm" variant="ghost" icon={Trash2} className="text-danger-ink hover:bg-danger-soft hover:text-danger-ink" onClick={() => setConfirm(true)}>
          Remove this proof
        </Button>
      </div>

      <Card padding="md">
        <p className="mb-3 truncate text-[13px] text-muted" title={doc.filename}>
          {doc.filename}
        </p>
        {hasPicture(doc) ? (
          <div className="space-y-4">
            {Array.from({ length: pages }, (_, i) => (
              <img
                key={i}
                src={api.pageUrl(doc.id, i + 1)}
                alt={pages > 1 ? `${copy.label}, page ${i + 1} of ${pages}` : copy.label}
                className="mx-auto block h-auto max-w-full rounded-lg border border-line bg-white"
                loading="lazy"
              />
            ))}
          </div>
        ) : (
          <p className="text-[14px] text-ink/85">This kind of file has no picture here — download it to open it.</p>
        )}
      </Card>

      <Dialog
        open={confirm}
        onClose={() => setConfirm(false)}
        size="sm"
        title="Remove this proof?"
        description={
          doc.source === "proof"
            ? "Its file is deleted from Ordnung for good, and the letter no longer lists it as proof."
            : "The file stays in Ordnung; only the link to the letter goes."
        }
        footer={
          <>
            <Button onClick={() => setConfirm(false)}>Keep it</Button>
            <Button
              variant="danger"
              icon={Trash2}
              loading={remove.isPending}
              onClick={() =>
                remove.mutate(
                  { id: link.draft_id, proofId: link.proof_id },
                  {
                    onSuccess: () => {
                      setConfirm(false);
                      toast.success("Proof removed", { description: copy.label });
                      navigate(letterHref, { replace: true });
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
    </div>
  );
}
