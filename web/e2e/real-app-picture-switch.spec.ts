/**
 * Settings → Data → *Text in pictures* (ADR 0024) on the real app (`ordnung serve`), which the end-to-end runs start
 * with `ORDNUNG_OCR=off`: the card says the variable turns it off whatever the switch says, the switch stays usable
 * and shows the saved choice, and a save says the choice counts once the variable is unset — as the doctor's row
 * says it too. At 320, 375 and 1280 px, light and dark, with axe. The switch is left on.
 *
 * With `ORDNUNG_E2E_OCR=on` the real app reads pictures (no variable): `e2e/real-app-pictures.spec.ts` switches it
 * there, and this spec is skipped.
 */
import type { Page } from "@playwright/test";
import { E2E_OCR } from "./env";
import { apiGet, apiSend, expect, expectAccessible, open, settle, test } from "./helpers";

const TITLE = "Text in pictures";
const SWITCH = /^Read the words in photos and scans Claude isn't reading/;
const VARIABLE =
  "Turned off by ORDNUNG_OCR=off while Ordnung runs: it reads no pictures, whatever this switch says. Your choice here counts once the variable is unset and Ordnung is started again.";

interface Health {
  picture_text: { state: string; detail: string; fix: string | null } | null;
  checks: { id: string; status: string; detail: string }[];
}

test.skip(E2E_OCR, "the real app reads pictures here (ORDNUNG_E2E_OCR=on): real-app-pictures.spec.ts switches it");

const card = (page: Page) => page.getByRole("main").getByRole("region", { name: TITLE });
const toast = (page: Page, title: string) => page.locator("li[data-toast]").filter({ hasText: title });

test("turned off by ORDNUNG_OCR: the card says so, and a save says when the choice counts", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  await apiSend(page, "PUT", "/api/settings", { read_picture_text: true });
  try {
    // the computer's own state, in the doctor's words
    const health = await apiGet<Health>(page, "/api/health");
    expect(health.picture_text).toEqual({ state: "off_by_variable", detail: "Turned off (ORDNUNG_OCR=off)", fix: null });

    for (const width of [320, 375, 1280] as const) {
      await page.setViewportSize({ width, height: width === 1280 ? 800 : 700 });
      await open(page, "/settings?section=data", "Settings");
      const callout = card(page).getByText(VARIABLE);
      await expect(callout).toBeVisible();
      await expect(callout.locator("code")).toHaveText("ORDNUNG_OCR=off");
      const theSwitch = card(page).getByRole("switch", { name: SWITCH });
      await expect(theSwitch).toHaveAttribute("aria-checked", "true");
      await expect(theSwitch).toBeEnabled();
      await card(page).scrollIntoViewIfNeeded();
      for (const theme of ["light", "dark"] as const) {
        await page.emulateMedia({ colorScheme: theme });
        await settle(page);
        expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), `${width} px ${theme}`).toBe(0);
        await expectAccessible(page, testInfo, `real-picture-switch-${width}-${theme}`);
      }
      await page.emulateMedia({ colorScheme: "light" });
    }

    // saved off: it counts once the variable is unset; the variable's state stays what health says
    await theSwitchSave(page);
    await expect(toast(page, "Saved.")).toContainText("It counts once ORDNUNG_OCR is unset.");
    await expect(card(page).getByRole("switch", { name: SWITCH })).toHaveAttribute("aria-checked", "false");
    expect((await apiGet<{ read_picture_text: boolean }>(page, "/api/settings")).read_picture_text).toBe(false);
    expect((await apiGet<Health>(page, "/api/health")).picture_text?.state).toBe("off_by_variable");
    await expect(card(page).getByText(VARIABLE)).toBeVisible();
  } finally {
    await apiSend(page, "PUT", "/api/settings", { read_picture_text: true });
  }
});

/** Flip the switch and save. */
async function theSwitchSave(page: Page) {
  await card(page).getByRole("switch", { name: SWITCH }).click();
  await card(page).getByRole("button", { name: "Save changes" }).click();
}
