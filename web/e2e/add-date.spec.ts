/**
 * "Add a date" on the real demo (feature audit G1: the wizard, Settings and the upload dialog promised "add your own
 * dates" with nowhere to do it): a reminder of your own on Timeline, and a deadline on a letter kept private, which
 * Claude never read and so has no dates of its own — from the keyboard, with the dialog and both pages free of
 * serious axe findings. On the private letter, ticking the date off keeps focus on its button (UX audit U4). A date
 * that repeats on a working day (audit item 26) is dated by its rule, shows it on Timeline, and is changed in its
 * own "Edit your date" dialog.
 *
 * It adds to-dos and a letter to the shared demo, so it runs last (its own project) and takes them away again.
 */
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import type { Page } from "@playwright/test";
import { WEB_DIR } from "./env";
import { expect, expectAccessible, open, setTour, test } from "./helpers";

const CLIENT = { "X-Ordnung-Client": "web" };
const SAMPLE = join(resolve(WEB_DIR, "..", "src", "ordnung", "demo", "samples"), "04_stadtwerke_vertrag.pdf");
/** Made for this run (the demo already has its own titles), so a rerun on the same demo finds only its own. */
const RUN = Date.now().toString(36);

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

/** Fill and send the dialog from the keyboard: Enter in its first field adds the date. */
async function addDate(page: Page, { title, date, kind }: { title: string; date: string; kind?: string }): Promise<void> {
  const dialog = page.getByRole("dialog", { name: "Add a date" });
  await expect(dialog).toBeVisible();
  const what = dialog.getByLabel("What is it?");
  await expect(what).toBeFocused();
  await dialog.getByLabel("When?").fill(date);
  if (kind) await dialog.getByRole("radio", { name: kind }).check();
  await what.fill(title);
  await what.press("Enter");
  await expect(dialog).toBeHidden();
  await expect(page.getByText("Date added", { exact: true })).toBeVisible();
}

async function deleteItems(page: Page, title: string): Promise<void> {
  const items = (await (await page.request.get("/api/items")).json()) as { id: string; title: string }[];
  for (const item of items.filter((i) => i.title === title)) await page.request.delete(`/api/items/${item.id}`, { headers: CLIENT });
}

test("on Timeline: a reminder of your own, added from the keyboard, is on the list", async ({ page }, testInfo) => {
  const title = `Call the landlord about the heating ${RUN}`;
  await open(page, "/timeline", "Timeline");
  const add = page.getByRole("main").getByRole("button", { name: "Add a date" });
  await add.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "Add a date" })).toBeVisible();
  await expectAccessible(page, testInfo, "add-date-dialog");
  await addDate(page, { title, date: "2026-10-14" });
  // focus is back on the button that opened it
  await expect(add).toBeFocused();
  const list = page.getByRole("region", { name: "Every date" });
  await expect(list.getByText(title)).toBeVisible();
  await expectAccessible(page, testInfo, "timeline-with-own-date");
  await deleteItems(page, title);
});

test("a monthly date on the 3rd working day: added from the keyboard, its next date and rule on the list, changed to every 3 months in its edit dialog", async ({
  page,
}, testInfo) => {
  const title = `UStVA ${RUN}`;
  await open(page, "/timeline", "Timeline");
  const add = page.getByRole("main").getByRole("button", { name: "Add a date" });
  await add.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Add a date" });
  await expect(dialog).toBeVisible();
  const what = dialog.getByLabel("What is it?");
  await expect(what).toBeFocused();
  await what.fill(title);
  await dialog.getByLabel("When?").fill("2026-10-14");
  const repeats = dialog.getByLabel("Repeats");
  await expect(repeats).toHaveValue("never");
  await repeats.focus();
  await repeats.selectOption({ label: "Every month on a working day" });
  const which = dialog.getByLabel("Which working day?");
  await expect(which).toHaveValue("3");
  await expect(which).toHaveAccessibleDescription(/The first one is in October 2026/);
  await expectAccessible(page, testInfo, "add-date-working-day");
  await what.press("Enter");
  await expect(dialog).toBeHidden();
  // the day it falls on, as the server dates it: Thu 1, Fri 2, (Sat 3 Oct is a holiday), Mon 5 Oct
  await expect(page.getByText(`${title} — Mon 5 Oct, repeats every month on the 3rd working day`)).toBeVisible();
  await expect(add).toBeFocused();

  // on the list at its next date, with its rule — a row of its own (no letter) that opens it
  const list = page.getByRole("region", { name: "Every date" });
  const row = list.getByRole("button", { name: new RegExp(title) });
  await expect(row).toContainText("Repeats every month on the 3rd working day");
  await expect(list.locator("li[data-date='2026-10-05']", { has: page.getByRole("button", { name: new RegExp(title) }) })).toHaveCount(1);
  await row.focus();
  await page.keyboard.press("Enter");
  const edit = page.getByRole("dialog", { name: "Edit your date" });
  await expect(edit).toBeVisible();
  await expect(edit.getByLabel("Next date")).toHaveValue("2026-10-05");
  await expect(edit.getByLabel("Repeats")).toHaveValue("working_day");
  await expect(edit.getByLabel("Which working day?")).toHaveValue("3");
  await expectAccessible(page, testInfo, "edit-date-dialog");
  await edit.getByLabel("Repeats").selectOption({ label: "Every 3 months on the 5th" });
  await edit.getByRole("button", { name: "Save" }).click();
  await expect(edit).toBeHidden();
  await expect(page.getByText(`${title} — Mon 5 Oct, repeats every 3 months`)).toBeVisible();
  await expect(list.getByRole("button", { name: new RegExp(title) })).toContainText("Repeats every 3 months");
  await deleteItems(page, title);
});

test("on a letter kept private: no dates of its own, a deadline added to it, ticked off without losing focus", async ({ page }, testInfo) => {
  const title = `Send the meter reading ${RUN}`;
  // a copy new to Ordnung (a comment after %%EOF changes its hash), kept private: Claude never reads it
  const file = Buffer.concat([readFileSync(SAMPLE), Buffer.from(`\n% e2e add-date ${RUN}\n`)]);
  const upload = await page.request.post("/api/documents", {
    multipart: { files: { name: `Stadtwerke_${RUN}.pdf`, mimeType: "application/pdf", buffer: file }, private: "true" },
    headers: CLIENT,
  });
  expect(upload.status(), await upload.text()).toBe(201);
  const docId = ((await upload.json()) as { documents: { id: string }[] }).documents[0]!.id;
  await expect.poll(async () => ((await (await page.request.get(`/api/documents/${docId}`)).json()) as { document: { status: string } }).document.status, { timeout: 30_000 }).toBe("processed");

  await open(page, `/documents/${docId}`);
  const todos = page.getByRole("region", { name: /^To-dos & dates/ });
  await expect(todos).toContainText("Claude didn't read this letter, so Ordnung found no dates in it.");
  await todos.getByRole("button", { name: "Add a date" }).click();
  await expect(page.getByRole("dialog", { name: "Add a date" })).toContainText(`For “Stadtwerke_${RUN}.pdf”`);
  await addDate(page, { title, date: "2026-10-09", kind: "Deadline" });

  const done = todos.getByRole("button", { name: `Mark “${title}” as done` });
  await expect(done).toBeVisible();
  await expect(todos.getByText("Date set by you")).toBeVisible();
  await expectAccessible(page, testInfo, "private-letter-with-own-date");

  // ticked off from the keyboard: the button keeps focus while it is saved and after (aria-disabled, not disabled)
  await done.focus();
  await page.keyboard.press("Space");
  const reopen = todos.getByRole("button", { name: `Reopen “${title}”` });
  await expect(reopen).toBeVisible();
  await expect(reopen).toBeFocused();

  const removed = await page.request.delete(`/api/documents/${docId}?purge=true`, { headers: CLIENT });
  expect(removed.ok(), `DELETE /api/documents/${docId} → ${removed.status()}`).toBe(true);
});
