/**
 * Formatting helpers. All relative dates are computed against the app's "today" (from
 * `/api/health`, see `useToday()`), never the browser clock, so demo mode (simulated today) works.
 *
 * UI language is English: dates en-GB style ("Fri 16 Oct"), money in one English format
 * ("€184.30"). Values copied from letters ("1.234,00 €", "2026-10-08 09:15") go through
 * {@link formatFactValue} / {@link formatInlineDates}.
 */
import {
  differenceInCalendarDays,
  differenceInMinutes,
  format as fnsFormat,
  isValid,
  parseISO,
  startOfDay,
} from "date-fns";
import type { CostInterval } from "@/api/types";

export type DateInput = string | Date;

/** Parse an ISO date (`2026-10-16`, local midnight) or timestamp. Throws on invalid input. */
export function parseDate(value: DateInput): Date {
  const d = value instanceof Date ? value : parseISO(value);
  if (!isValid(d)) throw new RangeError(`Invalid date: ${String(value)}`);
  return d;
}

/** Like {@link parseDate} but returns null for empty/invalid input. */
export function tryParseDate(value: DateInput | null | undefined): Date | null {
  if (!value) return null;
  const d = value instanceof Date ? value : parseISO(value);
  return isValid(d) ? d : null;
}

/** `Date` → `YYYY-MM-DD` (local calendar date). */
export function toISODate(d: Date): string {
  return fnsFormat(d, "yyyy-MM-dd");
}

/** Whole calendar days from `today` to `date` (negative = in the past). */
export function daysUntil(date: DateInput, today: DateInput): number {
  return differenceInCalendarDays(startOfDay(parseDate(date)), startOfDay(parseDate(today)));
}

export type DateStyle = "short" | "day" | "medium" | "long" | "numeric" | "month" | "weekday";

export interface FormatDateOptions {
  style?: DateStyle;
  /** When given (and `withYear` is "auto"), the year is shown only if it differs from today's. */
  today?: DateInput;
  withYear?: "auto" | "always" | "never";
}

/**
 * Format a date for humans.
 * - `short` (default): "Fri 16 Oct" (+ " 2027" when not this year)
 * - `day`: "16 Oct" · `medium`: "16 Oct 2026" · `long`: "Friday, 16 October 2026"
 * - `numeric`: "16.10.2026" (as on German letters) · `month`: "October 2026" · `weekday`: "Friday"
 */
export function formatDate(value: DateInput | null | undefined, opts: FormatDateOptions = {}): string {
  const d = tryParseDate(value ?? null);
  if (!d) return "—";
  const style = opts.style ?? "short";
  const withYear = opts.withYear ?? "auto";
  const today = opts.today ? tryParseDate(opts.today) : null;
  const showYear =
    withYear === "always" || (withYear === "auto" && today !== null && today.getFullYear() !== d.getFullYear());
  switch (style) {
    case "short":
      return fnsFormat(d, showYear ? "EEE d MMM yyyy" : "EEE d MMM");
    case "day":
      return fnsFormat(d, showYear ? "d MMM yyyy" : "d MMM");
    case "medium":
      return fnsFormat(d, "d MMM yyyy");
    case "long":
      return fnsFormat(d, "EEEE, d MMMM yyyy");
    case "numeric":
      return fnsFormat(d, "dd.MM.yyyy");
    case "month":
      return fnsFormat(d, "MMMM yyyy");
    case "weekday":
      return fnsFormat(d, "EEEE");
  }
}

/** "10:30" from "10:30:00" / "10:30". */
export function formatTime(value: string | null | undefined): string {
  if (!value) return "";
  const m = /^(\d{1,2}):(\d{2})/.exec(value);
  return m ? `${m[1]!.padStart(2, "0")}:${m[2]}` : value;
}

/** Timestamp → "Mon 28 Sep, 14:05" (local time). */
export function formatDateTime(value: DateInput | null | undefined, opts: { today?: DateInput } = {}): string {
  const d = tryParseDate(value ?? null);
  if (!d) return "—";
  return `${formatDate(d, { style: "short", today: opts.today })}, ${fnsFormat(d, "HH:mm")}`;
}

export type RelativeMode = "due" | "event";

/**
 * Relative day phrase: "today", "tomorrow", "in 5 days", "in 3 weeks", "in 4 months".
 * Past dates: mode `due` → "2 days overdue"; mode `event` → "yesterday" / "2 days ago".
 */
export function formatRelativeDays(date: DateInput, today: DateInput, mode: RelativeMode = "due"): string {
  const n = daysUntil(date, today);
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  if (n > 1) {
    if (n < 22) return `in ${n} days`;
    if (n < 60) return `in ${Math.round(n / 7)} weeks`;
    if (n < 365 * 2) return `in ${Math.round(n / 30.44)} months`;
    return `in ${Math.round(n / 365.25)} years`;
  }
  const a = -n;
  if (mode === "due") return a === 1 ? "1 day overdue" : `${a} days overdue`;
  if (a === 1) return "yesterday";
  if (a < 22) return `${a} days ago`;
  if (a < 60) return `${Math.round(a / 7)} weeks ago`;
  if (a < 365 * 2) return `${Math.round(a / 30.44)} months ago`;
  return `${Math.round(a / 365.25)} years ago`;
}

export type Urgency = "overdue" | "today" | "soon" | "week" | "month" | "later" | "past";

/**
 * Urgency bucket for colouring countdowns: overdue (due, past) · today · soon (≤ 3 days) ·
 * week (≤ 7) · month (≤ 30) · later · past (events in the past).
 */
export function urgencyOf(date: DateInput, today: DateInput, mode: RelativeMode = "due"): Urgency {
  const n = daysUntil(date, today);
  if (n < 0) return mode === "due" ? "overdue" : "past";
  if (n === 0) return "today";
  if (n <= 3) return "soon";
  if (n <= 7) return "week";
  if (n <= 30) return "month";
  return "later";
}

/** "3 min ago", "2 h ago", "yesterday", "12 Sep" — for activity logs (real timestamps). */
export function formatTimeAgo(value: DateInput, now: DateInput = new Date()): string {
  const d = parseDate(value);
  const ref = parseDate(now);
  const mins = differenceInMinutes(ref, d);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 60 * 24 && d.getDate() === ref.getDate()) return `${Math.floor(mins / 60)} h ago`;
  const days = differenceInCalendarDays(ref, d);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return formatDate(d, { style: "day", today: ref });
}

// ------------------------------------------------------------------------------------------------
// Money & numbers
// ------------------------------------------------------------------------------------------------

const moneyCache = new Map<string, Intl.NumberFormat>();

/**
 * One English money format everywhere ("€1,234.50"), matching the secretary's note and the
 * Ideas: "11.788 €" reads as eleven euros to an English reader.
 */
const MONEY_LOCALE = "en-IE";

function moneyFormatter(currency: string, decimals: number): Intl.NumberFormat {
  const key = `${currency}:${decimals}`;
  let f = moneyCache.get(key);
  if (!f) {
    f = new Intl.NumberFormat(MONEY_LOCALE, {
      style: "currency",
      currency,
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
    moneyCache.set(key, f);
  }
  return f;
}

export interface MoneyOptions {
  currency?: string | null;
  /** prefix "+" for positive amounts (e.g. "+84,00 €/year") */
  signed?: boolean;
  /** decimals; "auto" drops ",00" for whole amounts ≥ 100 */
  decimals?: number | "auto";
}

/** Money in the app's English format: 184.3 → "€184.30", 1234.5 → "€1,234.50". */
export function formatMoney(amount: number | null | undefined, opts: MoneyOptions = {}): string {
  if (amount === null || amount === undefined || Number.isNaN(amount)) return "—";
  const currency = opts.currency || "EUR";
  const decimals =
    opts.decimals === "auto" ? (Number.isInteger(amount) && Math.abs(amount) >= 100 ? 0 : 2) : opts.decimals ?? 2;
  let out: string;
  try {
    out = moneyFormatter(currency, decimals).format(amount);
  } catch {
    out = `${currency} ${amount.toFixed(decimals)}`;
  }
  if (opts.signed && amount > 0) out = `+${out}`;
  return out;
}

/** Sums of money by currency code (amounts without a currency count as euros) — never mixed. */
export type Totals = Record<string, number>;

/** `totals` with `amount` added to its currency's sum (rounded to cents). */
export function addToTotals(totals: Totals, amount: number, currency: string | null | undefined): Totals {
  const code = (currency || "EUR").toUpperCase();
  return { ...totals, [code]: Math.round(((totals[code] ?? 0) + amount) * 100) / 100 };
}

/** "€150 + US$50.00": euros first, then the other currencies A–Z (only ones with money). */
export function formatTotals(totals: Totals, opts: { decimals?: number | "auto" } = {}): string {
  const codes = Object.keys(totals)
    .filter((code) => totals[code])
    .sort((a, b) => Number(b === "EUR") - Number(a === "EUR") || a.localeCompare(b));
  return codes.length ? codes.map((code) => formatMoney(totals[code], { ...opts, currency: code })).join(" + ") : formatMoney(0, opts);
}

/** Interval suffix: monthly → "/month". */
export function formatIntervalSuffix(interval: CostInterval | null | undefined): string {
  switch (interval) {
    case "monthly":
      return "/month";
    case "quarterly":
      return "/quarter";
    case "yearly":
      return "/year";
    default:
      return "";
  }
}

/** Normalise a recurring cost to a monthly amount (yearly / 12, quarterly / 3). */
export function monthlyAmount(amount: number | null | undefined, interval: CostInterval | null | undefined): number | null {
  if (amount === null || amount === undefined || !interval || interval === "once") return null;
  const factor = { monthly: 1, quarterly: 1 / 3, yearly: 1 / 12 }[interval];
  return Math.round(amount * factor * 100) / 100;
}

/** 1536 → "1.5 KB", 2_400_000 → "2.3 MB". */
export function formatFileSize(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = bytes / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v >= 10 ? Math.round(v) : Math.round(v * 10) / 10} ${units[i]}`;
}

/** 12345 → "12.3k", 1_200_000 → "1.2M". */
export function formatCompact(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs < 1000) return String(Math.round(n));
  if (abs < 1_000_000) return `${(n / 1000).toFixed(abs < 10_000 ? 1 : 0).replace(/\.0$/, "")}k`;
  return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}

/** API-equivalent cost in US dollars: 0.4213 → "$0.42", 0.004 → "<$0.01". */
export function formatUsd(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  if (n > 0 && n < 0.01) return "<$0.01";
  return `$${n.toFixed(2)}`;
}

/** 0.873 → "87 %". */
export function formatPercent(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return "—";
  return `${Math.round(ratio * 100)} %`;
}

/** Group an IBAN in blocks of four: "DE44500105175407324931" → "DE44 5001 0517 5407 3249 31". */
export function formatIban(iban: string | null | undefined): string {
  if (!iban) return "—";
  return iban.replace(/\s+/g, "").replace(/(.{4})/g, "$1 ").trim();
}

// ------------------------------------------------------------------------------------------------
// Values copied from letters
// ------------------------------------------------------------------------------------------------

/**
 * A number as written on a letter or by the model: "1.234,50", "1,234.50", "1234.00", "23298",
 * "324,00". Null when it isn't one.
 */
export function parseLooseNumber(text: string): number | null {
  const t = text.trim().replace(/[\s\u00a0']/g, "");
  if (!/^-?[\d.,]+$/.test(t) || !/\d/.test(t)) return null;
  const lastDot = t.lastIndexOf(".");
  const lastComma = t.lastIndexOf(",");
  let normal: string;
  if (lastDot >= 0 && lastComma >= 0) {
    // both: the last one is the decimal separator ("1.234,50" / "1,234.50")
    normal = lastDot > lastComma ? t.replace(/,/g, "") : t.replace(/\./g, "").replace(",", ".");
  } else if (lastComma >= 0) {
    normal = /^-?\d{1,3}(,\d{3})+$/.test(t) ? t.replace(/,/g, "") : t.replace(",", ".");
  } else if (lastDot >= 0) {
    // "23.298" groups thousands (money is never written with three decimals); "1234.00" doesn't
    normal = /^-?\d{1,3}(\.\d{3})+$/.test(t) ? t.replace(/\./g, "") : t;
  } else normal = t;
  const n = Number(normal);
  return Number.isFinite(n) ? n : null;
}

const MONEY_VALUE = /^\s*(?:(€|EUR)\s*(-?[\d.,\s\u00a0]+)|(-?[\d.,\s\u00a0]+?)\s*(€|EUR|Euro))\s*$/i;
const ISO_VALUE = /^\s*(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2})(?::\d{2})?)?\s*$/;
const GERMAN_DATE_VALUE = /^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})(?:,?\s*(\d{1,2}:\d{2})(?:\s*Uhr)?)?\s*$/;

/**
 * A key fact's value in the app's format: "1234.00 EUR" / "1.234,00 €" → "€1,234.00",
 * "2026-10-08 09:15" / "08.10.2026" → "Thu 8 Oct 2026, 09:15". Anything else is returned as written.
 */
export function formatFactValue(value: string): string {
  const money = MONEY_VALUE.exec(value);
  if (money) {
    const n = parseLooseNumber(money[2] ?? money[3] ?? "");
    if (n !== null) return formatMoney(n);
  }
  const iso = ISO_VALUE.exec(value);
  if (iso) {
    const date = formatDate(iso[1]!, { style: "short", withYear: "always" });
    return iso[2] ? `${date}, ${formatTime(iso[2])}` : date;
  }
  const de = GERMAN_DATE_VALUE.exec(value);
  if (de) {
    const iso2 = `${de[3]}-${de[2]!.padStart(2, "0")}-${de[1]!.padStart(2, "0")}`;
    if (tryParseDate(iso2)) {
      const date = formatDate(iso2, { style: "short", withYear: "always" });
      return de[4] ? `${date}, ${formatTime(de[4])}` : date;
    }
  }
  return value;
}

// German two-letter weekdays only with their dot: "So 2026-10-04" may be English "so"
const WEEKDAY_BEFORE =
  "(?:(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tues?|Wed|Thu(?:rs?)?|Fri|Sat|Sun|" +
  "Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)\\.?|(?:Mo|Di|Mi|Do|Fr|Sa|So)\\.),?[ \\u00a0])?";
const INLINE_ISO = new RegExp(`\\b${WEEKDAY_BEFORE}(\\d{4}-\\d{2}-\\d{2})(?:[ T](\\d{2}:\\d{2})(?::\\d{2})?Z?)?\\b`, "g");

/**
 * ISO dates inside running text ("from 2026-09-28 to 2026-10-26") → "Mon 28 Sep". A weekday written
 * just before the date ("due Wed 2026-09-30") is part of it: the formatted date brings its own, so it
 * never reads "Wed Wed 30 Sep".
 */
export function formatInlineDates(text: string, today?: DateInput): string {
  return text.replace(INLINE_ISO, (whole, day: string, time?: string) => {
    if (!tryParseDate(day)) return whole;
    // without "today" the year can't be left out safely
    const date = formatDate(day, { style: "short", today, withYear: today ? "auto" : "always" });
    return time ? `${date}, ${formatTime(time)}` : date;
  });
}

const GERMAN_WORDS = /\b(der|die|das|und|nicht|wir|Sie|Ihr|Ihre|Ihren|ist|wird|werden|bei|mit|zu|auf|dem|den|des|ein|eine|einen|für|oder|von|bis|zum|zur|im|am|sich|bitte|sicherstellen|müssen|Betrag|Frist)\b/g;
const ENGLISH_WORDS = /\b(the|and|you|your|to|of|is|will|be|for|by|if|it|this|with)\b/gi;

/** A sentence written in German (the letter's words), not in English. */
export function looksGerman(text: string | null | undefined): boolean {
  const t = text ?? "";
  if (!t.trim()) return false;
  const de = (t.match(GERMAN_WORDS) ?? []).length + (/[äöüß]/i.test(t) ? 1 : 0);
  const en = (t.match(ENGLISH_WORDS) ?? []).length;
  return de >= 2 && de > en;
}
