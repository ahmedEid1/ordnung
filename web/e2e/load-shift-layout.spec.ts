/**
 * Pages that hold still while they load (cumulative layout shift, CLS), on the real demo: what jsdom can't measure.
 * Every test is a first visit unless it says otherwise: a fresh browser context, nothing in its storage. On a phone
 * (390 px) the processor is slowed four times, as on the audit's phone.
 *
 * - The Timeline: the calendar button, the lanes' zoom row and their legend keep their room while the dates load
 *   (it was 0.65 on a phone: the whole chart moved down when the calendar button came).
 * - The demo's Inbox: the New-mail tray and the letters come together (when the tray answered first it pushed the
 *   letters' stand-in down: 0.15). The tray is made to answer first here, every time.
 * - Contracts: "Decide by" keeps its room while the contracts load when this browser last saw a decision or knows
 *   nothing yet; a household with nothing to decide moves once on a first visit (by less), and never again.
 *
 * The shifts are summed whole (stricter than the browser's own CLS, which keeps only the worst burst). No fixed
 * waits: each page is read once it is loaded and still. Runs in the "layout" project.
 */
import type { Page, Route } from "@playwright/test";
import type { Contract, MailTrayItem } from "@/api/types";
import { expect, open, setTour, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

interface Shift {
  value: number;
  nodes: string[];
}

/** Collect every layout shift without recent input from the page's first paint on (call before it loads). */
async function watchShifts(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const shifts: { value: number; nodes: string[] }[] = [];
    (window as unknown as { __shifts: typeof shifts }).__shifts = shifts;
    const name = (n: Node | null) => {
      if (!(n instanceof Element)) return "?";
      const cls = typeof n.className === "string" ? n.className.split(/\s+/).filter(Boolean).slice(0, 2).join(".") : "";
      return `${n.tagName.toLowerCase()}${n.id ? `#${n.id}` : ""}${cls ? `.${cls}` : ""}`;
    };
    new PerformanceObserver((list) => {
      for (const e of list.getEntries() as (PerformanceEntry & { value: number; hadRecentInput: boolean; sources?: { node: Node | null }[] })[]) {
        if (!e.hadRecentInput) shifts.push({ value: e.value, nodes: (e.sources ?? []).map((s) => name(s.node)) });
      }
    }).observe({ type: "layout-shift", buffered: true });
  });
}

/** The sum of the shifts so far, with what moved (for the failure's message). */
async function shifted(page: Page): Promise<{ cls: number; what: string }> {
  const shifts = await page.evaluate(() => (window as unknown as { __shifts: Shift[] }).__shifts);
  return {
    cls: shifts.reduce((a, s) => a + s.value, 0),
    what: shifts.map((s) => `${s.value.toFixed(4)}: ${s.nodes.join(" | ")}`).join("; ") || "nothing moved",
  };
}

/** Open `path` with the shifts watched (390 px: the processor slowed four times) and return what moved. */
async function load(page: Page, path: string, heading: string): Promise<{ cls: number; what: string }> {
  await watchShifts(page);
  if ((page.viewportSize()?.width ?? 0) < 640) {
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  }
  await open(page, path, heading);
  return shifted(page);
}

/** A page opened again in the same browser (what it noted in its storage the first time is there). */
async function loadAgain(page: Page, path: string, heading: string): Promise<{ cls: number; what: string }> {
  const again = await page.context().newPage();
  try {
    return await load(again, path, heading);
  } finally {
    await again.close();
  }
}

const PHONE = { width: 390, height: 844 };
/** The Timeline holds still once fixed (0 in every run, Nov 2026; 0.65 on a phone and 0.03 on a desktop before). */
const TIMELINE_MAX = 0.01;
const DESKTOP = { width: 1280, height: 800 };

for (const [label, size] of [
  ["390", PHONE],
  ["1280", DESKTOP],
] as const) {
  test.describe(`${label} px`, () => {
    test.use({ viewport: size });

    test("the Timeline holds still while its lanes and dates load", async ({ page }) => {
      const { cls, what } = await load(page, "/timeline", "Timeline");
      expect(cls, what).toBeLessThanOrEqual(TIMELINE_MAX);
    });

    test("the Timeline holds still when its lanes come before its dates", async ({ page }) => {
      // the slower order for the page: the lanes draw first while the list's stand-in waits under them
      let lanesIn = () => {};
      const lanes = new Promise<void>((resolve) => (lanesIn = resolve));
      await page.route(
        (url) => url.pathname === "/api/lanes",
        async (route) => {
          await route.fallback();
          lanesIn();
        },
      );
      await page.route(
        (url) => url.pathname === "/api/timeline",
        async (route) => {
          await lanes;
          await route.fallback();
        },
      );
      const { cls, what } = await load(page, "/timeline", "Timeline");
      expect(cls, what).toBeLessThanOrEqual(TIMELINE_MAX);
    });

    test("Contracts with a decision to make: a first visit and a returning one hold still", async ({ page }) => {
      const first = await load(page, "/contracts", "Contracts");
      await expect(page.getByRole("heading", { name: /Decide by/ })).toBeVisible();
      expect(first.cls, first.what).toBeLessThanOrEqual(0.05);
      const again = await loadAgain(page, "/contracts", "Contracts");
      expect(again.cls, again.what).toBeLessThanOrEqual(0.05);
    });

    test("Contracts with nothing to decide: a first visit moves once, by less; a returning one holds still", async ({ page }) => {
      // the demo's contracts with no date to send a notice by: a household with nothing to decide now
      await page.context().route(
        (url) => url.pathname === "/api/contracts",
        async (route) => {
          if (route.request().method() !== "GET") return route.fallback();
          const response = await route.fetch();
          const contracts = (await response.json()) as Contract[];
          await route.fulfill({ response, json: contracts.map((c) => (c.computed ? { ...c, computed: { ...c.computed, send_by: null } } : c)) });
        },
      );
      const first = await load(page, "/contracts", "Contracts");
      await expect(page.getByRole("heading", { name: /Decide by/ })).toHaveCount(0);
      // the room kept for a decision this browser could not know about goes once: 0.092 at 390 px and 0.076 at 1280 px
      // in every run (Nov 2026), most of it that room; the rest is the cost summary's stand-in, shorter than the summary
      expect(first.cls, first.what).toBeLessThanOrEqual(0.1);
      const again = await loadAgain(page, "/contracts", "Contracts");
      expect(again.cls, again.what).toBeLessThanOrEqual(0.05);
    });
  });
}

// measured on a desktop: there the tray pushed the letters' stand-in down (0.15); at 390 px it did not (Nov 2026)
test.describe("1280 px", () => {
  test.use({ viewport: DESKTOP });

  test("the demo's Inbox holds still when its New-mail tray answers first", async ({ page }) => {
    let trayIn = () => {};
    const tray = new Promise<void>((resolve) => (trayIn = resolve));
    // the tray as a fresh demo has it (letters still in their envelopes), whatever earlier tests opened
    await page.route(
      (url) => url.pathname === "/api/demo/mail",
      async (route: Route) => {
        if (route.request().method() !== "GET") return route.fallback();
        const response = await route.fetch();
        const items = (await response.json()) as MailTrayItem[];
        await route.fulfill({ response, json: items.map((m) => ({ ...m, opened: false, doc_id: null })) });
        trayIn();
      },
    );
    await page.route(
      (url) => url.pathname === "/api/documents",
      async (route) => {
        await tray;
        await route.fallback();
      },
    );
    const { cls, what } = await load(page, "/inbox", "Inbox");
    await expect(page.getByRole("region", { name: /New mail/ })).toBeVisible();
    expect(cls, what).toBeLessThanOrEqual(0.05);
    });
});
