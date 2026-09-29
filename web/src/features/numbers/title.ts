/**
 * What a number is called on screen — on My numbers and in the party drawer, which shows the same call
 * sheet: the plain-English name, or the letter's own label where the name is generic. Pure (no React), so
 * the e2e suite checks the drawer against the same rule.
 */
import type { MyNumber } from "@/api/types";

/**
 * Kinds whose plain-English name says less than the letter's own label ("Your number" → "Scholarship ID";
 * "Company register" → "Handelsregister" or "Foundation register": which register it is).
 */
export const LABEL_FIRST: ReadonlySet<MyNumber["kind"]> = new Set<MyNumber["kind"]>(["other", "their_other", "reference", "register"]);

/** The row's heading: the plain-English name, or the letter's label where the name is generic. */
export function numberTitle(n: Pick<MyNumber, "kind" | "name" | "label">): string {
  return LABEL_FIRST.has(n.kind) ? n.label : n.name;
}

/** The letter's own label when it adds something to the title ("Tax ID (Steuer-ID)" · "Steuerliche Identifikationsnummer"). */
export function printedLabel(n: Pick<MyNumber, "kind" | "name" | "label">): string | null {
  const title = numberTitle(n);
  const label = n.label.trim();
  if (!label || title.toLowerCase().includes(label.toLowerCase().replace(/[.:]+$/, ""))) return null;
  return label;
}
