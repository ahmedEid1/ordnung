/**
 * Key facts and reference numbers as the model copied them from a German letter, shown the app's
 * way (UI audit round 1: "Gültig ab", "1.320 kWh" and "670,00 € (bisher 640,00 €)" were shown as
 * written):
 *
 * - labels in English with the letter's own word in brackets — "Valid from (Gültig ab)" — for the
 *   labels German letters usually have; a label that stays German is flagged so the page marks it
 *   `lang="de"`;
 * - values with money, numbers, units and dates in the app's English format — "63,00 € pro Monat"
 *   → "€63.00/month", "1.320 kWh" → "1,320 kWh", "01.10.–31.12.2025 (92 Tage)" → "1 Oct – 31 Dec
 *   2025 (92 days)"; a value that stays German ("Bis zum 10. eines Monats …") is flagged too.
 *
 * Display only: copy buttons copy the value as the letter wrote it.
 */
import { formatDate, formatFactValue, formatInlineText, formatMoney, formatTime, looksGerman, parseLooseNumber, tryParseDate } from "@/lib/format";
import { NBSP, protectRefs } from "@/lib/glue";

// ------------------------------------------------------------------------------------------------
// Labels German letters use most
// ------------------------------------------------------------------------------------------------

/**
 * English for the labels German letters use most. Keys are lower-case; a trailing "." is ignored
 * ("Versicherten-Nr."). Only whole labels: "Neue Gesamtmiete ab 01.11.2026" stays as written.
 */
const LABELS: Record<string, string> = {
  abonummer: "Subscription number",
  abrechnungszeitraum: "Billing period",
  abschlag: "Instalment",
  aktenzeichen: "File number",
  "amtsgericht/hrb": "Commercial register",
  arbeitspreis: "Unit price",
  aufnahmegebühr: "Joining fee",
  "aufenthaltserlaubnis gültig bis": "Residence permit valid until",
  auftragsnummer: "Order number",
  "beitrags-nr": "Contribution number",
  beitragsnummer: "Contribution number",
  "benutzer-nr": "User number",
  benutzernummer: "User number",
  bestellnummer: "Order number",
  betrag: "Amount",
  "einkünfte aus nichtselbständiger arbeit": "Income from employment",
  einkommensteuer: "Income tax",
  erstattung: "Refund",
  erstattungsbetrag: "Refund",
  bruttoarbeitslohn: "Gross wages",
  finanzamt: "Tax office",
  idnr: "Tax ID",
  lohnsteuer: "Wage tax",
  sonderausgaben: "Special expenses",
  "steuer-idnr": "Tax ID",
  "steuerliche identifikationsnummer": "Tax ID",
  vorsorgeaufwendungen: "Pension and insurance costs",
  werbungskosten: "Work expenses",
  "zu versteuerndes einkommen": "Taxable income",
  erstlaufzeit: "Initial term",
  fahrzeug: "Vehicle",
  "fällig am": "Due on",
  fälligkeit: "Due date",
  "festgesetzte einkommensteuer": "Income tax assessed",
  fortgeltungsfiktion: "Permit while you wait",
  gebühr: "Fee",
  "gesamt offen": "Total outstanding",
  gesamtbetrag: "Total amount",
  gesamtbrutto: "Gross pay",
  gesamtgebühren: "Total fees",
  gesamtmiete: "Total rent",
  "gläubiger-id": "Creditor ID",
  "grundmiete (nettokaltmiete)": "Base rent",
  grundmiete: "Base rent",
  grundpreis: "Base price",
  "gültig ab": "Valid from",
  "gültig bis": "Valid until",
  guthaben: "Credit",
  jahresverbrauch: "Annual use",
  kassenzeichen: "Payment reference",
  kaution: "Deposit",
  kirchensteuer: "Church tax",
  "kunden-nr": "Customer number",
  kundennummer: "Customer number",
  kündigungsfrist: "Notice period",
  laufzeit: "Term",
  lieferbeginn: "Supply starts",
  mahngebühr: "Reminder fee",
  mandatsreferenz: "Mandate reference",
  marktlokation: "Market location ID",
  matrikelnummer: "Student number",
  mediennummer: "Item number",
  mietbeginn: "Tenancy starts",
  "mietsicherheit (kaution)": "Security deposit",
  mindestlaufzeit: "Minimum term",
  mitgliedsnummer: "Membership number",
  monatsbeitrag: "Monthly fee",
  nachzahlung: "Amount to pay",
  nettoverdienst: "Net pay",
  nutzungszeitraum: "Period of use",
  personalnummer: "Staff number",
  preis: "Price",
  rechnungsbetrag: "Invoice amount",
  "rechnungs-nr": "Invoice number",
  rechnungsnummer: "Invoice number",
  "rentenversicherung arbeitnehmeranteil": "Pension insurance, your share",
  rückgabefrist: "Return by",
  säumnisgebühr: "Late fee",
  solidaritätszuschlag: "Solidarity surcharge",
  sperrschwelle: "Account blocked from",
  "steuer-id": "Tax ID",
  steuerklasse: "Tax class",
  steuernummer: "Tax number",
  studiengang: "Programme",
  "sv-nummer": "Social insurance number",
  tarif: "Tariff",
  tatort: "Place of offence",
  tatvorwurf: "Alleged offence",
  tatzeit: "Time of offence",
  termin: "Appointment",
  "unser zeichen": "Their reference",
  "ust-idnr": "VAT ID",
  "vers.-nr": "Policy number",
  "versicherten-nr": "Insurance number",
  versicherungsnummer: "Policy number",
  vertragskonto: "Contract account",
  vertragsnummer: "Contract number",
  verwarnungsgeld: "Fine",
  "voraussichtlicher jahresverbrauch": "Expected annual use",
  "vorauszahlung betriebskosten": "Advance for running costs",
  "vorauszahlung heiz- und warmwasserkosten": "Advance for heating and hot water",
  "vorauszahlungen geleistet": "Advances paid",
  vorgang: "Case number",
  "vorgangs-nr": "Case number",
  vorgangsnummer: "Case number",
  "weee-reg.-nr": "WEEE registration",
  wohnfläche: "Living space",
  wohnung: "Flat",
  wohnungsnummer: "Flat number",
  zahlungsweise: "Payment method",
  zählernummer: "Meter number",
  zeitraum: "Period",
};

const labelKey = (label: string) => label.trim().toLowerCase().replace(/\.$/, "");

/** One-word labels above ("tatzeit", "studiengang"): German words too short to spot otherwise. */
const LABEL_WORDS = new Set(Object.keys(LABELS).filter((k) => /^[\p{L}-]+$/u.test(k)));

// ------------------------------------------------------------------------------------------------
// German or not
// ------------------------------------------------------------------------------------------------

/** Short German words and abbreviations that never appear in an English label or value. */
const GERMAN_WORD =
  /^(?:und|oder|der|die|das|des|dem|den|ein|eine|eines|einer|dieses|nicht|bis|ab|pro|zum|zur|vom|mit|bei|für|gilt|zahlbar|bisher|monatlich|jährlich|brutto|netto|uhr|tag|tage|monat|monate|woche|wochen|jahr|jahre|stunden|ca|inkl|zzgl|gem|lt|nr|ihr|ihre|ihren|neue|neuer|alte|amtliches|raten|monatliche|monatlicher|monatlichen|jährliche|jährlicher|zahlen|bezahlen|gegen|wegen)$/;

/**
 * Parts of German compound nouns on letters ("Monatsbeitrag", "Kündigungsfrist", "Vertragsnummer")
 * that no English word contains ("beginn" but not "beginning").
 */
const GERMAN_STEM =
  /deutschland|beitrag|gebühr|zeitraum|betrag|frist|miete|kosten|verbrauch|zahlung|kündigung|laufzeit|steuer|abrechnung|vertrag|versicherung|nummer|zeichen|fahrzeug|vorwurf|lastschrift|abbuchung|preis|verdienst|konto|leistung|anteil|schwelle|wohnung|fläche|beginn(?!ing|er)|fiktion|erlaubnis|bescheid|behörde|kasse|zulage|zuschlag|pflicht|ausweis|geld/;

/** A German word; `short` also counts the short function words ("bis", "ab", "und") — not in English prose. */
function germanWord(word: string, short = true): boolean {
  const w = word.toLowerCase();
  return /[äöüß]/.test(w) || (short && GERMAN_WORD.test(w)) || GERMAN_STEM.test(w) || LABEL_WORDS.has(w);
}

/**
 * Text (a label or a value) written in German rather than English: at least as many German words
 * ("Neue Gesamtmiete ab …", "Bis zum 10. eines Monats …") as other words. English with a German
 * term in it ("BAföG-based assessment basis") stays English. Numbers and short abbreviations
 * ("BKK", "IBAN") don't count.
 */
export function isGermanText(text: string): boolean {
  if (looksGerman(text)) return true;
  let german = 0;
  let other = 0;
  for (const token of text.split(/[^\p{L}\p{N}-]+/u)) {
    const word = token.replace(/^-+|-+$/g, "");
    // numbers, abbreviations ("BKK", "IBAN") and "in" (both languages) say nothing
    if (!/\p{L}{2,}/u.test(word) || /^[\p{Lu}\d-]{2,4}$/u.test(word) || word === "in") continue;
    if (germanWord(word)) german += 1;
    else other += 1;
  }
  return german > 0 && german >= other;
}

// ------------------------------------------------------------------------------------------------
// Labels
// ------------------------------------------------------------------------------------------------

export interface FactLabel {
  /** The label in English (null: only the German is known). */
  en: string | null;
  /** The letter's German label: after the English in brackets, or alone. */
  de: string | null;
}

const capitalise = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/**
 * "Gültig ab" → { en: "Valid from", de: "Gültig ab" }; "Tatzeit (time of offence)" →
 * { en: "Time of offence", de: "Tatzeit" }; "Invoice number" → { en: "Invoice number", de: null };
 * "Neue Gesamtmiete ab 01.11.2026" → { en: null, de: "Neue Gesamtmiete ab 01.11.2026" }.
 */
export function factLabel(label: string): FactLabel {
  const text = label.trim();
  const known = LABELS[labelKey(text)];
  if (known) return { en: known, de: text };
  // "Tatzeit (time of offence)": the model already put the English in brackets
  const pair = /^(.+?)\s*\(([^()]+)\)$/.exec(text);
  if (pair && (LABELS[labelKey(pair[1]!)] || isGermanText(pair[1]!)) && !isGermanText(pair[2]!) && /\p{Ll}{3,}/u.test(pair[2]!)) {
    return { en: capitalise(pair[2]!.trim()), de: pair[1]!.trim() };
  }
  return isGermanText(text) ? { en: null, de: text } : { en: text, de: null };
}

/** The German label as it reads in brackets after the English: "Mietsicherheit (Kaution)" → "Mietsicherheit, Kaution". */
export function bracketed(de: string): string {
  return de.replace(/\s*\(([^()]+)\)/g, ", $1");
}

// ------------------------------------------------------------------------------------------------
// Values
// ------------------------------------------------------------------------------------------------

export interface FactValue {
  /** The value to show (display only: it may carry non-breaking glue). */
  text: string;
  /** The value is (still) German — mark it `lang="de"`. */
  german: boolean;
}

/** A number as a German letter writes it ("1.320", "48,6", "1.560,00") — or an English one ("34.99"). */
const NUM = String.raw`\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?`;

const UNITS: Record<string, string> = {
  tag: "days",
  tage: "days",
  tagen: "days",
  woche: "weeks",
  wochen: "weeks",
  monat: "months",
  monate: "months",
  monaten: "months",
  jahr: "years",
  jahre: "years",
  jahren: "years",
  stunde: "hours",
  stunden: "hours",
  std: "hours",
  qm: "m²",
};
const UNIT_RE = String.raw`ct\/kWh|Cent\/kWh|kWh|m²|m³|qm|km|kg|GB|MB|%|Tagen|Tage|Tag|Wochen|Woche|Monaten|Monate|Monat|Jahren|Jahre|Jahr|Stunden|Stunde|Std\.?`;
const QUALIFIER: Record<string, string> = { brutto: "gross", netto: "net", "inkl. mwst.": "incl. VAT", "zzgl. mwst.": "plus VAT" };
const QUALIFIER_RE = String.raw`\(\s*(brutto|netto|inkl\. MwSt\.|zzgl\. MwSt\.)\s*\)`;
const INTERVALS: Record<string, string> = {
  monat: "/month",
  monatlich: "/month",
  jahr: "/year",
  jährlich: "/year",
  quartal: "/quarter",
  vierteljährlich: "/quarter",
  woche: "/week",
  wöchentlich: "/week",
};

const MEASURE = new RegExp(String.raw`^(ca\.\s*)?(${NUM})\s?(${UNIT_RE})(?:\s*${QUALIFIER_RE})?$`, "iu");
const MONEY_PER = new RegExp(
  String.raw`^(?:(?:€|EUR)\s?(${NUM})|(${NUM})\s?(?:€|EUR|Euro))\s*(?:(?:pro|je|\/)\s*(Monat|Jahr|Quartal|Woche)|(monatlich|jährlich|vierteljährlich|wöchentlich))(?:\s*${QUALIFIER_RE})?$`,
  "iu",
);
const DATE_RANGE = /^(\d{1,2})\.(\d{1,2})\.(\d{4})?\s*[–-]\s*(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s*\((\d+)\s*(?:Tage|days)\))?$/;
const MONTH_RANGE = /^(\d{1,2})\.(\d{4})\s*[–-]\s*(\d{1,2})\.(\d{4})$/;
const DATE_TIME_RANGE = /^(\d{1,2})\.(\d{1,2})\.(\d{4}),?\s*(\d{1,2}:\d{2})\s*[–-]\s*(\d{1,2}:\d{2})(?:\s*Uhr)?$/;
/** A German date in running text — never the second half of a pair of days ("18./20.08.2026"). */
const INLINE_GERMAN_DATE = /(?<!\d\.?)(?<!\d\.\/)(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\.?\d)/g;
/** Two days of one month, as a German letter writes them: "ordered and delivered on 18./20.08.2026". */
const INLINE_GERMAN_DAY_PAIR = /(?<!\d\.?)(\d{1,2})\.\/(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\.?\d)/g;

const iso = (y: string | number, m: string, d: string) => `${y}-${m.padStart(2, "0")}-${d.padStart(2, "0")}`;
const valid = (s: string) => tryParseDate(s) !== null;

/**
 * German dates in English running text the app's way — "due by 09.10.2026" → "due by Fri 9 Oct 2026", a pair
 * of days "18./20.08.2026" → "18/20 Aug 2026" (UI audit round 2: it read "18./Thu 20 Aug 2026") — or the text
 * as written when one of them is no real date.
 */
function englishDates(text: string): string {
  const pairs = [...text.matchAll(INLINE_GERMAN_DAY_PAIR)];
  const singles = [...text.matchAll(INLINE_GERMAN_DATE)];
  if (!pairs.length && !singles.length) return text;
  const pairsValid = pairs.every(([, d1, d2, mo, y]) => Number(d1) < Number(d2) && valid(iso(y!, mo!, d1!)) && valid(iso(y!, mo!, d2!)));
  if (!pairsValid || !singles.every(([, d, mo, y]) => valid(iso(y!, mo!, d!)))) return text;
  return text
    .replace(INLINE_GERMAN_DAY_PAIR, (_all, d1: string, d2: string, mo: string, y: string) =>
      `${Number(d1)}/${formatDate(iso(y, mo, d2), { style: "medium" })}`.replace(/ /g, NBSP),
    )
    .replace(INLINE_GERMAN_DATE, (_all, d: string, mo: string, y: string) =>
      formatDate(iso(y, mo, d), { style: "short", withYear: "always" }).replace(/ /g, NBSP),
    );
}

/** "1.320" → "1,320"; "48,6" → "48.6"; as many decimals as written. */
function englishNumber(num: string): string | null {
  const n = parseLooseNumber(num);
  if (n === null) return null;
  const grouped = /^\d{1,3}(?:[.,]\d{3})+$/.test(num) && Number.isInteger(n);
  const decimals = grouped ? 0 : (/[.,](\d+)$/.exec(num)?.[1]?.length ?? 0);
  return new Intl.NumberFormat("en-GB", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(n);
}

function englishMoney(num: string): string | null {
  const n = parseLooseNumber(num);
  return n === null ? null : formatMoney(n, { decimals: /[.,]\d{2}$/.test(num) ? 2 : 0 });
}

const qualifier = (q: string | undefined) => (q ? ` (${QUALIFIER[q.toLowerCase()] ?? q})` : "");

function dateRange(m: RegExpExecArray): string | null {
  const endYear = Number(m[6]);
  let startYear = m[3] ? Number(m[3]) : endYear;
  if (!m[3] && Number(m[2]) > Number(m[5])) startYear -= 1;
  const start = iso(startYear, m[2]!, m[1]!);
  const end = iso(endYear, m[5]!, m[4]!);
  if (!valid(start) || !valid(end)) return null;
  const from = startYear === endYear ? formatDate(start, { style: "day", withYear: "never" }) : formatDate(start, { style: "medium" });
  const days = m[7] ? ` (${m[7]} ${m[7] === "1" ? "day" : "days"})` : "";
  return `${from} – ${formatDate(end, { style: "medium" })}${days}`;
}

function monthRange(m: RegExpExecArray): string | null {
  const start = iso(m[2]!, m[1]!, "1");
  const end = iso(m[4]!, m[3]!, "1");
  if (!valid(start) || !valid(end)) return null;
  const month = (d: string) => formatDate(d, { style: "month" }).slice(0, 3);
  return m[2] === m[4] ? `${month(start)} – ${month(end)} ${m[4]}` : `${month(start)} ${m[2]} – ${month(end)} ${m[4]}`;
}

/** A key fact's value in the app's format (see the module comment). */
export function factValue(value: string): FactValue {
  const raw = value.trim();
  const whole = formatFactValue(raw);
  if (whole !== raw) return { text: whole, german: false };

  let m = MEASURE.exec(raw);
  if (m) {
    const n = englishNumber(m[2]!);
    if (n !== null) {
      const key = m[3]!.toLowerCase().replace(/\.$/, "");
      let unit = UNITS[key] ?? m[3]!;
      if (UNITS[key] && n === "1") unit = unit.replace(/s$/, "");
      return { text: `${m[1] ? "approx. " : ""}${n}${unit === "%" ? "" : NBSP}${unit}${qualifier(m[4])}`, german: false };
    }
  }
  m = MONEY_PER.exec(raw);
  if (m) {
    const money = englishMoney(m[1] ?? m[2]!);
    const per = INTERVALS[(m[3] ?? m[4])!.toLowerCase()];
    if (money && per) return { text: `${money}${per}${qualifier(m[5])}`, german: false };
  }
  m = DATE_TIME_RANGE.exec(raw);
  if (m) {
    const day = iso(m[3]!, m[2]!, m[1]!);
    if (valid(day)) return { text: `${formatDate(day, { style: "short", withYear: "always" })}, ${formatTime(m[4])}–${formatTime(m[5])}`, german: false };
  }
  m = DATE_RANGE.exec(raw);
  if (m) {
    const text = dateRange(m);
    if (text) return { text, german: false };
  }
  m = MONTH_RANGE.exec(raw);
  if (m) {
    const text = monthRange(m);
    if (text) return { text, german: false };
  }

  // running text: money and ISO dates the app's way, units kept together
  let text = formatInlineText(raw)
    .replace(/\(\s*bisher\s+/gi, "(previously ")
    .replace(new RegExp(QUALIFIER_RE, "giu"), (_all, q: string) => `(${QUALIFIER[q.toLowerCase()] ?? q})`);
  const german = isGermanText(text);
  // a German date inside English words reads the app's way ("59.90 € on 01.12.2026") — unless one
  // of them is no real date (then the value stays as written)
  if (!german) text = englishDates(text);
  return { text, german };
}

// ------------------------------------------------------------------------------------------------
// Running English text with German in it
// ------------------------------------------------------------------------------------------------

/**
 * English running text (an explanation, a to-do title) in the app's format: money and ISO dates
 * ({@link formatInlineText}) and German dates ("due by 09.10.2026" → "due by Fri 9 Oct 2026").
 */
export function englishInline(text: string): string {
  return englishDates(formatInlineText(text));
}

export type LangPart = { text: string; german: boolean };

const WORD = /[\p{L}][\p{L}-]*/gu;

/**
 * Split English text into runs, the German words flagged — "the commute (Werbungskosten/
 * Entfernungspauschale)" → [..., "Werbungskosten" (German), "/", "Entfernungspauschale" (German), ")"] —
 * so they can be marked `lang="de"`: read out as German, and hyphenated by German rules where a
 * long compound has to break. German: a word with ä/ö/ü/ß or a German compound part, or a
 * capitalised word of eight letters or more inside brackets ("(Auftragsbestätigung)").
 */
export function germanRuns(text: string): LangPart[] {
  const parts: LangPart[] = [];
  let last = 0;
  let depth = 0;
  const push = (t: string, german: boolean) => {
    const prev = parts[parts.length - 1];
    if (prev && prev.german === german && !german) prev.text += t;
    else parts.push({ text: t, german });
  };
  for (const m of text.matchAll(WORD)) {
    const at = m.index ?? 0;
    const before = text.slice(last, at);
    depth += (before.match(/\(/g)?.length ?? 0) - (before.match(/\)/g)?.length ?? 0);
    if (before) push(before, false);
    const word = m[0];
    const german = germanWord(word, false) || (depth > 0 && /^\p{Lu}\p{Ll}{7,}/u.test(word));
    push(word, german);
    last = at + word.length;
  }
  if (last < text.length) push(text.slice(last), false);
  return parts;
}

// ------------------------------------------------------------------------------------------------
// Numbers
// ------------------------------------------------------------------------------------------------

/**
 * A reference as it should break: its digit groups ("5126 0184 5122") and hyphens ("TM-2026-0048213")
 * stay on one line, so "Kassenzeichen 5126 0184 5122" breaks before the number, not inside it. Display
 * only (copy buttons copy the value as written).
 */
export function unbrokenNumber(text: string): string {
  return protectRefs(text.replace(/(\d)[ \t]+(?=\d)/g, `$1${NBSP}`));
}

/** "5126 0184 5122" and "512601845122" are the same number. */
export function sameNumber(a: string, b: string): boolean {
  const norm = (s: string) => s.replace(/[\s\u00a0.\-/]/g, "").toLowerCase();
  return norm(a) !== "" && norm(a) === norm(b);
}
