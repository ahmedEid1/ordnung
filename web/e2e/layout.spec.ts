/**
 * Layout guards on real pages (what jsdom can't see): nothing makes a page scroll sideways at
 * 320 CSS px (WCAG 1.4.10), keyboard focus never ends up hidden under the sticky top bar or the
 * phone tab bar (WCAG 2.4.11), the focus ring is the accent colour from the first frame, tabs
 * that don't fit scroll with a fade and keep the selected tab in view, and popovers sit whole and
 * clear of the top bar (sheets on phones).
 */
import type { Locator, Page } from "@playwright/test";
import { apiGet, expect, open, setTour, settle, test } from "./helpers";

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

/**
 * What makes the page wider than the screen: [] when it fits, else the innermost elements that
 * stick out past the right edge (and aren't inside a scroll area that clips them).
 */
async function sideways(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const root = document.documentElement;
    if (root.scrollWidth <= root.clientWidth) return [];
    const edge = root.clientWidth + 0.5;
    const clipped = (el: Element) => {
      for (let n = el.parentElement; n && n !== document.body; n = n.parentElement) {
        if (getComputedStyle(n).overflowX !== "visible" && n.getBoundingClientRect().right <= edge) return true;
      }
      return false;
    };
    const out: string[] = [];
    for (const el of document.body.querySelectorAll("*")) {
      const r = el.getBoundingClientRect();
      if (!r.width || r.right <= edge || clipped(el)) continue;
      if ([...el.children].some((c) => c.getBoundingClientRect().right > edge)) continue;
      out.push(`<${el.tagName.toLowerCase()}> "${(el.textContent ?? "").trim().slice(0, 50)}" ends at ${Math.round(r.right)} px`);
    }
    return [`page is ${root.scrollWidth} px wide`, ...out.slice(0, 5)];
  });
}

test.describe("phone 320 px: no page scrolls sideways (WCAG 1.4.10 reflow)", () => {
  test.use({ viewport: { width: 320, height: 640 } });

  for (const [path, h1] of [
    ["/", /Sam/],
    ["/inbox", "Inbox"],
    ["/contracts", "Contracts"],
    ["/letters", "Letters"],
    ["/timeline", "Timeline"],
  ] as const) {
    test(`${path} fits`, async ({ page }) => {
      await open(page, path, h1);
      expect(await sideways(page)).toEqual([]);
    });
  }

  test("every letter fits", async ({ page }) => {
    test.setTimeout(180_000);
    const docs = await apiGet<{ id: string; title: string | null }[]>(page, "/api/documents");
    expect(docs.length).toBeGreaterThan(5);
    const wide: string[] = [];
    for (const doc of docs) {
      await open(page, `/documents/${doc.id}`);
      const problem = await sideways(page);
      if (problem.length) wide.push(`${doc.title ?? doc.id}: ${problem.join("; ")}`);
    }
    expect(wide).toEqual([]);
  });

  test("tabs that don't fit scroll with a fade, keep the selected tab in view and its focus ring whole", async ({ page }) => {
    await open(page, "/contracts", "Contracts");
    const list = page.getByRole("tablist", { name: "Show contracts" });
    const track = list.locator("xpath=..");
    const last = list.getByRole("tab").last();
    // the page's own status tabs fit a phone: only statuses that have contracts, on the whole row
    expect(await list.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
    // squeeze the row so that they can't, whatever statuses the demo has
    await track.evaluate((el) => {
      el.style.width = "8rem";
    });
    // more tabs to the right: that edge fades
    await expect(track).toHaveAttribute("data-overflow", /end/);
    await last.click();
    await expect(last).toHaveAttribute("aria-selected", "true");
    await settle(page);
    const inView = async (tab: Locator) =>
      tab.evaluate((el) => {
        const t = el.getBoundingClientRect();
        const l = el.parentElement!.getBoundingClientRect();
        return t.left >= l.left - 0.5 && t.right <= l.right + 0.5;
      });
    expect(await inView(last)).toBe(true);
    await expect(track).toHaveAttribute("data-overflow", /start/);
    // a swipe back along the row stays where the person left it
    await list.evaluate((el) => el.scrollTo({ left: 0 }));
    await expect(track).toHaveAttribute("data-overflow", "end");
    await page.waitForTimeout(300);
    expect(await list.evaluate((el) => el.scrollLeft)).toBe(0);
    // keyboard: back to the first tab, which scrolls back into view; the ring is drawn inside the tab
    await page.keyboard.press("Home");
    const first = list.getByRole("tab").first();
    await expect(first).toBeFocused();
    await settle(page);
    expect(await inView(first)).toBe(true);
    expect(await first.evaluate((el) => getComputedStyle(el).outlineOffset)).toBe("-2px");
    expect(await sideways(page)).toEqual([]);
  });
});

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

/**
 * Where a popover sits: fully in view (no inner scroll when the page can make room), clear of the
 * sticky top bar and never over its own trigger.
 */
async function popoverLayout(panel: Locator, trigger: Locator) {
  const t = (await trigger.boundingBox())!;
  return panel.evaluate((el, t) => {
    const r = el.getBoundingClientRect();
    const bar = document.querySelector("header")!.getBoundingClientRect();
    return {
      innerScroll: el.scrollHeight > el.clientHeight + 1,
      underTopBar: r.top < bar.bottom,
      overTrigger: r.top < t.y + t.height && r.bottom > t.y && r.left < t.x + t.width && r.right > t.x,
      inViewport: r.top >= 0 && r.bottom <= innerHeight,
    };
  }, t);
}
const fits = { innerScroll: false, underTopBar: false, overTrigger: false, inViewport: true };

for (const height of [800, 720]) {
  test.describe(`laptop 1280×${height}: popovers`, () => {
    test.use({ viewport: { width: 1280, height } });

    test("Today's Pay panel shows everything, clear of the top bar and its trigger; Tab out moves on", async ({ page }) => {
      await open(page, "/", /Sam/);
      const pay = page.getByRole("main").getByRole("button", { name: /^Pay: / }).first();
      await pay.click();
      const panel = page.getByRole("dialog", { name: /^Pay: / });
      await expect(panel.getByRole("button", { name: "Mark as paid" })).toBeVisible();
      // focus goes to the panel (announced by its name), not to a control further down
      await expect(panel).toBeFocused();
      await settle(page);
      expect(await popoverLayout(panel, pay)).toEqual(fits);

      // Tab through to the end: the panel closes and focus continues right after the Pay button
      const inPanel = () => page.evaluate(() => Boolean(document.activeElement?.closest("[data-popover]")));
      for (let i = 0; i < 12 && (await inPanel()); i++) await page.keyboard.press("Tab");
      await expect(panel).toHaveCount(0);
      const focus = await pay.evaluate((el) => {
        const a = document.activeElement as HTMLElement;
        const stops = [...document.querySelectorAll<HTMLElement>("#root a[href], #root button:not([disabled]), #root [tabindex]")].filter(
          (n) => n.tabIndex >= 0 && n.offsetParent !== null && !el.contains(n),
        );
        const next = stops.find((n) => el.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING);
        return { inPage: a !== document.body && Boolean(a.closest("#root")), nextStopAfterTrigger: a === next };
      });
      expect(focus).toEqual({ inPage: true, nextStopAfterTrigger: true });
    });

    test("the date receipt keeps its side and stays whole when the rules open", async ({ page }) => {
      await open(page, "/", /Sam/);
      const why = page.getByRole("main").getByRole("button", { name: /^Why this date\?/ }).first();
      await why.click();
      const panel = page.getByRole("dialog", { name: /^Why this date\?/ });
      await expect(panel).toBeVisible();
      await settle(page);
      const before = await popoverLayout(panel, why);
      const side = await panel.evaluate((el) => (el.style.bottom ? "top" : "bottom"));
      await panel.getByRole("button", { name: "Show the rules" }).click();
      await expect(panel.getByRole("button", { name: "Hide the rules" })).toBeVisible();
      await settle(page);
      expect(before).toEqual(fits);
      expect(await popoverLayout(panel, why)).toEqual(fits);
      expect(await panel.evaluate((el) => (el.style.bottom ? "top" : "bottom"))).toBe(side);
    });
  });
}

test.describe("phone: popovers are modal bottom sheets", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test("Tab stays in the sheet, the page behind doesn't scroll, Close returns to the trigger", async ({ page }) => {
    await open(page, "/", /Sam/);
    const why = page.getByRole("main").getByRole("button", { name: /^Why this date\?/ }).first();
    await why.click();
    const sheet = page.getByRole("dialog", { name: /^Why this date\?/ });
    await expect(sheet).toHaveAttribute("aria-modal", "true");
    await expect(sheet.getByRole("heading", { level: 2, name: "Why this date?" })).toBeVisible();
    const close = sheet.getByRole("button", { name: "Close" });
    expect((await close.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    for (let i = 0; i < 6; i++) {
      await page.keyboard.press("Tab");
      expect(await page.evaluate(() => Boolean(document.activeElement?.closest("[role=dialog]")))).toBe(true);
    }
    const y = await page.evaluate(() => scrollY);
    await page.mouse.move(195, 200);
    await page.mouse.wheel(0, 400);
    await page.waitForTimeout(200);
    expect(await page.evaluate(() => scrollY)).toBe(y);
    await close.click();
    await expect(sheet).toHaveCount(0);
    await expect(why).toBeFocused();
  });
});
