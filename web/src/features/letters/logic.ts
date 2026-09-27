/**
 * Letters (SPEC §11, §21): pure helpers for the composer and the editor.
 *
 * - Objection letters are offered only when the related decision's remedy
 *   (Rechtsbehelfsbelehrung) is an Einspruch or Widerspruch; the type and addressee come from the
 *   letter, never from a guess. Everything else gets an explanation and a pointer to advice.
 * - The composer can be opened pre-filled from anywhere: `/letters?kind=cancellation&contract=ctr_x`,
 *   `?kind=objection&doc=doc_x`, `?kind=general_reply&doc=doc_x` or `&to=pty_x`.
 */
import { addDays, parseISO } from "date-fns";
import {
  DRAFT_KINDS,
  SEND_CHANNELS,
  type Area,
  type Contract,
  type Document,
  type Draft,
  type DraftCheck,
  type DraftKind,
  type LetterAdvice,
  type Remedy,
  type SendChannel,
  type SendChannelKind,
} from "@/api/types";
import { SEND_CHANNEL_COPY, copyFor } from "@/lib/copy";
import { ADVICE_LINKS, type AdviceLink } from "@/components/ui/Disclaimer";
import { toISODate } from "@/lib/format";
import { offersEndingLetter } from "@/features/contracts/links";

// ------------------------------------------------------------------------------------------------
// Composer pre-fill
// ------------------------------------------------------------------------------------------------

export interface ComposerPrefill {
  kind: DraftKind | null;
  contractId: string | null;
  docId: string | null;
  partyId: string | null;
}

/** Query parameters that open the composer. `party` is accepted but also opens the People drawer. */
export const COMPOSER_PARAMS = ["new", "kind", "contract", "doc", "to"] as const;

export function isDraftKind(v: string | null | undefined): v is DraftKind {
  return Boolean(v) && (DRAFT_KINDS as readonly string[]).includes(v!);
}

/** Read the composer pre-fill from the URL; `null` when the composer should stay closed. */
export function parsePrefill(params: URLSearchParams): ComposerPrefill | null {
  const kindParam = params.get("kind");
  const contractId = params.get("contract") || null;
  const docId = params.get("doc") || null;
  const partyId = params.get("to") || null;
  const open = params.has("new") || isDraftKind(kindParam) || Boolean(contractId || docId || partyId);
  if (!open) return null;
  const kind: DraftKind | null = isDraftKind(kindParam) ? kindParam : contractId ? "cancellation" : docId || partyId ? "general_reply" : null;
  return { kind, contractId, docId, partyId };
}

// ------------------------------------------------------------------------------------------------
// Objection eligibility
// ------------------------------------------------------------------------------------------------

export type ObjectionCheck =
  | {
      ok: true;
      /** the letter's own instructions, or `null` when the law gives the remedy (a court order, a landlord's notice) */
      remedy: (Remedy & { type: "einspruch" | "widerspruch" }) | null;
      term: "Einspruch" | "Widerspruch";
      /** the remedy comes from the law, not the letter's instructions (§ 694, § 700 ZPO; § 574 BGB) */
      statutory: boolean;
    }
  | { ok: false; reason: "missing" | "klage" | "none" | "unclear" | "no_hardship"; title: string; body: string; advice: AdviceLink[] };

export function adviceFor(area: Area | null | undefined): AdviceLink[] {
  switch (area) {
    case "tax":
      return ADVICE_LINKS.tax;
    case "residence":
    case "study":
      return ADVICE_LINKS.residence;
    case "home":
      return ADVICE_LINKS.rent;
    default:
      return ADVICE_LINKS.consumer;
  }
}

/**
 * The remedy the law gives these letters, whatever their instructions were read as (mirrors
 * `STATUTORY_REMEDIES` in `src/ordnung/drafts/templates.py`).
 */
export const STATUTORY_REMEDY: Partial<Record<NonNullable<Document["kind"]>, "Einspruch" | "Widerspruch">> = {
  court_payment_order: "Widerspruch",
  enforcement_order: "Einspruch",
  landlord_notice: "Widerspruch",
};

/**
 * Can Ordnung draft an objection against this letter? (SPEC §21 "Remedies & letters") `card` is the
 * letter's "get advice" card, when loaded: a landlord's notice without notice period has no hardship
 * objection (§ 574 Abs. 1 S. 2 BGB) — its card offers no letter (`draft: null`), and the server refuses
 * one (`compose.objection_remedy`) with the card's words.
 */
export function objectionCheck(
  doc: (Pick<Document, "remedy" | "area"> & Partial<Pick<Document, "kind">>) | null | undefined,
  card?: LetterAdvice | null,
): ObjectionCheck {
  const remedy = doc?.remedy ?? null;
  const advice = adviceFor(doc?.area);
  const statutory = doc?.kind ? STATUTORY_REMEDY[doc.kind] : undefined;
  if (doc?.kind === "landlord_notice" && card?.kind === "landlord_notice" && card.draft === null) {
    const [fact] = card.facts;
    return {
      ok: false,
      reason: "no_hardship",
      title: fact?.title ?? "There is no hardship objection against this notice",
      body: fact?.text ?? "The hardship objection doesn't apply to a notice without notice period. Get advice at once.",
      advice,
    };
  }
  if (statutory) {
    const own = remedy && (remedy.type === "einspruch" || remedy.type === "widerspruch") ? (remedy as Remedy & { type: "einspruch" | "widerspruch" }) : null;
    return { ok: true, remedy: own, term: statutory, statutory: true };
  }
  if (remedy && (remedy.type === "einspruch" || remedy.type === "widerspruch")) {
    return {
      ok: true,
      remedy: remedy as Remedy & { type: "einspruch" | "widerspruch" },
      term: remedy.type === "einspruch" ? "Einspruch" : "Widerspruch",
      statutory: false,
    };
  }
  if (!remedy) {
    return {
      ok: false,
      reason: "missing",
      title: "This letter doesn't explain how to object",
      body:
        "Ordnung only drafts an objection when the decision includes instructions on how to object (Rechtsbehelfsbelehrung). Without them the period can be longer — often a year — but please get advice rather than rely on that.",
      advice,
    };
  }
  if (remedy.type === "klage") {
    return {
      ok: false,
      reason: "klage",
      title: "This decision can only be challenged in court",
      body: "The letter says the next step is a court action (Klage). Ordnung doesn't draft those — please get advice soon, court deadlines are strict.",
      advice,
    };
  }
  if (remedy.type === "none") {
    return {
      ok: false,
      reason: "none",
      title: "There is no objection against this letter",
      body: "The letter doesn't offer an objection. If you disagree, you can still reply and ask a question — or get advice.",
      advice,
    };
  }
  return {
    ok: false,
    reason: "unclear",
    title: "We couldn't tell how to object",
    body: "The instructions in the letter were unclear, so Ordnung won't guess the type of objection or where it must go. Please get advice before the deadline.",
    advice,
  };
}

/** Documents a letter can relate to (read, not in the trash). */
export function usableDocuments(docs: Document[]): Document[] {
  return docs
    .filter((d) => !d.deleted_at && (d.status === "processed" || d.status === "needs_review"))
    .sort((a, b) => ((b.doc_date ?? b.received_date ?? "") < (a.doc_date ?? a.received_date ?? "") ? -1 : 1));
}

export function objectionDocuments(docs: Document[]): Document[] {
  return usableDocuments(docs).filter((d) => objectionCheck(d).ok);
}

/** Contracts a cancellation (or, for a job, resignation) letter can end — soonest send-by first. */
export function cancellableContracts(contracts: Contract[]): Contract[] {
  return contracts
    .filter((c) => offersEndingLetter(c))
    .sort((a, b) => ((a.computed?.send_by ?? "9999") < (b.computed?.send_by ?? "9999") ? -1 : 1));
}

// ------------------------------------------------------------------------------------------------
// Drafts
// ------------------------------------------------------------------------------------------------

/** The follow-up to-do is created 21 days after sending (SPEC §11). */
export const FOLLOW_UP_DAYS = 21;

/** Kinds with a longer answer time: a data request gets a month (Art. 12(3) GDPR), so 35 days. */
export const FOLLOW_UP_DAYS_BY_KIND: Partial<Record<DraftKind, number>> = { data_access: 35 };

export function followUpDate(sentOn: string, kind?: DraftKind | null): string {
  const days = (kind && FOLLOW_UP_DAYS_BY_KIND[kind]) || FOLLOW_UP_DAYS;
  return toISODate(addDays(parseISO(sentOn.slice(0, 10)), days));
}

/** First line of an address block ("FunkNetz Mobil GmbH"). */
export function firstLine(block: string | null | undefined): string {
  return (block ?? "").split("\n").map((l) => l.trim()).find(Boolean) ?? "";
}

const KIND_TITLE: Record<DraftKind, string> = {
  cancellation: "Cancellation",
  objection: "Objection",
  general_reply: "Reply",
  withdrawal: "Withdrawal",
  extension_request: "Request for more time",
  payment_plan: "Instalment request",
  defect_notice: "Defect notice",
  data_access: "Data request",
  receipts_inspection: "Receipts request",
  deposit_return: "Deposit request",
  address_change: "New address",
};

/** German file-name stems of the PDF ("Kuendigung-FunkNetz-….pdf"). */
const PDF_STEM: Record<DraftKind, string> = {
  cancellation: "Kuendigung",
  objection: "Einspruch",
  general_reply: "Schreiben",
  withdrawal: "Widerruf",
  extension_request: "Fristverlaengerung",
  payment_plan: "Ratenzahlung",
  defect_notice: "Maengelanzeige",
  data_access: "Auskunft-Art15-DSGVO",
  receipts_inspection: "Belegeinsicht",
  deposit_return: "Kaution",
  address_change: "Adressaenderung",
};

/** English page title: "Cancellation to FunkNetz Mobil GmbH". */
export function draftTitle(d: Pick<Draft, "kind" | "recipient_block">, partyName?: string | null): string {
  const to = partyName || firstLine(d.recipient_block);
  return to ? `${KIND_TITLE[d.kind]} to ${to}` : `${KIND_TITLE[d.kind]} letter`;
}

/** A readable PDF file name: "Kuendigung-FunkNetz-Mobil-GmbH-2026-09-28.pdf". */
export function pdfFileName(d: Pick<Draft, "kind" | "recipient_block" | "created_at">): string {
  const kind = PDF_STEM[d.kind];
  const to = firstLine(d.recipient_block)
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");
  return [kind, to, d.created_at.slice(0, 10)].filter(Boolean).join("-") + ".pdf";
}

/** Add a cache-busting version to API asset URLs (never to data:/blob: URLs used in demo mode). */
export function versioned(url: string, version: string | null | undefined): string {
  if (!version || !url.startsWith("/")) return url;
  return `${url}${url.includes("?") ? "&" : "?"}v=${encodeURIComponent(version)}`;
}

export type EditableFields = Pick<Draft, "subject" | "body" | "sender_block" | "recipient_block" | "place_date">;
export const EDITABLE_KEYS = ["subject", "body", "sender_block", "recipient_block", "place_date"] as const;

export function editableOf(d: Draft): EditableFields {
  return { subject: d.subject, body: d.body, sender_block: d.sender_block, recipient_block: d.recipient_block, place_date: d.place_date };
}

/** The fields that changed (for a minimal PATCH). */
export function changedFields(base: EditableFields, next: EditableFields): Partial<EditableFields> {
  const out: Partial<EditableFields> = {};
  for (const k of EDITABLE_KEYS) if (base[k] !== next[k]) out[k] = next[k];
  return out;
}

/** Placeholders a person must still fill in ("…", "[Name]", "XXX"). */
export function findPlaceholders(text: string): string[] {
  const found = text.match(/…|\.\.\.|\[[^\]\n]{1,40}\]|\bX{3,}\b|_{3,}/g) ?? [];
  return [...new Set(found)];
}

const VIA: Record<string, string> = {
  online_button: "with the online cancel button",
  email: "by email",
  fax: "by fax",
  letter: "by post",
  registered_letter: "by Einschreiben",
  in_person: "in person",
  portal: "through the online portal",
};

/** "by email", "by Einschreiben" … (unknown channels: empty). */
export function sentVia(channel: string | null | undefined): string {
  return channel ? (VIA[channel] ?? "") : "";
}

// ------------------------------------------------------------------------------------------------
// Sending & checks
// ------------------------------------------------------------------------------------------------

/** Allowed first, recommended on top; not-allowed ways last. */
export function rankChannels(channels: SendChannel[]): SendChannel[] {
  const score = (c: SendChannel) => (c.allowed ? 0 : 10) + (c.recommended ? 0 : 1);
  return channels
    .map((c, i) => ({ c, i }))
    .sort((a, b) => score(a.c) - score(b.c) || a.i - b.i)
    .map(({ c }) => c);
}

/** Failed checks first, then the passed ones (original order within each group). */
export function sortChecks(checks: DraftCheck[]): DraftCheck[] {
  return [...checks.filter((c) => !c.ok), ...checks.filter((c) => c.ok)];
}

export interface SendChoice {
  channel: SendChannelKind;
  label: string;
  allowed: boolean;
  recommended: boolean;
}

/** The ways offered in the dialog: the guidance's channels (best first), then the usual others. */
export function sendChoices(guidance: Draft["send_guidance"]): SendChoice[] {
  const fromGuidance = rankChannels(guidance?.channels ?? []).map((c: SendChannel) => ({
    channel: c.channel,
    label: c.label || copyFor(SEND_CHANNEL_COPY, c.channel).label,
    allowed: c.allowed,
    recommended: c.recommended,
  }));
  const seen = new Set(fromGuidance.map((c) => c.channel));
  const common: SendChannelKind[] = ["registered_letter", "letter", "email", "online_button", "portal", "fax", "in_person"];
  const rest = common
    .filter((c) => (SEND_CHANNELS as readonly string[]).includes(c) && !seen.has(c))
    .map((c) => ({ channel: c, label: copyFor(SEND_CHANNEL_COPY, c).label, allowed: guidance?.form !== "written_form" || c === "registered_letter" || c === "letter" || c === "in_person", recommended: false }));
  return [...fromGuidance.filter((c) => c.allowed), ...rest, ...fromGuidance.filter((c) => !c.allowed)];
}
