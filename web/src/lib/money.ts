/**
 * Amounts as people in Germany type them — shared by every amount field (template letters, call notes).
 */

/**
 * Parse an amount typed German or English style to a number, or `null` when it can't be read for sure:
 * "1.234,50", "1.500" (German thousands), "80,5", "80,-", "1,234.50", "1,500" (English thousands),
 * "1234.5". A dot or comma followed by exactly three digits groups thousands — euro amounts have at
 * most two decimals — so "1.500" is 1500, never 1,50.
 */
export function parseMoney(text: string | undefined): number | null {
  const t = (text ?? "")
    .trim()
    .replace(/[€\s]|EUR/gi, "")
    .replace(/,[-–]$/, "");
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
