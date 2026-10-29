/**
 * Settings → Data → *Text in pictures* (ADR 0024) on the real demo, at 320, 375 and 1280 px in light and dark: the
 * card fits without sideways scroll and nothing sticks out of it — the doctor's install lines are long, with code in
 * them — and axe finds nothing serious, in each state its line shows. The demo runs with `ORDNUNG_OCR=off`, so its
 * own state is "turned off by the variable" (the callout above the switch); the other states are this computer's
 * health as the test answers it. Saving the switch off and on shows each toast; the demo's switch is left on.
 */
import type { Page, Route } from "@playwright/test";
import type { Health, PictureTextStatus } from "@/api/types";
import { apiGet, apiSend, expect, expectAccessible, open, setTour, settle, test } from "./helpers";

const WIDTHS = [320, 375, 1280] as const;
const THEMES = ["light", "dark"] as const;
const TITLE = "Text in pictures";
const SWITCH = /^Read the words in photos and scans Claude isn't reading/;

/** This computer's Text in pictures as the doctor words it on Linux (`ordnung.doctor.picture_text_status`). */
const STATES: Record<"reading" | "not_installed" | "not_usable" | "off", PictureTextStatus> = {
  reading: {
    state: "reading",
    detail: "Tesseract 5.3.4 (German and English): photos and scans Claude doesn't read are found by their words, not checked",
    fix: null,
  },
  not_installed: {
    state: "not_installed",
    detail: "Not installed (optional)",
    fix:
      "To find photos and scans Claude doesn't read by their words, install Tesseract: `sudo apt install tesseract-ocr " +
      "tesseract-ocr-deu` (Fedora: `sudo dnf install tesseract tesseract-langpack-deu`), then restart Ordnung.",
  },
  not_usable: {
    state: "not_usable",
    detail: "Tesseract 5.3.4 has no German language data: words with ä, ö, ü or ß are often misread",
    fix: "Install the German language data: `sudo apt install tesseract-ocr-deu` (Fedora: `sudo dnf install tesseract-langpack-deu`), then restart Ordnung.",
  },
  off: { state: "off", detail: "Off (Settings → Data → Text in pictures)", fix: null },
};
const VARIABLE = "Turned off by ORDNUNG_OCR=off while Ordnung runs: it reads no pictures, whatever this switch says.";

const card = (page: Page) => page.getByRole("main").getByRole("region", { name: TITLE });
const toast = (page: Page, title: string) => page.locator("li[data-toast]").filter({ hasText: title });

/** `GET /api/health` with this computer's Text in pictures as `answer` gives it (the demo's own when it gives none). */
async function answerHealth(page: Page, answer: () => Promise<PictureTextStatus | null>) {
  await page.route(
    (url) => url.pathname === "/api/health",
    async (route: Route) => {
      const real = await route.fetch();
      const health = (await real.json()) as Health;
      const pictureText = await answer();
      await route.fulfill({ response: real, json: pictureText ? { ...health, picture_text: pictureText } : health });
    },
  );
}

/** Nothing sticks out of the card or past the screen (text that runs past its own box too). */
async function outOfBounds(page: Page): Promise<string[]> {
  return card(page).evaluate((el) => {
    const out: string[] = [];
    const root = document.documentElement;
    if (root.scrollWidth > root.clientWidth) out.push(`the page scrolls sideways (${root.scrollWidth} > ${root.clientWidth})`);
    const r = el.getBoundingClientRect();
    if (r.right > root.clientWidth + 0.5) out.push("the card ends past the screen");
    for (const part of el.querySelectorAll<HTMLElement>("p, h3, span, code, button, label")) {
      const e = part.getBoundingClientRect();
      if (e.width && (e.right > r.right + 0.5 || e.left < r.left - 0.5)) out.push(`“${part.textContent?.slice(0, 40)}” sticks out of the card`);
      if (part.clientWidth && part.scrollWidth > part.clientWidth + 1 && getComputedStyle(part).overflowX === "visible")
        out.push(`“${part.textContent?.slice(0, 40)}” runs past its box`);
    }
    return out;
  });
}

async function checkCard(page: Page, testInfo: Parameters<typeof expectAccessible>[1], name: string) {
  await card(page).scrollIntoViewIfNeeded();
  for (const theme of THEMES) {
    await page.emulateMedia({ colorScheme: theme });
    await settle(page);
    expect(await outOfBounds(page), `${name} (${theme})`).toEqual([]);
    await expectAccessible(page, testInfo, `${name}-${theme}`);
  }
  await page.emulateMedia({ colorScheme: "light" });
}

test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

/** The shared demo as the other specs expect it: Text in pictures on. */
const switchOn = (page: Page) => apiSend(page, "PUT", "/api/settings", { read_picture_text: true });

for (const width of WIDTHS) {
  test(`${width} px: the card in each state fits and passes axe`, async ({ page }, testInfo) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width, height: width === 1280 ? 800 : 700 });
    let shown: PictureTextStatus | null = null;
    await answerHealth(page, () => Promise.resolve(shown));

    // the demo's own: turned off by the variable — the callout above the switch, no line under it
    await open(page, "/settings?section=data", "Settings");
    await expect(card(page).getByText(VARIABLE, { exact: false })).toBeVisible();
    await expect(card(page).getByRole("switch", { name: SWITCH })).toBeEnabled();
    await expect(card(page).locator("[data-tone]")).toHaveCount(0);
    await checkCard(page, testInfo, `picture-text-variable-${width}`);

    for (const state of ["not_installed", "not_usable", "reading"] as const) {
      shown = STATES[state];
      await open(page, "/settings?section=data", "Settings");
      const line = card(page).locator("[data-tone]");
      await expect(line).toBeVisible();
      await expect(line).toContainText(state === "not_installed" ? "Not installed on this computer (optional)." : STATES[state].detail);
      if (STATES[state].fix) await expect(line.locator("code").first()).toBeVisible();
      await expect(card(page).getByText(VARIABLE, { exact: false })).toHaveCount(0);
      await checkCard(page, testInfo, `picture-text-${state}-${width}`);
    }
  });
}

test("375 px: saved off and on, each with its toast, and the line follows", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 375, height: 700 });
  // this computer reads pictures while the switch is on (as the API answers it, from the saved switch)
  await answerHealth(page, async () => ((await apiGet<{ read_picture_text: boolean }>(page, "/api/settings")).read_picture_text ? STATES.reading : STATES.off));
  await switchOn(page);
  try {
    await open(page, "/settings?section=data", "Settings");
    const theSwitch = card(page).getByRole("switch", { name: SWITCH });
    await expect(theSwitch).toHaveAttribute("aria-checked", "true");
    await expect(card(page).locator("[data-tone]")).toContainText(STATES.reading.detail);

    await theSwitch.click();
    await card(page).getByRole("button", { name: "Save changes" }).click();
    await expect(toast(page, "Text in pictures is off.")).toContainText(
      "The words Ordnung had read in pictures are deleted. Search finds those letters by their name.",
    );
    await expect(card(page).locator("[data-tone]")).toHaveCount(0);
    expect((await apiGet<{ read_picture_text: boolean }>(page, "/api/settings")).read_picture_text).toBe(false);
    await expectAccessible(page, testInfo, "picture-text-saved-off-375");

    await theSwitch.click();
    await card(page).getByRole("button", { name: "Save changes" }).click();
    await expect(toast(page, "Text in pictures is on.")).toContainText("Ordnung reads the pictures of letters Claude isn't reading, one page at a time.");
    await expect(card(page).locator("[data-tone]")).toContainText(STATES.reading.detail);
    expect((await apiGet<{ read_picture_text: boolean }>(page, "/api/settings")).read_picture_text).toBe(true);
  } finally {
    await switchOn(page);
  }
});

test("1280 px: saved while the variable turns it off, the toast says when the choice counts", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await switchOn(page);
  try {
    await open(page, "/settings?section=data", "Settings");
    const theSwitch = card(page).getByRole("switch", { name: SWITCH });
    await theSwitch.click();
    await card(page).getByRole("button", { name: "Save changes" }).click();
    await expect(toast(page, "Saved.")).toContainText("It counts once ORDNUNG_OCR is unset.");
    await expect(theSwitch).toHaveAttribute("aria-checked", "false");
    await expect(card(page).getByText(VARIABLE, { exact: false })).toBeVisible();
  } finally {
    await switchOn(page);
  }
});
