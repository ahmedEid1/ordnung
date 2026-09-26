/**
 * The static demo's template letters: the fixed German sentences and English reference of
 * `src/ordnung/drafts/template_letters.py`, the facts each one requires (the same 422 message when
 * one is missing) and its sending advice (`src/ordnung/rules/send.py`). The demo has no model, so
 * the letter is the fixed text only — exactly what the real app writes without Claude.
 */
import { addDays, format, parseISO } from "date-fns";
import type { LetterDetails, SendChannel, SendGuidance, TemplateDraftKind } from "@/api/types";

export interface TemplateContext {
  details: LetterDetails;
  /** "Kundennummer 123" — the letter's first reference, labelled */
  reference: string | null;
  docDate: string | null;
  topic: string | null;
  /** the person's address (profile), for the flat and a new address */
  address: string;
  iban: string;
  taxOffice: boolean;
  schufa: boolean;
  today: string;
}

export interface TemplateLetter {
  subject: string;
  paragraphs: string[];
  subjectEn: string;
  paragraphsEn: string[];
  notes: string[];
  guidance: SendGuidance;
}

const REQUIRED: Record<TemplateDraftKind, [keyof LetterDetails, string][]> = {
  withdrawal: [["subject_matter", "what you ordered or agreed to"]],
  extension_request: [["until", "the new date you ask for"]],
  payment_plan: [
    ["instalment", "the monthly instalment you offer"],
    ["first_instalment", "the day of the first instalment"],
  ],
  defect_notice: [["defect", "what is broken or wrong"]],
  data_access: [],
  receipts_inspection: [],
  deposit_return: [["moved_out_on", "the day you handed the flat back"]],
  address_change: [["new_address", "your new address"]],
};

const de = (iso: string) => format(parseISO(iso), "dd.MM.yyyy");
const en = (iso: string) => format(parseISO(iso), "d MMMM yyyy");
const oneLine = (address: string | null | undefined) =>
  (address ?? "")
    .split(/\n|,/)
    .map((p) => p.trim())
    .filter(Boolean)
    .join(", ");
const dash = (...parts: (string | null | undefined)[]) => parts.filter(Boolean).join(" – ");
const moneyDe = (n: number) => `${n.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
const moneyEn = (n: number) => `€${n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
/** A weekend end moves to Monday (§ 193 BGB; the demo leaves out public holidays). */
const toWorkingDay = (iso: string) => {
  const day = parseISO(iso).getDay();
  return day === 6 ? format(addDays(parseISO(iso), 2), "yyyy-MM-dd") : day === 0 ? format(addDays(parseISO(iso), 1), "yyyy-MM-dd") : iso;
};
const sentence = (text: string) => {
  const t = text.trim().replace(/\s+/g, " ");
  return /[.!?]$/.test(t) ? t : `${t}.`;
};

/** What the person still has to give (plain English), empty when complete. */
export function missingFacts(kind: TemplateDraftKind, ctx: TemplateContext): string[] {
  const known: Partial<Record<keyof LetterDetails, unknown>> = {
    subject_matter: ctx.details.subject_matter || ctx.topic,
    new_address: ctx.details.new_address || ctx.address,
  };
  return REQUIRED[kind]
    .filter(([name]) => {
      const value = name in known ? known[name] : ctx.details[name];
      return value === null || value === undefined || (typeof value === "string" && !value.trim());
    })
    .map(([, label]) => label);
}

function channel(c: SendChannel["channel"], label: string, note: string, citation: string | null = null, recommended = false, allowed = true): SendChannel {
  return { channel: c, label, note, citation, recommended, allowed };
}

const EINSCHREIBEN = "Keep the posting receipt and ask for the delivery record (Auslieferungsbeleg).";

function generalGuidance(note = "No special form is needed."): SendGuidance {
  return {
    send_by: null,
    must_arrive_by: null,
    form: "any",
    form_note: note,
    channels: [
      channel("email", "E-mail", "Quick; keep the sent message.", null, true),
      channel("portal", "The sender's online portal", "If the letter mentions one."),
      channel("letter", "Letter", "Keep a copy."),
      channel("fax", "Fax", "Keep the transmission report."),
    ],
    tips: ["Keep a copy of what you send and any proof of delivery."],
  };
}

/** A court takes letters in writing only — never plain e-mail (`send.py` `_court_channels`). */
export function courtChannels(): SendChannel[] {
  return [
    channel("letter", "Signed letter", "Quote the court's reference (Aktenzeichen); keep a copy.", null, true),
    channel("fax", "Fax of the signed letter", "Keep the transmission report."),
    channel("in_person", "At the court's Rechtsantragstelle", "Free: staff take it down for you; bring the court's letter."),
    channel("email", "E-mail", "Not valid at a court.", null, false, false),
  ];
}

/** A court's name (`routing.is_court`): a word ending in "gericht", and no bailiff or court cashier. */
export function isCourtName(name: string | null | undefined): boolean {
  return /gericht\b/i.test(name ?? "") && !/vollzieh|kasse|zahlstelle/i.test(name ?? "");
}

/** Template letters the server refuses for a kind of letter (`compose.py` `template_refusal`). */
export function templateRefusal(kind: TemplateDraftKind, letterKind: string | null | undefined): string | null {
  if (kind === "extension_request" && letterKind === "court_payment_order")
    return "The two weeks to pay or object to a court payment order are set by law (§ 692 ZPO), and no one can extend them by being asked. Object in time instead — the letter's page offers the objection — or get advice at the court's Rechtsantragstelle.";
  if (kind === "extension_request" && letterKind === "enforcement_order")
    return "The two weeks to object to an enforcement order can't be extended (Notfrist, § 339 ZPO). Object in time instead — the letter's page offers the objection — or get advice at once.";
  if (kind === "extension_request" && letterKind === "dismissal")
    return "The three weeks for a court action against a dismissal are set by law (§ 4 KSchG) — your employer can't extend them. Get advice now (see the card on the letter).";
  if (kind === "payment_plan" && (letterKind === "court_payment_order" || letterKind === "enforcement_order"))
    return "A court doesn't agree instalments — the claimant does. Write to the claimant instead (choose them as the recipient, without the letter), and still pay or object by the court's deadline: an offer to pay in instalments doesn't stop the order.";
  return null;
}

function landlordGuidance(note: string): SendGuidance {
  return {
    ...generalGuidance(note),
    channels: [
      channel("registered_letter", "Letter by Einwurf-Einschreiben", EINSCHREIBEN, null, true),
      channel("email", "E-mail", "Quick; keep the sent message and ask for a confirmation."),
      channel("in_person", "Hand it over in person", "Take a witness who has read the letter."),
      channel("letter", "Letter by normal post", "Works, but you can't prove it arrived."),
    ],
  };
}

/** The fixed letter of `kind`; throws an Error with the API's message when a fact is missing. */
export function templateLetter(kind: TemplateDraftKind, ctx: TemplateContext): TemplateLetter {
  const missing = missingFacts(kind, ctx);
  if (missing.length) throw new Error(`To write this letter, add ${missing.join(" and ")}.`);
  const d = ctx.details;
  const flat = oneLine(ctx.address);
  switch (kind) {
    case "withdrawal": {
      const what = (d.subject_matter || ctx.topic || "").trim();
      const whenDe = [d.ordered_on ? `bestellt am ${de(d.ordered_on)}` : null, d.received_on ? `erhalten am ${de(d.received_on)}` : null].filter(Boolean).join(", ");
      const whenEn = [d.ordered_on ? `ordered on ${en(d.ordered_on)}` : null, d.received_on ? `received on ${en(d.received_on)}` : null].filter(Boolean).join(", ");
      const start = d.received_on || d.ordered_on;
      const until = start ? toWorkingDay(format(addDays(parseISO(start), 14), "yyyy-MM-dd")) : null;
      return {
        subject: dash(`Widerruf des Vertrags über „${what}“`, ctx.reference),
        paragraphs: [
          `hiermit widerrufe ich den von mir abgeschlossenen Vertrag über „${what}“${whenDe ? ` (${whenDe})` : ""}.`,
          "Bitte bestätigen Sie mir den Eingang dieses Widerrufs und erstatten Sie mir alle Zahlungen, die ich geleistet habe.",
        ],
        subjectEn: dash(`Withdrawal from the contract for “${what}”`, ctx.reference),
        paragraphsEn: [`I hereby withdraw from the contract I concluded for “${what}”${whenEn ? ` (${whenEn})` : ""}.`, "Please confirm receipt of this withdrawal and refund all payments I have made."],
        notes: until
          ? [until >= ctx.today ? `You can withdraw until ${en(until)} — sending it in time is enough.` : `The 14 days ended on ${en(until)}. If you were never properly told about the right to withdraw, it lasts longer — get advice.`]
          : ["Add when you ordered or received it: Ordnung then shows how long you can withdraw (usually 14 days)."],
        guidance: {
          send_by: until && until >= ctx.today ? until : null,
          must_arrive_by: null,
          form: "text_form",
          form_note: "Any clear statement is enough — no reasons, no signature. Sending it in time is enough (§ 355 Abs. 1 BGB); sending the goods back alone is not a withdrawal.",
          channels: [
            channel("online_button", "The shop's withdrawal button", "Online shops must offer one since 19 June 2026; it counts when you press it — save the confirmation.", "§ 356a BGB", true),
            channel("email", "E-mail", "Valid; keep the sent e-mail as proof of when you sent it.", "§ 355 Abs. 1, 2 BGB"),
            channel("registered_letter", "Letter by Einwurf-Einschreiben", EINSCHREIBEN, "§ 355 Abs. 1, 2 BGB"),
            channel("letter", "Letter by normal post", "Valid, but you can't prove when you sent it.", "§ 355 Abs. 1, 2 BGB"),
          ],
          tips: ["Send the goods back separately, as the shop's instructions say.", "Keep a copy of what you send and any proof of delivery."],
        },
      };
    }
    case "extension_request": {
      const until = d.until!;
      const current = d.deadline ?? null;
      if (current && until <= current) throw new Error("The new date must be later than the current deadline.");
      return {
        subject: dash("Bitte um Fristverlängerung", ctx.docDate ? `Ihr Schreiben vom ${de(ctx.docDate)}` : null, ctx.reference),
        paragraphs: [
          `${ctx.docDate ? `zu Ihrem Schreiben vom ${de(ctx.docDate)} ` : "in dieser Angelegenheit "}bitte ich Sie, die mir ${current ? `bis zum ${de(current)} gesetzte` : "gesetzte"} Frist bis zum ${de(until)} zu verlängern.`,
          "Bitte bestätigen Sie mir die Verlängerung kurz schriftlich.",
        ],
        subjectEn: dash("Request for an extension of the deadline", ctx.docDate ? `Your letter of ${en(ctx.docDate)}` : null, ctx.reference),
        paragraphsEn: [`${ctx.docDate ? `Regarding your letter of ${en(ctx.docDate)}, ` : ""}I kindly ask you to extend the deadline you set me${current ? ` for ${en(current)}` : ""} until ${en(until)}.`, "Please briefly confirm the extension in writing."],
        notes: ["Add a short reason in your wishes — offices decide case by case. Deadlines set by law (objections, court deadlines) can't be extended by asking: meet them anyway."],
        guidance: { ...generalGuidance(), must_arrive_by: current, tips: ["An extension only counts once they confirm it. Deadlines set by law can't be extended by asking: meet them anyway.", "Keep a copy of what you send and any proof of delivery."] },
      };
    }
    case "payment_plan": {
      const rate = d.instalment!;
      const first = d.first_instalment!;
      const amount = d.amount ?? null;
      if (amount !== null && rate > amount) throw new Error("The monthly instalment can't be more than the amount you owe.");
      const offerDe = `den Betrag in monatlichen Raten von ${moneyDe(rate)} zu zahlen, beginnend am ${de(first)}.`;
      const offerEn = `to pay the amount in monthly instalments of ${moneyEn(rate)}, starting on ${en(first)}.`;
      if (ctx.taxOffice) {
        return {
          subject: dash("Antrag auf Stundung nach § 222 AO", ctx.reference),
          paragraphs: [
            `hiermit beantrage ich die Stundung der${ctx.docDate ? ` mit Bescheid vom ${de(ctx.docDate)}` : ""} festgesetzten Steuer${amount !== null ? ` in Höhe von ${moneyDe(amount)}` : ""} nach § 222 AO.`,
            `Ich biete an, ${offerDe}`,
            "Die sofortige Zahlung des vollen Betrags wäre für mich eine erhebliche Härte.",
          ],
          subjectEn: dash("Application for deferral under § 222 AO", ctx.reference),
          paragraphsEn: [`I hereby apply for a deferral (Stundung) of the tax${amount !== null ? ` of ${moneyEn(amount)}` : ""} under § 222 AO.`, `I offer ${offerEn}`, "Paying the full amount at once would be a considerable hardship for me."],
          notes: ["The tax office usually charges interest on a deferral."],
          guidance: generalGuidance("No special form: ELSTER, fax, e-mail or a letter all work (§ 222 AO). Until the tax office agrees, the full amount stays due."),
        };
      }
      return {
        subject: dash("Bitte um Ratenzahlung", ctx.reference),
        paragraphs: [`zu Ihrer Forderung${ctx.docDate ? ` aus Ihrem Schreiben vom ${de(ctx.docDate)}` : ""}${amount !== null ? ` in Höhe von ${moneyDe(amount)}` : ""} biete ich Ihnen an, ${offerDe}`, "Bitte bestätigen Sie mir die Ratenzahlung schriftlich."],
        subjectEn: dash("Request to pay in instalments", ctx.reference),
        paragraphsEn: [`Regarding your claim${amount !== null ? ` of ${moneyEn(amount)}` : ""}, I offer ${offerEn}`, "Please confirm the instalment plan in writing."],
        notes: ["Until they agree, the full amount stays due."],
        guidance: generalGuidance("No special form is needed. Until they agree, the full amount stays due."),
      };
    }
    case "defect_notice": {
      const defect = sentence(d.defect ?? "");
      const paragraphs = [`hiermit zeige ich Ihnen einen Mangel in meiner Wohnung${flat ? ` ${flat}` : ""} an: ${defect}`];
      const paragraphsEn = [`I hereby notify you of a defect in my flat${flat ? ` at ${flat}` : ""}: ${defect}`];
      if (d.noticed_on) {
        paragraphs.push(`Der Mangel besteht seit dem ${de(d.noticed_on)}.`);
        paragraphsEn.push(`The defect has existed since ${en(d.noticed_on)}.`);
      }
      paragraphs.push(d.fix_by ? `Bitte beseitigen Sie den Mangel bis zum ${de(d.fix_by)}.` : "Bitte beseitigen Sie den Mangel umgehend.");
      paragraphsEn.push(d.fix_by ? `Please repair it by ${en(d.fix_by)}.` : "Please repair it without delay.");
      paragraphs.push("Bis zur Beseitigung behalte ich mir vor, die Miete zu mindern.");
      paragraphsEn.push("Until it is repaired, I reserve the right to reduce the rent.");
      return {
        subject: dash("Mängelanzeige", flat ? `Wohnung ${flat}` : null, ctx.reference),
        paragraphs,
        subjectEn: dash("Notice of a defect", flat ? `flat at ${flat}` : null, ctx.reference),
        paragraphsEn,
        notes: ["Report defects straight away: if you don't, you can lose the right to reduce the rent for that time (§ 536c BGB). Describe the defect in German if you can, and keep photos."],
        guidance: landlordGuidance("No special form, but keep proof that you reported the defect: from then on the rent may be reduced (§ 536c BGB)."),
      };
    }
    case "data_access": {
      const paragraphs = [
        "hiermit bitte ich Sie um Auskunft nach Art. 15 DSGVO, ob Sie personenbezogene Daten über mich verarbeiten.",
        "Falls ja, bitte ich um Auskunft über diese Daten, die Zwecke der Verarbeitung, die Empfänger, die geplante Speicherdauer und die Herkunft der Daten (Art. 15 Abs. 1 DSGVO) sowie um eine kostenlose Kopie der Daten (Art. 15 Abs. 3 DSGVO).",
      ];
      const paragraphsEn = [
        "I hereby request access under Art. 15 GDPR: please confirm whether you process personal data about me.",
        "If so, please tell me what data you hold, the purposes of processing, the recipients, how long it will be stored and where it came from (Art. 15(1) GDPR), and send me a free copy of the data (Art. 15(3) GDPR).",
      ];
      if (ctx.schufa) {
        paragraphs.push("Dazu gehören auch die zu meiner Person gespeicherten und übermittelten Scorewerte.");
        paragraphsEn.push("This includes the score values stored about me and passed on to others.");
      }
      paragraphs.push("Bitte antworten Sie innerhalb eines Monats nach Eingang dieses Schreibens (Art. 12 Abs. 3 DSGVO).");
      paragraphsEn.push("Please reply within one month of receiving this letter (Art. 12(3) GDPR).");
      return {
        subject: dash("Auskunftsersuchen nach Art. 15 DSGVO", ctx.reference),
        paragraphs,
        subjectEn: dash("Request for access under Art. 15 GDPR", ctx.reference),
        paragraphsEn,
        notes: ["They must answer within one month of receiving it. SCHUFA also offers this free copy online ('Datenkopie nach Art. 15 DSGVO') at meineschufa.de.", "If they ask you to prove who you are, send only what they need."],
        guidance: { ...generalGuidance(), tips: ["They must answer within one month (Art. 12 Abs. 3 GDPR), in hard cases within three.", "Keep a copy of what you send and any proof of delivery."] },
      };
    }
    case "receipts_inspection": {
      const period = (d.period ?? "").trim();
      return {
        subject: dash(`Belegeinsicht zur Betriebskostenabrechnung${ctx.docDate ? ` vom ${de(ctx.docDate)}` : ""}`, ctx.reference),
        paragraphs: [
          `zu Ihrer Betriebskostenabrechnung${ctx.docDate ? ` vom ${de(ctx.docDate)}` : ""}${period ? ` für den Abrechnungszeitraum ${period}` : ""} bitte ich um Einsicht in die Abrechnungsbelege (§ 556 Abs. 4 BGB).`,
          "Bitte teilen Sie mir mit, wann und wo ich die Belege einsehen kann, oder stellen Sie sie mir elektronisch zur Verfügung.",
          "Einwendungen gegen die Abrechnung behalte ich mir vor.",
        ],
        subjectEn: dash(`Inspection of the receipts for the operating-cost statement${ctx.docDate ? ` of ${en(ctx.docDate)}` : ""}`, ctx.reference),
        paragraphsEn: [
          `Regarding your operating-cost statement${ctx.docDate ? ` of ${en(ctx.docDate)}` : ""}${period ? ` for the billing period ${period}` : ""}, I ask to inspect the receipts it is based on (§ 556 Abs. 4 BGB).`,
          "Please let me know when and where I can see them, or make them available to me electronically.",
          "I reserve the right to object to the statement.",
        ],
        notes: ["Your objections to the statement must reach the landlord within 12 months of receiving it (§ 556 Abs. 3 BGB)."],
        guidance: generalGuidance(),
      };
    }
    case "deposit_return": {
      const old = oneLine(d.old_address);
      const iban = ctx.iban.replace(/\s/g, "") || "[IBAN]";
      const amount = d.amount ?? null;
      return {
        subject: dash("Rückzahlung der Mietkaution", old ? `Wohnung ${old}` : null, ctx.reference),
        paragraphs: [
          `das Mietverhältnis über die Wohnung${old ? ` ${old}` : ""} ist beendet; die Wohnung habe ich am ${de(d.moved_out_on!)} an Sie zurückgegeben.`,
          `Bitte rechnen Sie über die Mietkaution${amount !== null ? ` in Höhe von ${moneyDe(amount)}` : ""} ab und überweisen Sie mir das Guthaben einschließlich der Zinsen auf mein Konto mit der IBAN ${iban}.`,
          "Bitte teilen Sie mir mit, bis wann ich mit der Abrechnung rechnen kann.",
        ],
        subjectEn: dash("Return of the rent deposit", old ? `flat at ${old}` : null, ctx.reference),
        paragraphsEn: [
          `The tenancy of the flat${old ? ` at ${old}` : ""} has ended; I handed the flat back to you on ${en(d.moved_out_on!)}.`,
          `Please settle the rent deposit${amount !== null ? ` of ${moneyEn(amount)}` : ""} and transfer the balance, including interest, to my account with the IBAN ${iban}.`,
          "Please let me know when I can expect the settlement.",
        ],
        notes: [
          "There is no fixed legal deadline: landlords often take a few months and may keep part of the deposit until the next operating-cost statement.",
          ...(ctx.iban ? [] : ["Add your IBAN in Settings → Profile, or type it where the letter says [IBAN]."]),
        ],
        guidance: landlordGuidance("No special form is needed; keep proof of when you asked."),
      };
    }
    case "address_change": {
      const next = oneLine(d.new_address || ctx.address);
      const old = oneLine(d.old_address);
      const paragraphs = [`bitte beachten Sie, dass sich meine Anschrift${d.moved_on ? ` zum ${de(d.moved_on)}` : ""} geändert hat.`, `Meine neue Anschrift lautet: ${next}.`];
      const paragraphsEn = [`Please note that my address has changed${d.moved_on ? ` as of ${en(d.moved_on)}` : ""}.`, `My new address is: ${next}.`];
      if (old) {
        paragraphs.push(`Meine bisherige Anschrift war: ${old}.`);
        paragraphsEn.push(`My previous address was: ${old}.`);
      }
      paragraphs.push("Bitte senden Sie Ihre Post künftig an meine neue Anschrift.");
      paragraphsEn.push("Please send your post to my new address from now on.");
      return {
        subject: dash("Änderung meiner Anschrift", ctx.reference),
        paragraphs,
        subjectEn: dash("Change of address", ctx.reference),
        paragraphsEn,
        notes: ["Registering at the Bürgeramt within two weeks of moving in is a separate duty."],
        guidance: generalGuidance(),
      };
    }
  }
}
