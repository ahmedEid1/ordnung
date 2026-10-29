/**
 * axe's Label in Name check (`label-content-name-mismatch`, WCAG 2.5.3) as far as jsdom can run it: a control
 * named by `aria-label` must hold the text it shows in that name, word for word and in order. What it "shows" is
 * what axe reads: the text of every descendant — `aria-hidden` ones too, they are on screen — but the visually
 * hidden ones (`sr-only`), joined as the DOM holds them, so two spans with no space between them ("4" and "Your")
 * are one word ("4your"). Words are axe's: letters and digits only, lower case, a part in brackets left out.
 * A control named by its content needs no check: its name is what it shows.
 */
export function labelInName(el: Element): { ok: boolean; shown: string; name: string } {
  const name = el.getAttribute("aria-label") ?? "";
  const shown = shownText(el);
  if (!name.trim()) return { ok: true, shown, name };
  return { ok: contains(words(name), words(shown)), shown, name };
}

function shownText(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
  if (!(node instanceof Element)) return "";
  if (node.classList.contains("sr-only") || node.tagName.toLowerCase() === "title") return "";
  return [...node.childNodes].map(shownText).join("");
}

function words(text: string): string[] {
  let t = text.normalize("NFKD");
  for (let before = ""; before !== t; ) [before, t] = [t, t.replace(/\([^()]*\)/g, "")];
  return t
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
}

function contains(haystack: string[], needle: string[]): boolean {
  if (!needle.length) return true;
  for (let i = 0; i + needle.length <= haystack.length; i += 1) if (needle.every((w, j) => haystack[i + j] === w)) return true;
  return false;
}
