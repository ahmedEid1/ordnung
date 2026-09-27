/**
 * Tracking numbers, checked as the person types — the same written policy as the server
 * (`src/ordnung/drafts/tracking.py`), which checks again when the number is saved:
 *
 * - compatibility forms are folded (NFKC: full-width `ＲＴ１２３` is `RT123`), every other decimal digit
 *   becomes its ASCII digit (Arabic-Indic `١٢٣` is `123`), spaces, dots, hyphens and slashes are
 *   dropped and letters upper-cased — only ASCII is kept;
 * - UPU S10 (`RT 123 456 785 DE`: two letters, eight digits, a check digit, two letters) is accepted
 *   only with the right check digit (weights 8 6 4 2 3 5 9 7, 11 minus the sum modulo 11; 10 → 0,
 *   11 → 5); one that doesn't start with R is kept with a note (registered items do);
 * - twelve digits (Deutsche Post's domestic numbers) are kept unchecked with a note;
 * - anything else is refused with what a number looks like.
 */

export const TRACKING_EXAMPLE = "RT 123 456 785 DE";
export const TRACKING_MAX = 64;

const WEIGHTS = [8, 6, 4, 2, 3, 5, 9, 7] as const;
const S10 = /^([A-Z]{2})(\d{8})(\d)([A-Z]{2})$/;
const S10_SHAPE = /^[A-Z]{2}\d+[A-Z]{2}$/;
const DOMESTIC = /^\d{12}$/;

export const NOT_A_NUMBER = `This doesn't look like a tracking number. Type it as it is on your posting receipt: two letters, nine digits and two letters (like ${TRACKING_EXAMPLE}), or the 12 digits Deutsche Post prints.`;
export const WRONG_CHECK_DIGIT =
  "The last digit doesn't match the others (its check digit), so a digit is probably mistyped. Check the number against your receipt.";
export const NOT_REGISTERED = "Numbers of registered letters (Einschreiben) usually start with R — check that this is the right one.";
export const DOMESTIC_NOTE = "Ordnung can't check this kind of number — compare it digit by digit with your receipt.";

export type TrackingCheck =
  | { state: "empty" }
  | { state: "invalid"; message: string }
  | { state: "valid"; number: string; display: string; checked: boolean; note: string | null };

const DECIMAL = /\p{Nd}/u;

/** Every decimal digit, of any script, as its ASCII digit. Unicode encodes each script's digits as
 * runs of ten starting at zero, so a digit's value is its distance from the start of its run. */
export function asciiDigits(text: string): string {
  return text.replace(/\p{Nd}/gu, (digit) => {
    const code = digit.codePointAt(0)!;
    if (code < 128) return digit;
    let start = code;
    while (start > 0 && DECIMAL.test(String.fromCodePoint(start - 1))) start -= 1;
    return String((code - start) % 10);
  });
}

/** `rt 123-456 785 de` → `RT123456785DE`, `ＲＲ１２３` → `RR123`, `١٢٣` → `123`. */
export function normaliseTracking(text: string): string {
  return asciiDigits(text.normalize("NFKC"))
    .replace(/[\s./-]+/g, "")
    .toUpperCase();
}

/** The S10 check digit of eight digits (`"12345678"` → 5). */
export function s10CheckDigit(serial: string): number {
  if (!/^\d{8}$/.test(serial)) throw new Error("an S10 serial number has exactly eight digits");
  const remainder = [...serial].reduce((sum, digit, i) => sum + Number(digit) * WEIGHTS[i]!, 0) % 11;
  const check = 11 - remainder;
  return check === 10 ? 0 : check === 11 ? 5 : check;
}

/** A normalised number grouped for reading (`RT 123 456 785 DE`, `1234 5678 9012`) with plain spaces, so it
 * copies cleanly — show it in a `whitespace-nowrap` element so it never breaks inside. */
export function displayTracking(number: string): string {
  if (S10.test(number)) return `${number.slice(0, 2)} ${number.slice(2, 5)} ${number.slice(5, 8)} ${number.slice(8, 11)} ${number.slice(11)}`;
  if (DOMESTIC.test(number)) return `${number.slice(0, 4)} ${number.slice(4, 8)} ${number.slice(8)}`;
  return number;
}

/** Read what the person typed by the policy above. */
export function checkTracking(text: string): TrackingCheck {
  if (!text.trim()) return { state: "empty" };
  if (text.length > TRACKING_MAX) return { state: "invalid", message: NOT_A_NUMBER };
  const number = normaliseTracking(text);
  const s10 = S10.exec(number);
  if (s10) {
    const [, service, serial, check] = s10;
    if (s10CheckDigit(serial!) !== Number(check)) return { state: "invalid", message: WRONG_CHECK_DIGIT };
    return { state: "valid", number, display: displayTracking(number), checked: true, note: service!.startsWith("R") ? null : NOT_REGISTERED };
  }
  if (DOMESTIC.test(number)) return { state: "valid", number, display: displayTracking(number), checked: false, note: DOMESTIC_NOTE };
  if (S10_SHAPE.test(number)) {
    const digits = [...number].filter((c) => /\d/.test(c)).length;
    return {
      state: "invalid",
      message: `A number like this has two letters, nine digits and two letters (like ${TRACKING_EXAMPLE}) — this one has ${digits} digits. Check it against your receipt.`,
    };
  }
  return { state: "invalid", message: NOT_A_NUMBER };
}
