/**
 * Your household on the real app (`ordnung serve` with the fake Claude; ADR 0023). The fake answers with the demo's
 * recorded reading of the bank's fee increase, addressed to the demo persona, Sam Rivera. Renamed Alex Rivera for
 * this spec (`PUT /api/profile`, set back in `finally`; the real-app specs run one at a time), the person is no
 * longer the addressee, as in `real-app-addressee.spec.ts`.
 *
 * The person adds Sam Rivera and Mia Rivera in Settings; the letter then asks *Is this letter for Sam Rivera?* and
 * nothing is filed until a press: *Yes* files it, the toast's Undo asks again, *Yes* once more. Filed for Sam, Today
 * says so, a reply offers *Reply in Sam Rivera's name* (never filled in by itself), and the records copy holds the
 * household; once Sam no longer signs his letters, the reply goes out in the person's name with no offer of his.
 * Removed from the household, Sam's letter is the person's again ("For you", and Sam can be added back); filed as the
 * person's own, then deleted for good, it leaves no trace in the household. An Idea about Sam's letter starts with
 * "For Sam Rivera: " while it is filed for him, on Today too, and names no one once he is removed (a date a month
 * ahead is added to the letter, so the Idea is there whatever the day). Nothing is drafted. `finally` puts the
 * profile and the household back and deletes the letter.
 */
import { readFileSync } from "node:fs";
import type { Page } from "@playwright/test";
import type { Household } from "@/api/types";
import { REAL_LETTER } from "./env";
import { apiGet, apiSend, expect, open, test, type Letter } from "./helpers";

const FILE = "19_bank_preisaenderung.pdf";
const RENAMED = "Alex Rivera";
const ADDRESSEE = "Sam Rivera";
const CHILD = "Mia Rivera";
/** A date the person adds to the bank's letter, so that an Idea about the letter is there whatever the day. */
const CARD = "Bank card expires";

test.describe.configure({ mode: "serial" });

/** The letter once the API lists it as read (it is read in the background). */
async function readLetter(page: Page): Promise<Letter> {
  let found: (Letter & { status: string }) | undefined;
  await expect
    .poll(
      async () => {
        found = (await apiGet<(Letter & { status: string })[]>(page, "/api/documents")).find((d) => d.filename === FILE);
        return found?.status;
      },
      { message: `${FILE} is read`, timeout: 30_000 },
    )
    .toBe("processed");
  return found!;
}

/** No one in the household and nothing filed. */
async function emptyHousehold(page: Page): Promise<void> {
  const h = await apiGet<Household>(page, "/api/household");
  const answered = [...Object.keys(h.filed), ...h.mine];
  if (answered.length) await apiSend(page, "PATCH", "/api/household", { letters: Object.fromEntries(answered.map((id) => [id, null])) });
  // twice: the people removed by the first change keep their letters' links one change longer (for Undo)
  for (let n = 0; n < 2; n++) {
    const now = await apiGet<Household>(page, "/api/household");
    await apiSend(page, "PUT", "/api/household", { base: now.version, members: [] });
  }
}

/** The Idea that a date expires soon, about the to-do `itemId` (none: no such Idea now). */
async function ideaAbout(page: Page, itemId: string): Promise<{ title: string } | undefined> {
  const ideas = await apiGet<{ title: string; rule_id: string | null; refs: { type: string; id: string }[] }[]>(page, "/api/suggestions");
  return ideas.find((idea) => idea.rule_id === "expiry_soon" && idea.refs.some((ref) => ref.type === "item" && ref.id === itemId));
}

const header = (page: Page) => page.getByRole("main").getByRole("article").first().locator("header");
const card = (page: Page) => page.getByRole("region", { name: "Your household" });

test("a letter for someone of the household is asked about, filed with one press, and leaves nothing behind", async ({ page }) => {
  test.setTimeout(120_000);
  const before = await apiGet<{ name: string }>(page, "/api/profile");
  expect(before.name, "the real app's person is the demo persona").toBe(ADDRESSEE);
  const drafts = (await apiGet<unknown[]>(page, "/api/drafts")).length;
  try {
    await emptyHousehold(page);
    const upload = await page.request.post("/api/documents", {
      headers: { "X-Ordnung-Client": "web" },
      multipart: { files: { name: FILE, mimeType: "application/pdf", buffer: readFileSync(REAL_LETTER) }, combine: "false" },
    });
    expect(upload.status(), await upload.text()).toBe(201);
    const letter = await readLetter(page);
    await apiSend(page, "PUT", "/api/profile", { name: RENAMED });

    await test.step("Settings: Sam Rivera and Mia Rivera join the household", async () => {
      await open(page, "/settings?section=profile#set-household", "Settings");
      const form = page.getByRole("form", { name: "Add someone to your household" });
      for (const [name, signs] of [
        [ADDRESSEE, true],
        [CHILD, false],
      ] as const) {
        await form.getByRole("textbox", { name: "Name" }).fill(name);
        const box = form.getByRole("checkbox", { name: /Signs their own letters/ });
        if ((await box.isChecked()) !== signs) await box.click();
        await form.getByRole("button", { name: "Add to household" }).click();
        await expect(card(page).getByRole("listitem").filter({ hasText: name })).toBeVisible();
      }
      const h = await apiGet<Household>(page, "/api/household");
      expect(h.members.map((m) => [m.name, m.signs])).toEqual([
        [ADDRESSEE, true],
        [CHILD, false],
      ]);
      expect(h.filed, "adding people files nothing").toEqual({});
      expect(h.suggested).toEqual({ [letter.id]: h.members[0]!.id });
    });

    await test.step("the letter asks; Yes files it, Undo asks again, Yes once more", async () => {
      await open(page, `/documents/${letter.id}`);
      await expect(header(page).getByText(`Addressed to ${ADDRESSEE}`)).toBeVisible();
      const question = page.getByRole("group", { name: `Is this letter for ${ADDRESSEE}?` });
      await question.getByRole("button", { name: "Yes" }).click();
      const toast = page.locator("[data-toast]").filter({ hasText: `Filed for ${ADDRESSEE}` });
      await expect(toast).toBeVisible();
      await expect(header(page).getByText(`For ${ADDRESSEE}`, { exact: true })).toBeVisible();
      const sam = (await apiGet<Household>(page, "/api/household")).members[0]!;
      expect((await apiGet<Household>(page, "/api/household")).filed).toEqual({ [letter.id]: sam.id });
      await toast.getByRole("button", { name: "Undo" }).click();
      await expect(question).toBeVisible();
      expect((await apiGet<Household>(page, "/api/household")).filed, "Undo: not answered again").toEqual({});
      await question.getByRole("button", { name: "Yes" }).click();
      await expect(header(page).getByText(`For ${ADDRESSEE}`, { exact: true })).toBeVisible();
      expect((await apiGet<{ household: { filed_for: { name: string } | null } }>(page, `/api/documents/${letter.id}`)).household.filed_for?.name).toBe(ADDRESSEE);
    });

    await test.step("Today says whose letter it is; a reply offers Sam Rivera's name, who signs", async () => {
      await open(page, "/");
      const today = page.getByRole("main");
      await today.getByRole("button", { name: /^Recent letters/ }).click();
      await expect(today.getByRole("region", { name: /^Recent letters/ }).getByText(new RegExp(`^For ${ADDRESSEE} · `))).toBeVisible();
      await open(page, `/letters?kind=general_reply&doc=${letter.id}`);
      const dialog = page.getByRole("dialog", { name: "New letter" });
      const from = dialog.getByRole("textbox", { name: "From" });
      await expect(from).toHaveValue(RENAMED);
      await expect(from).toHaveAccessibleDescription(`This letter is filed for ${ADDRESSEE}.`);
      await dialog.getByRole("button", { name: `Reply in ${ADDRESSEE}'s name` }).click();
      await expect(from).toHaveValue(ADDRESSEE);
      await expect(from).toHaveAccessibleDescription(`This letter is filed for ${ADDRESSEE}. It goes out in the name of ${ADDRESSEE}, who signs it.`);
      await dialog.getByRole("button", { name: "Cancel" }).click();
      await expect(dialog).toBeHidden();
    });

    await test.step("the records copy holds the household: its people, the letter filed for Sam, nothing suggested", async () => {
      await open(page, "/settings?section=data", "Settings");
      const records = page.getByRole("region", { name: "Download a copy of your records" });
      const [download] = await Promise.all([page.waitForEvent("download"), records.getByRole("button", { name: "Download JSON" }).click()]);
      const copy = JSON.parse(readFileSync((await download.path())!, "utf8")) as { household: Record<string, unknown> };
      const h = await apiGet<Household>(page, "/api/household");
      expect(copy.household).toEqual({ members: h.members.map(({ id, name, signs }) => ({ id, name, signs })), filed: { [letter.id]: h.members[0]!.id }, mine: [] });
      expect(copy.household.members).toEqual([expect.objectContaining({ name: ADDRESSEE, signs: true }), expect.objectContaining({ name: CHILD, signs: false })]);
    });

    await test.step("the Ideas say whose letter it is: one about Sam's letter starts with his name", async () => {
      // a date added to the letter, a month ahead: its Idea is there whatever the day the test runs, and Today lists
      // it under Ideas (its to-do is not one of the Top 3, which an Idea would only repeat)
      const { today } = await apiGet<{ today: string }>(page, "/api/health");
      const inAMonth = new Date(Date.parse(`${today}T12:00:00Z`) + 30 * 86_400_000).toISOString().slice(0, 10);
      const date = await apiSend<{ id: string }>(page, "POST", "/api/items", { kind: "expiry", title: CARD, due_date: inAMonth, doc_id: letter.id });
      await expect
        .poll(async () => (await ideaAbout(page, date.id))?.title, { message: "the Idea about Sam's letter names him", timeout: 15_000 })
        .toMatch(new RegExp(`^For ${ADDRESSEE}: ${CARD}: expires `));
      await open(page, "/");
      const ideas = page.getByRole("main").getByRole("region", { name: "Ideas from your secretary" });
      const more = ideas.getByRole("button", { name: /^Show \d+ more Ideas?$/ });
      if (await more.count()) await more.click();
      await expect(ideas.getByText(new RegExp(`^For ${ADDRESSEE}: ${CARD}: expires `)).first()).toBeVisible();
    });

    await test.step("Sam no longer signs his letters: the reply goes out in the person's name, with no offer of his", async () => {
      await open(page, "/settings?section=profile#set-household", "Settings");
      await card(page).getByRole("button", { name: `Edit ${ADDRESSEE}` }).click();
      const editing = page.getByRole("form", { name: `Edit ${ADDRESSEE}` });
      await editing.getByRole("checkbox", { name: /Signs their own letters/ }).click();
      await editing.getByRole("button", { name: "Save" }).click();
      await expect(card(page).getByRole("listitem").filter({ hasText: ADDRESSEE })).toContainText("Doesn't sign letters");
      await open(page, `/letters?kind=general_reply&doc=${letter.id}`);
      const dialog = page.getByRole("dialog", { name: "New letter" });
      const from = dialog.getByRole("textbox", { name: "From" });
      await expect(from).toHaveValue(RENAMED);
      await expect(from).toHaveAccessibleDescription(`This letter is filed for ${ADDRESSEE}, who doesn't sign letters, so it goes out in your name.`);
      await expect(dialog.getByRole("button", { name: /^Reply in / })).toHaveCount(0);
      await dialog.getByRole("button", { name: "Cancel" }).click();
      await expect(dialog).toBeHidden();
    });

    await test.step("removed from the household, Sam's letter is the person's again", async () => {
      await open(page, "/settings?section=profile#set-household", "Settings");
      await card(page).getByRole("button", { name: `Remove ${ADDRESSEE}` }).click();
      const asking = page.getByRole("dialog", { name: `Remove ${ADDRESSEE}?` });
      await expect(asking).toContainText("Their 1 letter is in your own letters again. Nothing is deleted.");
      await asking.getByRole("button", { name: "Remove" }).click();
      await expect(card(page).getByRole("listitem")).toHaveCount(1);
      await open(page, `/documents/${letter.id}`);
      await expect(header(page).getByText("For you", { exact: true })).toBeVisible();
      await expect(header(page).getByRole("button", { name: `Add ${ADDRESSEE} to your household` })).toBeVisible();
      // and the Idea about its date names no one again, at once
      const date = (await apiGet<{ id: string; title: string }[]>(page, `/api/items?doc_id=${letter.id}`)).find((i) => i.title === CARD)!;
      await expect
        .poll(async () => (await ideaAbout(page, date.id))?.title, { message: "the Idea names no one", timeout: 15_000 })
        .toMatch(new RegExp(`^${CARD}: expires `));
    });

    await test.step("filed as the person's own, then deleted for good: nothing of it stays in the household", async () => {
      await page.getByRole("button", { name: "Change who this letter is for" }).click();
      await page.getByRole("dialog", { name: "Who is this letter for?" }).getByRole("button", { name: /^You/ }).click();
      await expect(page.locator("[data-toast]").filter({ hasText: "Filed as yours" })).toBeVisible();
      expect((await apiGet<Household>(page, "/api/household")).mine).toEqual([letter.id]);
      await apiSend(page, "DELETE", `/api/documents/${letter.id}?purge=true`);
      const after = await apiGet<Household>(page, "/api/household");
      expect(after.mine).toEqual([]);
      expect(JSON.stringify(after)).not.toContain(letter.id);
    });
  } finally {
    // as the other real-app specs expect it: the person's own name, no household, and no such letter
    await emptyHousehold(page);
    await apiSend(page, "PUT", "/api/profile", { name: before.name });
    for (const added of (await apiGet<Letter[]>(page, "/api/documents")).filter((d) => d.filename === FILE)) {
      await apiSend(page, "DELETE", `/api/documents/${added.id}?purge=true`);
    }
  }
  expect((await apiGet<{ name: string }>(page, "/api/profile")).name).toBe(ADDRESSEE);
  expect((await apiGet<Household>(page, "/api/household")).members).toEqual([]);
  expect(await apiGet<unknown[]>(page, "/api/drafts"), "nothing was drafted").toHaveLength(drafts);
});
