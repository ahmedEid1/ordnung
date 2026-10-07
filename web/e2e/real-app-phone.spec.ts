/**
 * The real app's phone access (design §18.5, with the security review's binding amendments): a phone pairs with a
 * code the computer shows and both screens show the same two check words; it uses Ordnung over HTTPS — every
 * everyday page, two photos that become one letter, a to-do ticked off — with no refusal on the way; what stays on
 * the computer is refused, and the computer's session never signs a phone in; wrong codes lock one phone out with
 * one answer for wrong, expired and missing codes; a code used twice pairs nobody; a phone removed on the computer
 * is signed out at once; turned off, nothing listens.
 *
 * The computer is the project's browser (its session, `REAL_BASE_URL`). Each phone is a Pixel 7 context of its own
 * ({@link phoneContext}) on `PHONE_BASE_URL`: HTTPS on loopback with the certificate the real app made, which the
 * real app offers only because playwright.config.ts sets `ORDNUNG_PHONE_TEST_ADDRESS` for it. Every phone is
 * 127.0.0.1 to the server, so they share one address's pairing limits ({@link roomToPair}). The tests share the
 * phones and the server's state, so they run in order; the last one turns phone access off, and `afterAll` always
 * does, and removes the letter the phone added (with the to-do on it).
 *
 * What the phone's pages must offer (web/src/pages/PairPage.tsx and phone mode, design §13.2-13.4 and amendment B2)
 * is named once below ({@link PAIR_HEADING} …), the computer's Settings → Phone by its cards' titles.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import type { Browser, BrowserContext, BrowserContextOptions, Locator, Page } from "@playwright/test";
import type { Activity, PairResult, PhoneDevice, PhoneStatus } from "@/api/types";
import {
  CODE_ALPHABET,
  CODE_USED_MESSAGE,
  COMPUTER_ONLY_MESSAGE,
  noticeDetail,
  PAIRING_TRIES_PER_CLIENT,
  PHONE_NOT_PAIRED_MESSAGE,
  TOO_MANY_TRIES_MESSAGE,
  WRONG_CODE_MESSAGE,
} from "@/mocks/data/phone";
import { PHONE_ADDRESS, PHONE_BASE_URL, PHONE_PORT, REAL_BASE_URL, REAL_DATA_DIR, REAL_LETTER, REAL_STORAGE_STATE, phoneCookie } from "./env";
import { apiGet, apiSend, expect, expectAccessible, open, phoneContext, test } from "./helpers";

test.describe.configure({ mode: "serial" });

// ------------------------------------------------------------------------------------------------
// What the pages offer
// ------------------------------------------------------------------------------------------------

/** The pairing page's heading (`/pair`, outside the app's shell). */
const PAIR_HEADING = "Pair this phone with Ordnung";
/** Its one button. */
const PAIR_BUTTON = "Pair this phone";
/** The phone's name, prefilled with a guess ("Android phone"). */
const NAME_FIELD = "This phone's name";
/** The code typed by hand (no code in the link): the one field a phone's keyboard offers a received code for. */
const CODE_FIELD = 'input[autocomplete="one-time-code"]';
/** After pairing, the page shows the two check words until the person goes on to Today with this button or link. */
const ONWARD = /^(Open Ordnung|Continue)$/;
/** `/pair?removed=1`: what a phone sees once the computer no longer knows its sign-in. */
const REMOVED = /This phone was removed on your computer/;
/** `/pair?removed=code_reused`: what the phone that paired first sees once another device used its code. */
const CODE_REUSED = /signed out because another device used the same pairing code/;
/** Settings on a paired phone (they live on the computer). */
const PHONE_SETTINGS_HEADING = "Settings are on your computer";
/** Where a paired phone downloads the certificate authority to trust (design §6.4, served by the listener's gate). */
const CERTIFICATE_PATH = "/ordnung-certificate.crt";

/** The phone's name in these tests, and the second phone's. */
const PHONE_NAME = "Sam's Pixel";
const SPARE_NAME = "Spare phone";
/** The two photos of one letter (two pages of a tax assessment) the phone takes. */
const PHOTOS = ["23_steuerbescheid_2025_p1.jpg", "23_steuerbescheid_2025_p2.jpg"].map((name) => join(dirname(REAL_LETTER), name));
/** The to-do the phone ticks off (the computer adds it to the photographed letter). */
const TODO_TITLE = "Take the tax assessment to the advisor";

/** Pairing requests one address may send a minute (the gate's `PAIR_POSTS_PER_CLIENT_PER_MINUTE`, `ordnung.phone.pairing`). */
const PAIR_POSTS_PER_MINUTE = 10;
const MINUTE_MS = 60_000;
const CLIENT = { "X-Ordnung-Client": "web" };

// ------------------------------------------------------------------------------------------------
// Phones
// ------------------------------------------------------------------------------------------------

interface Phone {
  context: BrowserContext;
  page: Page;
  /** 401 and 403 answers the phone got while {@link Phone.watching} ("403 GET /api/settings"). */
  refused: string[];
  watching: boolean;
  /** Uncaught errors in the phone's pages. */
  errors: string[];
  closed: boolean;
}

/** Every phone the tests opened: their page errors fail the test they happen in, and each test closes its own. */
const phones: Phone[] = [];
/** When each pairing request left a phone. */
const pairPosts: number[] = [];

async function openPhone(browser: Browser, options: BrowserContextOptions = {}): Promise<Phone> {
  const context = await phoneContext(browser, options);
  const phone: Phone = { context, page: undefined as unknown as Page, refused: [], watching: false, errors: [], closed: false };
  context.on("page", (page) => page.on("pageerror", (err) => phone.errors.push(err.stack ?? err.message)));
  context.on("request", (req) => {
    if (req.method() === "POST" && new URL(req.url()).pathname === "/api/phone/pair") pairPosts.push(Date.now());
  });
  context.on("response", (res) => {
    if (!phone.watching || (res.status() !== 401 && res.status() !== 403) || !res.url().startsWith(PHONE_BASE_URL)) return;
    const url = new URL(res.url());
    phone.refused.push(`${res.status()} ${res.request().method()} ${url.pathname}${url.search}`);
  });
  phone.page = await context.newPage();
  phones.push(phone);
  return phone;
}

/**
 * Wait, if need be, until `n` more pairing requests fit in the gate's minute for one address: every phone here is
 * 127.0.0.1, and a refusal for going over (429, "Too many pairing tries on your network just now") would read like
 * the lockout these tests look for.
 */
async function roomToPair(n: number): Promise<void> {
  const recent = pairPosts.filter((at) => Date.now() - at < MINUTE_MS).sort((a, b) => a - b);
  const over = recent.length + n - PAIR_POSTS_PER_MINUTE;
  if (over > 0) await new Promise((done) => setTimeout(done, recent[over - 1]! + MINUTE_MS + 1_000 - Date.now()));
}

/** The phone paired in the first test: it is used, refused, removed and finally finds nothing listening. */
let phone: Phone;
/** That phone's id on the computer. */
let phoneId = "";
/** The letter it photographed, and the to-do on it. */
let photoLetterId = "";
let todoId = "";

/** The session token of the real app (its `server.json`): the computer's sign-in, which a phone may never use. */
function sessionToken(): string {
  return (JSON.parse(readFileSync(join(REAL_DATA_DIR, "server.json"), "utf8")) as { token: string }).token;
}

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");

/** A code as the pairing page shows it: `K7QM2-XD9PA` (any hyphen, or none). */
const shownCode = (code: string): RegExp => new RegExp(`${code.slice(0, 5)}[-\\u2010\\u2011]?${code.slice(5)}`);

/** A code that isn't `code` (its last character moved `by` along the alphabet). */
function wrongCode(code: string, by: number): string {
  const last = CODE_ALPHABET.indexOf(code.at(-1)!);
  return code.slice(0, -1) + CODE_ALPHABET[(last + by) % CODE_ALPHABET.length];
}

// ------------------------------------------------------------------------------------------------
// The pairing page (on a phone)
// ------------------------------------------------------------------------------------------------

/**
 * Open the pairing page: the QR code's link (`url`, the code after `#`) or `/pair` to type the code. The page takes
 * the code out of the address at once, so it stays in neither the history nor the address bar.
 */
async function openPairing(page: Page, url = "/pair"): Promise<void> {
  await page.goto(url);
  await expect(page.getByRole("heading", { level: 1, name: PAIR_HEADING })).toBeVisible();
  await expect(page).toHaveURL(`${PHONE_BASE_URL}/pair`);
}

/** Tap "Pair this phone"; the server's answer. */
async function submitPairing(page: Page): Promise<{ status: number; body: Record<string, unknown> }> {
  const answer = page.waitForResponse((res) => res.request().method() === "POST" && new URL(res.url()).pathname === "/api/phone/pair");
  await page.getByRole("button", { name: PAIR_BUTTON }).click();
  const res = await answer;
  return { status: res.status(), body: (await res.json()) as Record<string, unknown> };
}

/** The refusal the pairing page shows (the server's words, in an alert). */
const alertSaying = (page: Page, words: string): Locator => page.getByRole("alert").filter({ hasText: words }).first();

/** Pair on the open pairing page as `name`: the answer, whose two check words the page shows. */
async function pairAs(page: Page, name: string): Promise<PairResult> {
  await page.getByLabel(NAME_FIELD).fill(name);
  const { status, body } = await submitPairing(page);
  expect(status, `pairing ${name}: ${JSON.stringify(body)}`).toBe(200);
  const result = body as unknown as PairResult;
  expect(result.check_words).toMatch(/^[a-z]+ [a-z]+$/);
  // the words stay until the person has compared them with the computer's
  await expect(page.getByText(result.check_words).first()).toBeVisible();
  return result;
}

/** From the paired page on to Today. */
async function goOn(page: Page): Promise<void> {
  await page.getByRole("button", { name: ONWARD }).or(page.getByRole("link", { name: ONWARD })).click();
  await page.waitForURL(`${PHONE_BASE_URL}/`);
  await expect(page.getByRole("main").getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForLoadState("networkidle");
}

/**
 * A phone the computer no longer knows, on its next page load: the pairing page, saying why (`removed`: the
 * `?removed=` the phone listener gives), and its sign-in forgotten. The phone's open page may already be on its way
 * there by itself (its live connection was cut, and the next request was refused), so a navigation of ours that
 * this one interrupts is fine.
 */
async function expectRemoved(target: Phone, removed: "1" | "code_reused" = "1"): Promise<void> {
  try {
    await target.page.goto("/inbox");
  } catch (err) {
    if (!/interrupted by another navigation|net::ERR_ABORTED/.test(String(err))) throw err;
  }
  await expect(target.page).toHaveURL(`${PHONE_BASE_URL}/pair?removed=${removed}`);
  await expect(target.page.getByText(removed === "1" ? REMOVED : CODE_REUSED).first()).toBeVisible();
  // the server told the browser to forget the sign-in
  expect((await target.context.cookies()).map((c) => c.name)).not.toContain(phoneCookie());
}

// ------------------------------------------------------------------------------------------------
// Settings → Phone (on the computer)
// ------------------------------------------------------------------------------------------------

const accessCard = (page: Page) => page.getByRole("region", { name: "Use Ordnung on your phone" });
const pairDialog = (page: Page) => page.getByRole("dialog", { name: "Pair a phone" });

/** "Pair a phone": the dialog, the link its QR code carries (`data-pairing-url`, for these tests) and the code in it. */
async function showCode(page: Page): Promise<{ dialog: Locator; url: string; code: string }> {
  await page.getByRole("region", { name: "Pair a phone" }).getByRole("button", { name: "Pair a phone" }).click();
  const dialog = pairDialog(page);
  const holder = dialog.locator("[data-pairing-url]");
  await expect(holder).toBeVisible();
  const url = (await holder.getAttribute("data-pairing-url")) ?? "";
  expect(url).toMatch(new RegExp(`^${escapeRegExp(PHONE_BASE_URL)}/pair#[${CODE_ALPHABET}]{10}$`));
  const code = new URL(url).hash.slice(1);
  await expect(dialog).toContainText(shownCode(code));
  return { dialog, url, code };
}

const phoneStatus = (page: Page) => apiGet<PhoneStatus>(page, "/api/phone");

async function device(page: Page, name: string): Promise<PhoneDevice | undefined> {
  return (await phoneStatus(page)).devices.find((d) => d.name === name);
}

/** The privacy log on the computer: what this phone did (`?device=`). */
const activityOf = (page: Page, id: string) => apiGet<Activity[]>(page, `/api/activity?limit=200&device=${encodeURIComponent(id)}`);

// ------------------------------------------------------------------------------------------------
// Tests
// ------------------------------------------------------------------------------------------------

test.afterEach(async () => {
  const errors = phones.flatMap((p) => p.errors.splice(0));
  // only the first phone lives on from test to test
  for (const p of phones.filter((p) => p !== phone && !p.closed)) {
    p.closed = true;
    await p.context.close();
  }
  expect(errors, "uncaught errors in a phone's page").toEqual([]);
});

test.afterAll(async ({ playwright }) => {
  for (const p of phones.filter((p) => !p.closed)) await p.context.close();
  const computer = await playwright.request.newContext({ baseURL: REAL_BASE_URL, storageState: REAL_STORAGE_STATE, extraHTTPHeaders: CLIENT });
  try {
    // off, whatever happened: nothing listens after these tests
    const off = await computer.put("/api/phone", { data: { enabled: false } });
    expect(off.ok(), `PUT /api/phone {enabled: false} → ${off.status()}`).toBe(true);
    // what the phone added goes (with the to-do on it) — once its reading is over, so no reading is cut off
    const docs = (await (await computer.get("/api/documents")).json()) as { id: string; source: string }[];
    for (const doc of docs.filter((d) => d.source === "phone" || d.id === photoLetterId)) {
      await expect
        .poll(async () => ((await (await computer.get(`/api/documents/${doc.id}`)).json()) as { document: { status: string } }).document.status, { timeout: 60_000 })
        .not.toMatch(/^(queued|processing)$/);
      const gone = await computer.delete(`/api/documents/${doc.id}?purge=true`);
      expect(gone.ok(), `DELETE /api/documents/${doc.id} → ${gone.status()}`).toBe(true);
    }
  } finally {
    await computer.dispose();
  }
});

test("a phone pairs with the code Settings → Phone shows, and both screens show the same two words", async ({ page, browser }) => {
  test.setTimeout(90_000);
  let code!: { dialog: Locator; url: string; code: string };
  await test.step("the computer turns phone access on and shows a code", async () => {
    // the address made explicit: a server without the test address refuses it, so no test ever listens on a network
    const on = await apiSend<PhoneStatus>(page, "PUT", "/api/phone", { enabled: true, address: PHONE_ADDRESS, port: PHONE_PORT });
    expect(on.problem, `phone access couldn't start: ${on.problem?.detail}`).toBeNull();
    expect(on).toMatchObject({ available: true, enabled: true, listening: true, url: PHONE_BASE_URL, address: PHONE_ADDRESS, port: PHONE_PORT, devices: [] });

    await open(page, "/settings?section=phone", "Settings");
    const card = accessCard(page);
    await expect(card.getByRole("switch", { name: "Phone access" })).toHaveAttribute("aria-checked", "true");
    await expect(card).toContainText(`On · ${PHONE_BASE_URL}`);
    code = await showCode(page);
  });

  await test.step("the phone opens the link: the code is on the page, and the computer sees the phone reach it", async () => {
    phone = await openPhone(browser);
    await openPairing(phone.page, code.url);
    await expect(phone.page.getByText(shownCode(code.code)).first()).toBeVisible();
    await expect(code.dialog).toContainText("Your phone reached this computer");
    await expect(code.dialog).toContainText(`From ${PHONE_ADDRESS}`);
  });

  await test.step("it pairs: the phone and the computer show the same two words", async () => {
    await roomToPair(1);
    const paired = await pairAs(phone.page, PHONE_NAME);
    expect(paired.name).toBe(PHONE_NAME);
    // the computer's dialog asks every 2 s
    await expect(code.dialog).toContainText(`Paired: ${PHONE_NAME}`, { timeout: 5_000 });
    await expect(code.dialog).toContainText("Your phone should show");
    await expect(code.dialog).toContainText(paired.check_words);
    const row = await device(page, PHONE_NAME);
    expect(row, "the phone in GET /api/phone").toMatchObject({ check_words: paired.check_words, platform: "Android · Chrome", last_address: PHONE_ADDRESS });
    phoneId = row!.id;
    await code.dialog.getByRole("button", { name: "Done", exact: true }).click();
    await expect(code.dialog).toBeHidden();
    await expect(page.getByRole("region", { name: "Paired phones" })).toContainText(PHONE_NAME);
  });

  await test.step("on to Today, signed in with a sign-in of its own", async () => {
    await goOn(phone.page);
    const cookies = await phone.context.cookies();
    const signIn = cookies.find((c) => c.name === phoneCookie());
    expect(signIn, `the cookie ${phoneCookie()} (the phone has ${cookies.map((c) => c.name).join(", ") || "none"})`).toMatchObject({
      domain: PHONE_ADDRESS,
      path: "/",
      secure: true,
      httpOnly: true,
      sameSite: "Strict",
    });
    // 400 days, refreshed on every page load
    expect(signIn!.expires - Date.now() / 1000).toBeGreaterThan(399 * 86_400);
    expect(cookies.filter((c) => c.name.startsWith("ordnung_token_")).map((c) => c.name), "the computer's session cookie").toEqual([]);
  });
});

test("the paired phone opens every everyday page without a refusal", async () => {
  phone.watching = true;
  const { page } = phone;
  for (const [path, h1] of [
    ["/", undefined],
    ["/inbox", "Inbox"],
    ["/timeline", "Timeline"],
    ["/contracts", "Contracts"],
    ["/letters", "Letters"],
    ["/ask", "Ask about your letters"],
    ["/numbers", "My numbers"],
    ["/settings", PHONE_SETTINGS_HEADING],
  ] as const) {
    await open(page, path, h1);
  }
  // Settings on a phone asks for no setting (each would be refused): it says where they are
  await expect(page.getByRole("main")).toContainText("Settings, backups, phone access and deleting stay in Ordnung on your computer");
  // and offers the optional trust step (Chrome on Android keeps the authority to the computer's address): the
  // authority, which the listener gives a paired phone only
  await expect(page.getByRole("link", { name: "Download the certificate" })).toHaveAttribute("href", CERTIFICATE_PATH);
  const authority = await phone.context.request.get(CERTIFICATE_PATH);
  expect(authority.status()).toBe(200);
  expect(authority.headers()["content-type"]).toBe("application/x-x509-ca-cert");
  expect((await authority.body())[0], "a DER certificate (a SEQUENCE)").toBe(0x30);
  expect(phone.refused, "401/403 answers on the phone").toEqual([]);
});

test("two photos taken on the phone become one letter on the computer, “from your phone”", async ({ page }) => {
  test.setTimeout(150_000);
  const { page: mobile } = phone;
  const before = new Set((await apiGet<{ id: string }[]>(page, "/api/documents")).map((d) => d.id));

  await test.step("Add letters → Photograph a letter, twice → Add letter", async () => {
    await open(mobile, "/");
    await mobile.getByRole("banner").getByRole("button", { name: "Add letters" }).click();
    const chooser = mobile.getByRole("dialog", { name: "Add a letter" });
    const firstShot = mobile.waitForEvent("filechooser");
    await chooser.getByRole("button", { name: "Photograph a letter" }).click();
    const camera = await firstShot;
    // the phone's camera, not its files: the rear camera, photos only, one at a time
    expect(await camera.element().getAttribute("capture")).toBe("environment");
    expect(await camera.element().getAttribute("accept")).toBe("image/*");
    expect(camera.isMultiple()).toBe(false);
    await camera.setFiles(PHOTOS[0]!);

    const pages = mobile.getByRole("dialog", { name: "Pages of one letter" });
    await expect(pages).toBeVisible();
    const secondShot = mobile.waitForEvent("filechooser");
    await pages.getByRole("button", { name: "Take another page" }).click();
    await (await secondShot).setFiles(PHOTOS[1]!);
    await expect(pages).toContainText("2 pages");

    const sent = mobile.waitForResponse((res) => res.request().method() === "POST" && new URL(res.url()).pathname === "/api/documents");
    await pages.getByRole("button", { name: "Add letter" }).click();
    expect((await sent).status()).toBe(201);
    await expect(pages).toBeHidden();
  });

  await test.step("the computer has one new two-page letter from the phone, and its privacy log says so", async () => {
    let found: { id: string; pages: number; source: string; status: string }[] = [];
    await expect
      .poll(
        async () => {
          found = (await apiGet<{ id: string; pages: number; source: string; status: string }[]>(page, "/api/documents")).filter((d) => !before.has(d.id));
          return found.map((d) => `${d.source} · ${d.pages} pages`);
        },
        { message: "one new letter, combined from the two photos", timeout: 30_000 },
      )
      .toEqual(["phone · 2 pages"]);
    photoLetterId = found[0]!.id;
    const added = (await activityOf(page, phoneId)).find((a) => a.kind === "document.added");
    expect(added?.message, "the privacy log's entry for the added letter").toMatch(/from your phone$/);
  });

  await test.step("the phone opens it: no way to delete it or download the original there", async () => {
    // read in the background by the fake Claude; its to-dos are only added to once that is over
    await expect
      .poll(async () => (await apiGet<{ document: { status: string } }>(page, `/api/documents/${photoLetterId}`)).document.status, { timeout: 90_000 })
      .not.toMatch(/^(queued|processing)$/);
    await open(mobile, `/documents/${photoLetterId}`);
    const main = mobile.getByRole("main");
    await expect(main.getByRole("button", { name: /^Delete\b/ })).toHaveCount(0);
    await expect(main.locator(`a[href$="/documents/${photoLetterId}/file"]`)).toHaveCount(0);
    expect(phone.refused, "401/403 answers on the phone").toEqual([]);
  });
});

test("a to-do ticked off on the phone is done on the computer, and the privacy log names the phone", async ({ page }) => {
  const due = new Date(Date.now() + 3 * 86_400_000).toISOString().slice(0, 10);
  todoId = (await apiSend<{ id: string }>(page, "POST", "/api/items", { kind: "task", title: TODO_TITLE, due_date: due, doc_id: photoLetterId })).id;

  const { page: mobile } = phone;
  await open(mobile, `/documents/${photoLetterId}`);
  await mobile.getByRole("region", { name: /To-dos & dates/ }).getByRole("button", { name: `Mark “${TODO_TITLE}” as done` }).click();

  await expect.poll(async () => (await apiGet<{ status: string }>(page, `/api/items/${todoId}`)).status, { message: "the to-do on the computer" }).toBe("done");
  const changes = (await activityOf(page, phoneId)).filter((a) => a.kind === "phone.changed");
  expect(changes.map((a) => a.data), "phone.changed entries in the privacy log").toContainEqual(
    expect.objectContaining({ device: phoneId, operation: "PATCH /api/items/{item_id}", refs: { item_id: todoId } }),
  );
  expect(phone.refused, "401/403 answers on the phone").toEqual([]);
  phone.watching = false;
});

test("what stays on the computer is refused on the phone, and the computer's sign-in never works there", async ({ page, browser }) => {
  const { page: mobile } = phone;
  await open(mobile, "/");

  await test.step("the phone's own requests: settings, Delete everything, an original, the doctor", async () => {
    const ask = (path: string, init: RequestInit = {}) =>
      mobile.evaluate(
        async ([p, i]) => {
          const res = await fetch(p, i);
          return { status: res.status, body: (await res.json()) as unknown };
        },
        [path, init] as const,
      );
    const refused = { status: 403, body: { code: "computer_only", detail: COMPUTER_ONLY_MESSAGE } };
    expect(await ask("/api/settings")).toEqual(refused);
    // with everything a page of the app sends (Origin, Fetch-Metadata and the app's header come from the browser)
    expect(await ask("/api/data", { method: "DELETE", headers: { ...CLIENT, "Content-Type": "application/json" }, body: JSON.stringify({ confirm: "DELETE" }) })).toEqual(refused);
    expect(await ask(`/api/documents/${photoLetterId}/file`)).toEqual(refused);
    expect(await ask("/api/health?probe=1")).toEqual(refused);
    expect(await ask("/api/phone")).toEqual(refused);
    // nothing was deleted
    expect((await apiGet<{ id: string }[]>(page, "/api/documents")).map((d) => d.id)).toContain(photoLetterId);
  });

  await test.step("on the phone, My numbers show only their last characters", async () => {
    expect((await apiGet<{ masked: boolean }>(mobile, "/api/numbers")).masked).toBe(true);
    expect((await apiGet<{ masked: boolean }>(page, "/api/numbers")).masked).toBe(false);
  });

  await test.step("the session token: as a bearer, as the computer's cookie, in the link", async () => {
    const token = sessionToken();
    const notPaired = { code: "phone_not_paired", detail: PHONE_NOT_PAIRED_MESSAGE };

    const bearer = await openPhone(browser, { extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
    const health = await bearer.context.request.get("/api/health");
    expect(health.status()).toBe(401);
    expect(await health.json()).toEqual(notPaired);

    // cookies ignore ports: the computer's session cookie for 127.0.0.1 comes along, and means nothing here
    const cookie = await openPhone(browser, { storageState: REAL_STORAGE_STATE });
    const docs = await cookie.context.request.get("/api/documents");
    expect(docs.status()).toBe(401);
    expect(await docs.json()).toEqual(notPaired);

    const link = await openPhone(browser);
    await link.page.goto(`/?token=${token}`);
    await expect(link.page).toHaveURL(`${PHONE_BASE_URL}/pair`);
    await expect(link.page.getByRole("heading", { level: 1, name: PAIR_HEADING })).toBeVisible();
    expect(await link.context.cookies()).toEqual([]);

    // nor does a phone that isn't paired get the certificate authority: it is sent to pair first
    const authority = await link.context.request.get(CERTIFICATE_PATH, { maxRedirects: 0 });
    expect(authority.status()).toBe(303);
    expect(authority.headers()["location"]).toBe("/pair");
  });
});

test("wrong codes lock one phone out with one answer for every wrong code; a code used twice pairs nobody", async ({ page, browser }) => {
  test.setTimeout(180_000);
  const typed = await openPhone(browser);
  const tryCode = async (code: string) => {
    await typed.page.locator(CODE_FIELD).fill(code);
    return submitPairing(typed.page);
  };
  const wrong = { status: 422, body: { code: "wrong_code", detail: WRONG_CODE_MESSAGE } };

  await test.step("with no code open, a typed code gets the answer a wrong one gets", async () => {
    await openPairing(typed.page);
    await roomToPair(1);
    expect(await tryCode("K7QM2-XD9PA")).toEqual(wrong);
    await expect(alertSaying(typed.page, WRONG_CODE_MESSAGE)).toBeVisible();
  });

  await open(page, "/settings?section=phone", "Settings");
  let code = await showCode(page);

  await test.step(`${PAIRING_TRIES_PER_CLIENT} wrong codes from one phone lock it out of the code, even the right one`, async () => {
    await roomToPair(PAIRING_TRIES_PER_CLIENT + 1);
    for (let i = 1; i <= PAIRING_TRIES_PER_CLIENT; i++) {
      expect(await tryCode(wrongCode(code.code, i)), `wrong code ${i}`).toEqual(wrong);
      await expect(alertSaying(typed.page, WRONG_CODE_MESSAGE)).toBeVisible();
    }
    await expect(code.dialog).toContainText(`${PAIRING_TRIES_PER_CLIENT} wrong codes typed so far, from ${PHONE_ADDRESS}`);
    const status = await phoneStatus(page);
    expect(status.pairing).toMatchObject({ wrong_tries: PAIRING_TRIES_PER_CLIENT, wrong_from: [PHONE_ADDRESS] });

    expect(await tryCode(code.code)).toEqual({ status: 429, body: { code: "too_many", detail: TOO_MANY_TRIES_MESSAGE } });
    await expect(alertSaying(typed.page, TOO_MANY_TRIES_MESSAGE)).toBeVisible();
    expect((await phoneStatus(page)).devices.map((d) => d.name)).toEqual([PHONE_NAME]);
  });

  let spare!: Phone;
  let spareWords = "";
  await test.step("a new code: a second phone types it and pairs", async () => {
    await code.dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(code.dialog).toBeHidden();
    code = await showCode(page);

    spare = await openPhone(browser);
    await openPairing(spare.page);
    // typed as a person might: lower case, with a dash
    await spare.page.locator(CODE_FIELD).fill(`${code.code.slice(0, 5)}-${code.code.slice(5)}`.toLowerCase());
    await roomToPair(1);
    spareWords = (await pairAs(spare.page, SPARE_NAME)).check_words;
    await expect(code.dialog).toContainText(`Paired: ${SPARE_NAME}`, { timeout: 5_000 });
    await expect(code.dialog).toContainText(spareWords);
    await goOn(spare.page);
  });

  await test.step("a third device sends the same code: neither stays paired, and the computer says why", async () => {
    const spareId = (await device(page, SPARE_NAME))!.id;
    const third = await openPhone(browser);
    await openPairing(third.page, code.url);
    await third.page.getByLabel(NAME_FIELD).fill("iPhone");
    await roomToPair(1);
    expect(await submitPairing(third.page)).toEqual({ status: 409, body: { code: "code_used", detail: CODE_USED_MESSAGE } });
    await expect(alertSaying(third.page, CODE_USED_MESSAGE)).toBeVisible();
    expect(await third.context.cookies()).toEqual([]);

    const detail = noticeDetail("code_reused", []);
    await expect(code.dialog).toContainText(detail, { timeout: 5_000 });
    const status = await phoneStatus(page);
    expect(status.notice).toMatchObject({ code: "code_reused", detail });
    expect(status.devices.map((d) => d.name), "the phone that used the code first is removed too").toEqual([PHONE_NAME]);
    expect((await activityOf(page, spareId)).map((a) => [a.kind, a.data.by])).toContainEqual(["phone.removed", "code_reused"]);

    // the spare phone is signed out at once, and told why; the first phone, paired with another code, is not
    await expectRemoved(spare, "code_reused");
    await open(phone.page, "/inbox", "Inbox");

    await code.dialog.getByRole("button", { name: "Done", exact: true }).click();
    await expect(code.dialog).toBeHidden();
    // Settings → Phone says so too, in the danger tone, until it is dismissed
    const notice = page
      .getByRole("main")
      .getByRole("alert")
      .filter({ hasText: detail })
      .filter({ has: page.getByRole("button", { name: "Dismiss" }) });
    await expect(notice).toBeVisible();
    await notice.getByRole("button", { name: "Dismiss" }).click();
    await expect(notice).toBeHidden();
  });
});

test("the pairing page and the phone's Today have no serious or critical axe violations", async ({ browser }, testInfo) => {
  const fresh = await openPhone(browser);
  await openPairing(fresh.page);
  await expectAccessible(fresh.page, testInfo, "pair-phone");

  await open(phone.page, "/");
  expect(phone.page.viewportSize()?.width).toBe(412);
  await expectAccessible(phone.page, testInfo, "today-on-a-phone");
});

test("a phone removed on the computer is signed out at once", async ({ page }) => {
  await open(page, "/settings?section=phone", "Settings");
  const list = page.getByRole("region", { name: "Paired phones" });
  await list.getByRole("button", { name: `Remove ${PHONE_NAME}…` }).click();
  const confirm = page.getByRole("dialog", { name: `Remove ${PHONE_NAME}?` });
  // what it changed lately: the letter it added, the to-do it ticked off
  await expect(confirm).toContainText(/[1-9]\d* changes? from this phone in the last 30 days/);
  await confirm.getByRole("button", { name: "Remove", exact: true }).click();
  await expect(confirm).toBeHidden();
  await expect(list).not.toContainText(PHONE_NAME);
  expect((await activityOf(page, phoneId)).map((a) => [a.kind, a.data.by])).toContainEqual(["phone.removed", "computer"]);

  await expectRemoved(phone);
});

test("turned off on the computer, phone access stops listening", async ({ page }) => {
  await open(page, "/settings?section=phone", "Settings");
  const card = accessCard(page);
  const toggle = card.getByRole("switch", { name: "Phone access" });
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  // the line under the switch: off, and no phone paired any more
  await expect(card.getByText("Off", { exact: true })).toBeVisible();
  expect(await phoneStatus(page)).toMatchObject({ enabled: false, listening: false });

  await expect(phone.page.goto("/")).rejects.toThrow(/ERR_CONNECTION_REFUSED/);
});
