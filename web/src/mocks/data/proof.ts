/**
 * Proof of sending, "Waiting for" and call notes in Sam's sample life: the FitWell cancellation Sam
 * posted by Einschreiben on Tue 22 Sep (tracking number and a photo of the posting receipt), the
 * deposit the student hall still owes, and a call with FitWell whose promise is overdue.
 *
 * The wording mirrors the server's written policy (`src/ordnung/drafts/proof.py`,
 * `src/ordnung/secretary/waiting.py`), so the static demo says what the app says.
 */
import type { CallNote, Document, Draft, Item, Party, Proof, ProofKind } from "@/api/types";
import { SAM, ts } from "./constants";
import { draftChecks } from "./drafts";
import { doc, item } from "./helpers";

const SENDER = `${SAM.name}\n${SAM.street}\n${SAM.city}\n${SAM.email}`;

// ------------------------------------------------------------------------------------------------
// the policy's words (drafts/proof.py)
// ------------------------------------------------------------------------------------------------

export const PROOF_TEXTS: Record<ProofKind, { label: string; shows: string; doesNotShow: string; arrival: boolean }> = {
  posting_receipt: {
    label: "Posting receipt",
    shows: "That a registered item with this number was handed in at the post office, and when.",
    doesNotShow: "Whether it arrived, or what was in the envelope.",
    arrival: false,
  },
  delivery_record: {
    label: "Delivery record",
    shows: "The day the carrier put it in their letterbox, confirmed by the carrier. With the posting receipt, courts have accepted it as prima facie proof that the letter arrived.",
    doesNotShow: "What was in the envelope.",
    arrival: true,
  },
  return_receipt: {
    label: "Return receipt",
    shows: "The day the letter was handed over, signed by whoever took it.",
    doesNotShow: "What was in the envelope.",
    arrival: true,
  },
  fax_report: {
    label: "Fax transmission report",
    shows: "That your fax reached this number at this time, and how many pages went through.",
    doesNotShow: "That every page arrived readable — an “OK” is an indication, not proof, that they received it.",
    arrival: false,
  },
  sent_email: {
    label: "Sent e-mail",
    shows: "What you sent and when it left your mailbox.",
    doesNotShow: "That it reached them or was read — ask them to confirm it arrived.",
    arrival: false,
  },
  cancel_confirmation: {
    label: "Cancel-button confirmation",
    shows: "Your cancellation with its date and time. The law presumes a cancellation made with the button reached them right after you sent it (§ 312k Abs. 4 BGB).",
    doesNotShow: "That they processed it, if it is only your saved page — their confirmation e-mail shows that.",
    arrival: true,
  },
  other: { label: "Other proof", shows: "What it shows — describe it in the note.", doesNotShow: "Ordnung can't tell; proof files are never read by AI.", arrival: false },
};

export const PROOF_CAVEAT =
  "Proof of sending shows that something was sent or delivered — never what was inside. Keep a copy of the letter as sent and, for a letter that matters, have someone see you put it in the envelope. Whether a proof is enough is for a court to decide; this is not legal advice.";

export const MISSING = {
  tracking: "Add the tracking number from your posting receipt (Einlieferungsbeleg).",
  posting: "Add a photo of the posting receipt — it shows the day you posted the letter.",
  delivery:
    "Ask Deutsche Post for a copy of the delivery record (Auslieferungsbeleg) while they still issue it, or keep the return receipt (Rückschein) if you sent it with one. The online tracking status alone was not accepted as proof that a letter arrived (BAG 2 AZR 68/24).",
  fax: "Keep the fax transmission report (Sendebericht): it shows the number, the time and the pages.",
  email: "Save the sent e-mail as a file or PDF, and ask them to confirm it arrived.",
  button: "Save the page the cancel button showed and the confirmation e-mail they must send you at once (§ 312k Abs. 3 and 4 BGB).",
  letter: "A normal letter leaves nothing that shows it arrived. If a deadline depends on it, send it again by Einwurf-Einschreiben.",
  in_person: "Ask them to sign and date your copy as received, or note who saw you hand it over.",
  portal: "Save the portal's confirmation, or a screenshot of the sent message with its date.",
} as const;

export const WAITING_FOR: Record<string, string | null> = {
  cancellation: "A written confirmation of the end date",
  objection: "A decision on your objection",
  general_reply: "An answer to your letter",
  withdrawal: "Your money back after the withdrawal",
  extension_request: "An answer to your request for more time",
  payment_plan: "An answer to your offer to pay in instalments",
  defect_notice: "The repair of the defect",
  data_access: "A copy of your data",
  receipts_inspection: "A date to see the receipts",
  deposit_return: "Your deposit back",
  address_change: null,
};

export const CHANNEL_WORDS: Record<string, string> = {
  online_button: "the online cancel button",
  email: "e-mail",
  fax: "fax",
  letter: "letter by post",
  registered_letter: "registered letter (Einschreiben)",
  in_person: "hand delivery",
  portal: "online portal",
};

/** The follow-up to-do of a sent letter (the seeded Wohnbau reply keeps its older id). */
export function followupIdFor(draftId: string): string {
  return draftId === "drf_wohnbau" ? "itm_followup_wohnbau" : `itm_followup_${draftId.replace(/^drf_/, "")}`;
}

// ------------------------------------------------------------------------------------------------
// the seeds
// ------------------------------------------------------------------------------------------------

export const PROOF_PARTIES: Party[] = [
  {
    id: "pty_studierendenwerk",
    name: "Studierendenwerk Musterstadt",
    kind: "landlord",
    aliases: [],
    identifiers: [{ label: "Mieternummer", value: "WH-3317" }],
    address: "Mensaweg 1, 12345 Musterstadt",
    email: "wohnen@stw-musterstadt.example",
    phone: null,
    website: null,
    notes: "Wohnheim Lindenhof, room 4.12 — moved out on 31 Aug 2025.",
    region: "NW",
    ibans: [],
    created_at: ts("2026-09-05"),
    updated_at: ts("2026-09-05"),
  },
];

const GYM_GUIDANCE: Draft["send_guidance"] = {
  send_by: null,
  must_arrive_by: null,
  form: "text_form",
  form_note: "Text form is enough: an email or a letter without handwritten signature is fine.",
  channels: [
    { channel: "online_button", label: "Cancel button in the FitWell app", allowed: true, recommended: true, note: "Counts the moment you press it — save the confirmation page.", citation: "§ 312k BGB" },
    { channel: "email", label: "Email to service@fitwell.example", allowed: true, recommended: false, note: "Keep the sent email; ask for a confirmation.", citation: "§ 309 Nr. 13 BGB" },
    { channel: "registered_letter", label: "Letter by Einwurf-Einschreiben", allowed: true, recommended: false, note: "Keep the posting receipt and ask for the delivery record.", citation: null },
  ],
  tips: ["Ask for a written confirmation of the end date."],
};

const GYM_DRAFT: Omit<Draft, "checks"> = {
  id: "drf_gym",
  kind: "cancellation",
  language: "de",
  party_id: "pty_fitwell",
  case_id: null,
  doc_id: "doc_gym_price",
  contract_id: "ctr_gym",
  sender_block: SENDER,
  recipient_block: "FitWell Studios\nLindenallee 22\n12345 Musterstadt",
  place_date: "Musterstadt, 22.09.2026",
  subject: "Kündigung meiner Mitgliedschaft „FitWell Flex“ – Mitgliedsnummer FW-20931",
  body:
    "Sehr geehrte Damen und Herren,\n\nhiermit kündige ich meine Mitgliedschaft „FitWell Flex“, Mitgliedsnummer FW-20931, fristgerecht zum 31.10.2026, hilfsweise zum nächstmöglichen Zeitpunkt.\n\nBitte bestätigen Sie mir den Eingang dieser Kündigung sowie das Beendigungsdatum schriftlich.\n\nMit freundlichen Grüßen\n\nSam Rivera",
  body_translation:
    "Dear Sir or Madam,\n\nI hereby cancel my “FitWell Flex” membership, member number FW-20931, with due notice effective 31 Oct 2026, or alternatively at the next possible date.\n\nPlease confirm receipt of this cancellation and the end date in writing.\n\nKind regards\n\nSam Rivera",
  enclosures: [],
  notes_for_user: [],
  send_guidance: GYM_GUIDANCE,
  sent_channel: "registered_letter",
  status: "sent",
  sent_at: ts("2026-09-22", "14:40"),
  tracking_number: "RT123456785DE",
  created_at: ts("2026-09-21", "20:05"),
  updated_at: ts("2026-09-22", "14:40"),
};

export const PROOF_DRAFTS: Draft[] = [
  {
    ...GYM_DRAFT,
    checks: draftChecks({ ...GYM_DRAFT, references: ["FW-20931"], letterDate: "14.09.2026", sentVia: "Letter by Einwurf-Einschreiben" }),
  },
];

export const PROOF_ITEMS: Item[] = [
  item({
    id: followupIdFor("drf_gym"),
    kind: "task",
    title: "Check for a reply from FitWell Studios",
    description: "You sent “Kündigung meiner Mitgliedschaft „FitWell Flex“” on Tue 22 Sep 2026 (Letter by Einwurf-Einschreiben).",
    action: "If nothing has arrived, call them or send a short reminder — and keep a note of it.",
    due_date: "2026-10-13",
    due_date_source: "computed",
    area: "leisure",
    party_id: "pty_fitwell",
    contract_id: "ctr_gym",
    doc_id: "doc_gym_price",
    origin: "draft",
    grounding: "user",
    created_at: ts("2026-09-22", "14:40"),
  }),
  item({
    id: "itm_deposit_hall",
    kind: "payment",
    direction: "in",
    title: "Deposit back from the student hall",
    description: "You moved out of Wohnheim Lindenhof on 31 Aug 2025. They said the deposit comes back after the final statement.",
    amount: 450,
    currency: "EUR",
    due_date: "2026-10-15",
    due_date_source: "manual",
    area: "home",
    party_id: "pty_studierendenwerk",
    origin: "manual",
    grounding: "user",
    created_at: ts("2026-09-05", "18:30"),
  }),
];

/** A placeholder for the photo of the posting receipt (the demo has no real photos). */
export const RECEIPT_DOC_ID = "doc_gym_receipt";

export const PROOF_DOCUMENTS: Document[] = [
  doc({
    id: RECEIPT_DOC_ID,
    filename: "Einlieferungsbeleg_FitWell.jpg",
    title: "Einlieferungsbeleg_FitWell.jpg",
    mime: "image/jpeg",
    direction: "outgoing",
    source: "proof",
    kind: null,
    area: null,
    ai_private: true,
    ai_processed_at: null,
    urgency: null,
    language: null,
    created_at: ts("2026-09-22", "14:45"),
  }),
];

export const PROOFS: Proof[] = [
  {
    id: "prf_gym_receipt",
    draft_id: "drf_gym",
    kind: "posting_receipt",
    doc_id: RECEIPT_DOC_ID,
    on_date: "2026-09-22",
    note: "Filiale Musterstadt-Mitte, 14:32",
    created_at: ts("2026-09-22", "14:45"),
    updated_at: ts("2026-09-22", "14:45"),
  },
];

export const CALL_NOTES: CallNote[] = [
  {
    id: "cal_fitwell",
    party_id: "pty_fitwell",
    case_id: null,
    called_on: "2026-09-23",
    contact: "Herr Brandt, member services",
    summary: "Asked whether my cancellation arrived. He could see it in their system and said the written confirmation goes out this week.",
    promise: "Written confirmation of the cancellation",
    promise_due: "2026-09-26",
    promise_amount: null,
    promise_kept_on: null,
    created_at: ts("2026-09-23", "11:20"),
    updated_at: ts("2026-09-23", "11:20"),
  },
];

/** A picture of a posting receipt, drawn like the demo's letters (no logos; marked as a specimen). */
export function receiptSvg(tracking: string, day: string, note: string | null): string {
  const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const lines = [
    ["Einlieferungsbeleg", 30, 700],
    ["Einschreiben Einwurf", 22, 400],
    [tracking, 26, 600],
    [`Eingeliefert am ${day}`, 20, 400],
    [note ?? "", 18, 400],
    ["Empfänger: FitWell Studios, 12345 Musterstadt", 18, 400],
    ["MUSTER · SPECIMEN", 16, 600],
  ] as const;
  const text = lines
    .map(([t, size, weight], i) => `<text x="48" y="${110 + i * 58}" font-family="Inter, Arial, sans-serif" font-size="${size}" font-weight="${weight}" fill="#262420">${esc(t)}</text>`)
    .join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600" viewBox="0 0 600 600"><rect width="600" height="600" fill="#e9e4da"/><rect x="24" y="40" width="552" height="500" rx="10" fill="#fdfbf6" stroke="#b9b1a2"/><rect x="24" y="40" width="552" height="18" fill="#f2c94c"/>${text}</svg>`;
}
