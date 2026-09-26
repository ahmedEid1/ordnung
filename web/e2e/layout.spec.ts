/**
 * Layout guards on real pages (what jsdom can't see): keyboard focus never ends up hidden under
 * the sticky top bar or the phone tab bar (WCAG 2.4.11), and the focus ring is the accent colour
 * from the first frame.
 */
import type { Page } from "@playwright/test";
import { expect, open, setTour, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

/**
 * Press Tab (or Shift+Tab) `stops` times and list every focused element that a fixed or sticky
 * element (top bar, tab bar) covers at its top or bottom edge.
 */
async function obscuredFocus(page: Page, stops: number, key: "Tab" | "Shift+Tab"): Promise<string[]> {
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

test.describe("phone: focus stays clear of the top bar and the tab bar", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  for (const [path, h1] of [
    ["/", /Sam/],
    ["/contracts", "Contracts"],
    ["/settings", "Settings"],
  ] as const) {
    test(`Tab through ${path}`, async ({ page }) => {
      await open(page, path, h1);
      expect(await obscuredFocus(page, 45, "Tab")).toEqual([]);
    });
  }
});

test.describe("laptop: focus stays clear of the sticky top bar", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("Shift+Tab back up through Today", async ({ page }) => {
    await open(page, "/", /Sam/);
    // start from the bottom of the page, where Shift+Tab walks back up under the top bar
    await page.evaluate(() => {
      (document.activeElement as HTMLElement | null)?.blur();
      window.scrollTo(0, document.documentElement.scrollHeight);
    });
    expect(await obscuredFocus(page, 45, "Shift+Tab")).toEqual([]);
  });

  test("the focus ring is the accent colour from the first frame", async ({ page }) => {
    await open(page, "/inbox", "Inbox");
    const { accent, atRest } = await page.evaluate(() => {
      const probe = document.createElement("span");
      probe.style.color = "var(--color-accent)";
      document.body.appendChild(probe);
      const accent = getComputedStyle(probe).color;
      probe.remove();
      // every element — also those with `transition-colors`, which animates outline-color
      const atRest = [...document.querySelectorAll("main button, main a")].map((el) => getComputedStyle(el).outlineColor);
      return { accent, atRest: [...new Set(atRest)] };
    });
    expect(atRest).toEqual([accent]);
    // …so the ring doesn't fade in from the text colour when focus arrives
    await page.getByRole("main").getByRole("heading", { level: 1 }).click();
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => getComputedStyle(document.activeElement!).outlineColor)).toBe(accent);
  });
});
