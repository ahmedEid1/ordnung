/**
 * Layout guards on real pages (what jsdom can't see): nothing makes a page scroll sideways at
 * 320 CSS px (WCAG 1.4.10), keyboard focus never ends up hidden under the sticky top bar, the
 * phone tab bar, a toast or Ask's question box (WCAG 2.4.11), Ask's live steps grow above that box, the focus ring is the accent colour from the first frame, tabs
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

/** Ask a question on /ask (the demo replays its recorded answers) and wait for the checked answer. */
async function ask(page: Page, question: string): Promise<void> {
  const turns = page.getByRole("main").getByRole("article");
  const before = await turns.count();
  await page.getByRole("textbox").first().fill(question);
  await page.getByRole("textbox").first().press("Enter");
  await expect(turns).toHaveCount(before + 1);
  await expect(page.getByRole("main").getByRole("status")).toHaveText("Answer ready.");
}

const ASKED = ["What do I have to pay in the next four weeks?", "When does my phone contract end, and by when do I have to cancel it?"];

/**
 * Answer `POST /api/ask` in the page with a slow stream that never ends: four steps, 150 ms apart,
 * then the "writing" event (the checked answer never comes).
 */
async function slowAnswer(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const real = window.fetch.bind(window);
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (new URL(url, location.href).pathname !== "/api/ask" || (init?.method ?? "GET").toUpperCase() !== "POST") return real(input, init);
      const events: object[] = [];
      for (let i = 1; i <= 4; i++) {
        events.push({ type: "tool_use", name: "search", input: { query: `Frist ${i}` }, text: `Searched your letters for “Frist ${i}”` });
        events.push({ type: "tool_result", name: "search", text: `Found ${i} letters` });
      }
      events.push({ type: "text" });
      const enc = new TextEncoder();
      const body = new ReadableStream({
        start(ctrl) {
          events.forEach((e, i) => setTimeout(() => ctrl.enqueue(enc.encode(`data: ${JSON.stringify(e)}\n\n`)), 150 * (i + 1)));
        },
      });
      return Promise.resolve(new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }));
    };
  });
}

/** How the "Writing the answer" line and its question sit against the sticky question box. */
function writingLine(page: Page) {
  return page.evaluate(() => {
    const line = [...document.querySelectorAll("main [data-turn] p:not(.sr-only)")].find((el) => el.textContent?.startsWith("Writing the answer"));
    const composer = document.querySelector("[data-ask-composer]")!.getBoundingClientRect();
    const turn = line?.closest("[data-turn]")?.getBoundingClientRect();
    if (!line || !turn) return null;
    return { aboveComposer: line.getBoundingClientRect().bottom <= composer.top + 1, questionShown: turn.top >= 56 };
  });
}

// review round 2 of phase 2: on /ask the sticky question box covers the bottom of the screen too —
// focused citation markers and source chips ended up under it, and the live steps grew behind it
test.describe("phone: on Ask, focus and the growing answer stay clear of the question box", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test("Tab through two answered questions", async ({ page }) => {
    await open(page, "/ask");
    for (const question of ASKED) await ask(page, question);
    await page.evaluate(() => {
      (document.activeElement as HTMLElement | null)?.blur();
      window.scrollTo(0, 0);
    });
    expect(await obscuredFocus(page, 60, "Tab")).toEqual([]);
  });

  test("at 320 × 640 the steps and the writing line grow above the question box", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 640 });
    await slowAnswer(page);
    await open(page, "/ask");
    await page.getByRole("textbox").first().fill("Which deadlines do I have?");
    await page.getByRole("textbox").first().press("Enter");
    await expect(page.getByRole("main").getByText(/^Writing the answer — it appears once Ordnung has checked it against your records/)).toBeVisible();
    await expect.poll(() => writingLine(page)).toEqual({ aboveComposer: true, questionShown: true });
  });
});

test.describe("laptop: on Ask, focus stays clear of the question box", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("Tab through two answered questions", async ({ page }) => {
    await open(page, "/ask");
    for (const question of ASKED) await ask(page, question);
    await page.evaluate(() => {
      (document.activeElement as HTMLElement | null)?.blur();
      window.scrollTo(0, 0);
    });
    expect(await obscuredFocus(page, 60, "Tab")).toEqual([]);
  });
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

    test("Today's Pay panel shows everything, clear of the top bar and its trigger; Tab out moves on", async ({ page }) => {
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
