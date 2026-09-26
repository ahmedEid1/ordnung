/**
 * The composer's template letters (SPEC §11): what each asks for and who it goes to. The backend
 * (`src/ordnung/drafts/template_letters.py`) writes the fixed sentences and refuses a letter with a
 * required fact missing; this file only decides what the form shows and when "Write the letter" is
 * enabled — the same required facts, so the button never promises a letter the server refuses.
 */
import type { LucideIcon } from "lucide-react";
import { CalendarPlus, DatabaseSearch, FileSearch, HandCoins, KeyRound, MapPinHouse, Undo2, Wrench } from "lucide-react";
import type { LetterDetails, PartyKind, TemplateDraftKind } from "@/api/types";

/** Who a template letter can go to: a letter it answers or a person/organisation, or a typed address. */
export type TemplateTarget = "letter-or-party" | "party" | "party-or-typed";

export type DetailField =
  | { name: "subject_matter" | "period"; type: "text"; label: string; hint?: string; placeholder?: string; required?: boolean }
  | { name: "defect" | "new_address" | "old_address"; type: "textarea"; label: string; hint?: string; placeholder?: string; required?: boolean }
  | {
      name: "ordered_on" | "received_on" | "deadline" | "until" | "first_instalment" | "noticed_on" | "fix_by" | "moved_out_on" | "moved_on";
      type: "date";
      label: string;
      hint?: string;
      required?: boolean;
      /** only future days (a new deadline, a first instalment) or only past days (a delivery) */
      when?: "future" | "past";
    }
  | { name: "amount" | "instalment"; type: "money"; label: string; hint?: string; required?: boolean }
  | { name: "instructions_missing"; type: "checkbox"; label: string; hint?: string };

export interface TemplateConfig {
  kind: TemplateDraftKind;
  title: string;
  /** one short line under the title in the chooser */
  blurb: string;
  icon: LucideIcon;
  target: TemplateTarget;
  /** step 2's question */
  whichLabel: string;
  /** party kinds listed first in the recipient picker */
  preferredParties?: PartyKind[];
  fields: DetailField[];
  /** the placeholder of the "your wishes" box */
  wishes: string;
}

export const TEMPLATES: TemplateConfig[] = [
  {
    kind: "withdrawal",
    title: "Withdraw from a purchase",
    blurb: "Online, by phone or at the door — usually 14 days",
    icon: Undo2,
    target: "letter-or-party",
    whichLabel: "Which order or contract?",
    preferredParties: ["retailer", "company", "telecom", "gym"],
    fields: [
      { name: "subject_matter", type: "text", label: "What did you order or sign up for?", placeholder: "e.g. Kaffeemaschine KM-200", required: true },
      { name: "ordered_on", type: "date", label: "Ordered or signed on", when: "past" },
      { name: "received_on", type: "date", label: "Goods received on", hint: "For goods, the 14 days start when they arrive.", when: "past" },
      { name: "instructions_missing", type: "checkbox", label: "I was never told about my right to withdraw", hint: "Then it can last up to 12 months and 14 days." },
    ],
    wishes: "e.g. Please refund the money to my card.",
  },
  {
    kind: "extension_request",
    title: "Ask for more time",
    blurb: "A short extension for a deadline in a letter",
    icon: CalendarPlus,
    target: "letter-or-party",
    whichLabel: "Which letter set the deadline?",
    fields: [
      { name: "until", type: "date", label: "New date you ask for", required: true, when: "future" },
      { name: "deadline", type: "date", label: "Current deadline", hint: "Leave empty to use the deadline in the letter." },
    ],
    wishes: "e.g. I'm waiting for documents from my employer.",
  },
  {
    kind: "payment_plan",
    title: "Pay in instalments",
    blurb: "Ratenzahlung — or Stundung from the tax office",
    icon: HandCoins,
    target: "letter-or-party",
    whichLabel: "Which bill or decision?",
    fields: [
      { name: "instalment", type: "money", label: "Monthly instalment you can pay", required: true },
      { name: "first_instalment", type: "date", label: "First instalment on", required: true, when: "future" },
      { name: "amount", type: "money", label: "Total amount", hint: "Leave empty to use the amount in the letter." },
    ],
    wishes: "e.g. My income dropped after my contract ended.",
  },
  {
    kind: "defect_notice",
    title: "Report a defect",
    blurb: "Something broken in your flat",
    icon: Wrench,
    target: "party",
    whichLabel: "Who is your landlord?",
    preferredParties: ["landlord", "person", "company"],
    fields: [
      { name: "defect", type: "textarea", label: "What is broken or wrong?", hint: "In German if you can — it goes into the letter as you write it.", placeholder: "z. B. Die Heizung im Bad funktioniert nicht.", required: true },
      { name: "noticed_on", type: "date", label: "Since when?", when: "past" },
      { name: "fix_by", type: "date", label: "Repair by", when: "future" },
    ],
    wishes: "e.g. I'm at home on weekday mornings for a repair appointment.",
  },
  {
    kind: "data_access",
    title: "Ask for your data",
    blurb: "Art. 15 GDPR — incl. the free SCHUFA copy",
    icon: DatabaseSearch,
    target: "party-or-typed",
    whichLabel: "Which company or office?",
    fields: [],
    wishes: "e.g. Please send the copy by post.",
  },
  {
    kind: "receipts_inspection",
    title: "See the receipts",
    blurb: "Behind an operating-cost statement",
    icon: FileSearch,
    target: "letter-or-party",
    whichLabel: "Which statement?",
    preferredParties: ["landlord", "company"],
    fields: [{ name: "period", type: "text", label: "Billing period", placeholder: "01.01.2025 – 31.12.2025", hint: "Leave empty to use the period the statement names." }],
    wishes: "e.g. Please send scans of the heating and water bills.",
  },
  {
    kind: "deposit_return",
    title: "Get your deposit back",
    blurb: "After you moved out (Kaution)",
    icon: KeyRound,
    target: "party",
    whichLabel: "Who was your landlord?",
    preferredParties: ["landlord", "person", "company"],
    fields: [
      { name: "moved_out_on", type: "date", label: "Flat handed back on", required: true, when: "past" },
      { name: "amount", type: "money", label: "Deposit paid" },
      { name: "old_address", type: "textarea", label: "Address of the flat", placeholder: "Street and number, postcode and town" },
    ],
    wishes: "e.g. The handover report shows no damage.",
  },
  {
    kind: "address_change",
    title: "Share a new address",
    blurb: "Tell a bank, insurer or office you moved",
    icon: MapPinHouse,
    target: "party",
    whichLabel: "Who should know?",
    preferredParties: ["bank", "insurer", "health_insurer", "telecom", "utility", "university", "employer"],
    fields: [
      { name: "new_address", type: "textarea", label: "Your new address", hint: "From your profile — change it here if it isn't up to date.", required: true },
      { name: "old_address", type: "textarea", label: "Your previous address", placeholder: "Street and number, postcode and town" },
      { name: "moved_on", type: "date", label: "Moved on" },
    ],
    wishes: "e.g. Please update my address for all my contracts.",
  },
];

export const TEMPLATE_BY_KIND = Object.fromEntries(TEMPLATES.map((t) => [t.kind, t])) as Record<TemplateDraftKind, TemplateConfig>;

export function isTemplateKind(kind: string | null | undefined): kind is TemplateDraftKind {
  return Boolean(kind && kind in TEMPLATE_BY_KIND);
}

/** SCHUFA's consumer service address (its Art. 14 GDPR information sheet), for the one-click data request. */
export const SCHUFA_ADDRESS = "SCHUFA Holding AG\nPrivatkunden ServiceCenter\nPostfach 10 34 41\n50474 Köln";

/** The form's values: every field as a string (dates ISO, amounts as typed), the checkbox as a flag. */
export type DetailValues = Partial<Record<Exclude<DetailField["name"], "instructions_missing">, string>> & { instructions_missing?: boolean };

/** Parse an amount typed German or English style ("1.234,50", "1234.5", "80") to a number. */
export function parseMoney(text: string | undefined): number | null {
  const t = (text ?? "").trim().replace(/[€\s]/g, "");
  if (!t) return null;
  const normalised = /,\d{1,2}$/.test(t) ? t.replace(/\./g, "").replace(",", ".") : t.replace(/,/g, "");
  const n = Number(normalised);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

/** Required facts still missing (their labels), in form order. */
export function missingFields(config: TemplateConfig, values: DetailValues): string[] {
  return config.fields
    .filter((f) => "required" in f && f.required)
    .filter((f) => {
      if (f.type === "money") return (parseMoney(values[f.name]) ?? 0) <= 0;
      return !(values[f.name as keyof DetailValues] as string | undefined)?.trim();
    })
    .map((f) => f.label);
}

/** A problem with a given value (a date on the wrong side of today, an unreadable amount). */
export function fieldError(field: DetailField, values: DetailValues, today: string): string | null {
  if (field.type === "money") {
    const raw = values[field.name]?.trim();
    if (raw && parseMoney(raw) === null) return "Enter an amount like 80 or 1.234,50.";
    return null;
  }
  if (field.type !== "date") return null;
  const value = values[field.name];
  if (!value) return null;
  if (field.when === "future" && value <= today) return "Choose a day after today.";
  if (field.when === "past" && value > today) return "This day can't be in the future.";
  if (field.name === "until" && values.deadline && value <= values.deadline) return "Choose a day after the current deadline.";
  return null;
}

/** The `details` of `POST /api/drafts`: only the fields of this template, typed. */
export function detailsPayload(config: TemplateConfig, values: DetailValues, recipient?: string | null): LetterDetails {
  const out: Record<string, unknown> = {};
  for (const f of config.fields) {
    if (f.type === "checkbox") {
      if (values.instructions_missing) out.instructions_missing = true;
      continue;
    }
    const raw = values[f.name]?.trim();
    if (!raw) continue;
    out[f.name] = f.type === "money" ? parseMoney(raw) : raw;
  }
  if (recipient?.trim()) out.recipient = recipient.trim();
  return out as LetterDetails;
}

/** Parties sorted for a template's picker: preferred kinds first, then by name. */
export function sortForTemplate<P extends { kind: PartyKind; name: string }>(parties: P[], config: TemplateConfig | null): P[] {
  const rank = (p: P) => {
    const i = config?.preferredParties?.indexOf(p.kind) ?? -1;
    return i < 0 ? 99 : i;
  };
  return [...parties].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
}
