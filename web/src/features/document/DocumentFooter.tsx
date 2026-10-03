/**
 * Provenance + housekeeping: "Read by Claude on 28 Sep 2026 · text of 2 pages", and the actions
 * Reprocess · Download original · Delete (with a confirmation listing what would disappear).
 */
import { useState } from "react";
import { useNavigate } from "react-router";
import { Download, Lock, PenLine, RotateCw, ScanText, Sparkles, Trash2 } from "lucide-react";
import type { DocumentDetail, DocumentKind } from "@/api/types";
import { api } from "@/api/endpoints";
import { useDeleteDocument, useReprocessDocument } from "@/api/hooks";
import { seedJob } from "@/api/sse";
import { formatDate } from "@/lib/format";
import { plural, prefersReducedMotion } from "@/lib/utils";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { toast } from "@/components/ui/Toast";
import { isOpenItem, openItemCounts, scamSuggestion } from "./verdict";
import { useStartDraft } from "./actions";

const NOUN: Record<string, string> = {
  deadline: "deadline",
  payment: "payment",
  appointment: "appointment",
  task: "to-do",
  expiry: "expiry date",
  reminder: "reminder",
  milestone: "milestone",
};

const joinAnd = (parts: string[]) => (parts.length < 2 ? parts.join("") : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`);

export function provenanceText(doc: DocumentDetail["document"]): string {
  const pages = plural(doc.pages, "page");
  // privacy statements name who doesn't read it, as the held card, the verdict's badge and Settings do
  if (doc.status === "held") return `Not read yet — not sent to Claude · ${pages}`;
  if (doc.ai_private) return `Kept private — not read by Claude · ${pages}`;
  if (!doc.ai_processed_at) return `Not read yet · ${pages}`;
  const when = formatDate(doc.ai_processed_at, { style: "medium" });
  return doc.text_mode === "vision" ? `Read by Claude on ${when} · from a photo, ${pages}` : `Read by Claude on ${when} · text of ${pages}`;
}

/**
 * Documents nobody writes back to (a passport, a certificate, a payslip, a receipt, an appointment card): no
 * "Draft a reply" under them (UI audit round 1). The key facts call their numbers "Numbers on this document".
 */
export const NO_REPLY_KINDS: ReadonlySet<DocumentKind> = new Set<DocumentKind>(["identity_document", "certificate", "receipt", "payslip", "appointment"]);

/**
 * The provenance line as it wraps on a phone: never inside the date, between "1" and "page", or before its dot
 * ("Read by Claude on 28 Sep 2026 ·" / "from a photo, 1 page" — UI audit round 1: "1" / "page").
 */
export function keepTogether(text: string): string {
  const [first = "", ...rest] = text.split(" · ");
  // the short tail ("from a photo, 1 page") in one piece; one text node, so the line reads (and is found) as written
  const head = first.replace(/\b(\d{1,2}) ([A-Z][a-z]{2}) (\d{4})\b/g, "$1\u00a0$2\u00a0$3").replace(/\b(\d+) (?=[a-z])/g, "$1\u00a0");
  return [head, ...rest.map((part) => part.replace(/ /g, "\u00a0"))].join("\u00a0· ");
}

/**
 * Where the letter went: nowhere while it is private, or while no model call carried it — the API knows
 * (`given_to_model`): a letter that waits, or whose call never started (Claude not installed), was not sent.
 */
export function sentText(detail: DocumentDetail): string {
  if (detail.document.ai_private) return "This letter never left your computer.";
  if (!detail.given_to_model) return "Not sent to Claude. The letter hasn't left your computer.";
  return "The letter's text or image was sent to Anthropic through your own Claude account. The file itself stays on this computer.";
}

export function DocumentFooter({ detail }: { detail: DocumentDetail }) {
  const doc = detail.document;
  const navigate = useNavigate();
  const reprocess = useReprocessDocument();
  const del = useDeleteDocument();
  const [confirm, setConfirm] = useState(false);
  const draft = useStartDraft();
  const scam = Boolean(scamSuggestion(detail));
  const busy = doc.status === "queued" || doc.status === "processing";
  const counts = openItemCounts(detail.items);
  const openItems = detail.items.filter(isOpenItem);
  const Icon = doc.ai_private ? Lock : doc.text_mode === "vision" ? ScanText : Sparkles;
  const reply = !scam && !busy && doc.direction === "incoming" && !doc.ai_private && !(doc.kind && NO_REPLY_KINDS.has(doc.kind));

  return (
    <footer className="border-t border-line pt-5">
      {/* a chip on one line; wrapped on a phone, it keeps a card's corners, not a stretched pill's (UI audit round 1) */}
      <p className="inline-flex max-w-full items-start gap-1.5 rounded-xl border border-line bg-surface px-3 py-1 text-[12.5px] leading-5 text-muted">
        <Icon className="mt-[3px] size-3.5 shrink-0" aria-hidden />
        <span className="min-w-0 [overflow-wrap:anywhere]">{keepTogether(provenanceText(doc))}</span>
      </p>
      <p className="mt-2 text-[12px] leading-5 text-muted">{sentText(detail)}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {/* a letter that couldn't be read has its "Try again" at the top: no second button for the same thing */}
        {!doc.ai_private && !busy && doc.status !== "failed" ? (
          <Button
            size="sm"
            icon={RotateCw}
            loading={reprocess.isPending}
            onClick={() =>
              reprocess.mutate(doc.id, {
                onSuccess: (job) => {
                  seedJob({ job_id: job.id, doc_id: doc.id, stage: "intake", progress: 0, status: "running" });
                  // the live progress appears at the top of the panel
                  window.scrollTo({ top: 0, behavior: prefersReducedMotion() ? "auto" : "smooth" });
                },
              })
            }
          >
            Read again
          </Button>
        ) : null}
        {reply ? (
          <Button
            size="sm"
            icon={PenLine}
            loading={draft.pending}
            onClick={() => draft.start("general_reply", { doc_id: doc.id, party_id: doc.party_id, case_id: doc.case_id })}
          >
            Draft a reply
          </Button>
        ) : null}
        <a href={api.fileUrl(doc.id)} download={doc.filename} className={buttonVariants({ size: "sm" })}>
          <Download aria-hidden />
          Download original
        </a>
        {/* apart from the others at the end of its row — also when it wraps onto a row of its own (UI audit round 1) */}
        <Button
          size="sm"
          variant="ghost"
          icon={Trash2}
          className="ml-auto text-danger-ink hover:bg-danger-soft hover:text-danger-ink"
          onClick={() => setConfirm(true)}
        >
          Delete
        </Button>
      </div>

      <Dialog
        open={confirm}
        onClose={() => setConfirm(false)}
        title="Delete this letter?"
        description="The file, its page images and everything Ordnung read from it are removed from this computer."
        size="sm"
        footer={
          <>
            <Button onClick={() => setConfirm(false)}>Keep it</Button>
            <Button
              variant="danger"
              icon={Trash2}
              loading={del.isPending}
              onClick={() =>
                del.mutate(doc.id, {
                  onSuccess: () => {
                    setConfirm(false);
                    toast.success("Letter deleted", { description: doc.title ?? doc.filename });
                    navigate("/inbox");
                  },
                })
              }
            >
              Delete letter
            </Button>
          </>
        }
      >
        {openItems.length ? (
          <div className="rounded-xl border border-danger/25 bg-danger-soft px-4 py-3">
            <p className="text-[13.5px] font-semibold text-danger-ink">This also removes {joinAnd(counts.map((c) => plural(c.count, NOUN[c.kind] ?? "to-do")))} from your to-dos & dates:</p>
            <ul className="mt-2 space-y-1 text-[13px] text-ink/85">
              {openItems.slice(0, 5).map((i) => (
                <li key={i.id} className="flex gap-2">
                  <span aria-hidden className="mt-[7px] size-1 shrink-0 rounded-full bg-danger" />
                  <span className="min-w-0">
                    {i.title}
                    {i.due_date ? <span className="text-muted"> — {formatDate(i.due_date, { style: "day" })}</span> : null}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-[13.5px] text-muted">No open to-dos come from this letter.</p>
        )}
        {detail.drafts.length ? <p className="mt-3 text-[13px] text-muted">Letters you drafted about it stay in Letters.</p> : null}
        {detail.proof_of.length ? (
          <p className="mt-3 rounded-xl border border-warn/25 bg-warn-soft px-4 py-3 text-[13.5px] text-warn-ink">
            This file is also the proof of {detail.proof_of.length === 1 ? "your letter" : "your letters"} {detail.proof_of.map((l) => `“${l.subject}”`).join(", ")}: deleting it removes that proof too.
          </p>
        ) : null}
      </Dialog>
    </footer>
  );
}
