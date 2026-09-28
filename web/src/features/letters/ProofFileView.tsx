import { Fragment, useState } from "react";
import { Link, useNavigate } from "react-router";
import { ArrowLeft, Download, Lock, Trash2 } from "lucide-react";
import { api } from "@/api/endpoints";
import { useRemoveProof } from "@/api/hooks";
import type { DocumentDetail, ProofKind } from "@/api/types";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { toast } from "@/components/ui/Toast";
import { hasLongWord } from "@/features/document/verdict";
import { PROOF_KIND_COPY, TONES, copyFor } from "@/lib/copy";
import { protectRefs } from "@/lib/glue";
import { cn } from "@/lib/utils";
import { hasPicture } from "./proof";
import { RemoveProofDialog } from "./RemoveProofDialog";

/** "Proof: Posting receipt" — the proof page's name in the top bar and the tab: its kind, never the file's name. */
export function proofPageTitle(kind: ProofKind): string {
  return `Proof: ${copyFor(PROOF_KIND_COPY, kind).label.replace(/\s*\([^)]*\)$/, "")}`;
}

/**
 * A file name that breaks after its underscores, as between words ("…_Einwurf-Einschreiben_" / "FunkNetz_…"),
 * and inside a part only when that part is wider than the line; references stay whole ("FN-88213407").
 * The break points are `<wbr>`: nothing is added to the text, so it copies as it is.
 */
function FileName({ name }: { name: string }) {
  return (
    <>
      {name.split(/(?<=_)/).map((part, i) => (
        <Fragment key={i}>
          {i ? <wbr /> : null}
          {protectRefs(part)}
        </Fragment>
      ))}
    </>
  );
}

/**
 * A proof file opened on its own (`/letters/:id/proofs/:docId`): it belongs to the letter it proves,
 * never to the Inbox — so this says what it is and for which letter, shows the file (its full name —
 * the one place it isn't cut short), and removes it as a proof (not as "a letter"), with the same
 * confirmation as the letter's proof card. Proof files are never read by Claude, so there is no kind,
 * no "what you need to do" and no evidence here.
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
    // lined up with the breadcrumb, like the letter it belongs to (never a centred column)
    <div className="max-w-3xl">
      {/* on phones the title has the whole width (as on the letter page): "(Einlieferungsbeleg)" never breaks */}
      <header className="mb-5 flex min-w-0 gap-3">
        <span className={cn("hidden size-11 shrink-0 place-items-center rounded-xl sm:grid", TONES[copy.tone].soft, TONES[copy.tone].icon)} aria-hidden>
          <copy.icon className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium text-muted">Proof of sending</p>
          {/* the detail pages' one title size (--text-detail); a very long word one step smaller on phones */}
          <h1 className={cn("display mt-0.5 font-semibold text-ink [overflow-wrap:anywhere]", hasLongWord(copy.label) ? "text-detail-long" : "text-detail")}>{copy.label}</h1>
          <p className="mt-1.5 text-[14px] text-ink/85 [overflow-wrap:anywhere]">
            For your letter{" "}
            <Link to={letterHref} className="font-medium underline decoration-line-strong underline-offset-2 hover:decoration-current" lang="de">
              {link.subject || "Your letter"}
            </Link>
            {detail.proof_of.length > 1 ? <span className="text-muted"> and {detail.proof_of.length - 1} more</span> : null}
          </p>
          <p className="mt-1 flex items-start gap-1.5 text-[13px] text-muted">
            <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            {/* private *and* never read: a letter Claude read before someone marked it private is said to be so */}
            <span>{doc.ai_private && !doc.ai_processed_at ? "Kept private — never sent to Claude." : "This file was in Ordnung before it became a proof, and it was given to Claude to read."}</span>
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
        {/* the file's whole name (phones can't show a tooltip): it wraps, never runs out of the card */}
        <p className="mb-3 text-[13px] leading-5 text-muted [overflow-wrap:anywhere]" title={doc.filename}>
          <FileName name={doc.filename} />
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

      <RemoveProofDialog
        open={confirm}
        onClose={() => setConfirm(false)}
        kind={link.kind}
        document={doc}
        pending={remove.isPending}
        onRemove={() =>
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
      />
    </div>
  );
}
