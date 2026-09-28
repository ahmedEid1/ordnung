/**
 * Proof of a sent letter — the small decisions the page makes itself (what the server decides comes
 * with the overview: what each proof shows, what's missing, the timeline, what the letter waits for).
 */
import type { Document, Draft, ProofKind, ProofOverview, WaitingEntry, WaitingStatus } from "@/api/types";
import { PROOF_KINDS } from "@/api/types";

/** The proof kinds that fit each way of sending, most useful first (as the server's `CHANNEL_PROOFS`). */
const CHANNEL_PROOFS: Record<string, readonly ProofKind[]> = {
  registered_letter: ["posting_receipt", "delivery_record", "return_receipt"],
  fax: ["fax_report"],
  email: ["sent_email"],
  online_button: ["cancel_confirmation"],
};

/** Every kind, the ones that fit the channel first (for the kind picker). */
export function proofKindsFor(channel: string | null | undefined): ProofKind[] {
  const fitting = CHANNEL_PROOFS[channel ?? ""] ?? [];
  return [...fitting, ...PROOF_KINDS.filter((k) => !fitting.includes(k))];
}

/** An Einschreiben bought online has no posting receipt: the printout of its stamp ("other") comes first. */
const ONLINE_STAMP_PROOFS: readonly ProofKind[] = ["other", "delivery_record", "return_receipt"];

/** The kind to suggest next: the first fitting one the letter doesn't have yet, else "other". */
export function suggestedKind(channel: string | null | undefined, have: readonly ProofKind[], trackingFormat?: string | null): ProofKind {
  const fitting = channel === "registered_letter" && trackingFormat === "online_stamp" ? ONLINE_STAMP_PROOFS : (CHANNEL_PROOFS[channel ?? ""] ?? []);
  return fitting.find((k) => !have.includes(k)) ?? "other";
}

/** What the day of a proof means, per kind ("Posted on", "Delivered on" …). */
export const PROOF_DAY_LABEL: Record<ProofKind, string> = {
  posting_receipt: "Posted on",
  delivery_record: "Delivered on",
  return_receipt: "Handed over on",
  fax_report: "Faxed on",
  sent_email: "Sent on",
  cancel_confirmation: "Cancelled on",
  other: "Date it shows",
};

/** Only a registered letter (Einschreiben) has a tracking number — a plain letter has none (as the server). */
export function takesTrackingNumber(channel: string | null | undefined): boolean {
  return channel === "registered_letter";
}

/** The day a proof of this kind shows is the sending day (so the form starts with it). */
export const SENDING_DAY_KINDS: readonly ProofKind[] = ["posting_receipt", "fax_report", "sent_email", "cancel_confirmation"];

/**
 * `Nachweis Kündigung Mitgliedschaft FW-4711 2026-09-10.pdf` — the same name the server gives the file
 * (`drafts/sent.py nachweis_file_name`): the subject without characters file systems refuse, and the day.
 */
export function nachweisFileName(d: Pick<Draft, "subject" | "sent_at" | "created_at">): string {
  const refused = '\\/:*?"<>|';
  const cleaned = [...(d.subject || "Schreiben")].map((c) => (c.charCodeAt(0) < 32 || refused.includes(c) ? " " : c)).join("");
  const words = cleaned.split(/\s+/).join(" ").slice(0, 80).trim() || "Schreiben";
  return `Nachweis ${words} ${(d.sent_at ?? d.created_at).slice(0, 10)}.pdf`;
}

/** A proof's own page: under its letter (and Letters in the nav), never the Inbox's letter viewer. */
export const proofFileHref = (draftId: string, docId: string) => `/letters/${draftId}/proofs/${docId}`;

/** Whether the server draws a picture of the file (a photo or a PDF page); else the kind's icon is shown. */
export function hasPicture(doc: Pick<Document, "mime">): boolean {
  return doc.mime.startsWith("image/") || doc.mime === "application/pdf";
}

/** What to add first, by how the letter went ("your posting receipt"; an Einschreiben bought online has none — the
 * printout of its stamp); `null` when nothing fits. */
export function startWith(channel: string | null | undefined, trackingFormat?: string | null): string | null {
  switch (channel) {
    case "registered_letter":
      return trackingFormat === "online_stamp" ? "a printout or screenshot of your online stamp" : "a photo of your posting receipt";
    case "fax":
      return "your fax transmission report";
    case "email":
      return "the sent e-mail, saved as a file";
    case "online_button":
      return "the cancel button's confirmation page";
    default:
      return null;
  }
}

/** How the waiting box looks for each status (overdue in red, as on Waiting for and the Letters count). */
export const WAITING_TONE: Record<WaitingStatus, "info" | "danger" | "success"> = {
  waiting: "info",
  overdue: "danger",
  answered: "success",
  closed: "info",
};

/** Proofs of the kinds already added (to suggest the next one). */
export function kindsIn(overview: ProofOverview | undefined): ProofKind[] {
  return (overview?.proofs ?? []).map((p) => p.proof.kind);
}

/** "Waiting for a written confirmation…", "Still waiting for …", "Did their letter bring …?" */
export function waitingTitle(entry: Pick<WaitingEntry, "status" | "title">): string {
  const what = entry.title.charAt(0).toLowerCase() + entry.title.slice(1);
  switch (entry.status) {
    case "overdue":
      return `Still waiting for ${what}`;
    case "answered":
      return `Did their letter bring ${what}?`;
    case "closed":
      return `Closed: ${what}`;
    default:
      return `Waiting for ${what}`;
  }
}
