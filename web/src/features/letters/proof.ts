/**
 * Proof of a sent letter — the small decisions the page makes itself (what the server decides comes
 * with the overview: what each proof shows, what's missing, the timeline, what the letter waits for).
 */
import type { Draft, ProofKind, ProofOverview, WaitingEntry, WaitingStatus } from "@/api/types";
import { PROOF_KINDS } from "@/api/types";
import { firstLine } from "./logic";

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

/** The kind to suggest next: the first fitting one the letter doesn't have yet, else "other". */
export function suggestedKind(channel: string | null | undefined, have: readonly ProofKind[]): ProofKind {
  return (CHANNEL_PROOFS[channel ?? ""] ?? []).find((k) => !have.includes(k)) ?? "other";
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

/** A tracking number only belongs to a letter that went by post. */
export function takesTrackingNumber(channel: string | null | undefined): boolean {
  return channel === "registered_letter" || channel === "letter";
}

/** `nachweis-kuendigung-FitWell-Studios-2026-09-22.pdf`. */
export function nachweisFileName(d: Pick<Draft, "kind" | "recipient_block" | "sent_at" | "created_at">): string {
  const to = firstLine(d.recipient_block)
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");
  return ["nachweis", to, (d.sent_at ?? d.created_at).slice(0, 10)].filter(Boolean).join("-") + ".pdf";
}

/** How the waiting box looks for each status. */
export const WAITING_TONE: Record<WaitingStatus, "info" | "warn" | "success"> = {
  waiting: "info",
  overdue: "warn",
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
