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
  type Item,
  type LetterAdvice,
  type Remedy,
  type SendChannel,
  type SendChannelKind,
} from "@/api/types";
import { SEND_CHANNEL_COPY, copyFor } from "@/lib/copy";
import { ADVICE_LINKS, type AdviceLink } from "@/components/ui/Disclaimer";
import { toISODate } from "@/lib/format";
import { offersEndingLetter } from "@/features/contracts/links";
import { isRollingContract } from "@/features/contracts/model";

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

/** Papers nobody writes back to: an ID document or a payslip is kept, never answered. */
const NOT_ANSWERED = new Set<Document["kind"]>(["identity_document", "payslip"]);

/** The date a letter is known by: its own date, else the day it arrived. */
export function letterDate(d: Pick<Document, "doc_date" | "received_date">): string | null {
  return d.doc_date ?? d.received_date ?? null;
}

/** Documents a letter can relate to (read, not in the trash, not an ID or a payslip) — newest first. */
export function usableDocuments(docs: Document[]): Document[] {
  return docs
    .filter((d) => !d.deleted_at && (d.status === "processed" || d.status === "needs_review") && !NOT_ANSWERED.has(d.kind))
    .sort((a, b) => ((letterDate(b) ?? "") < (letterDate(a) ?? "") ? -1 : 1));
}

type DeadlineItem = Pick<Item, "kind" | "status" | "due_date"> & Partial<Pick<Item, "date_spec">>;

/** The open objection deadline among a letter's to-dos (the day the objection must arrive by), if any. */
export function objectionDeadline<T extends DeadlineItem>(items: readonly T[]): T | null {
  const open = items.filter((i) => i.kind === "deadline" && i.due_date && i.date_spec?.nature === "objection" && i.status !== "done" && i.status !== "dismissed");
  return open.sort((a, b) => (a.due_date! < b.due_date! ? -1 : a.due_date! > b.due_date! ? 1 : 0))[0] ?? null;
}

export function objectionDocuments(docs: Document[]): Document[] {
  return usableDocuments(docs).filter((d) => objectionCheck(d).ok);
}

/**
 * Contracts a cancellation (or, for a job, resignation) letter can end — soonest send-by first. A contract
 * you can cancel any month has no send-by that runs out (its date only says when it would end): it follows
 * the dated ones, as on the Contracts page.
 */
export function cancellableContracts(contracts: Contract[]): Contract[] {
  const key = (c: Contract) => (isRollingContract(c) ? null : c.computed?.send_by) ?? "9999";
  return contracts.filter((c) => offersEndingLetter(c)).sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0));
}

// ------------------------------------------------------------------------------------------------
// Drafts
// ------------------------------------------------------------------------------------------------

/** When a letter in progress is due: its send-by date, else the day it must arrive (a reply may have neither). */
function draftDue(d: Pick<Draft, "send_guidance">): string | null {
  return d.send_guidance?.send_by ?? d.send_guidance?.must_arrive_by ?? null;
}

/**
 * The Letters list's two groups: letters in progress by what is due first (those without a date after
 * them, the newest first), sent letters the latest first.
 */
export function splitDrafts<T extends Pick<Draft, "status" | "send_guidance" | "created_at" | "sent_at">>(drafts: readonly T[]): { inProgress: T[]; sent: T[] } {
  const inProgress = drafts
    .filter((d) => d.status !== "sent")
    .sort((a, b) => {
      const da = draftDue(a);
      const db = draftDue(b);
      if (da && db && da !== db) return da < db ? -1 : 1;
      if (da && !db) return -1;
      if (db && !da) return 1;
      return b.created_at.localeCompare(a.created_at);
    });
  const sent = drafts.filter((d) => d.status === "sent").sort((a, b) => (b.sent_at ?? b.created_at).localeCompare(a.sent_at ?? a.created_at));
  return { inProgress, sent };
}

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

/** The objection's own term, as its subject names it ("Widerspruch gegen …", "Objection (Widerspruch) …"). */
function objectionStem(subject: string | undefined): string {
  const m = /\b(Einspruch|Widerspruch)\b/.exec(subject ?? "");
  return m ? m[1]! : PDF_STEM.objection;
}

/** A readable PDF file name: "Kuendigung-FunkNetz-Mobil-GmbH-2026-09-28.pdf" ("Widerspruch-…" for a Widerspruch). */
export function pdfFileName(d: Pick<Draft, "kind" | "recipient_block" | "created_at"> & Partial<Pick<Draft, "subject">>): string {
  const kind = d.kind === "objection" ? objectionStem(d.subject) : PDF_STEM[d.kind];
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
  /** not one of the ways "How to send it" names for this letter ("Another way" in the dialog) */
  other: boolean;
}

/**
 * The ways offered in the dialog: the guidance's channels with the guidance's own labels (best
 * first, the ones that don't count last), then — as "Another way" — the usual others.
 */
export function sendChoices(guidance: Draft["send_guidance"]): SendChoice[] {
  const fromGuidance = rankChannels(guidance?.channels ?? []).map((c: SendChannel) => ({
    channel: c.channel,
    label: c.label || copyFor(SEND_CHANNEL_COPY, c.channel).label,
    allowed: c.allowed,
    recommended: c.recommended,
    other: false,
  }));
  const seen = new Set(fromGuidance.map((c) => c.channel));
  const common: SendChannelKind[] = ["registered_letter", "letter", "email", "online_button", "portal", "fax", "in_person"];
  const rest = common
    .filter((c) => (SEND_CHANNELS as readonly string[]).includes(c) && !seen.has(c))
    .map((c) => ({
      channel: c,
      label: copyFor(SEND_CHANNEL_COPY, c).label,
      allowed: guidance?.form !== "written_form" || c === "registered_letter" || c === "letter" || c === "in_person",
      recommended: false,
      other: fromGuidance.length > 0,
    }));
  return [...fromGuidance, ...rest];
}

/** Whether sending it this way counts for this letter (a way the guidance doesn't name counts unless it needs signed paper). */
export function channelCounts(guidance: Draft["send_guidance"], channel: string | null | undefined): boolean {
  if (!channel) return true;
  const choice = sendChoices(guidance).find((c) => c.channel === channel);
  return choice ? choice.allowed : true;
}

/** "Based on the law as of …" among a letter's notes: the page's own disclaimer says it (with advice links). */
const DISCLAIMER_NOTE = /^Based on the law as of\b/;

/** The letter's "Good to know" notes, without the disclaimer the page shows anyway. */
export function notesToShow(notes: string[]): string[] {
  return notes.filter((n) => !DISCLAIMER_NOTE.test(n.trim()));
}

/** "All 9 checks passed" / "1 thing needs a look". */
export function checksSummary(checks: DraftCheck[]): { failed: number; text: string } {
  const failed = checks.filter((c) => !c.ok).length;
  return { failed, text: failed ? `${failed} ${failed === 1 ? "thing needs" : "things need"} a look` : `All ${checks.length} checks passed` };
}

/** An API message as plain text: the demo's "Run `ordnung serve` …" without the code marks. */
export function plainText(message: string): string {
  return message.replace(/`([^`]*)`/g, "“$1”");
}

/**
 * Whether an objection to this letter can ask to suspend enforcement: an enforcement order or an
 * authority's decision — not a court payment order (nothing to enforce yet) or a landlord's notice.
 * The composer asks it (an explicit choice), so "Draft objection" on such a letter opens the composer.
 */
export function canSuspend(doc: Pick<Document, "kind"> | null): boolean {
  return Boolean(doc) && doc!.kind !== "court_payment_order" && doc!.kind !== "landlord_notice";
}

const COURT_NAME =
  /(?:amts|land|landes|oberlandes|kammer|arbeits|sozial|verwaltungs|finanz|mahn|familien|insolvenz|vollstreckungs|nachlass|betreuungs|register|verfassungs|staats|bundes)gericht(?:e?s|shofe?s?)?\b|\bbundesfinanzhofe?s?\b/i;
/** A court's abbreviation before its place ("AG Hagen") — a federal court's may stand alone ("BGH"), a local one's
 * never ("AG" alone is no court for the server either: review round 4 of phase 2). */
const COURT_ABBREVIATION =
  /(?:^|[(,;/]\s*|\b(?:des|dem|der|beim|vom|am)\s+)(?:(?:AG|LG|OLG|ArbG|LAG|SG|LSG|VG|OVG|VGH|FG)\s+\p{Lu}|(?:BGH|BFH|BSG|BAG|BVerwG|BVerfG)(?:\s+\p{Lu}|\s*$|\s*[-–—,;/(]))/u;
const LEGAL_FORM = /\b(?:GmbH|mbH|AG|SE|KGaA|KG|OHG|UG|GbR|eG|e\.\s?V|Ltd|Inc|LLC)(?![\p{L}\d])/u;
const NOT_A_COURT = /vollzieh|kasse(?:n(?:stelle)?)?\b|zahlstelle/i;

/**
 * Whether a name may be a court's (`routing.may_be_court`): it names a kind of court ("Amtsgericht Hünfeld",
 * "Zentrales Mahngericht") or abbreviates one before its place ("AG Hagen") — no company ("LG Electronics GmbH"),
 * bailiff or court cashier. The server decides for sure; this only tells when to ask for the court.
 */
export function mayBeCourt(name: string | null | undefined): boolean {
  const text = (name ?? "").trim();
  if (!text || NOT_A_COURT.test(text)) return false;
  if (COURT_NAME.test(text)) return true;
  const firstLine = text.split("\n")[0]!;
  return COURT_ABBREVIATION.test(firstLine) && !LEGAL_FORM.test(firstLine.replace(/^\s*(?:AG|LG|OLG)\b/, ""));
}

/**
 * Whether an objection to this letter needs the court typed in: a court order whose sender, as filed, is no
 * court (a Mahnbescheid re-filed from what was read as the claimant's reminder) and whose instructions name
 * none. An objection goes to the court that issued the order — sent to the claimant it doesn't stop the order
 * (§ 694, § 700 ZPO); the server refuses to address it to anyone else (drafts/compose.py
 * `objection_to_typed_court`, review round 3 of phase 2).
 */
export function needsTypedCourt(
  doc: Pick<Document, "kind" | "remedy"> | null,
  party: { name: string } | null | undefined,
): boolean {
  if (!doc || (doc.kind !== "court_payment_order" && doc.kind !== "enforcement_order")) return false;
  if (party && mayBeCourt(party.name)) return false;
  return !mayBeCourt(doc.remedy?.addressee ?? null);
}
