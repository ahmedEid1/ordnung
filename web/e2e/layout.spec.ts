/**
 * Layout guards on real pages (what jsdom can't see): nothing makes a page scroll sideways at
 * 320 CSS px (WCAG 1.4.10), keyboard focus never ends up hidden under the sticky top bar, the
 * phone tab bar or a toast (WCAG 2.4.11), the focus ring is the accent colour from the first frame, tabs
 * that don't fit scroll with a fade and keep the selected tab in view, and popovers sit whole and
 * clear of the top bar (sheets on phones). Ask's question box has its own file, `ask-focus-layout.spec.ts`:
 * its answers replay only on a ledger the demo recorded, so it runs first.
 */
import type { Locator, Page } from "@playwright/test";
import { obscuredFocus } from "./focus";
import { apiGet, expect, open, setTour, settle, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

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

// UI audit round 1 (R1-deferred-8): on phones the demo tour — its bar, or the card it opens into —
// partly covered the field that had focus; the page's scroll-padding counts its height now
test.describe("phone: focus stays clear of the demo tour", () => {
  test.use({ viewport: { width: 320, height: 640 }, isMobile: true, hasTouch: true });
  test.afterEach(async ({ page }) => {
    await setTour(page, null);
  });

  test("Tab through Settings with the tour bar, then with its whole card open", async ({ page }) => {
    await setTour(page, 0);
    await open(page, "/settings", "Settings");
    const bar = page.getByRole("button", { name: /^Demo tour · 1 of 4: .* — show the whole step$/ });
    await expect(bar).toBeVisible();
    expect(await obscuredFocus(page, 30, "Tab")).toEqual([]);

    await bar.click();
    await expect(page.getByRole("region", { name: "Demo tour" }).getByRole("heading")).toBeVisible();
    await page.evaluate(() => {
      (document.activeElement as HTMLElement | null)?.blur();
      window.scrollTo(0, 0);
    });
    expect(await obscuredFocus(page, 30, "Tab")).toEqual([]);
  });
});

/**
 * Put a toast up that stays (an error waits for the person), then go to `path` in the app — the toast stays
 * with it, as an Undo toast does for 15 s after "Mark as paid" or "Save notice period".
 */
async function withToastOn(page: Page, path: string, h1: string | RegExp): Promise<void> {
  await open(page, "/dev/ui", "Design system");
  await page.getByRole("button", { name: "Error toast" }).click();
  const toast = page.getByRole("region", { name: /^Notifications/ }).getByRole("listitem");
  await expect(toast).toHaveCount(1);
  await page.evaluate((to) => {
    window.history.pushState({}, "", to);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, path);
  await expect(page.getByRole("main").getByRole("heading", { level: 1 }).first()).toHaveText(h1);
  await page.waitForLoadState("networkidle");
  await settle(page);
  await expect(toast).toHaveCount(1);
  await page.evaluate(() => {
    (document.activeElement as HTMLElement | null)?.blur();
    window.scrollTo(0, 0);
  });
}

// UI audit round 2 (R2-ui-foundations-1): while a toast (or an upload card) was up, Tab moved focus to
// controls hidden behind it — the page's scroll-padding left the toast column out; it mirrors
// `.room-for-overlays` now (phones: the taller of the tour bar and the toasts; from md: the toast column)
for (const [width, height, phone] of [
  [320, 640, true],
  [390, 844, true],
  [768, 1024, false],
  [1280, 800, false],
] as const) {
  test.describe(`${width} px: focus stays clear of a toast`, () => {
    test.use({ viewport: { width, height }, isMobile: phone, hasTouch: phone });

    for (const [path, h1] of [
      ["/", /Sam/],
      ["/contracts", "Contracts"],
    ] as const) {
      test(`Tab through ${path} with a toast up`, async ({ page }) => {
        await withToastOn(page, path, h1);
        expect(await obscuredFocus(page, 45, "Tab")).toEqual([]);
      });
    }
  });
}

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
 * Where a popover sits: clear of the sticky top bar, never over its own trigger, whole in the
 * viewport, and it scrolls inside only when the screen is too short for it. The panel's rule
 * (Popover, `scrollToFit`): the page scrolls to make room for its natural height as far as the
 * trigger stays in view — up to the top bar or down to the bottom inset, as far as the page can
 * still scroll — and only what is still missing scrolls inside the panel, which then takes all the
 * room its side has. So a panel that could have sat whole must not scroll inside, whatever the demo
 * puts in it; one the screen is too short for must reach its side's inset.
 */
async function popoverLayout(panel: Locator, trigger: Locator) {
  const t = (await trigger.boundingBox())!;
  return panel.evaluate((el, t) => {
    const r = el.getBoundingClientRect();
    const bar = document.querySelector("header")!.getBoundingClientRect();
    const root = document.documentElement;
    const vh = root.clientHeight;
    // the insets a panel keeps clear of are the page's own scroll padding (Popover's `pageInsets`)
    const px = (v: string) => (Number.isFinite(parseFloat(v)) ? parseFloat(v) : 0);
    const style = getComputedStyle(root);
    const ins = { top: Math.max(8, px(style.scrollPaddingTop)), bottom: Math.max(8, px(style.scrollPaddingBottom)) };
    const below = !el.style.bottom;
    const gap = below ? r.top - (t.y + t.height) : t.y - r.bottom;
    // how much further the page could still scroll to move the trigger towards the far edge
    const movable = below
      ? Math.max(0, Math.min(root.scrollHeight - vh - scrollY, t.y - ins.top))
      : Math.max(0, Math.min(scrollY, vh - ins.bottom - (t.y + t.height)));
    const mostRoom = below ? vh - ins.bottom - (t.y + t.height - movable) - gap : t.y + movable - gap - ins.top;
    const height = el.scrollHeight + ((el as HTMLElement).offsetHeight - el.clientHeight);
    const scrolls = el.scrollHeight > el.clientHeight + 1;
    const fillsSide = below ? r.bottom >= vh - ins.bottom - 1 : r.top <= ins.top + 1;
    return {
      // scrolls inside although the page could have made room for all of it
      needlessInnerScroll: scrolls && height <= mostRoom + 1,
      // scrolls inside (the screen is too short for it) without taking all the room its side has
      shortOfItsSide: scrolls && !fillsSide,
      underTopBar: r.top < bar.bottom,
      overTrigger: r.top < t.y + t.height && r.bottom > t.y && r.left < t.x + t.width && r.right > t.x,
      inViewport: r.top >= 0 && r.bottom <= innerHeight,
      sizes: { height: Math.round(height), shown: el.clientHeight, mostRoom: Math.round(mostRoom), side: below ? "bottom" : "top" },
    };
  }, t);
}
const fits = { needlessInnerScroll: false, shortOfItsSide: false, underTopBar: false, overTrigger: false, inViewport: true };

/** `popoverLayout` against `fits`, saying how tall the panel is and how much room the page had for it. */
async function expectFits(panel: Locator, trigger: Locator): Promise<void> {
  const { sizes, ...layout } = await popoverLayout(panel, trigger);
  expect(layout, `panel ${sizes.height} px tall (${sizes.shown} px shown) ${sizes.side === "bottom" ? "below" : "above"} its trigger, room for ${sizes.mostRoom} px`).toEqual(fits);
}

/** Scroll the page so `trigger` sits a third of the way down the viewport (as far as the page can scroll). */
async function pinInView(page: Page, trigger: Locator): Promise<void> {
  await trigger.evaluate((el) => {
    const r = el.getBoundingClientRect();
    window.scrollBy({ top: r.top - innerHeight / 3, behavior: "instant" });
  });
  await settle(page);
}

for (const height of [800, 720]) {
  test.describe(`laptop 1280×${height}: popovers`, () => {
    test.use({ viewport: { width: 1280, height } });

    test("Today's Pay panel shows everything the screen has room for, clear of the top bar and its trigger; Tab out moves on", async ({ page }) => {
      await open(page, "/", /Sam/);
      const pay = page.getByRole("main").getByRole("button", { name: /^Pay: / }).first();
      // a fixed place for the trigger — a third of the way down — whatever the shared demo's earlier tests left
      // on Today and wherever the click would scroll it (review round 3 of phase 2: a run with the trigger near
      // the top left no room to make below it, and the panel scrolled inside)
      await pinInView(page, pay);
      await pay.click();
      const panel = page.getByRole("dialog", { name: /^Pay: / });
      await expect(panel.getByRole("button", { name: "Mark as paid" })).toBeVisible();
      // focus goes to the panel (announced by its name), not to a control further down
      await expect(panel).toBeFocused();
      await settle(page);
      // what the demo puts in the panel (transfer details, the IBAN check, the GiroCode) can be taller than
      // a 720 px screen leaves under the top bar: then, and only then, it scrolls inside
      await expectFits(panel, pay);

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
      await expectFits(panel, why);
      const side = await panel.evaluate((el) => (el.style.bottom ? "top" : "bottom"));
      await panel.getByRole("button", { name: "Show the rules" }).click();
      await expect(panel.getByRole("button", { name: "Hide the rules" })).toBeVisible();
      await settle(page);
      await expectFits(panel, why);
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
