/**
 * Shared steps for the e2e suite: talking to the demo API with the page's session, finding demo letters
 * by their sample's file name and demo contracts by their category, the New-mail tray, waiting for a page to
 * settle, the raw-enum guard and the axe scan.
 */
import AxeBuilder from "@axe-core/playwright";
import { test as base, expect, type Locator, type Page, type TestInfo } from "@playwright/test";
import type { Contract, ContractCategory } from "@/api/types";
import { assertNoRawEnums } from "@/lib/copy";

/** `test` that also fails when the app throws an uncaught error in the browser. */
export const test = base.extend<{ pageErrors: void }>({
  pageErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("pageerror", (err) => errors.push(err.stack ?? err.message));
      await use();
      expect(errors, "uncaught errors in the page").toEqual([]);
    },
    { auto: true },
  ],
});
export { expect };

// ------------------------------------------------------------------------------------------------
// API (same cookie as the page; non-GET requests need the app's CSRF header)
// ------------------------------------------------------------------------------------------------

const CLIENT = { "X-Ordnung-Client": "web" };

export async function apiGet<T>(page: Page, path: string): Promise<T> {
  const res = await page.request.get(path);
  expect(res.ok(), `GET ${path} → ${res.status()}`).toBe(true);
  return (await res.json()) as T;
}

export async function apiPatch<T>(page: Page, path: string, data: unknown): Promise<T> {
  const res = await page.request.patch(path, { data, headers: CLIENT });
  expect(res.ok(), `PATCH ${path} → ${res.status()}`).toBe(true);
  return (await res.json()) as T;
}

export interface TourState {
  active: boolean;
  step: number;
  completed: boolean;
}

/** Put the demo tour at a step (0-based), or hide it (`null`), before the page loads it. */
export function setTour(page: Page, step: number | null): Promise<TourState> {
  return apiPatch<TourState>(page, "/api/demo/tour", step === null ? { active: false, completed: true } : { active: true, step, completed: false });
}

// ------------------------------------------------------------------------------------------------
// Demo letters: found by their sample's file name, never by the title the model wrote
// ------------------------------------------------------------------------------------------------

/** A letter as `GET /api/documents` lists it. */
export interface Letter {
  id: string;
  filename: string;
  title: string | null;
}

/** A to-do of a letter, as `GET /api/documents/{id}` lists it. */
export interface LetterItem {
  id: string;
  kind: string;
  title: string;
  status: string;
  due_date: string | null;
}

/**
 * The demo letter read from the sample `file` ("08_rechnung_techmarkt.pdf"). A sample's file name never
 * changes; its title is the model's and changes with every re-recording of the demo, so a test finds its
 * letter by the file and reads the title from the API when it needs it (the database is prebuilt: ids may
 * change too).
 */
export async function letter(page: Page, file: string): Promise<Letter> {
  const docs = await apiGet<Letter[]>(page, "/api/documents");
  const doc = docs.find((d) => d.filename === file);
  expect(doc, `no demo letter from the sample ${file} (the Inbox has ${docs.map((d) => d.filename).join(", ")})`).toBeTruthy();
  return doc!;
}

/** Id of the demo letter read from the sample `file` ({@link letter}). */
export async function letterId(page: Page, file: string): Promise<string> {
  return (await letter(page, file)).id;
}

/** A letter's title and to-dos, from its own page's API (`id`: {@link letterId}, or a New-mail letter's {@link openMail}). */
export async function letterDetail(page: Page, id: string): Promise<{ title: string; items: LetterItem[] }> {
  const { document, items } = await apiGet<{ document: Letter; items: LetterItem[] }>(page, `/api/documents/${id}`);
  expect(document.title, `the letter ${document.filename} has a title`).toBeTruthy();
  return { title: document.title!, items };
}

/** The one to-do of `kind` on the letter `id` (fails naming the letter's to-dos when there is none). */
export async function letterItem(page: Page, id: string, kind: string): Promise<LetterItem> {
  const { title, items } = await letterDetail(page, id);
  const found = items.filter((i) => i.kind === kind);
  expect(found.length, `one ${kind} to-do on “${title}” (it has ${items.map((i) => `${i.kind} “${i.title}”`).join(", ") || "none"})`).toBe(1);
  return found[0]!;
}

// ------------------------------------------------------------------------------------------------
// Demo contracts: found by what they are, never by the name the model gave them
// ------------------------------------------------------------------------------------------------

/**
 * The one demo contract of `category` ("mobile", "insurance"…), as `GET /api/contracts` lists it. A contract's
 * name is the model's and changes with a re-recording ("Stromliefervertrag" became "MusterStrom Flex" with
 * prompt 11), so a test finds its contract by what it is and builds the text it expects from `name`
 * ({@link shownAs}). Fails, naming the demo's contracts, unless exactly one contract is of that category —
 * never another contract in its place.
 */
export async function contractOf(page: Page, category: ContractCategory): Promise<Contract> {
  const all = await apiGet<Contract[]>(page, "/api/contracts");
  const found = all.filter((c) => c.category === category);
  expect(found.map((c) => c.name), `one ${category} contract in the demo (it has ${all.map((c) => `${c.category} “${c.name}”`).join(", ")})`).toHaveLength(1);
  return found[0]!;
}

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");

/**
 * `text` (a title from the API) as the app shows it, as a pattern: on screen amounts, dates and references
 * are glued with no-break spaces and hyphens, and long German words carry soft hyphens (display only), so
 * the page's text isn't the API's character for character. `whole`: the text and nothing else.
 */
export function shownAs(text: string, { whole = false }: { whole?: boolean } = {}): RegExp {
  const body = [...text.trim()]
    .map((ch) => (/\s/.test(ch) ? "[\\s\\u00a0\\u202f]+" : ch === "-" ? "[-\\u2011]" : escapeRegExp(ch)))
    .join("\\u00ad?");
  return new RegExp(whole ? `^${body}$` : body);
}

// ------------------------------------------------------------------------------------------------
// Pages
// ------------------------------------------------------------------------------------------------

/**
 * Wait until no (finite) animation is running for a few frames. With reduced motion the app still
 * fades content in (opacity only); a scan in the middle of a fade would measure washed-out text.
 */
export async function settle(page: Page): Promise<void> {
  await page.waitForFunction(
    () => {
      const w = window as unknown as { __e2eCalmFrames?: number };
      const busy = document.getAnimations().some((a) => a.playState === "running" && a.effect?.getTiming().iterations !== Infinity);
      w.__e2eCalmFrames = busy ? 0 : (w.__e2eCalmFrames ?? 0) + 1;
      return w.__e2eCalmFrames >= 3;
    },
    undefined,
    { polling: "raf" },
  );
}

/**
 * Navigate and wait until the page has its data and is still: network idle, its `<h1>` visible
 * (`heading`, when given), no fades — and not the app's "Something went wrong" screen.
 */
export async function open(page: Page, path: string, heading?: string | RegExp): Promise<void> {
  await page.goto(path);
  await page.waitForLoadState("networkidle");
  const h1 = page.getByRole("main").getByRole("heading", { level: 1 }).first();
  await expect(h1).toBeVisible();
  await expect(h1, `${path} crashed`).not.toHaveText("Something went wrong on this page");
  if (heading) await expect(h1).toHaveText(heading);
  await settle(page);
}

interface MailTrayItem {
  id: string;
  sender: string;
  opened: boolean;
  doc_id: string | null;
}

/** The New-mail envelope of a sender on the Inbox. */
export function envelope(page: Page, sender: string): Locator {
  return page
    .getByRole("region", { name: /^New mail/ })
    .getByRole("listitem")
    .filter({ hasText: sender })
    .first();
}

/**
 * The letter a New-mail letter became once it was opened (a tray letter is no letter until then): found by
 * its tray sender, as the tray names it — never by the title the model gave it.
 */
export async function mailLetterId(page: Page, sender: string): Promise<string> {
  const tray = await apiGet<MailTrayItem[]>(page, "/api/demo/mail");
  const item = tray.find((t) => t.sender.startsWith(sender));
  expect(item, `a New-mail letter from ${sender}`).toBeTruthy();
  expect(item!.doc_id, `the New-mail letter from ${sender} was opened`).toBeTruthy();
  return item!.doc_id!;
}

/**
 * Open a New-mail letter and wait for the viewer: `id` is the letter it became. The demo tray is shared by
 * all tests of a run: when the letter was already opened (a retry), go straight to its document.
 */
export async function openMail(page: Page, sender: string): Promise<{ fresh: boolean; id: string }> {
  const tray = await apiGet<MailTrayItem[]>(page, "/api/demo/mail");
  const item = tray.find((t) => t.sender.startsWith(sender));
  expect(item, `a New-mail letter from ${sender}`).toBeTruthy();
  if (item!.opened && item!.doc_id) {
    await open(page, `/documents/${item!.doc_id}`);
    return { fresh: false, id: item!.doc_id };
  }
  await open(page, "/inbox");
  await envelope(page, sender).getByRole("button", { name: "Let Ordnung read it" }).click();
  // one letter read from the tray → the Inbox opens it once the stepper is done
  await page.waitForURL(/\/documents\/doc_/, { timeout: 30_000 });
  await page.waitForLoadState("networkidle");
  return { fresh: true, id: await mailLetterId(page, sender) };
}

// ------------------------------------------------------------------------------------------------
// Raw enum values (SPEC §14 copy table) — reuses the app's own guard from `src/lib/copy.ts`
// ------------------------------------------------------------------------------------------------

/** Fail when the visible text of the page shows a raw enum value ("needs_review", a bare "deadline" badge…). */
export async function expectNoRawEnums(page: Page, where: string): Promise<void> {
  const { text, leaves } = await page.evaluate(() => {
    const visible = (el: Element) => (el as HTMLElement).checkVisibility?.({ checkOpacity: true, checkVisibilityCSS: true }) ?? true;
    const leaves: string[] = [];
    for (const el of Array.from(document.body.querySelectorAll("*"))) {
      if (el.children.length || el.closest("script,style,noscript,textarea,[contenteditable]")) continue;
      const t = (el.textContent ?? "").trim();
      if (t && visible(el)) leaves.push(t);
    }
    return { text: document.body.innerText, leaves };
  });
  expect(() => assertNoRawEnums(text), `${where}: page text`).not.toThrow();
  for (const leaf of leaves) expect(() => assertNoRawEnums(leaf, { exactWord: true }), `${where}: "${leaf}"`).not.toThrow();
}

// ------------------------------------------------------------------------------------------------
// Accessibility
// ------------------------------------------------------------------------------------------------

const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];

/**
 * The evidence highlights drawn over a letter's page image are as tall as the printed line they
 * mark, so they can't be 24 px apart. WCAG 2.5.8's "equivalent" exception applies: every highlight
 * has a full-size "show … on the page" button next to its fact. Only this rule and these targets.
 */
function isExempt(ruleId: string, target: string): boolean {
  return ruleId === "target-size" && target.startsWith("button[data-highlight=");
}

/**
 * axe-core scan of the whole page (WCAG 2.2 A/AA + best practices): no serious or critical
 * violations. Minor/moderate findings are attached to the report (not failures).
 */
export async function expectAccessible(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  await settle(page);
  const results = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
  const violations = results.violations
    .map((v) => ({ ...v, nodes: v.nodes.filter((n) => !isExempt(v.id, n.target.join(" "))) }))
    .filter((v) => v.nodes.length);
  const blocking = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  const minor = violations.filter((v) => !blocking.includes(v));
  if (minor.length) {
    await testInfo.attach(`axe-minor-${name}.json`, {
      body: JSON.stringify(minor.map((v) => ({ id: v.id, impact: v.impact, help: v.help, targets: v.nodes.map((n) => n.target.join(" ")) })), null, 2),
      contentType: "application/json",
    });
  }
  const summary = blocking.map(
    (v) => `${v.id} (${v.impact}): ${v.help}\n${v.nodes.map((n) => `    ${n.target.join(" ")} — ${n.failureSummary?.split("\n").slice(1).join(" ").trim()}`).join("\n")}`,
  );
  expect(summary, `${name}: serious/critical axe violations`).toEqual([]);
}
