/**
 * Step helpers for the state catalogs: navigate and wait, click the first visible match, hover,
 * type, and a few app-specific moves (the New-mail tray, the "Add letters" file input). Every
 * helper waits for the page to settle afterwards.
 */
import { controlEvents, fakeFile, settle } from "./browser.mjs";

/** Thrown by a state that doesn't exist at this viewport (e.g. the phone-only search sheet on a laptop). */
export class NotApplicable extends Error {
  constructor(reason) {
    super(reason);
    this.name = "NotApplicable";
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * The context a state's `run(ctx)` gets. `ctx.path(p)` turns an app path into a URL (hash routes
 * on the static demo).
 */
export function stepContext({ page, server, api, target, viewport, theme, vp, shared, hash }) {
  const ctx = {
    page,
    server,
    api,
    target,
    viewport,
    theme,
    width: vp.width,
    height: vp.height,
    phone: vp.width < 768,
    /** md breakpoint and up: sidebar instead of the tab bar */
    tabletUp: vp.width >= 768,
    desktop: vp.width >= 1024,
    shared,
    notes: [],
    expectErrorScreen: false,

    url(path) {
      if (hash) return `${server.base}/#${path.startsWith("/") ? path : `/${path}`}`;
      return `${server.base}${path}`;
    },

    note(msg) {
      ctx.notes.push(msg);
    },

    notApplicable(reason) {
      throw new NotApplicable(reason);
    },

    /** Navigate and wait until the page is settled (`heading: false` skips the <h1> check). */
    async goto(path, { heading = true, idle = true, timeout = 20_000, headingTimeout = 8000 } = {}) {
      await page.goto(ctx.url(path), { waitUntil: "domcontentloaded", timeout });
      if (heading) {
        await page
          .locator("h1")
          .filter({ visible: true })
          .first()
          .waitFor({ state: "visible", timeout: headingTimeout })
          .catch(() => ctx.note("no visible <h1> after navigation"));
      }
      await settle(page, { idle });
    },

    /** First visible element of a locator (waits for it). */
    async visible(locator, { timeout = 10_000 } = {}) {
      const loc = locator.filter({ visible: true }).first();
      await loc.waitFor({ state: "visible", timeout });
      return loc;
    },

    async exists(locator, { timeout = 1500 } = {}) {
      try {
        await locator.filter({ visible: true }).first().waitFor({ state: "visible", timeout });
        return true;
      } catch {
        return false;
      }
    },

    /** Scroll it to the middle of the viewport (clear of sticky top bars and bottom tab bars). */
    async centre(loc) {
      await loc.evaluate((el) => el.scrollIntoView({ block: "center", inline: "nearest" })).catch(() => {});
    },

    async click(locator, { settleAfter = true, timeout = 10_000, force = false } = {}) {
      const loc = await ctx.visible(locator, { timeout });
      await ctx.centre(loc);
      await loc.click({ timeout, force });
      if (settleAfter) await settle(page);
      return loc;
    },

    async hover(locator, { wait = 450 } = {}) {
      const loc = await ctx.visible(locator);
      await ctx.centre(loc);
      await loc.hover({ timeout: 5000 }).catch(async () => {
        // something covers it (or the page scrolls sideways): point at it anyway, and say so
        ctx.note("hovered without the actionability check — the element was covered or not stable");
        await loc.hover({ force: true });
      });
      await sleep(wait);
      await settle(page, { idle: false });
      return loc;
    },

    /** Keyboard focus (shows focus-only UI such as tooltips the way a keyboard user sees them). */
    async keyboardFocus(locator) {
      const loc = await ctx.visible(locator);
      await loc.scrollIntoViewIfNeeded().catch(() => {});
      // focus the element before it, then Tab onto it: :focus-visible like a real keyboard user
      await loc.evaluate((el) => {
        const all = Array.from(document.querySelectorAll('a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])')).filter((e) => !e.disabled);
        const i = all.indexOf(el);
        const prev = all[i - 1];
        if (prev) prev.focus();
        else el.focus();
      });
      await page.keyboard.press("Tab");
      await sleep(200);
      await settle(page, { idle: false });
      return loc;
    },

    async type(locator, text, { settleAfter = true, delay = 0 } = {}) {
      const loc = await ctx.visible(locator);
      await loc.scrollIntoViewIfNeeded().catch(() => {});
      await loc.click();
      await loc.fill("");
      if (delay) await loc.pressSequentially(text, { delay });
      else await loc.fill(text);
      if (settleAfter) await settle(page);
      return loc;
    },

    async select(locator, value) {
      const loc = await ctx.visible(locator);
      await loc.selectOption(value);
      await settle(page);
      return loc;
    },

    async press(key) {
      await page.keyboard.press(key);
      await settle(page);
    },

    async scrollTo(locator) {
      const loc = await ctx.visible(locator);
      await loc.evaluate((el) => el.scrollIntoView({ block: "center" }));
      await settle(page, { idle: false });
      return loc;
    },

    async wait(ms) {
      await sleep(ms);
    },

    /** Take over `/api/events` (see browser.controlEvents). Call before `goto`. */
    async events() {
      return controlEvents(page);
    },

    /** Put files on the app's hidden "Add letters" input (as if chosen in the file picker). */
    async addFiles(files) {
      const input = page.locator('input[type=file][multiple]').first();
      await input.setInputFiles(files.map((f) => (typeof f === "string" ? f : f.buffer ? f : fakeFile(f.name, f.mimeType))));
      await settle(page);
    },

    /** Simulate dragging files over the window (the global drop zone). */
    async dragFilesOver() {
      await page.evaluate(() => {
        const dt = new DataTransfer();
        dt.items.add(new File(["%PDF-1.4"], "Brief.pdf", { type: "application/pdf" }));
        window.dispatchEvent(new DragEvent("dragenter", { dataTransfer: dt, bubbles: true, cancelable: true }));
        window.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true }));
      });
      await settle(page, { idle: false });
    },
  };
  return ctx;
}

/** The main region's buttons/links by accessible name (visible ones only). */
export const inMain = (page) => page.getByRole("main");

/**
 * `text` (a title from the API) as the app shows it, as a pattern: amounts, dates and references are glued
 * with no-break spaces and hyphens on screen, long German words carry soft hyphens (as the e2e suite's
 * `shownAs`). A letter's or a to-do's title is the model's and changes with every recording of the demo, so
 * the audit reads it from the API instead of spelling it out.
 */
export function shownAs(text) {
  const char = (ch) => (/\s/.test(ch) ? "[\\s\\u00a0\\u202f]+" : ch === "-" ? "[-\\u2011]" : ch.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&"));
  return new RegExp([...text.trim()].map(char).join("\\u00ad?"));
}
