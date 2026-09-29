/**
 * The letter page on the real demo, where jsdom can't look (UI audit round 1, letters-a): the
 * German letter is never squeezed next to the sending panel (its panes sit side by side only when
 * the card has room, by a container query), the print preview follows the letter with no empty
 * band, the preview is an image (phones show no PDF inline), the header's chips aren't cut off, on
 * phones "Mark as sent" comes first across the whole row, and Save stays in reach while you edit.
 */
import type { Page } from "@playwright/test";
import { apiGet, contractOf, expect, open, setTour, test } from "./helpers";

interface DraftSummary {
  id: string;
  kind: string;
  status: string;
}

/** The phone contract's cancellation (drafted here if the demo has none yet). */
async function cancellationId(page: Page): Promise<string> {
  const drafts = await apiGet<DraftSummary[]>(page, "/api/drafts");
  const found = drafts.find((d) => d.kind === "cancellation" && d.status !== "sent");
  if (found) return found.id;
  const phone = await contractOf(page, "mobile");
  const res = await page.request.post("/api/drafts", { data: { kind: "cancellation", contract_id: phone.id, language: "de" }, headers: { "X-Ordnung-Client": "web" } });
  expect(res.ok()).toBe(true);
  return ((await res.json()) as DraftSummary).id;
}

async function openLetter(page: Page, width: number, height = 900): Promise<void> {
  await page.setViewportSize({ width, height });
  await open(page, `/letters/${await cancellationId(page)}`);
}

const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

for (const width of [1024, 1280, 1440, 1920]) {
  test(`letter at ${width}px: the German text has room, the preview follows without a gap, nothing cut off`, async ({ page }) => {
    await openLetter(page, width);
    expect(await noSideScroll(page)).toBe(true);
    const text = page.getByRole("textbox", { name: "Letter text (German)" });
    await expect(text).toBeVisible();
    // before: 118 px at 1024 and 255 px at 1280, next to the sending panel
    expect((await text.boundingBox())!.width).toBeGreaterThanOrEqual(360);

    // side by side only when each pane gets 380 px; else one pane and a toggle
    const card = page.locator("[data-letter-editor]");
    const cardWidth = (await card.boundingBox())!.width;
    const toggle = card.getByRole("radiogroup", { name: "Show the letter or its translation" });
    if (cardWidth >= 760) {
      await expect(toggle).toBeHidden();
      await expect(card.getByRole("heading", { level: 2, name: "What it says (English)" })).toBeVisible();
    } else {
      await expect(toggle).toBeVisible();
    }

    // the preview comes right after what's above it in its column (no band stretched by the other column)
    const preview = page.getByRole("region", { name: "Print preview" });
    const gap = await preview.evaluate((el) => {
      const prev = el.previousElementSibling as HTMLElement;
      return el.getBoundingClientRect().top - prev.getBoundingClientRect().bottom;
    });
    expect(gap).toBeLessThanOrEqual(25);

    // the header's chips are whole (they have their own row until the buttons leave room)
    const chip = page.getByRole("button", { name: /FunkNetz Mobil GmbH — open details/ });
    expect(await chip.evaluate((el) => [...el.querySelectorAll("span")].every((s) => s.scrollWidth <= s.clientWidth + 1))).toBe(true);
  });
}

test("the print preview is an image of the letter, with the PDF a link away", async ({ page }) => {
  await openLetter(page, 1280);
  const preview = page.getByRole("region", { name: "Print preview" });
  await expect(preview.locator("iframe")).toHaveCount(0);
  const img = preview.getByRole("img", { name: "Preview of the printable letter" });
  await expect(img).toBeVisible();
  expect(await img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth)).toBeGreaterThan(1000);
  expect(await img.getAttribute("src")).toMatch(/\/api\/drafts\/[^/]+\/preview\.png\?v=/);
  const pdf = await page.request.get((await preview.getByRole("link", { name: /Open the PDF/ }).getAttribute("href"))!);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");
});

for (const width of [320, 390]) {
  test(`letter at ${width}px: “Mark as sent” first and across the row; Save stays in reach while editing`, async ({ page }) => {
    await openLetter(page, width, 740);
    expect(await noSideScroll(page)).toBe(true);
    const main = page.getByRole("main");
    const send = main.getByRole("button", { name: "Mark as sent" });
    const saved = main.getByRole("button", { name: /Saved/ });
    const sendBox = (await send.boundingBox())!;
    const savedBox = (await saved.boundingBox())!;
    expect(sendBox.y).toBeLessThan(savedBox.y); // first
    const row = (await send.evaluate((el) => el.parentElement!.getBoundingClientRect().width)) as number;
    expect(sendBox.width).toBeGreaterThanOrEqual(row - 1); // the whole row
    // the toggle's labels are whole
    for (const label of ["German", "English"]) {
      const seg = main.getByRole("radio", { name: label === "German" ? "Letter (German)" : "In English" });
      expect(await seg.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    }

    // editing far down the letter: a save bar above the tab bar
    const text = main.getByRole("textbox", { name: "Letter text (German)" });
    await text.click();
    await page.keyboard.press("ControlOrMeta+End");
    await page.keyboard.type(" Danke.");
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight / 2));
    const bar = page.locator("[data-save-bar]");
    await expect(bar).toBeVisible();
    await expect(bar.getByRole("button", { name: "Save" })).toBeVisible();
    const tabs = await page.getByRole("navigation", { name: "Primary" }).boundingBox();
    const barBox = (await bar.boundingBox())!;
    if (tabs) expect(barBox.y + barBox.height).toBeLessThanOrEqual(tabs.y + 1);
    // nothing saved: discard the edit again
    await bar.getByRole("button", { name: "Discard" }).click();
    await expect(bar).toBeHidden();
    await expect(main.getByRole("button", { name: /Saved/ })).toBeDisabled();
  });
}
