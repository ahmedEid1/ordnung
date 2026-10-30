/**
 * The evaluation's report page (`python -m evals.present --site`), as GitHub Pages serves it beside the online demo
 * at /ordnung/evals/: built from `evals/present/presentation.json` into a folder of its own, with the standard library
 * only (the runner's `python3`, as `.github/workflows/demo.yml` builds it), and opened from that folder. It needs no
 * server: no demo, no app, no model.
 *
 * In light and dark, at 320, 375 and 1280 px: axe (WCAG 2.2 A/AA and best practices) finds nothing serious or
 * critical, nothing scrolls sideways, every chart's table opens, and a phone gets the narrow charts, whose smallest
 * text is at least 12 px as drawn.
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { expect, expectAccessible, test } from "./helpers";
import { WEB_DIR } from "./env";

const REPO_DIR = join(WEB_DIR, "..");
/** The Python that builds the page: the standard library only, so any `python3` will do. */
const PYTHON = process.env.ORDNUNG_E2E_PYTHON ?? "python3";
const WIDTHS = [320, 375, 1280];
/** At or below this width the page swaps every chart for its narrow layout (evals/present/site.py). */
const NARROW_MAX = 600;

let site = "";

test.beforeAll(() => {
  site = mkdtempSync(join(tmpdir(), "ordnung-eval-report-"));
  execFileSync(PYTHON, ["-m", "evals.present", "--site", site, "--check-site"], { cwd: REPO_DIR, stdio: "pipe" });
});

test.afterAll(() => {
  if (site) rmSync(site, { recursive: true, force: true });
});

for (const colorScheme of ["light", "dark"] as const) {
  for (const width of WIDTHS) {
    test(`the report page at ${width} px in ${colorScheme}`, async ({ page }, testInfo) => {
      await page.emulateMedia({ colorScheme });
      await page.setViewportSize({ width, height: 900 });
      await page.goto(pathToFileURL(join(site, "index.html")).href);
      await expect(page.getByRole("heading", { level: 1, name: "Ordnung evaluation" })).toBeVisible();
      const scheme = await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme);
      expect(scheme).toBe(colorScheme);

      // every chart's numbers as a table, one click away
      const summaries = page.locator("figure summary");
      const charts = await summaries.count();
      expect(charts).toBeGreaterThanOrEqual(5);
      for (let i = 0; i < charts; i++) {
        await summaries.nth(i).click();
        await expect(page.locator("figure details").nth(i).locator("table")).toBeVisible();
      }

      // nothing scrolls sideways (wide tables scroll inside their own focusable region)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, "the page scrolls sideways").toBeLessThanOrEqual(0);

      // a phone gets the narrow charts, and their smallest text stays readable as drawn
      const narrow = width <= NARROW_MAX;
      const shown = page.locator(narrow ? "figure .narrow svg" : "figure .wide svg");
      await expect(shown.first()).toBeVisible();
      await expect(page.locator(narrow ? "figure .wide svg" : "figure .narrow svg").first()).toBeHidden();
      if (narrow) {
        const smallest = await shown.evaluateAll((svgs) =>
          Math.min(
            ...svgs.flatMap((svg) => {
              const scale = svg.getBoundingClientRect().width / (svg as SVGSVGElement).viewBox.baseVal.width;
              return [...svg.querySelectorAll("text")].map((text) => Number(text.getAttribute("font-size")) * scale);
            }),
          ),
        );
        expect(smallest, "the narrow charts' smallest text, in px").toBeGreaterThanOrEqual(12);
      }

      await expectAccessible(page, testInfo, `eval-report-${colorScheme}-${width}`);
    });
  }
}
