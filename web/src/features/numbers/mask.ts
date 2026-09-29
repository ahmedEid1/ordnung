/**
 * My numbers are hidden on screen until the person chooses "Show" (someone may be looking over their
 * shoulder). A hidden number keeps its shape — spaces and marks stay — and its last few characters, so
 * the person can tell which one it is, like a card number's "•••• 4242".
 */

const HIDDEN = "•";
const ALNUM = /[\p{L}\p{N}]/u;

/** How many trailing letters and digits stay visible: enough to recognise a number, never to use it. */
export function visibleTail(length: number): number {
  if (length >= 8) return 3;
  if (length >= 5) return 2;
  return 0;
}

/** `"57 216 480 354"` → `"•• ••• ••• 354"`. */
export function maskValue(value: string): string {
  const chars = Array.from(value);
  const total = chars.filter((c) => ALNUM.test(c)).length;
  let keep = visibleTail(total);
  const out: string[] = [];
  for (let i = chars.length - 1; i >= 0; i -= 1) {
    const c = chars[i]!;
    if (!ALNUM.test(c)) out.push(c);
    else if (keep > 0) {
      out.push(c);
      keep -= 1;
    } else out.push(HIDDEN);
  }
  return out.reverse().join("");
}

/** What a screen reader hears for a hidden number: "hidden, ends in 354" (or just "hidden"). */
export function hiddenLabel(value: string): string {
  const chars = Array.from(value).filter((c) => ALNUM.test(c));
  const tail = chars.slice(chars.length - visibleTail(chars.length)).join("");
  return tail ? `hidden, ends in ${tail.split("").join(" ")}` : "hidden";
}
