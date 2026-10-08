import type { Draft, DraftCheck, DraftKind, SendGuidance } from "@/api/types";
import { SAM, ts } from "./constants";

const SENDER = `${SAM.name}\n${SAM.street}\n${SAM.city}\n${SAM.email}`;

/** The API's check labels, in its display order (`src/ordnung/drafts/checks.py`, `LABELS`). */
export const CHECK_LABELS = {
  has_reference: "Mentions your customer or reference number",
  has_dates: "States the dates that matter",
  recipient_complete: "Recipient's name and address are complete",
  sender_complete: "Your name and address are complete",
  no_placeholders: "No placeholders left to fill in",
  language_matches: "Written in the letter's language",
  citations_known: "Only laws Ordnung knows are cited",
  no_new_identifiers: "No unknown account numbers, emails or ID numbers",
  delivery_channel_ok: "Sent in a way that counts",
} as const;
type CheckId = keyof typeof CHECK_LABELS;

/** What a letter's address block misses: a street (or PO box) and a postcode with town. */
function addressGaps(block: string): string[] {
  const rest = block.split("\n").map((l) => l.trim()).filter(Boolean).slice(1);
  if (!rest.length) return ["name", "street and house number", "postcode and town"];
  const postcode = rest.filter((l) => /(?:^|\s)\d{4,5}\s+\S/.test(l));
  const street = rest.filter((l) => !postcode.includes(l) && /^(?:Postfach\s+\d|.*[A-Za-zÄÖÜäöüß].*\d)/i.test(l));
  return [...(street.length ? [] : ["street and house number"]), ...(postcode.length ? [] : ["postcode and town"])];
}

/** A reference number without spaces, slashes, dots or dashes ("7700 4412 09" → "7700441209"). */
const normalizeRef = (s: string) => s.replace(/[\s/.\-_]/g, "").toLowerCase();

export interface CheckFacts {
  kind: DraftKind;
  language?: string | null;
  subject: string;
  body: string;
  sender_block: string;
  recipient_block: string;
  /** the customer or reference numbers known for the letter (contract, their letter, the sender) */
  references?: (string | null | undefined)[];
  /** the date of the letter it answers ("09.09.2026") */
  letterDate?: string | null;
  /** how it goes out: the form note, or the channel it was sent by */
  formNote?: string | null;
  sentVia?: string | null;
}

/** Template letters that need a date in them: (passed, what to add) — `checks._DATED_TEMPLATES`. */
const DATED_TEMPLATES: Partial<Record<DraftKind, readonly [string, string]>> = {
  withdrawal: ["Names when you ordered or received it.", "Add when you ordered or received it, so they find your order."],
  extension_request: ["Names the new date you ask for.", "Name the new date you ask for."],
  payment_plan: ["Names when the instalments start.", "Name the day of the first instalment."],
  defect_notice: ["Says since when, or by when it should be fixed.", "Say since when the defect exists or by when it should be fixed."],
  deposit_return: ["Names when you handed the flat back.", "Add the day you handed the flat back."],
};
/** A date as the server's check reads one (`checks._any_date`): "09.10.2026" or "9 October 2026". */
const ANY_DATE = /\b\d{1,2}\.\d{1,2}\.\d{4}\b|\b\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|December) \d{4}\b/;

/**
 * The checks the API runs on a draft (`src/ordnung/drafts/checks.py`), worked out the same way for
 * the demo's letters: a cancellation names its end date, an objection the decision's date, a
 * template letter the date it is about (a withdrawal, a request for more time …), and a reply needs
 * neither.
 */
export function draftChecks(f: CheckFacts): DraftCheck[] {
  const text = `${f.subject}\n${f.body}`;
  const check = (id: CheckId, ok: boolean, detail: string | null): DraftCheck => ({ id, label: CHECK_LABELS[id], ok, detail });
  const dated = DATED_TEMPLATES[f.kind];
  const dates = dated
    ? ANY_DATE.test(f.body)
      ? check("has_dates", true, dated[0])
      : check("has_dates", false, dated[1])
    : f.kind === "cancellation"
      ? check("has_dates", true, "Says when the contract should end.")
      : f.kind === "objection"
        ? f.letterDate && text.includes(f.letterDate)
          ? check("has_dates", true, "Names the date of the decision.")
          : check("has_dates", false, f.letterDate ? `Name the date of the decision you object to (${f.letterDate}).` : "Add the date of the decision you object to.")
        : check("has_dates", true, "No dates are needed for this letter.");
  const refs = [...new Set((f.references ?? []).filter((r): r is string => Boolean(r && normalizeRef(r).length >= 3)))];
  const found = refs.find((r) => normalizeRef(text).includes(normalizeRef(r)));
  const reference = found
    ? check("has_reference", true, `Mentions ${found}.`)
    : refs.length
      ? check("has_reference", false, `Add your reference so they can find your file: ${refs.slice(0, 3).join(", ")}.`)
      : f.letterDate && text.includes(f.letterDate)
        ? check("has_reference", true, `Refers to their letter of ${f.letterDate}.`)
        : check("has_reference", false, "We don't know a customer or reference number for this letter — add one if you have it, so they can find your file.");
  const recipientGaps = addressGaps(f.recipient_block);
  const senderGaps = addressGaps(f.sender_block);
  const placeholders = ["…", "[", "XXX"].filter((p) => text.includes(p));
  return [
    reference,
    dates,
    check("recipient_complete", !recipientGaps.length, recipientGaps.length ? `Add the recipient's ${recipientGaps.join(" and ")}.` : null),
    check("sender_complete", !senderGaps.length, senderGaps.length ? `Add your ${senderGaps.join(" and ")} (Settings → Profile), so they can reply by post.` : null),
    check("no_placeholders", !placeholders.length, placeholders.length ? `Replace ${placeholders.map((p) => `“${p}”`).join(", ")} before sending.` : null),
    check("language_matches", true, `Reads like ${f.language === "en" ? "English" : "German"}.`),
    check("citations_known", true, text.includes("§") ? "Every law cited is in Ordnung's rules or in the letter." : "No laws are cited."),
    check("no_new_identifiers", true, null),
    check("delivery_channel_ok", true, f.sentVia ? `${f.sentVia} is fine for this letter.` : (f.formNote ?? "No special form is needed.")),
  ];
}

export function phoneGuidance(): SendGuidance {
  return {
    send_by: "2026-10-08",
    must_arrive_by: "2026-10-14",
    post_too_late: false,
    form: "text_form",
    form_note: "Text form is enough: an email or a letter without handwritten signature is fine.",
    channels: [
      { channel: "online_button", label: "Cancel button in „Mein FunkNetz“", allowed: true, recommended: true, note: "Instant, with confirmation — usable until 14 Oct.", citation: "§ 312k BGB" },
      { channel: "email", label: "Email to kuendigung@funknetz.example", allowed: true, recommended: false, note: "Keep the sent email; ask for a confirmation.", citation: "§ 309 Nr. 13 BGB" },
      { channel: "registered_letter", label: "Einwurf-Einschreiben", allowed: true, recommended: false, note: "Post by Thu 8 Oct and keep the receipt.", citation: null },
    ],
    tips: ["Ask for a written confirmation of the end date.", "Save a copy of what you sent."],
  };
}

/** A stored draft with the checks the API would have run on it. */
function withChecks(d: Omit<Draft, "checks">, facts: Pick<CheckFacts, "references" | "letterDate">): Draft {
  const channel = d.send_guidance?.channels.find((c) => c.channel === d.sent_channel);
  return {
    ...d,
    checks: draftChecks({ ...d, ...facts, formNote: d.send_guidance?.form_note, sentVia: d.status === "sent" ? (channel?.label ?? null) : null }),
  };
}

export const DRAFTS: Draft[] = [
  withChecks({
    id: "drf_phone",
    kind: "cancellation",
    language: "de",
    party_id: "pty_funknetz",
    case_id: "cas_phone",
    doc_id: "doc_phone",
    contract_id: "ctr_phone",
    sender_block: SENDER,
    recipient_block: "FunkNetz Mobil GmbH\nWellenweg 7\n12351 Beispielhausen",
    place_date: "Musterstadt, 28.09.2026",
    subject: "Kündigung meines Mobilfunkvertrags – Kundennummer 7700 4412 09",
    body:
      "Sehr geehrte Damen und Herren,\n\nhiermit kündige ich meinen Mobilfunkvertrag (Tarif Allnet L, Kundennummer 7700 4412 09) fristgerecht zum 14.11.2026, hilfsweise zum nächstmöglichen Zeitpunkt.\n\nBitte bestätigen Sie mir den Eingang dieser Kündigung und das Beendigungsdatum schriftlich.\n\nMit freundlichen Grüßen\n\nSam Rivera",
    body_translation:
      "Dear Sir or Madam,\n\nI hereby cancel my mobile contract (Allnet L plan, customer number 7700 4412 09) with due notice effective 14 Nov 2026, or alternatively at the next possible date.\n\nPlease confirm receipt of this cancellation and the end date in writing.\n\nKind regards\n\nSam Rivera",
    enclosures: [],
    notes_for_user: ["If you want to keep your phone number, ask your new provider to port it — don't cancel the number itself."],
    send_guidance: phoneGuidance(),
    sent_channel: null,
    status: "draft",
    sent_at: null,
    tracking_number: null,
    answered_on: null,
    answer_doc_id: null,
    created_at: ts("2026-09-27", "20:10"),
    updated_at: ts("2026-09-27", "20:12"),
  }, { references: ["7700 4412 09"] }),
  withChecks({
    id: "drf_wohnbau",
    kind: "general_reply",
    language: "de",
    party_id: "pty_wohnbau",
    case_id: "cas_flat",
    doc_id: "doc_nebenkosten",
    contract_id: "ctr_rent",
    sender_block: SENDER,
    recipient_block: "Wohnbau Musterstadt eG\nFrau Beispiel\nHafenstraße 4\n12345 Musterstadt",
    place_date: "Musterstadt, 15.09.2026",
    subject: "Betriebskostenabrechnung 2025, Wohnung Nr. 12 – Bitte um Belegeinsicht",
    body:
      "Sehr geehrte Frau Beispiel,\n\nvielen Dank für die Betriebskostenabrechnung 2025 vom 09.09.2026 (Mieternummer 12-0412-07). Ich möchte gerne die zugehörigen Belege einsehen. Bitte nennen Sie mir einen Termin in Ihrer Geschäftsstelle.\n\nMit freundlichen Grüßen\n\nSam Rivera",
    body_translation:
      "Dear Ms Beispiel,\n\nthank you for the 2025 utility cost statement of 9 Sep 2026 (tenant number 12-0412-07). I would like to inspect the related receipts. Please suggest an appointment at your office.\n\nKind regards\n\nSam Rivera",
    enclosures: [],
    notes_for_user: [],
    send_guidance: {
      send_by: null,
      must_arrive_by: null,
      post_too_late: false,
      form: "any",
      form_note: null,
      channels: [{ channel: "email", label: "Email to vermietung@wohnbau-musterstadt.example", allowed: true, recommended: true, note: null, citation: null }],
      tips: [],
    },
    sent_channel: "email",
    status: "sent",
    sent_at: ts("2026-09-15", "19:00"),
    tracking_number: null,
    answered_on: null,
    answer_doc_id: null,
    created_at: ts("2026-09-15", "18:50"),
    updated_at: ts("2026-09-15", "19:00"),
  }, { references: ["12-0412-07"], letterDate: "09.09.2026" }),
];
