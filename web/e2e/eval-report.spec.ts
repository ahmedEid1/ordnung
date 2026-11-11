/**
 * The evaluation's report page (`python -m evals.present --site`), as GitHub Pages serves it beside the online demo
 * at /ordnung/evals/: built from `evals/present/presentation.json` into a folder of its own, with the standard library
 * only (the runner's `python3`, as `.github/workflows/demo.yml` builds it), and opened from that folder. It needs no
 * server: no demo, no app, no model.
 *
 * The page as committed, and the page of the pre-registered final run once it is published: three synthetic final
 * runs of tests/helpers_final.py (one that holds up, one that does not, and one with a single read) whose
 * `presentation.json` the project's Python writes into a folder of their own (tests/e2e_support/final_report.py),
 * the page then built from it as the real one is, with `--root`.
 *
 * In light and dark, at 320, 375 and 1280 px: axe (WCAG 2.2 A/AA and best practices) finds nothing serious or
 * critical, nothing scrolls sideways, every chart's table opens, and a phone gets the narrow charts, whose smallest
 * text is at least 12 px as drawn. A final run's page also shows its chart, its sections 16 (deviations) and 17
 * (provenance) in its contents, and the stability over the reads only with two reads or more.
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
/** The Python that writes a synthetic final run's `presentation.json`: the project's environment (CI's e2e job has it). */
const VENV_PYTHON = process.env.ORDNUNG_E2E_VENV_PYTHON ?? join(REPO_DIR, ".venv", "bin", "python");
const WIDTHS = [320, 375, 1280];
/** At or below this width the page swaps every chart for its narrow layout (evals/present/site.py). */
const NARROW_MAX = 600;

interface Case {
  /** The start of each test's title. */
  name: string;
  /** The synthetic final run of tests/helpers_final.py the page is built from; none for the page as committed. */
  final?: "good" | "bad" | "one_read";
  /** Whether the final run has two reads or more, so that its stability over the reads is drawn. */
  stable?: boolean;
}

const CASES: Case[] = [
  { name: "the report page" },
  { name: "the report page of a final run that holds up", final: "good", stable: true },
  { name: "the report page of a final run that does not", final: "bad", stable: true },
  { name: "the report page of a final run with one read", final: "one_read", stable: false },
];

/** Build the page of `final` (or the page as committed) into a new folder: `{ site, root }`, root holding its data. */
function build(final: Case["final"]): { site: string; root: string | null } {
  const site = mkdtempSync(join(tmpdir(), "ordnung-eval-report-"));
  const page = ["-m", "evals.present", "--site", site, "--check-site"];
  if (!final) {
    execFileSync(PYTHON, page, { cwd: REPO_DIR, stdio: "pipe" });
    return { site, root: null };
  }
  const root = mkdtempSync(join(tmpdir(), `ordnung-eval-final-${final}-`));
  execFileSync(VENV_PYTHON, ["tests/e2e_support/final_report.py", "--scenario", final, "--out", root], {
    cwd: REPO_DIR,
    stdio: "pipe",
  });
  execFileSync(PYTHON, ["-m", "evals.present", "--root", root, ...page.slice(2)], { cwd: REPO_DIR, stdio: "pipe" });
  return { site, root };
}

for (const { name, final, stable } of CASES) {
  test.describe(name, () => {
    let built: { site: string; root: string | null } | null = null;

    test.beforeAll(() => {
      built = build(final);
    });

    test.afterAll(() => {
      for (const dir of [built?.site, built?.root]) if (dir) rmSync(dir, { recursive: true, force: true });
    });

    for (const colorScheme of ["light", "dark"] as const) {
      for (const width of WIDTHS) {
        test(`${name} at ${width} px in ${colorScheme}`, async ({ page }, testInfo) => {
          await page.emulateMedia({ colorScheme });
          await page.setViewportSize({ width, height: 900 });
          await page.goto(pathToFileURL(join(built!.site, "index.html")).href);
          await expect(page.getByRole("heading", { level: 1, name: "Ordnung evaluation" })).toBeVisible();
          const scheme = await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme);
          expect(scheme).toBe(colorScheme);

          // every chart's numbers as a table, one click away
          const summaries = page.locator("figure summary");
          const charts = await summaries.count();
          expect(charts).toBeGreaterThanOrEqual(final ? (stable ? 8 : 7) : 5);
          for (let i = 0; i < charts; i++) {
            await summaries.nth(i).click();
            await expect(page.locator("figure details").nth(i).locator("table")).toBeVisible();
          }

          if (final) {
            // the final run's chart and, with two reads or more, its stability over the reads
            await expect(page.locator("figure#final")).toHaveCount(1);
            await expect(page.locator("figure#final-differences")).toHaveCount(1);
            await expect(page.locator("figure#final-stability")).toHaveCount(stable ? 1 : 0);
            // the deviations and the provenance, in the contents and on the page
            for (const [anchor, title] of [
              ["16-deviations", "16. Deviations"],
              ["17-provenance", "17. Provenance"],
            ]) {
              await expect(page.locator(`nav.toc a[href="#${anchor}"]`)).toHaveText(title);
              await expect(page.getByRole("heading", { level: 2, name: title, exact: true })).toBeVisible();
            }
          }

          // nothing scrolls sideways (wide tables scroll inside their own focusable region)
          const overflow = await page.evaluate(
            () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
          );
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

          await expectAccessible(page, testInfo, `eval-report-${final ?? "committed"}-${colorScheme}-${width}`);
        });
      }
    }
  });
}
