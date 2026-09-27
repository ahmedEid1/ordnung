/**
 * Recorded Ask conversations (the demo replays these; other questions get a friendly note).
 * Each answer: tool calls first (the visible trace), then streamed text with [doc:ID]/[item:ID]
 * citation markers that the UI turns into chips.
 *
 * The answers follow the app's answer check (`src/ordnung/assistant/support.py`, ADR 0008): every
 * date and amount sits in a sentence that cites the record holding it (or the list's lead line
 * does), totals come from the money overview, and an amount the record flags as read from a photo
 * is quoted as the letter's. One answer shows what the check does to an answer that breaks the
 * rules; like the real API, the mock server never sends the words (`raw`) before the check.
 */
import type { SuggestionRef } from "@/api/types";

export interface RecordedAnswer {
  question: string;
  /** lower-case keywords; a question matching all of any group replays this answer */
  match: string[][];
  tools: { name: string; input: Record<string, unknown>; result: string }[];
  /** the checked answer (what `done` carries and the conversation keeps) */
  text: string;
  /** what the model wrote before Ordnung's check, when the check changed it (never sent) */
  raw?: string;
  /** the check's note, shown under the answer (the `done` event's `note`) */
  note?: string;
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
      { name: "list_items", input: { kind: "payment", status: "open", to: "2026-10-26" }, result: "Found 8 to-dos & dates" },
    ],
    // review round 4: the headline said 6 payments over a list of 8, and the tool call stopped at 15 Oct
    text:
      "In the next four weeks you have **8 payments**, soonest first:\n\n" +
      "- **Parking fine, €30.00** — by **Tue 29 Sep** to be safe [item:itm_parking]\n" +
      "- **TechMarkt reminder, €94.99** — by **Wed 30 Sep** [item:itm_tm_dunning]\n" +
      "- **Library fee, €4.50** — by **Fri 2 Oct** [item:itm_library_fee]\n" +
      "- **Rent for October, €640.00** — by **Mon 5 Oct**, the third working day [item:itm_rent_oct]\n" +
      "- **Utility back payment, €184.30** — by **Fri 9 Oct** [item:itm_nk]\n" +
      "- **Residence permit fee, €93.00** — paid at your appointment on **Wed 14 Oct** [item:itm_abh_fee]\n" +
      "- **Electricity instalment, €48.00** — **Thu 15 Oct** [item:itm_power_abschlag]\n" +
      "- **Health insurance contribution, €142.86** — **Thu 15 Oct** [item:itm_bkk]",
    citations: [
      { type: "item", id: "itm_parking" },
      { type: "item", id: "itm_tm_dunning" },
      { type: "item", id: "itm_library_fee" },
      { type: "item", id: "itm_rent_oct" },
      { type: "item", id: "itm_nk" },
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
    // the check (ADR 0008): the refund was read by AI from a photo, so it may only be quoted as the
    // letter's words; "before Sat 17 Oct" is the model's own date arithmetic (no record holds it),
    // so that sentence is left out
    raw:
      "Finanzamt Musterstadt [party:pty_finanzamt] sent your **income tax assessment for 2025** [doc:doc_tax]:\n\n" +
      "- The letter says you get **€324.00** back [doc:doc_tax].\n" +
      "- They did **not accept your laptop** as a work expense, because proof of work use was missing [doc:doc_tax].\n\n" +
      "If you disagree, you can file an **Einspruch** (objection). It is free, a short letter is enough and the reasons can follow later. It must reach the Finanzamt by **Wed 21 Oct** [item:itm_tax_objection]; post it by **Thu 15 Oct** to be safe. Plan an evening before Sat 17 Oct to write it.\n\n" +
      "The letter was read from a phone photo, so please compare the date with the paper letter.",
    text:
      "Finanzamt Musterstadt [party:pty_finanzamt] sent your **income tax assessment for 2025** [doc:doc_tax]:\n\n" +
      "- The letter says you get **“€324.00”** back [doc:doc_tax].\n" +
      "- They did **not accept your laptop** as a work expense, because proof of work use was missing [doc:doc_tax].\n\n" +
      "If you disagree, you can file an **Einspruch** (objection). It is free, a short letter is enough and the reasons can follow later. It must reach the Finanzamt by **Wed 21 Oct** [item:itm_tax_objection]; post it by **Thu 15 Oct** to be safe.\n\n" +
      "The letter was read from a phone photo, so please compare the date with the paper letter.",
    note:
      "Left out 1 sentence: its date, time or amount isn't among the dates and amounts Ordnung saved for the linked letter, to-do or contract. " +
      "Amounts in quotation marks are the letter's, read from a photo or not found on its page; Ordnung has not confirmed them.",
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
      { name: "list_items", input: { from: "2026-10-01", to: "2026-10-31", status: "open" }, result: "Found 13 to-dos & dates" },
    ],
    text:
      "October brings **13 open to-dos and dates**, the first ones right at the start:\n\n" +
      "- **Fri 2 Oct** — return the two library books and pay the **€4.50** fee [item:itm_library_return][item:itm_library_fee]\n" +
      "- **Mon 5 Oct** — rent for October, **€640.00** [item:itm_rent_oct]\n" +
      "- **Tue 6 Oct** — post your objection to FitWell's price increase by then if you want to make one; it must arrive by **Mon 12 Oct** (an email is enough) [item:itm_gym_price]. It's also the day to chase Wohnbau, which hasn't answered your request [item:itm_followup_wohnbau]\n" +
      "- **Thu 8 Oct, 09:15** — dentist, check-up and cleaning [item:itm_dentist]\n" +
      "- **Thu 8 Oct** — post your phone-contract cancellation by then if you want to switch; it must arrive by **Wed 14 Oct** [item:itm_phone_cancel]\n" +
      "- **Fri 9 Oct** — utility back payment (Nebenkosten), **€184.30** [item:itm_nk]\n" +
      "- **Tue 13 Oct** — get your documents ready for the Ausländerbehörde [item:itm_abh_docs]\n" +
      "- **Wed 14 Oct, 10:30** — residence permit appointment at the Ausländerbehörde, where you pay the **€93.00** fee [item:itm_abh_appt][item:itm_abh_fee]\n" +
      "- **Thu 15 Oct** — electricity instalment, **€48.00**, and health insurance contribution, **€142.86** [item:itm_power_abschlag][item:itm_bkk]",
    citations: [
      { type: "item", id: "itm_library_return" },
      { type: "item", id: "itm_library_fee" },
      { type: "item", id: "itm_rent_oct" },
      { type: "item", id: "itm_gym_price" },
      { type: "item", id: "itm_followup_wohnbau" },
      { type: "item", id: "itm_dentist" },
      { type: "item", id: "itm_phone_cancel" },
      { type: "item", id: "itm_nk" },
      { type: "item", id: "itm_abh_docs" },
      { type: "item", id: "itm_abh_appt" },
      { type: "item", id: "itm_abh_fee" },
      { type: "item", id: "itm_power_abschlag" },
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
      "1. **Parking fine, €30** — pay by **Tue 29 Sep** to be safe [item:itm_parking]. I don't know when the letter arrived, so I counted from the letter date; if it came later you have a bit more time [doc:doc_parking].\n" +
      "2. **TechMarkt reminder, €94.99** — due **Wed 30 Sep**, otherwise it may go to a debt collector [doc:doc_tm_dunning].\n" +
      "3. **Library** — return the two books and pay **€4.50** by **Fri 2 Oct** [item:itm_library_fee].\n\n" +
      "Nothing else is due before Sunday. Next week brings rent (Mon 5 Oct) [item:itm_rent_oct], your objection to FitWell's price increase if you want to make one (post it by Tue 6 Oct, or email it by Mon 12 Oct) [item:itm_gym_price], the dentist (Thu 8 Oct, 09:15) [item:itm_dentist], your phone-contract decision [item:itm_phone_cancel] and the Nebenkosten back payment, **€184.30** by **Fri 9 Oct** [item:itm_nk].",
    citations: [
      { type: "item", id: "itm_parking" },
      { type: "document", id: "doc_parking" },
      { type: "document", id: "doc_tm_dunning" },
      { type: "item", id: "itm_library_fee" },
      { type: "item", id: "itm_rent_oct" },
      { type: "item", id: "itm_gym_price" },
      { type: "item", id: "itm_dentist" },
      { type: "item", id: "itm_phone_cancel" },
      { type: "item", id: "itm_nk" },
    ],
  },
  {
    question: "When does my phone contract end, and by when do I have to cancel it?",
    match: [["phone"], ["funknetz"], ["handy"], ["mobile"]],
    tools: [
      { name: "search", input: { query: "FunkNetz Kündigung" }, result: "1 letter: Phone contract — FunkNetz Allnet L" },
      { name: "list_contracts", input: { category: "mobile" }, result: "1 contract: FunkNetz Allnet L (€34.99/month)" },
      { name: "explain_date", input: { id: "itm_phone_cancel" }, result: "Due Wed 14 Oct 2026, send by Thu 8 Oct (§ 56 TKG)" },
    ],
    text:
      "Your FunkNetz contract's 24-month minimum term ends on **Sat 14 Nov 2026** [contract:ctr_phone]. With one month's notice, FunkNetz must **receive** your cancellation by **Wed 14 Oct** — if you post it, send it by **Thu 8 Oct** [item:itm_phone_cancel].\n\n" +
      "The quickest way is the cancel button in „Mein FunkNetz“ (they must offer one, § 312k BGB). If you miss the date, nothing bad happens: the contract continues month to month and you can cancel any time with one month's notice [doc:doc_phone].\n\n" +
      // an offer the page can keep: a link to the composer, filled in for this contract (UI audit round 1:
      // "Want me to draft the cancellation letter?" had no way to say yes)
      "[Draft the cancellation letter](/letters?kind=cancellation&contract=ctr_phone) — Ordnung fills in the contract and its dates.",
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
      { name: "money_summary", input: {}, result: "Fixed costs €987.00/month across 9 contracts" },
      { name: "list_contracts", input: { status: "active" }, result: "10 active contracts" },
    ],
    text:
      "Your fixed costs are **€987.00 a month** in total (Ordnung's money overview):\n\n" +
      "- Rent (incl. utilities): **€640.00** [contract:ctr_rent]\n" +
      "- Health insurance: **€142.86** from October [contract:ctr_bkk]\n" +
      "- Deutschlandticket: **€63.00** [contract:ctr_dticket]\n" +
      "- Electricity: **€48.00** [contract:ctr_power] — **€55.00** from Sun 15 Nov if you stay [item:itm_power_new]\n" +
      "- Phone: **€34.99** [contract:ctr_phone] · Gym: **€29.90** [contract:ctr_gym] · Broadcasting fee: **€18.36** [contract:ctr_rundfunk] · Liability insurance: **€4.99** [contract:ctr_liability] · Bank account: **€4.90** [contract:ctr_bank]\n\n" +
      "Tip: your semester fee already includes a Deutschlandsemesterticket — you may be paying for public transport twice [doc:doc_uni].",
    citations: [
      { type: "contract", id: "ctr_rent" },
      { type: "contract", id: "ctr_bkk" },
      { type: "contract", id: "ctr_dticket" },
      { type: "contract", id: "ctr_power" },
      { type: "item", id: "itm_power_new" },
      { type: "contract", id: "ctr_phone" },
      { type: "contract", id: "ctr_gym" },
      { type: "contract", id: "ctr_rundfunk" },
      { type: "contract", id: "ctr_liability" },
      { type: "contract", id: "ctr_bank" },
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
      "The fee is **€93.00**, paid at the appointment [item:itm_abh_fee]. One more thing: your passport expires on 10 Feb 2027, so the office may only extend your permit until then [item:itm_passport_expiry].",
    citations: [
      { type: "item", id: "itm_abh_appt" },
      { type: "document", id: "doc_abh" },
      { type: "item", id: "itm_abh_fee" },
      { type: "item", id: "itm_passport_expiry" },
    ],
  },
];

/**
 * The message of the `demo_miss` error a question without a recording gets (the local demo's one
 * `DEMO_MISS` in `ordnung/assistant/ask.py`). The Ask page shows its own note for the code ("No recorded
 * answer for this question"); the message is for anything else that reads the stream.
 */
export const FALLBACK_ANSWER =
  "The demo replays answers recorded for its sample letters, and there is none for this question. Try one of the suggested questions.";
