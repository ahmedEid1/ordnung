/**
 * Keyboard focus hidden under something pinned (WCAG 2.4.11): shared by the layout guards
 * (`layout.spec.ts`) and Ask's guards (`ask-focus-layout.spec.ts`).
 */
import type { Page } from "@playwright/test";

/**
 * Press Tab (or Shift+Tab) `stops` times and list every focused element that a fixed or sticky
 * element (top bar, tab bar) covers at its top or bottom edge.
 */
export async function obscuredFocus(page: Page, stops: number, key: "Tab" | "Shift+Tab"): Promise<string[]> {
  const hidden: string[] = [];
  for (let i = 0; i < stops; i++) {
    await page.keyboard.press(key);
    const problem = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body || el === document.documentElement) return null;
      const r = el.getBoundingClientRect();
      // taller than the space between the bars: can't be fully shown, the browser shows its top
      if (!r.width || !r.height || r.height > innerHeight - 160) return null;
      const pinned = (node: Element | null) => {
        for (let n = node; n; n = n.parentElement) {
          const pos = getComputedStyle(n).position;
          if (pos === "fixed" || pos === "sticky") return n;
        }
        return null;
      };
      const x = r.left + Math.min(r.width / 2, 12);
      for (const y of [r.top + 1, r.bottom - 1]) {
        const top = document.elementFromPoint(Math.max(0, x), Math.min(Math.max(0, y), innerHeight - 1));
        if (!top || el.contains(top) || top.contains(el)) continue;
        const bar = pinned(top);
        if (bar && !bar.contains(el)) {
          const name = (el.getAttribute("aria-label") ?? el.textContent ?? el.tagName).trim().slice(0, 60);
          return `"${name}" (${Math.round(r.top)}–${Math.round(r.bottom)} px) under <${bar.tagName.toLowerCase()} class="${String(bar.className).slice(0, 40)}…">`;
        }
      }
      return null;
    });
    if (problem) hidden.push(problem);
  }
  return hidden;
}
