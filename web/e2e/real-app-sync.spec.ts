/**
 * Hand-off sync between two real computers (design §23.5, ADR 0018): one `ordnung serve` set up as usual (the
 * project's real app, "laptop") and a second one on its own data folder, new ("desktop"); each keeps its secrets
 * in a password store of its own (`tests/e2e_support/e2e_keyring.py`) and sees its own copy of "the" synced
 * folder, which e2e/sync-tool.ts keeps in step only when a test says so — late, out of order, in pieces and with
 * conflict copies, as Nextcloud, Syncthing or Dropbox do.
 *
 * One story, in order (the tests share both computers and the folder):
 *
 * 1. the laptop starts syncing with a suggested passphrase, adds a letter, and the top bar says it is saved;
 * 2. the desktop's welcome page offers "I already use Ordnung on another computer": it joins, says what is still
 *    on its way while the sync tool has brought only the head, and opens with the laptop's letter once the rest has
 *    arrived (shuffled, half of it written in place, with conflict copies next to it);
 * 3. once the desktop's claim reaches the laptop, the laptop stands by: a write there is refused with the server's
 *    sentence in one toast, the standing-by screen appears by itself, and "Use Ordnung here" takes Ordnung back;
 * 4. both computers change something while neither sees the other: the laptop is asked once which Ordnung to
 *    keep, keeps its own, and the desktop's next "Use Ordnung here" saves the desktop's data as a kept copy first;
 * 5. neither copy of the folder holds a readable byte: only Ordnung's meaningless names (and the tool's own files,
 *    which Ordnung never touched), no name, title, passphrase, letter or database;
 * 6. Settings → Your computers, the standing-by screen and the choice pass axe in light and dark mode.
 *
 * Afterwards both computers leave sync and the laptop's letter goes, so the real-app specs after this one find the
 * laptop as they expect it. What the pages offer (P3's copy, design §19) is named once below; the server's
 * sentences are `ordnung.sync`'s constants (tests/test_e2e_support.py keeps the copies here equal to them).
 *
 * Limits: both computers run on one machine with a simulated sync tool. A pass with a real Nextcloud, Syncthing or
 * iCloud Drive folder on two physical computers is still to be done by hand (ADR 0018).
 */
import type { APIRequestContext, Browser, BrowserContext, Page, TestInfo } from "@playwright/test";
import type { components } from "@/api/schema";
import { readFileSync } from "node:fs";
import { REAL_B_BASE_URL, REAL_B_STORAGE_STATE, REAL_BASE_URL, REAL_LETTER, REAL_STORAGE_STATE, SYNC_A_DIR, SYNC_B_DIR } from "./env";
import { apiGet, apiSend, expect, expectAccessible, expectNoRawEnums, letterDetail, open, settle, shownAs, test, type Letter, type LetterItem } from "./helpers";
import { isOrdnungName, isSyncToolFile, ORDNUNG_NAMES, SyncTool, type Side } from "./sync-tool";

type SyncStatus = components["schemas"]["SyncStatus"];

test.describe.configure({ mode: "serial" });

// ------------------------------------------------------------------------------------------------
// What the pages offer (design §19: Settings → Your computers, /join, the standing-by screen, the choice)
// ------------------------------------------------------------------------------------------------

const COMPUTERS = "/settings?section=computers";
/** The setup card's title in Settings, and on `/join`. */
const SETUP_TITLE = "Use Ordnung on more than one computer";
const JOIN_TITLE = "Bring Ordnung over from your other computer";
const FOLDER_FIELD = "Sync folder";
const NAME_FIELD = "This computer's name";
/** A new sync's passphrase (twice), and the one typed to join. */
const PASSPHRASE_FIELD = "Passphrase";
const REPEAT_FIELD = "Repeat the passphrase";
const JOIN_PASSPHRASE_FIELD = "The sync passphrase";
const SUGGEST = "Suggest a strong one";
/** The card's footer button: first the folder is looked at, then a new sync starts or an existing one is joined. */
const NEXT = "Next";
const START = "Start syncing";
const BRING = "Bring it here";
/** What the folder turned out to be, under its field. */
const NEW_FOLDER = /A new sync starts in this folder/;
const EXISTING_FOLDER = /This folder holds a sync from your other computer/;
/** The welcome page's way to `/join`, and `/join`'s heading. */
const JOIN_LINK = "I already use Ordnung on another computer";
const BRINGING = (from: string) => new RegExp(`Bringing Ordnung over from ${from}`);
/** The standing-by screen (instead of the app's pages) and its one button. */
const STANDBY_HEADING = (name: string) => `Ordnung is in use on ${name}`;
const USE_HERE = "Use Ordnung here";
/** The top bar's word on saving, on the computer in use. */
const SAVED = /^Saved\b/;
/** The banner when both computers changed, its button, the dialog, a side and its answer. */
const CHOOSE = /^Choose/;
const CHOICE_DIALOG = "Which Ordnung do you want to keep?";
const THIS_SIDE = (name: string) => new RegExp(`^This computer \\(${name}\\)`);
const KEEP = "Keep this one";
/** A to-do's "done" button on a letter's page. */
const DONE = /^Mark “.+” as done$/;

// ------------------------------------------------------------------------------------------------
// The server's sentences (`ordnung.sync`: STANDBY_MESSAGE)
// ------------------------------------------------------------------------------------------------

const STANDBY_MESSAGE = (name: string) => `Ordnung is in use on ${name}. Use it here first (Settings → Your computers).`;

// ------------------------------------------------------------------------------------------------
// The two computers and the folder
// ------------------------------------------------------------------------------------------------

/** The project's real app (set up by the global setup) and the second, new computer. */
const A = { name: "laptop", side: "a" as Side, folder: SYNC_A_DIR, baseURL: REAL_BASE_URL, storageState: REAL_STORAGE_STATE };
const B = { name: "desktop", side: "b" as Side, folder: SYNC_B_DIR, baseURL: REAL_B_BASE_URL, storageState: REAL_B_STORAGE_STATE };
const tool = new SyncTool({ a: SYNC_A_DIR, b: SYNC_B_DIR });
const FILE = "19_bank_preisaenderung.pdf";
/** What each computer adds to the letter while neither sees the other. */
const A_TODO = "Compare the fees of two other banks";
const B_TODO = "Ask the bank whether the old account model can stay";
const CLIENT = { "X-Ordnung-Client": "web" };

/** How long a computer may take to see what the sync tool brought: it reads the folder every 15 s (`SCAN_S`). */
const SCAN_WAIT = 50_000;
/** A save follows 2 s after a person's change and at most 60 s after the first unsaved one (`PUSH_MAX_WAIT_S`). */
const SAVE_WAIT = 75_000;
/** A whole step of the story: a reading, saves, scans and a take-over. */
const STEP_TIMEOUT = 240_000;

/** A letter as `GET /api/documents` lists it, with how far its reading got. */
type ListedLetter = Letter & { status: string };

/** Set in the first test: the passphrase the laptop's setup suggested, and the letter it added. */
let passphrase = "";
let letter: ListedLetter | undefined;

/** The sync status, straight from the server (never through a page's routes). */
const syncOf = (page: Page): Promise<SyncStatus> => apiGet<SyncStatus>(page, "/api/sync");

/** Wait until the server's sync status satisfies `ok`; the message says what it was last. */
async function until(page: Page, what: string, ok: (s: SyncStatus) => boolean, timeout = SCAN_WAIT): Promise<SyncStatus> {
  let last: SyncStatus | undefined;
  await expect
    .poll(
      async () => {
        last = await syncOf(page);
        return ok(last);
      },
      { message: `${what} (it was: ${describe(last)})`, timeout, intervals: [500, 1_000, 2_000] },
    )
    .toBe(true);
  return last!;
}

function describe(status: SyncStatus | undefined): string {
  if (!status) return "not asked yet";
  const { connected, mode, activity, in_use_on, pending_changes, last_saved_at, take_over_waiting } = status;
  return JSON.stringify({ connected, mode, activity, in_use_on, pending_changes, last_saved_at, take_over_waiting, problem: status.problem?.code, choice: Boolean(status.choice) });
}

const saved = (s: SyncStatus) => s.connected && s.mode === "in_use" && s.activity === "idle" && !s.pending_changes && Boolean(s.last_saved_at);

interface Computer {
  context: BrowserContext;
  page: Page;
  errors: string[];
}

/** The second computer's browser (the project's own `page` is the laptop's); its page errors fail the test. */
async function desktop(browser: Browser): Promise<Computer> {
  const context = await browser.newContext({ baseURL: B.baseURL, storageState: B.storageState });
  const page = await context.newPage();
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(err.stack ?? err.message));
  return { context, page, errors };
}

async function closeDesktop(computer: Computer): Promise<void> {
  await computer.context.close();
  expect(computer.errors, "uncaught errors on the desktop's pages").toEqual([]);
}

/** The letter's to-dos on one computer. */
async function todos(page: Page, id: string): Promise<LetterItem[]> {
  return (await apiGet<{ items: LetterItem[] }>(page, `/api/documents/${id}`)).items;
}

/** A to-do of the person's own on the letter (a person change, through the API as the app sends it). */
async function addTodo(page: Page, title: string): Promise<void> {
  await apiSend(page, "POST", "/api/items", { kind: "task", title, due_date: "2026-11-20", doc_id: letter!.id });
}

/** axe over the whole page as it is now, once light and once dark (the app follows the system's scheme). */
async function accessibleInBothThemes(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    const html = page.locator("html");
    if (scheme === "dark") await expect(html).toHaveClass(/\bdark\b/);
    else await expect(html).not.toHaveClass(/\bdark\b/);
    await settle(page);
    await expectAccessible(page, testInfo, `${name}-${scheme}`);
  }
  await page.emulateMedia({ colorScheme: null });
}

// ------------------------------------------------------------------------------------------------
// The story
// ------------------------------------------------------------------------------------------------

test("the laptop starts syncing with a suggested passphrase, and its letter is saved to the folder", async ({ page }) => {
  test.setTimeout(STEP_TIMEOUT);
  tool.markFolders();
  const before = await syncOf(page);
  expect(before.available, `hand-off sync can be used here (the e2e password store): ${before.unavailable}`).toBe(true);
  expect(before.connected).toBe(false);

  await test.step("set up: the folder is looked at, a five-word passphrase is suggested", async () => {
    await open(page, COMPUTERS, "Settings");
    const card = page.getByRole("region", { name: SETUP_TITLE });
    await card.getByLabel(FOLDER_FIELD).fill(A.folder);
    await card.getByLabel(NAME_FIELD).fill(A.name);
    await card.getByRole("button", { name: NEXT }).click();
    await expect(card.getByText(NEW_FOLDER)).toBeVisible();
    await card.getByRole("button", { name: SUGGEST }).click();
    passphrase = await card.getByLabel(PASSPHRASE_FIELD, { exact: true }).inputValue();
    expect(passphrase.split(/[^\p{L}\p{Nd}]+/u).filter(Boolean), `five words: ${passphrase.replace(/\p{L}/gu, "x")}`).toHaveLength(5);
    await expect(card.getByLabel(REPEAT_FIELD)).toHaveValue(passphrase);
    await card.getByRole("button", { name: START }).click();
    const on = await until(page, "the laptop is in use and syncs", (s) => s.connected && s.mode === "in_use");
    expect([on.this_computer, on.folder]).toEqual([A.name, A.folder]);
    expect(JSON.stringify(on), "the status never carries the passphrase").not.toContain(passphrase);
  });

  await test.step("a letter added here is read", async () => {
    await open(page, "/inbox", "Inbox");
    await page.locator("input[type=file][multiple]").first().setInputFiles(REAL_LETTER);
    const dialog = page.getByRole("dialog", { name: "Add this letter?" });
    await dialog.getByRole("button", { name: "Add letter" }).click();
    await expect(dialog).toBeHidden();
    await expect
      .poll(
        async () => {
          letter = (await apiGet<ListedLetter[]>(page, "/api/documents")).find((d) => d.filename === FILE);
          return letter?.status;
        },
        { message: `${FILE} is read`, timeout: 30_000 },
      )
      .toBe("processed");
  });

  await test.step("saved to the folder: the top bar says so, and the folder holds only Ordnung's names", async () => {
    await until(page, "the letter is saved to the sync folder", saved, SAVE_WAIT);
    await open(page, "/");
    await expect(page.getByRole("link", { name: SAVED }).first()).toBeVisible();
    const names = [...tool.files("a").keys()];
    expect(names.filter((n) => ORDNUNG_NAMES.keyFile.test(n)), "one key file").toHaveLength(1);
    expect(names.filter((n) => ORDNUNG_NAMES.head.test(n)), "the laptop's head").toHaveLength(1);
    expect(names.filter((n) => ORDNUNG_NAMES.object.test(n)).length, "the letter's files, the database, the lists").toBeGreaterThan(3);
    expect(names.filter((n) => !isOrdnungName(n))).toEqual([]);
  });
});

test("the desktop joins from its welcome page, waits for what hasn't arrived, and opens with the laptop's letter", async ({ browser }) => {
  test.setTimeout(STEP_TIMEOUT);
  const b = await desktop(browser);
  expect((await syncOf(b.page)).available, "hand-off sync can be used on the desktop").toBe(true);

  await test.step("the sync tool brings the key file and the laptop's head first, the letter's files not yet", async () => {
    const first = await tool.deliver("a", { only: (path) => !ORDNUNG_NAMES.object.test(path) });
    expect(first.filter((d) => ORDNUNG_NAMES.head.test(d.path))).toHaveLength(1);
    expect(tool.pending("a").length, "objects still on their way").toBeGreaterThan(3);
  });

  await test.step("“I already use Ordnung on another computer”: the folder and the passphrase", async () => {
    await b.page.goto("/");
    await b.page.waitForURL(/\/welcome/);
    await b.page.getByRole("link", { name: JOIN_LINK }).click();
    await b.page.waitForURL(/\/join$/);
    await expect(b.page.getByRole("heading", { level: 1, name: JOIN_LINK })).toBeVisible();
    const card = b.page.getByRole("region", { name: JOIN_TITLE });
    await card.getByLabel(FOLDER_FIELD).fill(B.folder);
    await card.getByLabel(NAME_FIELD).fill(B.name);
    await card.getByRole("button", { name: NEXT }).click();
    await expect(card.getByText(EXISTING_FOLDER)).toBeVisible();
    await card.getByLabel(JOIN_PASSPHRASE_FIELD, { exact: true }).fill(passphrase);
    await card.getByRole("button", { name: BRING }).click();
  });

  await test.step("it says what is still on its way, and applies nothing before everything is here", async () => {
    const waiting = await until(b.page, "the desktop waits for the letter's files", (s) => s.connected && (s.take_over_waiting || s.arriving !== null));
    if (waiting.arriving) expect(waiting.arriving.have).toBeLessThan(waiting.arriving.need);
    await expect(b.page.getByRole("heading", { name: BRINGING(A.name) })).toBeVisible();
    expect(await apiGet<Letter[]>(b.page, "/api/documents"), "nothing applied yet").toEqual([]);
  });

  await test.step("the rest arrives shuffled, half of it in pieces, with conflict copies: the desktop opens with the letter", async () => {
    const rest = await tool.deliver("a", { order: "shuffled", seed: 7, inPlace: true, pauseMs: 40, conflictCopies: true });
    expect(rest.length).toBeGreaterThan(3);
    const joined = await until(b.page, "the desktop is in use", (s) => s.mode === "in_use" && s.activity === "idle", SCAN_WAIT * 2);
    expect([joined.this_computer, joined.base_from, joined.problem]).toEqual([B.name, A.name, null]);
    // `/join` opens the app by itself once Ordnung is in use here
    await b.page.waitForURL((url) => url.pathname === "/", { timeout: SCAN_WAIT });
    const there = await apiGet<Letter[]>(b.page, "/api/documents");
    expect(there.map((d) => d.filename)).toEqual([FILE]);
    expect((await apiGet<{ name: string }>(b.page, "/api/profile")).name, "the profile came along").toBe("Sam Rivera");
    const { title } = await letterDetail(b.page, letter!.id);
    await open(b.page, `/documents/${letter!.id}`, shownAs(title));
  });
  await closeDesktop(b);
});

test("the laptop stands by once the desktop's claim arrives, refuses writes, and takes Ordnung back with one click", async ({ page }, testInfo) => {
  test.setTimeout(STEP_TIMEOUT);
  const inUse = await syncOf(page);
  expect(inUse.mode, "the laptop doesn't know yet").toBe("in_use");

  // The letter's page stays as it was loaded — its idea of sync held back until the person's next write is
  // refused — so the refusal is what tells the page, as on a laptop whose page didn't hear in time.
  let stale: SyncStatus | null = inUse;
  await page.route(
    (url) => url.pathname === "/api/sync",
    (route) => (stale && route.request().method() === "GET" ? route.fulfill({ json: stale }) : route.fallback()),
  );
  await page.route(
    (url) => url.pathname.startsWith("/api/items/"),
    async (route) => {
      if (route.request().method() === "GET") return route.fallback();
      const response = await route.fetch();
      stale = null; // the refusal is in: from now on the page hears how things are
      await route.fulfill({ response });
    },
  );
  await open(page, `/documents/${letter!.id}`);
  const done = page.getByRole("main").getByRole("button", { name: DONE }).first();
  await expect(done).toBeVisible();

  await test.step("the desktop's claim arrives: the laptop stands by", async () => {
    const delivered = await tool.deliver("b");
    expect(delivered.filter((d) => ORDNUNG_NAMES.head.test(d.path)).map((d) => d.change)).toContain("added");
    await until(page, "the laptop stands by", (s) => s.mode === "standing_by" && s.in_use_on === B.name);
  });

  await test.step("a write is refused before it runs: one toast with the server's sentence, then the standing-by screen", async () => {
    const open_ = (await todos(page, letter!.id)).filter((t) => t.status === "open").length;
    await done.click();
    await expect(page.getByText(STANDBY_MESSAGE(B.name)).first()).toBeVisible();
    await expect(page.getByRole("heading", { level: 1, name: STANDBY_HEADING(B.name) })).toBeVisible({ timeout: 15_000 });
    expect((await todos(page, letter!.id)).filter((t) => t.status === "open"), "nothing was changed").toHaveLength(open_);
    const refused = await page.request.post("/api/items", { data: { kind: "task", title: A_TODO, due_date: "2026-11-20", doc_id: letter!.id }, headers: CLIENT });
    expect(refused.status()).toBe(409);
    expect(await refused.json()).toEqual({ detail: STANDBY_MESSAGE(B.name), code: "standby" });
  });
  await page.unrouteAll({ behavior: "wait" });

  await test.step("the standing-by screen: no raw codes, accessible", async () => {
    await open(page, "/");
    await expect(page.getByRole("heading", { level: 1, name: STANDBY_HEADING(B.name) })).toBeVisible();
    await expect(page.getByRole("button", { name: USE_HERE })).toBeFocused();
    await expectNoRawEnums(page, "the standing-by screen");
    await accessibleInBothThemes(page, testInfo, "standing-by");
  });

  await test.step("“Use Ordnung here”: one click, no “are you sure?”, and the laptop is in use again", async () => {
    await page.getByRole("button", { name: USE_HERE }).click();
    const back = await until(page, "the laptop is in use again", (s) => s.mode === "in_use" && s.activity === "idle");
    expect(back.in_use_on).toBe(A.name);
    await expect(page.getByRole("heading", { level: 1, name: STANDBY_HEADING(B.name) })).toBeHidden();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });
});

test("both computers changed: the laptop is asked once, keeps its own, and the desktop keeps a copy of its data", async ({ page, browser }, testInfo) => {
  test.setTimeout(STEP_TIMEOUT * 2);
  const b = await desktop(browser);

  await test.step("the desktop, not yet told, adds a to-do and saves it", async () => {
    expect((await syncOf(b.page)).mode, "the desktop still thinks it is in use").toBe("in_use");
    await addTodo(b.page, B_TODO);
    await until(b.page, "the desktop saved its change", saved, SAVE_WAIT);
  });

  await test.step("the laptop's claim reaches the desktop: it stands by", async () => {
    await tool.deliver("a");
    await until(b.page, "the desktop stands by", (s) => s.mode === "standing_by" && s.in_use_on === A.name);
  });

  await test.step("the laptop adds a to-do too and saves it", async () => {
    await addTodo(page, A_TODO);
    await until(page, "the laptop saved its change", saved, SAVE_WAIT);
  });

  await test.step("the sync tool brings both: the laptop asks which Ordnung to keep", async () => {
    await tool.deliver("b", { order: "reversed", conflictCopies: true });
    await tool.deliver("a", { order: "shuffled", seed: 11 });
    const asked = await until(page, "the laptop asks which Ordnung to keep", (s) => s.choice !== null && s.choice.sides.length === 2);
    expect(asked.choice!.sides.map((side) => [side.computer, side.this]).sort()).toEqual([
      [B.name, false],
      [A.name, true],
    ].sort());
  });

  await test.step("the choice, accessible; the laptop keeps its own", async () => {
    await open(page, "/");
    await page.getByRole("button", { name: CHOOSE }).first().click();
    const dialog = page.getByRole("dialog", { name: CHOICE_DIALOG });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("radio")).toHaveCount(2);
    for (const radio of await dialog.getByRole("radio").all()) await expect(radio, "nothing is chosen for the person").not.toBeChecked();
    await expectNoRawEnums(page, "the choice");
    await accessibleInBothThemes(page, testInfo, "choice-dialog");
    await dialog.getByRole("radio", { name: THIS_SIDE(A.name) }).check();
    await dialog.getByRole("button", { name: KEEP }).click();
    await expect(dialog).toBeHidden({ timeout: 30_000 });
    const kept = await until(page, "the laptop is in use with its own Ordnung", (s) => s.choice === null && s.mode === "in_use" && s.activity === "idle");
    expect(kept.problem).toBeNull();
    const titles = (await todos(page, letter!.id)).map((t) => t.title);
    expect(titles).toContain(A_TODO);
    expect(titles).not.toContain(B_TODO);
    await until(page, "the laptop saved what it kept", saved, SAVE_WAIT);
  });

  await test.step("the desktop takes over: its own data is kept as an encrypted copy first", async () => {
    await tool.deliver("a");
    // the laptop's answer covers the desktop's change (dropped by a choice): nothing to ask there any more
    await until(b.page, "the desktop has the laptop's answer", (s) => s.mode === "standing_by" && s.choice === null && s.up_to_date);
    await open(b.page, "/");
    await expect(b.page.getByRole("heading", { level: 1, name: STANDBY_HEADING(A.name) })).toBeVisible();
    await b.page.getByRole("button", { name: USE_HERE }).click();
    const over = await until(b.page, "the desktop is in use with the laptop's Ordnung and a kept copy", (s) => s.mode === "in_use" && s.activity === "idle" && s.kept.length > 0, SCAN_WAIT * 2);
    const titles = (await todos(b.page, letter!.id)).map((t) => t.title);
    expect(titles).toContain(A_TODO);
    expect(titles, "the desktop's change is in its kept copy, not in the data").not.toContain(B_TODO);
    const copy = over.kept[0]!;
    expect(copy.name).toMatch(/^ordnung-kept-\d{4}-\d{2}-\d{2}-\d{4}(-\d+)?\.ordnung-backup$/);
    const download = await b.page.request.get(`/api/sync/kept/${copy.name}`);
    expect(download.status()).toBe(200);
    const bytes = await download.body();
    expect(bytes.subarray(0, 15).toString("latin1"), "an ordinary encrypted backup").toBe("ORDNUNG-BACKUP\n");
    expect(bytes.includes(Buffer.from(B_TODO))).toBe(false);
  });

  await test.step("Settings → Your computers on the desktop: no raw codes, accessible", async () => {
    await open(b.page, COMPUTERS, "Settings");
    await expect(b.page.getByRole("main").getByText(A.name).first()).toBeVisible();
    await expectNoRawEnums(b.page, "Settings → Your computers");
    await accessibleInBothThemes(b.page, testInfo, "your-computers");
  });
  await closeDesktop(b);
});

test("neither copy of the folder holds anything readable, and Ordnung left the sync tool's files alone", async ({ page }) => {
  const title = letter!.title!;
  const original = readFileSync(REAL_LETTER);
  const middle = original.subarray(Math.floor(original.length / 2), Math.floor(original.length / 2) + 64);
  const secrets: [string, Buffer][] = [
    ["the profile's name", Buffer.from("Sam Rivera")],
    ["the letter's title", Buffer.from(title)],
    ["the laptop's to-do", Buffer.from(A_TODO)],
    ["the desktop's to-do", Buffer.from(B_TODO)],
    ["the passphrase", Buffer.from(passphrase)],
    ["the passphrase (NFC)", Buffer.from(passphrase.normalize("NFC"))],
    ["the laptop's name", Buffer.from(A.name)],
    ["the desktop's name", Buffer.from(B.name)],
    ["a PDF", Buffer.from("%PDF-")],
    ["a database", Buffer.from("SQLite format 3")],
    ["a backup's header", Buffer.from("ORDNUNG-BACKUP")],
    ["the letter's own bytes", middle],
    ["a letter's id", Buffer.from(letter!.id)],
  ];
  for (const side of ["a", "b"] as const) {
    const files = tool.files(side);
    const foreign = [...files.keys()].filter((path) => !isOrdnungName(path) && !isSyncToolFile(path));
    expect(foreign, `${side}: only Ordnung's names and the sync tool's own files`).toEqual([]);
    expect(tool.made[side].length, `${side}: the sync tool left files of its own there`).toBeGreaterThan(1);
    expect(tool.madeStillThere(side).sort(), `${side}: Ordnung never removed the conflict copies or the marker`).toEqual([...tool.made[side]].sort());
    for (const [path, seen] of files) {
      if (isSyncToolFile(path)) continue;
      expect(path, "names say nothing").not.toMatch(/doc_|\d{4}-\d{2}-\d{2}|\.(pdf|jpg|png|db|json)$/i);
      if (ORDNUNG_NAMES.keyFile.test(path)) expect(seen.size, "the key file").toBe(92);
      const bytes = tool.read(side, path);
      for (const [what, needle] of secrets) expect(bytes.includes(needle), `${side}/${path} holds ${what}`).toBe(false);
    }
  }
  // the computer in use agrees: nothing is wrong with the folder for it
  expect((await syncOf(page)).problem).toBeNull();
});

test.afterAll(async ({ playwright }) => {
  // both computers leave sync, whatever happened, and the laptop's letter goes (with the to-dos on it), so the
  // real-app specs after this one find the laptop as the global setup left it
  const computers: [string, APIRequestContext][] = [];
  for (const { baseURL, storageState, name } of [A, B]) {
    computers.push([name, await playwright.request.newContext({ baseURL, storageState, extraHTTPHeaders: CLIENT })]);
  }
  try {
    for (const [name, computer] of computers) {
      const left = await computer.delete("/api/sync", { data: { forget_passphrase: true, unreceived_ok: true } });
      expect(left.ok(), `DELETE /api/sync on the ${name} → ${left.status()} ${await left.text()}`).toBe(true);
    }
    const laptop = computers[0]![1];
    const docs = (await (await laptop.get("/api/documents")).json()) as Letter[];
    for (const doc of docs.filter((d) => d.filename === FILE)) {
      const gone = await laptop.delete(`/api/documents/${doc.id}?purge=true`);
      expect(gone.ok(), `DELETE /api/documents/${doc.id} → ${gone.status()}`).toBe(true);
    }
  } finally {
    for (const [, computer] of computers) await computer.dispose();
  }
});
