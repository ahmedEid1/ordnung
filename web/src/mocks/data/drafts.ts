import type { Draft, DraftCheck, SendGuidance } from "@/api/types";
import { SAM, ts } from "./constants";

const SENDER = `${SAM.name}\n${SAM.street}\n${SAM.city}\n${SAM.email}`;

export const CHECKS_OK: DraftCheck[] = [
  { id: "has_reference", label: "Your customer number / reference is included", ok: true, detail: null },
  { id: "has_dates", label: "The end date is stated", ok: true, detail: null },
  { id: "recipient_complete", label: "Recipient address is complete", ok: true, detail: null },
  { id: "sender_complete", label: "Your name and address are complete", ok: true, detail: null },
  { id: "no_placeholders", label: "No placeholders left", ok: true, detail: null },
  { id: "citations_known", label: "Every § cited is in the rules catalog or the letter", ok: true, detail: null },
  { id: "no_new_identifiers", label: "No invented account or ID numbers", ok: true, detail: null },
  { id: "delivery_channel_ok", label: "The chosen way of sending is allowed", ok: true, detail: null },
];

export function phoneGuidance(): SendGuidance {
  return {
    send_by: "2026-10-08",
    must_arrive_by: "2026-10-14",
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

export const DRAFTS: Draft[] = [
  {
    id: "drf_phone",
    kind: "cancellation",
    language: "de",
    party_id: "pty_funknetz",
    case_id: "cas_phone",
    doc_id: "doc_phone",
    contract_id: "ctr_phone",
    sender_block: SENDER,
    recipient_block: "FunkNetz Mobil GmbH\nPostfach 10 20 30\n12340 Musterstadt",
    place_date: "Musterstadt, 28.09.2026",
    subject: "Kündigung meines Mobilfunkvertrags – Kundennummer 7700 4412 09",
    body:
      "Sehr geehrte Damen und Herren,\n\nhiermit kündige ich meinen Mobilfunkvertrag (Tarif Allnet L, Kundennummer 7700 4412 09) fristgerecht zum 14.11.2026, hilfsweise zum nächstmöglichen Zeitpunkt.\n\nBitte bestätigen Sie mir den Eingang dieser Kündigung und das Beendigungsdatum schriftlich.\n\nMit freundlichen Grüßen\n\nSam Rivera",
    body_translation:
      "Dear Sir or Madam,\n\nI hereby cancel my mobile contract (Allnet L plan, customer number 7700 4412 09) with due notice effective 14 Nov 2026, or alternatively at the next possible date.\n\nPlease confirm receipt of this cancellation and the end date in writing.\n\nKind regards\n\nSam Rivera",
    enclosures: [],
    notes_for_user: ["If you want to keep your phone number, ask your new provider to port it — don't cancel the number itself."],
    checks: CHECKS_OK,
    send_guidance: phoneGuidance(),
    sent_channel: null,
    status: "draft",
    sent_at: null,
    created_at: ts("2026-09-27", "20:10"),
    updated_at: ts("2026-09-27", "20:12"),
  },
  {
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
      "Sehr geehrte Frau Beispiel,\n\nvielen Dank für die Betriebskostenabrechnung 2025 vom 09.09.2026. Ich möchte gerne die zugehörigen Belege einsehen. Bitte nennen Sie mir einen Termin in Ihrer Geschäftsstelle.\n\nMit freundlichen Grüßen\n\nSam Rivera",
    body_translation:
      "Dear Ms Beispiel,\n\nthank you for the 2025 utility cost statement of 9 Sep 2026. I would like to inspect the related receipts. Please suggest an appointment at your office.\n\nKind regards\n\nSam Rivera",
    enclosures: [],
    notes_for_user: [],
    checks: CHECKS_OK.slice(0, 5),
    send_guidance: {
      send_by: null,
      must_arrive_by: null,
      form: "any",
      form_note: null,
      channels: [{ channel: "email", label: "Email to vermietung@wohnbau-musterstadt.example", allowed: true, recommended: true, note: null, citation: null }],
      tips: [],
    },
    sent_channel: "email",
    status: "sent",
    sent_at: ts("2026-09-15", "19:00"),
    created_at: ts("2026-09-15", "18:50"),
    updated_at: ts("2026-09-15", "19:00"),
  },
];
