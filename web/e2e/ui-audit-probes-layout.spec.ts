/**
 * The UI audit's covered and target-size rules (`scripts/ui-audit/probes.mjs`), on pages drawn here. They
 * still report a control behind something the person did not open: a top bar at the top of the page, a
 * floating panel nobody opened, a card fixed at the bottom over the last control when the page leaves it no
 * room, a note drawn over a button, a button wholly under another, small targets side by side. They no longer
 * report the page behind what the person opened (a search box's message panel), a control a person can still
 * click on 24 px of it (a chart bar under the notice window drawn on it), a bar under a lane-label column pinned
 * sideways, a control the end of the page scrolls clear of a card fixed at the bottom, or a target axe finds
 * too small only because a sticky bar lies over it where the page happens to be scrolled (UI audit E1).
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { axeFindings, layoutFindings } from "../scripts/ui-audit/probes.mjs";

/** The ids of the controls the covered probe reports. */
async function covered(page: Page): Promise<string[]> {
  const { findings } = await layoutFindings(page);
  return findings
    .filter((f) => f.probe === "covered")
    .map((f) => /#([\w-]+)/.exec(f.selector)?.[1] ?? f.selector)
    .sort();
}

const doc = (body: string) => `<!doctype html><html lang="en"><head><title>Probe</title></head>
  <body style="margin:0;font:16px/24px sans-serif">${body}</body></html>`;
const plain = "padding:0;border:0;background:#dde";

test.describe("laptop", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  // a top bar with a search box and its message panel (no role, as the app's "Keep typing" panel), over two
  // controls of the page at its top
  const searchPage = (box: string) =>
    doc(`<header style="position:fixed;top:0;left:0;right:0;height:56px;background:#fff;z-index:10">
      <div style="position:relative;margin-left:600px;width:300px;padding-top:10px">
        <input id="q" type="search" aria-label="Search" ${box} style="width:280px;height:36px">
        <div id="panel" style="position:absolute;top:50px;left:0;width:300px;height:120px;background:#eee">Keep typing</div>
      </div>
    </header>
    <main style="position:relative;height:2000px"><h1 style="position:absolute;top:200px;margin:0">Probe</h1>
      <a id="under-bar" href="#a" style="position:absolute;top:16px;left:16px">Under the bar</a>
      <a id="under-panel" href="#b" style="position:absolute;top:100px;left:620px">To pay</a>
    </main>`);

  test("the covered probe still reports controls under a top bar and under a panel nobody opened", async ({ page }) => {
    await page.setContent(searchPage(""));
    expect(await covered(page)).toEqual(["under-bar", "under-panel"]);
    // a search box that is closed while its panel still shows: not something the person has open
    await page.setContent(searchPage('role="combobox" aria-expanded="false" aria-controls="panel"'));
    expect(await covered(page)).toEqual(["under-bar", "under-panel"]);
  });

  test("the covered probe leaves the page behind a search box's panel the person opened, as behind a menu", async ({ page }) => {
    await page.setContent(searchPage('role="combobox" aria-expanded="true" aria-controls="panel"'));
    expect(await covered(page)).toEqual([]);
  });

  test("a control under another control counts as covered only when no 24 px of it can be clicked", async ({ page }) => {
    const row = (inner: string) => `<div style="position:relative;height:24px;margin:16px">${inner}</div>`;
    const at = (left: number, width: number) => `position:absolute;top:0;left:${left}px;width:${width}px;height:24px;${plain}`;
    await page.setContent(
      doc(`<main><h1>Probe</h1>
        ${row(`<button id="term" style="${at(0, 300)}">Minimum term</button><button id="window" style="${at(100, 100)}">Time to cancel</button>`)}
        ${row(`<button id="short" style="${at(0, 60)}">Short</button><button id="wide" style="${at(0, 200)}">Wide</button>`)}
        ${row(`<button id="under-note" style="${at(0, 300)}">Under a note</button><div style="${at(100, 100)};background:#fff">A note</div>`)}
      </main>`),
    );
    // the term bar's two ends take the click; the short button is wholly under the wide one; a note is no control
    expect(await covered(page)).toEqual(["short", "under-note"]);
  });

  test("a bar under a lane-label column pinned sideways is not covered: it scrolls out from under it", async ({ page }) => {
    await page.setContent(
      doc(`<main><h1>Probe</h1>
        <div id="scroller" style="overflow-x:auto;width:800px;margin:16px">
          <div style="position:relative;width:2000px;height:60px">
            <div style="position:sticky;left:0;width:150px;height:60px;background:#fff;z-index:1">Contracts</div>
            <button id="bar" style="position:absolute;left:100px;top:18px;width:600px;height:24px;${plain}">MusterStrom</button>
          </div>
        </div>
      </main>`),
    );
    await page.locator("#scroller").evaluate((el) => (el.scrollLeft = 300));
    expect(await covered(page)).toEqual([]);
  });
});

test.describe("phone", () => {
  test.use({ viewport: { width: 320, height: 640 } });

  // a tall card fixed over the tab bar (the tour's whole step): its top is above the middle of the screen
  const cardPage = (room: number) =>
    doc(`<main><h1 style="margin:0">Probe</h1>
      <div style="height:300px"></div><button id="first" style="height:32px">First</button>
      <div style="height:1200px"></div><button id="last" style="height:32px">Last</button>
      <div style="height:${room}px"></div>
    </main>
    <section aria-label="Card" style="position:fixed;left:12px;right:12px;bottom:76px;height:283px;background:#fff;border:1px solid #888">
      <p>A step of the tour.</p><button id="minimise">Minimise</button>
    </section>`);

  test("a card fixed at the bottom covers only what the end of the page can't scroll clear of it", async ({ page }) => {
    // the page keeps room for the card: the first control scrolls clear of it, the last one is above it
    await page.setContent(cardPage(380));
    expect(await covered(page)).toEqual([]);
    // no room: the last control stays under the card
    await page.setContent(cardPage(100));
    expect(await covered(page)).toEqual(["last"]);
  });
});

test.describe("phone, axe", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("axe's target-size counts a target under a sticky bar only if it is too small where it is in the clear", async ({ page }) => {
    const bar = `width:100px;height:40px;${plain}`;
    const tiny = `width:16px;height:16px;${plain}`;
    // the phone's top bar: sticky, 56 px, its buttons 40 px
    await page.setContent(
      doc(`<header style="position:sticky;top:0;box-sizing:border-box;height:56px;padding:8px;display:flex;gap:8px;background:#fff;z-index:10">
        <button style="${bar}">Search</button><button style="${bar}">Add</button><button style="${bar}">Numbers</button>
      </header>
      <main><h1>Probe</h1>
        <div style="height:400px"></div>
        <a id="why" href="#x" style="display:inline-block;width:128px;height:24px">Why these dates?</a>
        <div style="height:1200px"></div>
        <p><button id="tiny-a" style="${tiny}">a</button><button id="tiny-b" style="${tiny}">b</button></p>
      </main>`),
    );
    // leave "Why these dates?" half under the bar's buttons, as a state can leave the page scrolled: there,
    // axe itself counts it too small
    const scrolled = await page.locator("#why").evaluate((el) => {
      window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 38);
      return window.scrollY;
    });
    const there = await new AxeBuilder({ page }).include("#why").withRules(["target-size"]).analyze();
    expect(there.violations.map((v) => v.id), "axe on its own, with the target under the bar").toEqual(["target-size"]);
    const sized = (await axeFindings(page)).filter((f) => f.kind === "target-size").map((f) => f.selector);
    expect(sized.sort()).toEqual(["#tiny-a", "#tiny-b"]);
    expect(await page.evaluate(() => window.scrollY), "the page is scrolled back").toBe(scrolled);
  });
});
