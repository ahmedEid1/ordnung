/**
 * Shared steps for the e2e suite: talking to the demo API with the page's session, the New-mail
 * tray, waiting for a page to settle, the raw-enum guard and the axe scan.
 */
import AxeBuilder from "@axe-core/playwright";
import { test as base, expect, type Locator, type Page, type TestInfo } from "@playwright/test";
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

interface DocumentSummary {
  id: string;
  title: string | null;
}

/** Id of the first letter whose title matches (the demo database is prebuilt, ids may change). */
export async function documentId(page: Page, title: RegExp): Promise<string> {
  const docs = await apiGet<DocumentSummary[]>(page, "/api/documents");
  const doc = docs.find((d) => d.title && title.test(d.title));
  expect(doc, `a letter titled ${title}`).toBeTruthy();
  return doc!.id;
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
 * Open a New-mail letter and wait for the viewer. The demo tray is shared by all tests of a run:
 * when the letter was already opened (a retry), go straight to its document.
 */
export async function openMail(page: Page, sender: string): Promise<{ fresh: boolean }> {
  const tray = await apiGet<MailTrayItem[]>(page, "/api/demo/mail");
  const item = tray.find((t) => t.sender.startsWith(sender));
  expect(item, `a New-mail letter from ${sender}`).toBeTruthy();
  if (item!.opened && item!.doc_id) {
    await open(page, `/documents/${item!.doc_id}`);
    return { fresh: false };
  }
  await open(page, "/inbox");
  await envelope(page, sender).getByRole("button", { name: "Let Ordnung read it" }).click();
  // one letter read from the tray → the Inbox opens it once the stepper is done
  await page.waitForURL(/\/documents\/doc_/, { timeout: 30_000 });
  await page.waitForLoadState("networkidle");
  return { fresh: true };
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
