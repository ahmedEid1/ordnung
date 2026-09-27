/**
 * E-mails and what they brought: an e-mail lists its attachments and what became of each (a letter
 * of its own — linked —, already in Ordnung, a picture inside the e-mail, listed only, not added with
 * the reason); a letter that came attached to an e-mail links back to it.
 */
import { Link } from "react-router";
import { ArrowRight, CircleDashed, CircleX, FileCheck, Files, ImageOff, Mail, Paperclip, type LucideIcon } from "lucide-react";
import type { AttachmentOutcome, DocumentDetail, EmailAttachment } from "@/api/types";
import { TONES, type Tone } from "@/lib/copy";
import { cn } from "@/lib/utils";
import { PanelSection } from "./PanelSection";

/** What each outcome is called on the e-mail (the server's `detail` says the rest, e.g. why it was refused). */
export const ATTACHMENT_OUTCOME_COPY = {
  added: { label: "Added as its own letter", icon: FileCheck, tone: "ok" },
  known: { label: "Already in Ordnung", icon: Files, tone: "neutral" },
  inline: { label: "A picture inside the e-mail (a logo or similar) — not read", icon: ImageOff, tone: "neutral" },
  not_read: { label: "Not read — Ordnung only reads PDFs and photos from e-mails", icon: CircleDashed, tone: "neutral" },
  refused: { label: "Not added", icon: CircleX, tone: "danger" },
  over_limit: { label: "Not read", icon: CircleDashed, tone: "warn" },
} satisfies Record<AttachmentOutcome, { label: string; icon: LucideIcon; tone: Tone }>;

/**
 * A reason the server wrote as a sentence, continued after "Not added — ": its first letter
 * lower-cased — unless its first word is a name ("Ordnung isn't allowed…", "Claude…") or an
 * abbreviation ("PDF…"), which keep their capitals.
 */
export function reasonClause(reason: string): string {
  const first = reason.match(/^[^\s,.;:—–-]+/)?.[0] ?? "";
  if (/^(Ordnung|Claude)(\b|'|’)/.test(first) || /^[A-Z0-9]{2,}/.test(first)) return reason;
  return reason.charAt(0).toLowerCase() + reason.slice(1);
}

/** The line under an attachment's name: what became of it — and why, when the server said (a refusal's reason). */
export function attachmentLine(a: Pick<EmailAttachment, "outcome" | "detail">): string {
  const label = ATTACHMENT_OUTCOME_COPY[a.outcome].label;
  return (a.outcome === "refused" || a.outcome === "over_limit") && a.detail ? `${label} — ${reasonClause(a.detail)}` : label;
}

export function EmailParts({ detail }: { detail: DocumentDetail }) {
  const { email, attachments } = detail;
  const more = detail.attachments_more;
  if (!email && !attachments.length) return null;
  return (
    <>
      {email ? (
        <PanelSection id="email" title="Came with an e-mail" icon={Mail}>
          <Link
            to={`/documents/${email.id}`}
            className="card flex items-center gap-3 px-4 py-3 transition-colors hover:border-line-strong hover:bg-surface-2/50 focus-visible:ring-2 focus-visible:ring-accent sm:px-5"
          >
            <Mail className="size-4 shrink-0 text-muted" aria-hidden />
            <span className="min-w-0 flex-1">
              <span className="block text-[14px] font-medium text-ink [overflow-wrap:anywhere]">{email.title ?? email.filename}</span>
              <span className="block text-[12.5px] text-muted">This letter was attached to it.</span>
            </span>
            <ArrowRight className="size-4 shrink-0 text-faint" aria-hidden />
          </Link>
        </PanelSection>
      ) : null}
      {attachments.length ? (
        <PanelSection id="attachments" title="Attachments" icon={Paperclip} count={attachments.length + more}>
          <ul className="card divide-y divide-line overflow-hidden">
            {attachments.map((a, i) => (
              <AttachmentRow key={`${a.filename}-${i}`} attachment={a} />
            ))}
          </ul>
          {more ? (
            <p className="mt-2 text-[13px] leading-5 text-muted">
              {more === 1 ? "1 more part of this e-mail isn't listed" : `${more} more parts of this e-mail aren't listed`} — Ordnung lists the first {attachments.length}.
            </p>
          ) : null}
        </PanelSection>
      ) : null}
    </>
  );
}

function AttachmentRow({ attachment: a }: { attachment: EmailAttachment }) {
  const c = ATTACHMENT_OUTCOME_COPY[a.outcome];
  const t = TONES[c.tone];
  const Icon = c.icon;
  const line = attachmentLine(a);
  return (
    <li className="relative flex items-start gap-3 px-4 py-3 sm:px-5">
      <span className={cn("mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg", t.soft)}>
        <Icon className={cn("size-3.5", t.icon)} aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        {a.doc_id ? (
          <Link
            to={`/documents/${a.doc_id}`}
            title={a.filename}
            className="line-clamp-2 break-words text-[14px] font-medium leading-snug text-ink outline-none [overflow-wrap:anywhere] after:absolute after:inset-0 after:content-[''] hover:text-accent focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-accent"
          >
            {a.filename}
          </Link>
        ) : (
          <p title={a.filename} className="line-clamp-2 break-words text-[14px] font-medium leading-snug text-ink [overflow-wrap:anywhere]">
            {a.filename}
          </p>
        )}
        <p className={cn("mt-0.5 text-[12.5px] leading-5", c.tone === "danger" ? t.text : c.tone === "ok" ? t.text : "text-muted")}>{line}</p>
      </div>
      {a.doc_id ? <ArrowRight className="mt-1 size-4 shrink-0 text-faint" aria-hidden /> : null}
    </li>
  );
}
