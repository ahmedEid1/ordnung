/**
 * Display-only glue that keeps units together on screen: non-breaking spaces and hyphens.
 * Separate from `format.ts` (no date library), so the app entry can undo it on copy.
 */

export const NBSP = "\u00a0";
/** U+2011 NON-BREAKING HYPHEN: looks like "-", never breaks a line. */
export const NB_HYPHEN = "\u2011";

/** A reference or ID with hyphens: "TM-2026-0048213", "FN-88213407", "05-2-03", "71-4471220". */
const REF = /\b[A-Z]{1,5}-(?=[\dA-Z-]*\d)[\dA-Z]+(?:-[\dA-Z]+)*\b|\b\d+(?:-\d+)+\b/g;

/**
 * Reference and ID numbers never break at their hyphens ("TM-2026- / 0048213"): the hyphens
 * inside them become non-breaking hyphens. Display only — selected text is copied through
 * {@link plainText} (see `main.tsx`); never put the result into a value that is sent, saved or
 * copied by a button.
 */
export function protectRefs(text: string): string {
  return text.replace(REF, (ref) => ref.replace(/-/g, NB_HYPHEN));
}

/** Keep a citation's parts on one line ("§ 38 Abs. 1 S. 4 SGB III" never breaks after "§"). Display only. */
export function keepCitations(text: string): string {
  return text.replace(/(§|Abs\.|S\.|Nr\.|Art\.)\s+(?=\d)/g, "$1\u00a0");
}

/** Undo the display-only glue (non-breaking spaces and hyphens) for text that leaves the app. */
export function plainText(text: string): string {
  return text.replace(/[\u00a0\u202f]/g, " ").replace(/\u2011/g, "-");
}

/**
 * `copy` handler (installed once in `main.tsx`): text selected on a page is copied without the
 * glue, so a reference pasted into a bank transfer or an e-mail is exactly what the letter says.
 * Fields keep the browser's own copy.
 */
export function copyWithoutGlue(e: ClipboardEvent): void {
  const target = e.target instanceof Element ? e.target : null;
  if (target?.closest("input, textarea, [contenteditable='true']")) return;
  const text = window.getSelection()?.toString() ?? "";
  const plain = plainText(text);
  if (!e.clipboardData || plain === text) return;
  e.clipboardData.setData("text/plain", plain);
  e.preventDefault();
}
