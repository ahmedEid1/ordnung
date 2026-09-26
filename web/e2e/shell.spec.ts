/**
 * The app shell on real pages (what jsdom can't see): the skip link is a whole padded pill on
 * screen; section pages share one left edge that the top-bar title and actions line up with;
 * a letter page on a phone has a back button to where it was opened from and Inbox as the
 * current tab; the tablet rail names its sections; the sidebar toggle keeps focus; the tab-bar
 * focus ring stays inside the bar; and "Try again" keeps the "isn't running" card.
 */
import { apiGet, expect, open, setTour, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

for (const viewport of [
  { width: 390, height: 844 },
  { width: 1280, height: 800 },
]) {
  test.describe(`${viewport.width} px: skip link`, () => {
    test.use({ viewport });

    test("is a padded one-line pill on screen, and moves focus to the page", async ({ page }) => {
      await open(page, "/", /Sam/);
      await page.keyboard.press("Tab");
      const skip = page.getByRole("link", { name: "Skip to content" });
      await expect(skip).toBeFocused();
      await expect(skip).toBeInViewport({ ratio: 1 });
      const box = await skip.evaluate((el) => {
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return { padX: parseFloat(s.paddingLeft), padY: parseFloat(s.paddingTop), lines: Math.round((r.height - 2 * parseFloat(s.paddingTop)) / parseFloat(s.lineHeight)) };
      });
      expect(box).toEqual({ padX: 12, padY: 8, lines: 1 });
      await page.keyboard.press("Enter");
      await expect(page.getByRole("main")).toBeFocused();
      await expect(page).toHaveURL(/\/$/);
    });
  });
}

test.describe("1920 px: one content column", () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test("section pages share a left edge, and the top bar's title and actions line up with it", async ({ page }) => {
    const edges: Record<string, { h1: number; barStart: number; barEnd: number; columnEnd: number }> = {};
    for (const [path, h1] of [
      ["/", /Sam/],
      ["/inbox", "Inbox"],
      ["/timeline", "Timeline"],
      ["/contracts", "Contracts"],
      ["/letters", "Letters"],
      ["/settings", "Settings"],
    ] as const) {
      await open(page, path, h1);
      edges[path] = await page.evaluate(() => {
        const row = document.querySelector("header")!.firstElementChild as HTMLElement;
        const rowStyle = getComputedStyle(row);
        const column = document.querySelector("main")!.firstElementChild as HTMLElement;
        const add = [...row.querySelectorAll("button")].filter((b) => b.offsetParent !== null).pop()!;
        return {
          h1: Math.round(document.querySelector("main h1")!.getBoundingClientRect().left),
          barStart: Math.round(row.getBoundingClientRect().left + parseFloat(rowStyle.paddingLeft)),
          barEnd: Math.round(add.getBoundingClientRect().right),
          columnEnd: Math.round(column.getBoundingClientRect().right - parseFloat(getComputedStyle(column).paddingRight)),
        };
      });
    }
    const first = edges["/"]!;
    for (const [path, e] of Object.entries(edges)) {
      expect(e.h1, `${path}: h1 left edge`).toBe(first.h1);
      expect(e.barStart, `${path}: top bar starts at the h1`).toBe(e.h1);
      expect(e.barEnd, `${path}: "Add letters" ends with the column`).toBe(e.columnEnd);
    }
  });
});

test.describe("phone: a letter page", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test("has a back button to where it was opened from, and Inbox is the current tab", async ({ page }) => {
    await open(page, "/contracts", "Contracts");
    await page.getByRole("main").locator('a[href^="/documents/"]').first().click();
    await page.waitForURL(/\/documents\//);
    await page.waitForLoadState("networkidle");
    const back = page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", { name: "Back to Contracts" });
    await expect(back).toBeVisible();
    const box = (await back.boundingBox())!;
    expect(Math.min(box.width, box.height)).toBeGreaterThanOrEqual(36);
    // the logo gives way to it
    await expect(page.getByRole("banner").getByRole("link", { name: "Ordnung — Today" })).toBeHidden();
    await expect(page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: /^Inbox/ })).toHaveAttribute("aria-current", "page");
    await back.click();
    await expect(page).toHaveURL(/\/contracts$/);
  });

  test("tab bar: the focus ring goes round the icon pill, inside the bar", async ({ page }) => {
    await open(page, "/", /Sam/);
    const bar = page.getByRole("navigation", { name: "Primary" });
    await bar.getByRole("link", { name: "Today" }).focus();
    await page.keyboard.press("Tab");
    const inbox = bar.getByRole("link", { name: /^Inbox/ });
    await expect(inbox).toBeFocused();
    const ring = await inbox.evaluate((link) => {
      const pill = link.firstElementChild as HTMLElement;
      const nav = link.closest("nav")!.getBoundingClientRect();
      const r = pill.getBoundingClientRect();
      return {
        linkOutline: getComputedStyle(link).outlineStyle,
        pillRing: getComputedStyle(pill).boxShadow !== "none",
        inside: r.top - 2 >= nav.top && r.bottom + 2 <= nav.bottom,
      };
    });
    expect(ring).toEqual({ linkOutline: "none", pillRing: true, inside: true });
  });
});

test.describe("tablet 768 px: the rail", () => {
  test.use({ viewport: { width: 768, height: 1024 } });

  test("names every section under its icon, uncut, and shows the number to check", async ({ page }) => {
    await open(page, "/inbox", "Inbox");
    const nav = page.getByRole("navigation", { name: "Primary" });
    for (const label of ["Today", "Inbox", "Timeline", "Contracts", "Letters", "Ask"]) {
      const text = nav.getByText(label, { exact: true });
      await expect(text).toBeVisible();
      expect(await text.evaluate((el) => el.scrollWidth <= el.clientWidth), `${label} is not cut off`).toBe(true);
    }
    const toCheck = await apiGet<unknown[]>(page, "/api/documents?status=needs_review");
    if (toCheck.length) await expect(nav.getByRole("link", { name: /^Inbox, / })).toContainText(String(toCheck.length));
  });
});

test.describe("laptop: sidebar", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("collapse and expand are one button that keeps focus", async ({ page }) => {
    await open(page, "/", /Sam/);
    await page.getByRole("button", { name: "Collapse sidebar" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "Expand sidebar" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "Collapse sidebar" })).toBeFocused();
  });
});

test.describe("Ordnung isn't reachable", () => {
  test("'Try again' keeps the card and its focus, and says when it still fails", async ({ page }) => {
    await page.route("**/api/health", (route) => route.abort());
    await page.goto("/");
    const heading = page.getByRole("heading", { level: 1, name: "Ordnung isn't running" });
    await expect(heading).toBeVisible({ timeout: 15_000 });
    const retry = page.getByRole("button", { name: "Try again" });
    await retry.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("status")).toHaveText("Trying again…");
    await expect(heading).toBeVisible();
    await expect(retry).toBeFocused();
    await expect(page.getByRole("status")).toHaveText("Still can't reach Ordnung.", { timeout: 15_000 });
    await expect(retry).toBeFocused();
  });
});
