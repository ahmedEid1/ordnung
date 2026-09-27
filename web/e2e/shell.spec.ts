/**
 * The app shell on real pages (what jsdom can't see): the skip link is a whole padded pill on
 * screen; section pages share one left edge that the top-bar title and actions line up with;
 * a letter page on a phone has a back button to where it was opened from and Inbox as the
 * current tab; the tablet rail names its sections; the sidebar toggle keeps focus; the tab-bar
 * focus ring stays inside the bar; and "Try again" keeps the "isn't running" card. Then the
 * overlays of the shell: the letter search's dropdown and phone sheet, the card of letters being
 * read on a phone, and the opaque drop overlay.
 */
import type { Page, Route } from "@playwright/test";
import { apiGet, expect, open, settle, setTour, test } from "./helpers";

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

for (const viewport of [
  { width: 900, height: 640 },
  { width: 800, height: 600 },
]) {
  test.describe(`${viewport.width}×${viewport.height}: a short rail`, () => {
    test.use({ viewport });

    test("keeps Settings and the theme toggle on screen: the sections scroll inside the rail", async ({ page }) => {
      await open(page, "/", /Sam/);
      const sidebar = page.getByRole("complementary", { name: "Sidebar" });
      for (const target of [sidebar.getByRole("link", { name: "Settings" }), sidebar.getByRole("button", { name: /theme|mode/i })]) {
        const box = (await target.boundingBox())!;
        expect(box.y + box.height, "inside the window").toBeLessThanOrEqual(viewport.height);
      }
      // every section can still be reached: the last one scrolls into view when it takes the focus
      const ask = sidebar.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Ask" });
      await ask.focus();
      const box = (await ask.boundingBox())!;
      expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
    });
  });
}

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

// ------------------------------------------------------------------------------------------------
// Search, letters being read and the drop overlay (audit round 1, bucket "shell-b")
// ------------------------------------------------------------------------------------------------

const searchField = (page: Page) => page.getByRole("combobox", { name: "Search your letters" });

for (const viewport of [
  { width: 768, height: 1024 },
  { width: 1280, height: 800 },
]) {
  test.describe(`${viewport.width} px: letter search`, () => {
    test.use({ viewport });

    test("the dropdown fits the screen: field-wide for a message, up to 30rem for results; the active option stays in view", async ({ page }) => {
      await open(page, "/", /Sam/);
      await page.keyboard.press("/");
      const field = searchField(page);
      await expect(field).toBeFocused();
      // a clear focus ring (not just a 1 px border)
      expect(await field.evaluate((el) => getComputedStyle(el).boxShadow)).not.toBe("none");
      const panel = page.locator("[data-search-panel]");
      await field.fill("M");
      await expect(panel).toContainText("Keep typing");
      const fieldBox = (await field.boundingBox())!;
      let box = (await panel.boundingBox())!;
      expect(Math.abs(box.width - fieldBox.width)).toBeLessThanOrEqual(1);

      await field.fill("Muster");
      const options = page.getByRole("listbox", { name: "Matching letters" }).getByRole("option");
      await expect(options.first()).toBeVisible();
      box = (await panel.boundingBox())!;
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
      expect(box.width).toBeGreaterThanOrEqual(fieldBox.width - 1);
      expect(box.width).toBeLessThanOrEqual(480);

      const count = await options.count();
      for (let i = 1; i < count; i++) await page.keyboard.press("ArrowDown");
      const last = options.nth(count - 1);
      await expect(last).toHaveAttribute("aria-selected", "true");
      const list = (await page.getByRole("listbox", { name: "Matching letters" }).boundingBox())!;
      const item = (await last.boundingBox())!;
      expect(item.y).toBeGreaterThanOrEqual(list.y - 1);
      expect(item.y + item.height).toBeLessThanOrEqual(list.y + list.height + 1);
    });
  });
}

test.describe("phone 320 px: the search sheet", () => {
  test.use({ viewport: { width: 320, height: 640 }, isMobile: true, hasTouch: true });

  test("shows whole titles on two lines, lined up with the field, and Escape clears before it closes", async ({ page }) => {
    await open(page, "/", /Sam/);
    await page.getByRole("button", { name: "Search letters" }).click();
    const sheet = page.getByRole("dialog", { name: "Search letters" });
    await expect(sheet.getByRole("listbox", { name: "Recent letters" })).toBeVisible();
    const field = sheet.getByRole("combobox", { name: "Search your letters" });
    await field.fill("Muster");
    const first = sheet.getByRole("listbox", { name: "Matching letters" }).getByRole("option").first();
    await expect(first).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    // the list is flush with the field: the icon starts where the field starts
    const icon = (await first.locator("span[aria-hidden], span[role=img]").first().boundingBox())!;
    const fieldBox = (await field.boundingBox())!;
    expect(Math.abs(icon.x - fieldBox.x)).toBeLessThanOrEqual(2);
    // long titles take a second line instead of ending after a few characters
    const titles = sheet.locator("[role=option] .line-clamp-2");
    const heights = await titles.evaluateAll((els) => els.map((el) => el.getBoundingClientRect().height / parseFloat(getComputedStyle(el).lineHeight)));
    expect(Math.max(...heights)).toBeGreaterThan(1.5);

    await page.keyboard.press("Escape");
    await expect(field).toHaveValue("");
    await expect(sheet).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();
  });
});

/** Take over `/api/events` so the test can send job progress (as the UI audit does). */
async function controlEvents(page: Page) {
  const waiting: Route[] = [];
  await page.route((url) => new URL(url.href).pathname === "/api/events", (route) => void waiting.push(route));
  return async (events: { type: string; data: unknown }[]) => {
    await expect.poll(() => waiting.length).toBeGreaterThan(0);
    const body = ["retry: 3600000", "", ...events.flatMap((e) => [`event: ${e.type}`, `data: ${JSON.stringify(e.data)}`, ""])].join("\n") + "\n";
    for (const r of waiting.splice(0)) await r.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body });
  };
}

test.describe("phone 320 px: letters being read", () => {
  test.use({ viewport: { width: 320, height: 640 }, isMobile: true, hasTouch: true });

  test("several letters share one compact card that opens within 40% of the screen", async ({ page }) => {
    const deliver = await controlEvents(page);
    await open(page, "/", /Sam/);
    const docs = await apiGet<{ id: string }[]>(page, "/api/documents");
    const progress = (doc: string, stage: string, status: string, error: string | null = null) => ({
      type: "job.progress",
      data: { job_id: `job_${doc}`, doc_id: doc, stage, progress: 0.5, status, error },
    });
    await deliver([progress(docs[1]!.id, "verify", "running"), progress(docs[2]!.id, "done", "done"), progress(docs[3]!.id, "transcribe", "failed", "The file is damaged.")]);
    const summary = page.getByRole("button", { name: /^Reading 1 letter/ });
    await expect(summary).toBeVisible();
    const card = page.locator("[data-upload-group]");
    expect((await card.boundingBox())!.height).toBeLessThan(640 * 0.15);
    await summary.click();
    await expect(page.getByRole("list", { name: "Each letter" }).locator("[data-upload-row]")).toHaveCount(3);
    await settle(page);
    expect((await card.boundingBox())!.height).toBeLessThanOrEqual(640 * 0.4 + 1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });
});

test.describe("1920 px: drop overlay", () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test("an opaque card: nothing on the page shows through its text", async ({ page }) => {
    await open(page, "/", /Sam/);
    await page.evaluate(() => {
      const dt = new DataTransfer();
      dt.items.add(new File(["%PDF"], "brief.pdf", { type: "application/pdf" }));
      window.dispatchEvent(new DragEvent("dragenter", { dataTransfer: dt }));
    });
    const title = page.getByText("Drop to add letters");
    await expect(title).toBeVisible();
    await settle(page);
    const alpha = await title.evaluate((el) => {
      const bg = getComputedStyle(el.parentElement!).backgroundColor;
      const m = /rgba?\(([^)]+)\)/.exec(bg);
      const parts = m ? m[1]!.split(",").map((p) => p.trim()) : [];
      return parts.length === 4 ? Number(parts[3]) : 1;
    });
    expect(alpha).toBe(1);
  });
});
