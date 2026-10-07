/**
 * The layout sweep: every main page and the key states — every demo letter, a drafted letter and the
 * composer, the main dialogs, drawers and popovers, Ask with a replayed answer, every Settings section,
 * My numbers, This week, Waiting for, a letter's "How it was read" tab and the 404 page — at 320, 390,
 * 768, 1280 and 1920 px, in light and dark mode.
 *
 * Each state is opened once per device — a phone (touch) for 320 and 390 px, a desktop for 768, 1280 and
 * 1920 px — then the window is resized and the theme switched in place, and a few states run side by
 * side. At every width and in both themes a state fails on:
 *
 * - a page that scrolls sideways (WCAG 1.4.10 reflow), or an element past the left or right edge of the
 *   screen outside a scroll container;
 * - an interactive element smaller than 24 × 24 px (WCAG 2.5.8). Excepted: links in running text (a
 *   citation marker after its words, too — a person's or organisation's marker is a button, and one right
 *   after another marker follows its words as well; only a marker ("Source n: …"), on the line its words end
 *   on: a marker alone in a list item or on a line of its own, and any other small text button, are not
 *   excepted), and the evidence highlights on a letter's page image (each has a full-size "show … on the page" button next to
 *   its fact); a stretched link counts as its whole row;
 * - an interactive element whose centre is covered: by the sticky top bar or the phone's tab bar where
 *   the page can't be scrolled out from under them, or by anything else on the page;
 * - text cut off by its box — unless it is cut on purpose (an ellipsis or a line clamp in its classes) and
 *   the whole value is at hand: in its `title` or accessible name, or behind the "Read more" that controls
 *   it (`aria-expanded` + `aria-controls`);
 * - a control cut off by a box that clips it (not one that scrolls), an icon drawn at zero size, a screen
 *   without exactly one `<h1>` and one `<main>` (a modal dialog is its own screen);
 * - an axe-core WCAG 2.2 A/AA violation (any impact), at 390 and 1280 px in both themes;
 * - an uncaught error in the page.
 *
 * The probes are the UI audit's (`scripts/ui-audit/probes.mjs`, `make ui-audit`). A failure names the
 * state, width, theme, element (a short CSS path and its text) and where it is on the page; a screenshot
 * of the first failing view of each state is attached to the report.
 *
 * It changes nothing in the shared demo (it asks one recorded question; when no letter has been drafted
 * yet it drafts the phone contract's cancellation), and runs in its own project right after `pages`.
 * `ORDNUNG_SWEEP_JOBS` sets how many states run side by side (default 3).
 */
import type { Browser, Page, TestInfo } from "@playwright/test";
import { axeFindings, layoutFindings, type Finding } from "../scripts/ui-audit/probes.mjs";
import { BASE_URL, STORAGE_STATE } from "./env";
import { apiGet, expect, open, settle, test } from "./helpers";

type Theme = "light" | "dark";
type Device = "phone" | "desktop";

const DEVICES: Record<Device, { sizes: [width: number, height: number][]; touch: boolean }> = {
  phone: {
    sizes: [
      [320, 640],
      [390, 844],
    ],
    touch: true,
  },
  desktop: {
    sizes: [
      [768, 1024],
      [1280, 800],
      [1920, 1080],
    ],
    touch: false,
  },
};
const AXE_WIDTHS = new Set([390, 1280]);
const JOBS = Math.max(1, Number(process.env.ORDNUNG_SWEEP_JOBS ?? 3) || 3);
const CLIENT = { "X-Ordnung-Client": "web" };

interface Demo {
  docs: { id: string; filename: string; title: string | null }[];
  draftId: string;
  parties: { id: string; name: string }[];
  contracts: { id: string; name: string; category: string }[];
}

interface SweepState {
  name: string;
  /** Open the state: navigate, click… (the window has the device's first size, light theme). */
  enter: (page: Page, demo: Demo) => Promise<void>;
  /**
   * Is the state still there after a resize? A popover placed for a laptop may close when the window
   * turns into a tablet; then the state is opened again at the new size.
   */
  present?: (page: Page) => Promise<boolean>;
}

const main = (page: Page) => page.getByRole("main");
const dialogShown = (page: Page) => page.getByRole("dialog").first().isVisible();

// ------------------------------------------------------------------------------------------------
// Which findings fail
// ------------------------------------------------------------------------------------------------

/** Why this finding fails the sweep, or null when it doesn't. */
function failure(f: Finding): string | null {
  switch (f.probe) {
    case "page-overflow":
      return `the page scrolls sideways (${f.text})`;
    case "offscreen":
      return `past the edge of the screen by ${f.detail.by} px`;
    case "target-size":
      return f.kind === "exempt" ? null : `target of ${f.detail.width} × ${f.detail.height} px (under 24 × 24)`;
    case "covered":
      return `its centre is covered by ${f.detail.by} "${f.detail.byText ?? ""}" (${f.detail.at})`;
    case "clipped-text":
      return `text cut off (${f.detail.how}, ${f.detail.hiddenPx} px hidden)`;
    case "clipped-content":
      return `control cut off by ${f.detail.container} (${f.detail.axis}; ${Math.round(Number(f.detail.visibleShare) * 100)} % of it shows)`;
    case "structure":
      return f.text;
    case "empty-icon":
      return "icon drawn at zero size";
    case "truncated":
      // the probe says where the whole text is: its title or accessible name, or the "Read more" that opens it
      return f.detail.fullValueAt ? null : `text cut short (${f.detail.how}) and its whole value is nowhere at hand (no title, accessible name or "Read more")`;
    case "axe":
      // the evidence highlights on a page image (see `target-size` above; helpers.ts exempts them the same way)
      if (f.kind === "target-size" && /^<button[^>]* data-highlight=/.test(f.text)) return null;
      return `axe ${f.kind} (${f.detail.impact}): ${f.detail.help} — ${f.detail.summary}`;
    case "probe-error":
      return f.text;
    default:
      return null;
  }
}

const where = (f: Finding) => (f.rect ? ` at x ${f.rect.x}, y ${f.rect.y} (${f.rect.w} × ${f.rect.h} px)` : "");

// ------------------------------------------------------------------------------------------------
// Sweeping a state
// ------------------------------------------------------------------------------------------------

/**
 * Switch the theme the way the app follows the system's (no theme chosen in Settings). Colour transitions
 * are switched off for the moment of the switch, so the probes don't measure colours half-way.
 */
async function setTheme(page: Page, theme: Theme): Promise<void> {
  await page.evaluate(() => {
    const style = document.createElement("style");
    style.id = "__sweep_theme";
    style.textContent = "*,*::before,*::after{transition:none!important}";
    document.head.appendChild(style);
  });
  await page.emulateMedia({ colorScheme: theme });
  await expect(page.locator("html")).toHaveClass(theme === "dark" ? /\bdark\b/ : /^(?![\s\S]*\bdark\b)/);
  await page.evaluate(() => {
    // a style read makes the new colours final before transitions come back
    void getComputedStyle(document.body).color;
    document.getElementById("__sweep_theme")?.remove();
  });
  await settle(page);
}

/** A step that didn't finish in time (see `within`). */
class Stuck extends Error {}

/**
 * `promise`, or an error naming the step once it has taken `seconds`: a page that gets stuck fails its own
 * state, readably, instead of holding up the whole test until its timeout.
 */
function within<T>(seconds: number, step: string, promise: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Stuck(`${step} took longer than ${seconds} s`)), seconds * 1000);
  });
  return Promise.race([promise, late]).finally(() => clearTimeout(timer));
}

/**
 * Open `state` on `device` and check it at each of the device's sizes in both themes: the failures, one line
 * each, and whether it got stuck (a step ran out of time: `within`, or one of Playwright's own time limits).
 */
async function sweep(browser: Browser, device: Device, state: SweepState, demo: Demo, testInfo: TestInfo): Promise<{ problems: string[]; stuck: boolean }> {
  const [width0, height0] = DEVICES[device].sizes[0]!;
  // the project's `use` (playwright.config.ts), with this device's size
  const context = await browser.newContext({
    baseURL: BASE_URL,
    storageState: STORAGE_STATE,
    viewport: { width: width0, height: height0 },
    isMobile: DEVICES[device].touch,
    hasTouch: DEVICES[device].touch,
    colorScheme: "light",
    reducedMotion: "reduce",
    locale: "en-GB",
    timezoneId: "Europe/Berlin",
  });
  const page = await context.newPage();
  // (the runner's own defaults are "no limit"; `within` limits the in-page probes, which have none either)
  page.setDefaultTimeout(30_000);
  const problems: string[] = [];
  page.on("pageerror", (err) => problems.push(`${state.name} (${device}): uncaught error in the page: ${err.message}`));
  let shot = false;
  let stuck = false;
  let at = "opening it";
  try {
    await within(90, "opening the state", state.enter(page, demo));
    let themes: Theme[] = ["light", "dark"];
    for (const [i, [width, height]] of DEVICES[device].sizes.entries()) {
      at = `${width} px`;
      if (i > 0) {
        await page.setViewportSize({ width, height });
        await within(30, "settling after the resize", settle(page));
        if (state.present && !(await state.present(page))) {
          await within(30, "switching to light", setTheme(page, "light"));
          themes = ["light", "dark"];
          await within(90, "opening the state again", state.enter(page, demo));
        }
      }
      for (const theme of themes) {
        await within(30, `switching to ${theme}`, setTheme(page, theme));
        const { findings } = await within(60, `the layout probes (${theme})`, layoutFindings(page));
        if (AXE_WIDTHS.has(width)) findings.push(...(await within(90, `axe (${theme})`, axeFindings(page))));
        const view = `${state.name} @ ${width} px ${theme}`;
        const failed = findings.flatMap((f) => {
          const why = failure(f);
          return why ? [`${view}: ${why} — ${f.selector} "${f.text}"${where(f)}`] : [];
        });
        if (failed.length && !shot) {
          shot = true;
          await testInfo.attach(`${view}.png`, { body: await page.screenshot(), contentType: "image/png" });
        }
        problems.push(...failed);
      }
      // the next width starts in the theme this one ended with
      themes = [...themes].reverse();
    }
  } catch (err) {
    // (Playwright's message without its colours, on one line)
    const message = String((err as Error).message ?? err)
      .replace(new RegExp(`${String.fromCharCode(27)}\\[[0-9;]*m`, "g"), "")
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .slice(0, 4)
      .join(" · ");
    stuck = err instanceof Stuck || /Timeout \d+ms exceeded/.test(message);
    problems.push(`${state.name} (${device}, ${at}): ${message}`);
  } finally {
    await within(30, "closing the page", context.close()).catch(() => {});
  }
  return { problems, stuck };
}

/**
 * Sweep every state on both devices, `JOBS` at a time (a state that got stuck is tried once more); every
 * failure of every state, then one assertion.
 */
async function sweepAll(browser: Browser, states: SweepState[], testInfo: TestInfo): Promise<void> {
  const jobs = states.flatMap((state) => (["phone", "desktop"] as const).map((device) => ({ state, device })));
  const problems: string[][] = jobs.map(() => []);
  let next = 0;
  await Promise.all(
    Array.from({ length: Math.min(JOBS, jobs.length) }, async () => {
      while (next < jobs.length) {
        const i = next++;
        const { state, device } = jobs[i]!;
        let run = await sweep(browser, device, state, demo, testInfo);
        if (run.stuck) {
          // once more from the start: a page that got stuck once (a busy machine) isn't a layout fault; the
          // report says it happened
          testInfo.annotations.push({ type: "sweep: tried again", description: run.problems.at(-1) });
          run = await sweep(browser, device, state, demo, testInfo);
        }
        problems[i] = run.problems;
      }
    }),
  );
  expect(problems.flat(), "layout and accessibility problems (state @ width theme: what — element — where)").toEqual([]);
}

// ------------------------------------------------------------------------------------------------
// The states
// ------------------------------------------------------------------------------------------------

let demo: Demo;

test.beforeAll(async ({ browser }) => {
  const context = await browser.newContext({ baseURL: BASE_URL, storageState: STORAGE_STATE });
  const page = await context.newPage();
  // the tour card floats over every page; the sweep is about the pages
  const tour = await page.request.patch("/api/demo/tour", { data: { active: false, completed: true }, headers: CLIENT });
  expect(tour.ok(), `PATCH /api/demo/tour → ${tour.status()}`).toBe(true);
  const contracts = await apiGet<Demo["contracts"]>(page, "/api/contracts");
  // the letter pages.spec.ts drafts (the phone contract's cancellation); drafted here when the sweep runs alone
  let drafts = await apiGet<{ id: string }[]>(page, "/api/drafts");
  if (!drafts.length) {
    const res = await page.request.post("/api/drafts", { data: { kind: "cancellation", contract_id: phoneContract(contracts).id }, headers: CLIENT });
    expect(res.ok(), `POST /api/drafts → ${res.status()}`).toBe(true);
    drafts = [(await res.json()) as { id: string }];
  }
  demo = { docs: await apiGet(page, "/api/documents"), draftId: drafts[0]!.id, parties: await apiGet(page, "/api/parties"), contracts };
  await context.close();
});

/** The demo letter read from the sample `file`: never found by its title, which the model writes anew with each recording. */
function letter(demo: Demo, file: string): Demo["docs"][number] {
  const doc = demo.docs.find((d) => d.filename === file);
  if (!doc) throw new Error(`no demo letter from the sample ${file} (the Inbox has ${demo.docs.map((d) => d.filename).join(", ")})`);
  return doc;
}
/**
 * The demo's phone contract: by what it is, never by the name the model gave it (a re-recording renames it),
 * and never another contract in its place.
 */
function phoneContract(contracts: Demo["contracts"]): Demo["contracts"][number] {
  const phone = contracts.filter((c) => c.category === "mobile");
  if (phone.length !== 1) throw new Error(`one mobile contract in the demo (it has ${contracts.map((c) => `${c.category} “${c.name}”`).join(", ")})`);
  return phone[0]!;
}

const MAIN_PAGES: SweepState[] = [
  { name: "Today", enter: (page) => open(page, "/", /Sam/) },
  { name: "Inbox", enter: (page) => open(page, "/inbox", "Inbox") },
  { name: "Timeline", enter: (page) => open(page, "/timeline", "Timeline") },
  { name: "Contracts", enter: (page) => open(page, "/contracts", "Contracts") },
  { name: "Letters", enter: (page) => open(page, "/letters", "Letters") },
  { name: "Waiting for", enter: (page) => open(page, "/letters/waiting") },
  { name: "My numbers", enter: (page) => open(page, "/numbers", "My numbers") },
  { name: "My numbers · Open cases", enter: (page) => open(page, "/numbers?tab=cases", "My numbers") },
  { name: "My numbers · Organisations", enter: (page) => open(page, "/numbers?tab=organisations", "My numbers") },
  { name: "This week", enter: (page) => open(page, "/week", "Weekly review") },
  { name: "This week · Pay", enter: (page) => open(page, "/week?step=pay", "Weekly review") },
  { name: "This week · Decide", enter: (page) => open(page, "/week?step=decide", "Weekly review") },
  { name: "404", enter: (page) => open(page, "/this-page-does-not-exist") },
];

const SETTINGS: SweepState[] = ["profile", "region", "reminders", "calendar", "folder", "phone", "ai", "claude", "privacy", "rules", "data"].map((section) => ({
  name: `Settings · ${section}`,
  enter: (page) => open(page, `/settings?section=${section}`, "Settings"),
}));

const ASK_LETTERS_TRACE: SweepState[] = [
  {
    name: "Ask with a replayed answer",
    enter: async (page) => {
      await open(page, "/ask");
      const box = page.getByRole("textbox").first();
      await box.fill("What do I have to pay in the next four weeks?");
      await box.press("Enter");
      await expect(main(page).getByRole("status")).toHaveText("Answer ready.", { timeout: 20_000 });
      await page.evaluate(() => window.scrollTo(0, 0));
      await settle(page);
    },
  },
  {
    name: "How it was read",
    enter: async (page, demo) => {
      await open(page, `/documents/${letter(demo, "15_mahnung_techmarkt.pdf").id}?view=trace`);
      await expect(page.getByRole("list", { name: "Steps of this reading" })).toBeVisible();
      await settle(page);
    },
  },
  {
    name: "Drafted letter",
    enter: async (page, demo) => {
      await open(page, `/letters/${demo.draftId}`);
      await expect(page.getByRole("region", { name: "Checks" })).toBeVisible();
      await settle(page);
    },
  },
  {
    name: "Composer · new letter",
    enter: async (page) => {
      await open(page, "/letters?new=1");
      await expect(page.getByRole("dialog", { name: "New letter" })).toBeVisible();
      await settle(page);
    },
    present: dialogShown,
  },
  {
    name: "Composer · cancelling the phone contract",
    enter: async (page, demo) => {
      await open(page, `/letters?kind=cancellation&contract=${phoneContract(demo.contracts).id}`);
      await expect(page.getByRole("dialog", { name: "New letter" }).getByRole("button", { name: /Write the letter/ })).toBeVisible();
      await settle(page);
    },
    present: dialogShown,
  },
];

const OVERLAYS: SweepState[] = [
  {
    name: "Mark as sent dialog",
    enter: async (page, demo) => {
      await open(page, `/letters/${demo.draftId}`);
      await main(page).getByRole("button", { name: "Mark as sent" }).click();
      await expect(page.getByRole("dialog")).toBeVisible();
      await settle(page);
    },
    present: dialogShown,
  },
  {
    name: "People & organisations drawer",
    enter: async (page, demo) => {
      const party = [...demo.parties].sort((a, b) => b.name.length - a.name.length)[0]!;
      await page.goto(`/?party=${party.id}`);
      await expect(page.getByRole("dialog", { name: party.name }).getByRole("heading", { level: 3 }).first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      await settle(page);
    },
    present: dialogShown,
  },
  {
    name: "Pay panel on Today",
    enter: async (page) => {
      await open(page, "/", /Sam/);
      await main(page).getByRole("button", { name: /^Pay: / }).first().click();
      await expect(page.getByRole("dialog", { name: /^Pay: / })).toBeVisible();
      await settle(page);
    },
    present: dialogShown,
  },
  {
    name: "Pay panel with a GiroCode",
    enter: async (page, demo) => {
      await open(page, `/documents/${letter(demo, "13_nebenkostenabrechnung_2025.pdf").id}`);
      await page.getByRole("article").first().getByRole("button", { name: /^Pay\b/ }).click();
      const panel = page.getByRole("dialog", { name: /^Pay/ });
      await expect(panel).toBeVisible();
      const show = panel.getByRole("button", { name: "Show code" });
      if (await show.isVisible()) await show.click();
      await expect(panel.locator("svg[data-qr-version]")).toBeVisible();
      await settle(page);
    },
    present: dialogShown,
  },
  {
    name: "Why this date? with the rules",
    enter: async (page, demo) => {
      await open(page, `/documents/${letter(demo, "15_mahnung_techmarkt.pdf").id}`);
      await page.getByRole("article").first().getByRole("button", { name: /Why this date\?/ }).first().click();
      const panel = page.getByRole("dialog", { name: /^Why this date\?/ });
      await panel.getByRole("button", { name: "Show the rules" }).click();
      await expect(panel.getByRole("button", { name: "Hide the rules" })).toBeVisible();
      await settle(page);
    },
    present: dialogShown,
  },
  {
    name: "Add letters dialog",
    enter: async (page) => {
      await open(page, "/inbox", "Inbox");
      await page.locator("input[type=file][multiple]").first().setInputFiles({
        name: "Einkommensteuerbescheid_2025_Finanzamt_Musterstadt_Steuernummer_123-456-78901_Seite1.pdf",
        mimeType: "application/pdf",
        buffer: Buffer.from("%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"),
      });
      await expect(page.getByRole("dialog")).toBeVisible();
      await settle(page);
    },
    present: dialogShown,
  },
  {
    name: "Letter search",
    enter: async (page) => {
      await open(page, "/", /Sam/);
      const sheet = page.getByRole("button", { name: "Search letters" });
      if (await sheet.isVisible()) await sheet.click();
      await page.getByRole("combobox", { name: "Search your letters" }).fill("Muster");
      await expect(page.getByRole("listbox").first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      await settle(page);
    },
    present: (page) => page.getByRole("listbox").first().isVisible(),
  },
  {
    name: "Delete-letter confirmation",
    enter: async (page, demo) => {
      await open(page, `/documents/${letter(demo, "01_mobilfunkvertrag.pdf").id}`);
      await main(page).getByRole("button", { name: /^Delete$/ }).click();
      await expect(page.getByRole("alertdialog").or(page.getByRole("dialog")).first()).toBeVisible();
      await settle(page);
    },
    present: (page) => page.getByRole("alertdialog").or(page.getByRole("dialog")).first().isVisible(),
  },
  {
    name: "Notice-period edit",
    enter: async (page) => {
      await open(page, "/contracts", "Contracts");
      await main(page).getByRole("button", { name: /^(Add|Change) notice period/ }).first().click();
      await expect(main(page).getByRole("form", { name: /^Notice period for / })).toBeVisible();
      await settle(page);
    },
    present: (page) => main(page).getByRole("form", { name: /^Notice period for / }).isVisible(),
  },
];

// ------------------------------------------------------------------------------------------------

test.describe("layout sweep: 320, 390, 768, 1280 and 1920 px, light and dark", () => {
  test.describe.configure({ timeout: 8 * 60_000 });

  test("the main pages", async ({ browser }, testInfo) => {
    await sweepAll(browser, MAIN_PAGES, testInfo);
  });

  test("every Settings section", async ({ browser }, testInfo) => {
    await sweepAll(browser, SETTINGS, testInfo);
  });

  test("Ask with an answer, a drafted letter, the composer and How it was read", async ({ browser }, testInfo) => {
    await sweepAll(browser, ASK_LETTERS_TRACE, testInfo);
  });

  test("dialogs, drawers and popovers", async ({ browser }, testInfo) => {
    await sweepAll(browser, OVERLAYS, testInfo);
  });

  test("every demo letter", async ({ browser }, testInfo) => {
    const letters = demo.docs.map((doc): SweepState => ({ name: `Letter “${doc.title ?? doc.id}”`, enter: (page) => open(page, `/documents/${doc.id}`) }));
    await sweepAll(browser, letters, testInfo);
  });
});
