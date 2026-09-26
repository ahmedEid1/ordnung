/**
 * Recorded Ask conversations (the demo replays these; other questions get a friendly note).
 * Each answer: tool calls first (the visible trace), then streamed text with [doc:ID]/[item:ID]
 * citation markers that the UI turns into chips.
 */
import type { SuggestionRef } from "@/api/types";

export interface RecordedAnswer {
  question: string;
  /** lower-case keywords; a question matching all of any group replays this answer */
  match: string[][];
  tools: { name: string; input: Record<string, unknown>; result: string }[];
  text: string;
  citations: SuggestionRef[];
}

/** Same as the app's suggested questions and the real demo's `src/ordnung/demo/asks.json`. */
export const SUGGESTED_QUESTIONS = [
  "When does my phone contract end, and by when do I have to cancel it?",
  "What do I have to pay in the next four weeks?",
  "Which deadlines are coming up in October?",
  "When does my residence permit expire, and what should I do before then?",
];

export const RECORDED: RecordedAnswer[] = [
  {
    question: "What do I have to pay in the next four weeks?",
    match: [["pay", "before"], ["pay", "october"], ["payments", "october"], ["pay", "weeks"]],
    tools: [
      { name: "today", input: {}, result: "Today is Mon 28 Sep 2026 (demo date)" },
      { name: "list_items", input: { kind: "payment", status: "open", to: "2026-10-15" }, result: "Found 8 to-dos & dates" },
    ],
    text:
      "Up to 15 October you have **6 payments**, about **1.046,79 €** in total:\n\n" +
      "- **Parking fine, 30,00 €** — by **Tue 29 Sep** to be safe [item:itm_parking]\n" +
      "- **TechMarkt reminder, 94,99 €** — by **Wed 30 Sep** [item:itm_tm_dunning]\n" +
      "- **Library fee, 4,50 €** — by **Fri 2 Oct** [item:itm_library_fee]\n" +
      "- **Rent for October, 640,00 €** — by **Mon 5 Oct**, the third working day [item:itm_rent_oct]\n" +
      "- **Utility back payment, 184,30 €** — by **Fri 9 Oct** [doc:doc_nebenkosten]\n" +
      "- **Residence permit fee, 93,00 €** — paid at your appointment on **Wed 14 Oct** [item:itm_abh_fee]\n\n" +
      "On 15 October itself, your electricity instalment (48,00 €) and your health insurance contribution (142,86 €) are due as well [item:itm_power_abschlag][item:itm_bkk].",
    citations: [
      { type: "item", id: "itm_parking" },
      { type: "item", id: "itm_tm_dunning" },
      { type: "item", id: "itm_library_fee" },
      { type: "item", id: "itm_rent_oct" },
      { type: "document", id: "doc_nebenkosten" },
      { type: "item", id: "itm_abh_fee" },
      { type: "item", id: "itm_power_abschlag" },
      { type: "item", id: "itm_bkk" },
    ],
  },
  {
    question: "What did the Finanzamt send me?",
    match: [["finanzamt"], ["tax office"], ["tax", "assessment"]],
    tools: [
      { name: "search", input: { query: "Finanzamt" }, result: "1 letter: Income tax assessment 2025" },
      { name: "get_document", input: { doc_id: "doc_tax" }, result: "Read the letter" },
      { name: "explain_date", input: { item_or_contract_id: "itm_tax_objection" }, result: "Found how the date was worked out" },
    ],
    text:
      "Finanzamt Musterstadt [party:pty_finanzamt] sent your **income tax assessment for 2025** (Bescheid of 15 Sep 2026) [doc:doc_tax]:\n\n" +
      "- You get **324,00 €** back.\n" +
      "- They did **not accept your laptop (1.049,00 €)** as a work expense, because proof of work use was missing.\n\n" +
      "If you disagree, you can file an **Einspruch** (objection). It is free, a short letter is enough and the reasons can follow later. It must reach the Finanzamt by **Wed 21 Oct** [item:itm_tax_objection].\n\n" +
      "The letter was read from a phone photo, so please compare the date with the paper letter.",
    citations: [
      { type: "party", id: "pty_finanzamt" },
      { type: "document", id: "doc_tax" },
      { type: "item", id: "itm_tax_objection" },
    ],
  },
  {
    question: "Which deadlines are coming up in October?",
    match: [["deadline", "october"], ["dates", "october"], ["due", "october"]],
    tools: [
      { name: "today", input: {}, result: "Today is Mon 28 Sep 2026 (demo date)" },
      { name: "list_items", input: { from: "2026-10-01", to: "2026-10-31", status: "open" }, result: "Found 6 to-dos & dates" },
    ],
    text:
      "October brings **six dates**, the first ones right at the start:\n\n" +
      "- **Fri 2 Oct** — return the library books and pay **4,50 €** [item:itm_library_fee]\n" +
      "- **Mon 5 Oct** — rent for October, **640,00 €** [item:itm_rent_oct]\n" +
      "- **Thu 8 Oct, 09:15** — dentist, check-up and cleaning [item:itm_dentist]\n" +
      "- **Thu 8 Oct** — post your phone-contract cancellation by then if you want to switch; it must arrive by **Wed 14 Oct** [item:itm_phone_cancel]\n" +
      "- **Wed 14 Oct, 10:30** — residence permit appointment at the Ausländerbehörde [item:itm_abh_appt]\n" +
      "- **Thu 15 Oct** — health insurance contribution [item:itm_bkk]",
    citations: [
      { type: "item", id: "itm_library_fee" },
      { type: "item", id: "itm_rent_oct" },
      { type: "item", id: "itm_dentist" },
      { type: "item", id: "itm_phone_cancel" },
      { type: "item", id: "itm_abh_appt" },
      { type: "item", id: "itm_bkk" },
    ],
  },
  {
    question: "What do I need to do this week?",
    match: [["this week"], ["do", "week"], ["todo"], ["to-do"]],
    tools: [
      { name: "today", input: {}, result: "Today is Mon 28 Sep 2026 (demo date)" },
      { name: "list_items", input: { from: "2026-09-28", to: "2026-10-04", status: "open" }, result: "Found 4 to-dos & dates" },
    ],
    text:
      "Here's your week, most urgent first:\n\n" +
      "1. **Parking fine, 30 €** — pay by **Tue 29 Sep** to be safe [item:itm_parking]. I don't know when the letter arrived, so I counted from the letter date; if it came later you have a bit more time [doc:doc_parking].\n" +
      "2. **TechMarkt reminder, 94,99 €** — due **Wed 30 Sep**, otherwise it may go to a debt collector [doc:doc_tm_dunning].\n" +
      "3. **Library** — return the two books and pay **4,50 €** by **Fri 2 Oct** [item:itm_library_fee].\n\n" +
      "Nothing else is due before Sunday. Next week brings rent (Mon 5 Oct), the dentist (Thu 8 Oct, 09:15) and your phone-contract decision.",
    citations: [
      { type: "item", id: "itm_parking" },
      { type: "document", id: "doc_parking" },
      { type: "document", id: "doc_tm_dunning" },
      { type: "item", id: "itm_library_fee" },
    ],
  },
  {
    question: "When does my phone contract end, and by when do I have to cancel it?",
    match: [["phone"], ["funknetz"], ["handy"], ["mobile"]],
    tools: [
      { name: "search", input: { query: "FunkNetz Kündigung" }, result: "1 letter: Phone contract — FunkNetz Allnet L" },
      { name: "list_contracts", input: { category: "mobile" }, result: "1 contract: FunkNetz Allnet L (34,99 €/month)" },
      { name: "explain_date", input: { id: "itm_phone_cancel" }, result: "Due Wed 14 Oct 2026, send by Thu 8 Oct (§ 56 TKG)" },
    ],
    text:
      "Your FunkNetz contract's 24-month minimum term ends on **Sat 14 Nov 2026** [contract:ctr_phone]. With one month's notice, FunkNetz must **receive** your cancellation by **Wed 14 Oct** — if you post it, send it by **Thu 8 Oct** [item:itm_phone_cancel].\n\n" +
      "The quickest way is the cancel button in „Mein FunkNetz“ (they must offer one, § 312k BGB). If you miss the date, nothing bad happens: the contract continues month to month and you can cancel any time with one month's notice [doc:doc_phone].\n\n" +
      "Want me to draft the cancellation letter?",
    citations: [
      { type: "contract", id: "ctr_phone" },
      { type: "item", id: "itm_phone_cancel" },
      { type: "document", id: "doc_phone" },
    ],
  },
  {
    question: "How much do I pay every month?",
    match: [["month"], ["fixed"], ["costs"], ["pay", "every"]],
    tools: [
      { name: "money_summary", input: {}, result: "Fixed costs 987,00 €/month across 9 contracts" },
      { name: "list_contracts", input: { status: "active" }, result: "10 active contracts" },
    ],
    text:
      "Your fixed costs are about **987 € a month** [contract:ctr_rent]:\n\n" +
      "- Rent (incl. utilities): **640,00 €**\n" +
      "- Health insurance: **142,86 €** from October [doc:doc_bkk]\n" +
      "- Deutschlandticket: **63,00 €** [contract:ctr_dticket]\n" +
      "- Electricity: **48,00 €** (55 € from November if you stay)\n" +
      "- Phone: **34,99 €** · Gym: **29,90 €** · Broadcasting fee: **18,36 €** · Liability insurance: **4,99 €** · Bank account: **4,90 €**\n\n" +
      "Tip: your semester fee already includes a Deutschlandsemesterticket — you may be paying for public transport twice [doc:doc_uni].",
    citations: [
      { type: "contract", id: "ctr_rent" },
      { type: "document", id: "doc_bkk" },
      { type: "contract", id: "ctr_dticket" },
      { type: "document", id: "doc_uni" },
    ],
  },
  {
    question: "What should I bring to the Ausländerbehörde?",
    match: [["ausländerbehörde"], ["auslanderbehorde"], ["bring"], ["residence"], ["permit"], ["appointment"]],
    tools: [
      { name: "search", input: { query: "Ausländerbehörde Termin" }, result: "1 letter: Residence permit extension — appointment 14 Oct" },
      { name: "get_document", input: { id: "doc_abh" }, result: "Invitation, dated 21 Sep 2026" },
    ],
    text:
      "Your appointment is **Wed 14 Oct, 10:30**, Rathausplatz 1, room 2.14 [item:itm_abh_appt]. The letter asks you to bring [doc:doc_abh]:\n\n" +
      "- your valid **passport**\n- a current **biometric photo**\n- your **enrolment certificate** (Immatrikulationsbescheinigung)\n- proof of **health insurance**\n- proof that you can **support yourself** (e.g. blocked account or work contract)\n\n" +
      "The fee is **93 €**, paid at the appointment. One more thing: your passport expires on 10 Feb 2027, so the office may only extend your permit until then [item:itm_passport_expiry].",
    citations: [
      { type: "item", id: "itm_abh_appt" },
      { type: "document", id: "doc_abh" },
      { type: "item", id: "itm_passport_expiry" },
    ],
  },
];

export const FALLBACK_ANSWER =
  "The demo uses recorded answers, so I can only replay a few questions here. Try one of the suggestions — or install Ordnung to ask anything about your own letters.";
