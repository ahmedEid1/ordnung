/**
 * The composer's template letters (SPEC §11): what each asks for and who it goes to. The backend
 * (`src/ordnung/drafts/template_letters.py`) writes the fixed sentences and refuses a letter with a
 * required fact missing; this file only decides what the form shows and when "Write the letter" is
 * enabled — the same required facts, so the button never promises a letter the server refuses.
 */
import type { LucideIcon } from "lucide-react";
import { CalendarPlus, DatabaseSearch, FileSearch, HandCoins, KeyRound, MapPinHouse, Undo2, Wrench } from "lucide-react";
import type { Document, Item, LetterDetails, PartyKind, TemplateDraftKind } from "@/api/types";
import { formatDate, formatMoney } from "@/lib/format";

/** Who a template letter can go to: a letter it answers or a person/organisation, or a typed address. */
export type TemplateTarget = "letter-or-party" | "party" | "party-or-typed";

/** A required fact also says what is missing in plain words (`need`), for the composer's "Still needed" line. */
type Requirement = { required?: false; need?: never } | { required: true; need: string };

export type DetailField =
  | ({ name: "subject_matter" | "period"; type: "text"; label: string; hint?: string; placeholder?: string } & Requirement)
  | ({ name: "defect" | "new_address" | "old_address"; type: "textarea"; label: string; hint?: string; placeholder?: string } & Requirement)
  | ({
      name: "ordered_on" | "received_on" | "deadline" | "until" | "first_instalment" | "noticed_on" | "fix_by" | "moved_out_on" | "moved_on";
      type: "date";
      label: string;
      hint?: string;
      /** only future days (a new deadline, a first instalment) or only past days (a delivery) */
      when?: "future" | "past";
    } & Requirement)
  | ({ name: "amount" | "instalment"; type: "money"; label: string; hint?: string } & Requirement)
  | { name: "instructions_missing"; type: "checkbox"; label: string; hint?: string; required?: false; need?: never };

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
      { name: "subject_matter", type: "text", label: "What did you order or sign up for?", placeholder: "e.g. Kaffeemaschine KM-200", required: true, need: "what you ordered" },
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
      { name: "until", type: "date", label: "New date you ask for", required: true, need: "the new date", when: "future" },
      { name: "deadline", type: "date", label: "Current deadline", hint: "The date you were given, if the letter itself doesn't name it." },
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
      { name: "instalment", type: "money", label: "Monthly instalment you can pay", required: true, need: "the monthly instalment" },
      { name: "first_instalment", type: "date", label: "First instalment on", required: true, need: "the day of the first instalment", when: "future" },
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
      { name: "defect", type: "textarea", label: "What is broken or wrong?", hint: "In German if you can — it goes into the letter as you write it.", placeholder: "z. B. Die Heizung im Bad funktioniert nicht.", required: true, need: "what is broken" },
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
      { name: "moved_out_on", type: "date", label: "Flat handed back on", required: true, need: "the day you handed the flat back", when: "past" },
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
      { name: "new_address", type: "textarea", label: "Your new address", hint: "From your profile — change it here if it isn't up to date.", required: true, need: "your new address" },
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

/**
 * Parse an amount typed German or English style to a number, or `null` when it can't be read for sure:
 * "1.234,50", "1.500" (German thousands), "80,5", "80,-", "1,234.50", "1,500" (English thousands),
 * "1234.5". A dot or comma followed by exactly three digits groups thousands — euro amounts have at
 * most two decimals — so "1.500" is 1500, never 1,50.
 */
export function parseMoney(text: string | undefined): number | null {
  const t = (text ?? "").trim().replace(/[€\s]|EUR/gi, "").replace(/,[-–]$/, "");
  if (!t) return null;
  let normalised: string | null = null;
  if (/^\d{1,3}(\.\d{3})+(,\d{1,2})?$/.test(t)) normalised = t.replace(/\./g, "").replace(",", ".");
  else if (/^\d{1,3}(,\d{3})+(\.\d{1,2})?$/.test(t)) normalised = t.replace(/,/g, "");
  else if (/^\d+,\d{1,2}$/.test(t)) normalised = t.replace(",", ".");
  else if (/^\d+(\.\d{1,2})?$/.test(t)) normalised = t;
  if (normalised === null) return null;
  const n = Number(normalised);
  return Number.isFinite(n) ? n : null;
}

/** What the letter a template answers already says: its earliest open deadline and payment. The server
 * uses them when the person leaves "Current deadline" or "Total amount" empty (drafts/compose.py). */
export interface LetterDefaults {
  deadline: string | null;
  amount: number | null;
}

const OPEN = new Set(["open", "snoozed"]);

type DefaultsItem = Pick<Item, "kind" | "status" | "due_date" | "amount"> & Partial<Pick<Item, "origin" | "date_spec">>;

/**
 * A deadline the law sets — one the law adds to the letter (`origin: "rule"`) or an objection period:
 * nobody extends it by being asked (drafts/compose.py `extendable`).
 */
export function isStatutoryDeadline(i: Partial<Pick<Item, "origin" | "date_spec">>): boolean {
  return i.origin === "rule" || i.date_spec?.nature === "objection";
}

/** The letter's defaults from its to-dos — the same choice the server makes (`_earliest_open`): the
 * deadline to extend is never one the law sets. */
export function letterDefaults(items: readonly DefaultsItem[]): LetterDefaults {
  const earliest = (kinds: string[], extendable = false) =>
    items
      .filter((i) => OPEN.has(i.status) && kinds.includes(i.kind) && i.due_date && !(extendable && isStatutoryDeadline(i)))
      .sort((a, b) => (a.due_date! < b.due_date! ? -1 : a.due_date! > b.due_date! ? 1 : 0))[0] ?? null;
  return { deadline: earliest(["deadline", "task"], true)?.due_date ?? null, amount: earliest(["payment"])?.amount ?? null };
}

/** The letter's open deadlines the law sets (a request for more time can't move them). */
export function statutoryDeadlines<T extends DefaultsItem>(items: readonly T[]): T[] {
  return items.filter((i) => OPEN.has(i.status) && (i.kind === "deadline" || i.kind === "task") && i.due_date && isStatutoryDeadline(i));
}

const COURT_ORDERS = new Set<Document["kind"]>(["court_payment_order", "enforcement_order"]);

/**
 * Why a template letter can't answer this letter — the server refuses the same (drafts/compose.py
 * `template_refusal`): more time against a deadline the law sets (a court order, a dismissal), or
 * instalments offered to a court instead of the claimant.
 */
export function templateRefusal(kind: TemplateDraftKind, letterKind: Document["kind"] | null | undefined): { title: string; body: string } | null {
  if (kind === "extension_request" && letterKind && COURT_ORDERS.has(letterKind)) {
    return {
      title: "A court's deadline can't be extended",
      body:
        letterKind === "enforcement_order"
          ? "The period to object to an enforcement order is a Notfrist (two weeks, § 339 ZPO; one week at a labour court, § 59 ArbGG) — no one can extend it. Object in time instead, or get advice at once."
          : "The period to pay or object to a court payment order is set by law (two weeks, § 692 ZPO; one week at a labour court, § 46a ArbGG) — no one can extend it by being asked. Object in time instead, or get advice at the court's Rechtsantragstelle.",
    };
  }
  if (kind === "extension_request" && letterKind === "dismissal") {
    return {
      title: "The three weeks can't be extended",
      body: "The three weeks for a court action against a dismissal are set by law (§ 4 KSchG) — your employer can't extend them. Get advice now (see the card on the letter).",
    };
  }
  if (kind === "payment_plan" && letterKind && COURT_ORDERS.has(letterKind)) {
    return {
      title: "Offer instalments to the claimant, not the court",
      body: "A court doesn't agree instalments — the claimant does. Choose the claimant below instead of the letter, and still pay or object by the court's deadline: an offer to pay in instalments doesn't stop the order.",
    };
  }
  return null;
}

const NO_DEFAULTS: LetterDefaults = { deadline: null, amount: null };

/** Required facts still missing, as plain words ("the monthly instalment"), in form order. */
export function missingFields(config: TemplateConfig, values: DetailValues): string[] {
  return config.fields
    .filter((f) => f.required)
    .filter((f) => {
      if (f.type === "money") return (parseMoney(values[f.name]) ?? 0) <= 0;
      return !(values[f.name as keyof DetailValues] as string | undefined)?.trim();
    })
    .map((f) => f.need ?? f.label);
}

/** "a, b and c". */
export function joinAnd(parts: string[]): string {
  return parts.length < 2 ? parts.join("") : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

/** The day after `today` (ISO), the first day a "future" date field accepts. */
export function nextDay(today: string): string {
  const d = new Date(`${today}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

/**
 * A problem with a given value (a date on the wrong side of today, an unreadable amount), checked the
 * way the server checks it — including against the letter's own deadline and amount (`defaults`) when
 * the person left theirs empty, so "Write the letter" is never enabled for a letter the server refuses.
 */
export function fieldError(field: DetailField, values: DetailValues, today: string, defaults: LetterDefaults = NO_DEFAULTS): string | null {
  if (field.type === "money") {
    const raw = values[field.name]?.trim();
    if (!raw) return null;
    const value = parseMoney(raw);
    if (value === null) return "Enter an amount like 80, 1.500 or 1.234,50.";
    if (field.name === "instalment") {
      const total = parseMoney(values.amount) ?? defaults.amount;
      if (total !== null && value > total) return `The instalment can't be more than the amount you owe (${formatMoney(total)}).`;
    }
    return null;
  }
  if (field.type !== "date") return null;
  const value = values[field.name];
  if (!value) return null;
  if (field.when === "future" && value <= today) return "Choose a day after today.";
  if (field.when === "past" && value > today) return "This day can't be in the future.";
  if (field.name === "until") {
    const current = values.deadline || defaults.deadline;
    if (current && value <= current) {
      return values.deadline ? "Choose a day after the current deadline." : `Choose a day after the letter's deadline (${formatDate(current, { style: "short" })}).`;
    }
  }
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
