#!/usr/bin/env node
/**
 * README screenshots and the demo video, captured from a running demo (`make capture`).
 *
 *   ordnung demo --serve --no-browser --reset --port 8797 --data-dir /tmp/ordnung-capture
 *   node web/scripts/capture.mjs --data /tmp/ordnung-capture --port 8797 --out docs/assets
 *
 * The video reads the tax assessment from the New-mail tray, so start from a fresh demo (--reset).
 * It writes `<out>/video/demo.webm`; `make capture` turns that into `demo.mp4` and `demo.gif`.
 * Set PW_CHROMIUM_PATH to use a Chromium that is already installed.
 */
import { mkdirSync, readFileSync, readdirSync, renameSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";
import { parseArgs } from "node:util";
import { chromium } from "@playwright/test";

const { values: opts } = parseArgs({
  options: {
    data: { type: "string", default: "/tmp/ordnung-capture" },
    port: { type: "string", default: "8797" },
    out: { type: "string", default: "docs/assets" },
    only: { type: "string" }, // "video" or "shots"
  },
});

const BASE = `http://127.0.0.1:${opts.port}`;
const OUT = resolve(opts.out);
const TOKEN = JSON.parse(readFileSync(join(opts.data, "server.json"), "utf8")).token;
const CLIENT = { "X-Ordnung-Client": "web" };
const FINANZAMT = "Finanzamt Musterstadt";
const PHONE_QUESTION = "When does my phone contract end, and by when do I have to cancel it?";

// ------------------------------------------------------------------------------------------------
// A visible cursor and a caption bar (a headless recording shows neither), kept across page loads
// ------------------------------------------------------------------------------------------------

function overlay() {
  const install = () => {
    if (document.getElementById("cap-cursor")) return;
    const cursor = document.createElement("div");
    cursor.id = "cap-cursor";
    cursor.style.cssText =
      "position:fixed;z-index:2147483647;width:24px;height:24px;margin:-2px 0 0 -4px;pointer-events:none;transition:transform .12s ease;";
    cursor.innerHTML =
      '<svg viewBox="0 0 24 24" width="24" height="24"><path d="M5 2.5l14 10.6-6.2 1.1-3.6 6.3z" fill="#16181d" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    const [x, y] = (sessionStorage.getItem("cap-xy") ?? "-60,-60").split(",").map(Number);
    cursor.style.left = `${x}px`;
    cursor.style.top = `${y}px`;
    document.body.appendChild(cursor);
    document.addEventListener(
      "mousemove",
      (e) => {
        cursor.style.left = `${e.clientX}px`;
        cursor.style.top = `${e.clientY}px`;
        sessionStorage.setItem("cap-xy", `${e.clientX},${e.clientY}`);
      },
      true,
    );
    document.addEventListener("mousedown", () => (cursor.style.transform = "scale(.82)"), true);
    document.addEventListener("mouseup", () => (cursor.style.transform = ""), true);

    const bar = document.createElement("div");
    bar.id = "cap-caption";
    bar.style.cssText =
      "position:fixed;left:50%;bottom:26px;transform:translateX(-50%);z-index:2147483646;pointer-events:none;" +
      "background:rgba(16,24,32,.9);color:#fff;font:600 17px/1.4 var(--font-sans, system-ui, sans-serif);" +
      "padding:10px 20px;border-radius:12px;max-width:78%;text-align:center;box-shadow:0 8px 30px rgba(0,0,0,.25);" +
      "transition:opacity .3s ease;opacity:0;";
    document.body.appendChild(bar);
    window.__caption = (text) => {
      bar.textContent = text ?? "";
      bar.style.opacity = text ? "1" : "0";
      sessionStorage.setItem("cap-text", text ?? "");
    };
    window.__caption(sessionStorage.getItem("cap-text") ?? "");
  };
  if (document.body) install();
  else document.addEventListener("DOMContentLoaded", install);
}

async function caption(page, text) {
  await page.evaluate((t) => window.__caption?.(t), text);
}

async function pointAt(page, locator) {
  await locator.waitFor();
  // centre it: the sticky top bar covers anything scrolled only just into view
  const moved = await locator.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const inView = r.top > 90 && r.bottom < window.innerHeight - 110;
    if (!inView) el.scrollIntoView({ block: "center", behavior: "smooth" });
    return !inView;
  });
  if (moved) await page.waitForTimeout(700);
  const box = await locator.boundingBox();
  if (!box) throw new Error(`nothing to point at: ${locator}`);
  const x = box.x + Math.min(box.width / 2, 60);
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y, { steps: 28 });
  return { x, y };
}

async function click(page, locator, { pause = 450 } = {}) {
  const { x, y } = await pointAt(page, locator);
  await page.waitForTimeout(pause);
  await page.mouse.click(x, y);
}

async function scrollBy(page, dy, { steps = 12, pause = 45 } = {}) {
  for (let i = 0; i < steps; i += 1) {
    await page.mouse.wheel(0, dy / steps);
    await page.waitForTimeout(pause);
  }
}

async function nav(page, label) {
  const links = page.getByRole("navigation").getByRole("link", { name: new RegExp(`^(\\d+)?${label}`) });
  await click(page, links.filter({ visible: true }).first());
  await page.waitForLoadState("networkidle");
  await page.getByRole("main").getByRole("heading", { level: 1 }).first().waitFor();
}

// ------------------------------------------------------------------------------------------------
// Session and demo state
// ------------------------------------------------------------------------------------------------

async function newContext(browser, extra = {}) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, ...extra });
  await context.addCookies([{ name: "ordnung_token", value: TOKEN, url: BASE, httpOnly: true, sameSite: "Strict" }]);
  await context.request.patch(`${BASE}/api/demo/tour`, { data: { active: false, completed: true }, headers: CLIENT });
  return context;
}

async function settle(page, ms = 600) {
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(ms);
}

async function documentIdFor(context, title) {
  const docs = await (await context.request.get(`${BASE}/api/documents`)).json();
  return docs.find((d) => d.title && title.test(d.title))?.id;
}

// ------------------------------------------------------------------------------------------------
// The video: a 70-second tour of the golden path
// ------------------------------------------------------------------------------------------------

async function recordVideo(browser) {
  const dir = join(OUT, "video");
  rmSync(dir, { recursive: true, force: true });
  const size = { width: 1280, height: 800 };
  const context = await newContext(browser, { viewport: size, recordVideo: { dir, size } });
  await context.addInitScript(overlay);
  const page = await context.newPage();
  page.on("pageerror", (err) => console.error(`page error: ${err.stack ?? err}`));
  page.on("console", (m) => m.type() === "error" && console.error(`console: ${m.text()}`));
  try {
    await tour(page);
  } catch (err) {
    await page.screenshot({ path: join(OUT, "capture-error.png") }).catch(() => {});
    const details = page.locator("details");
    if (await details.count()) {
      await details.first().click().catch(() => {});
      console.error(await details.first().innerText().catch(() => ""));
    }
    await context.close();
    throw err;
  }
  const video = page.video();
  await context.close();
  const recorded = await video.path();
  renameSync(recorded, join(dir, "demo.webm"));
  for (const name of readdirSync(dir)) if (name !== "demo.webm") rmSync(join(dir, name));
  console.log(`video → ${join(dir, "demo.webm")}`);
}

async function tour(page) {
  await page.goto(`${BASE}/`);
  await settle(page, 400);

  await caption(page, "Ordnung is a private AI secretary for life admin. This is Sam's “Today”.");
  await page.mouse.move(640, 300, { steps: 20 });
  await page.waitForTimeout(3200);
  await scrollBy(page, 420);
  await page.waitForTimeout(1600);
  await scrollBy(page, -420);

  await caption(page, "A photographed tax assessment just arrived.");
  await nav(page, "Inbox");
  const letter = page
    .getByRole("region", { name: /^New mail/ })
    .getByRole("listitem")
    .filter({ hasText: FINANZAMT })
    .first();
  await pointAt(page, letter);
  await page.waitForTimeout(1400);
  await caption(page, "Claude reads it. Code checks every fact and computes the dates.");
  await click(page, letter.getByRole("button", { name: "Let Ordnung read it" }));
  await page.waitForURL(/\/documents\/doc_/, { timeout: 60_000 });
  await settle(page, 900);

  await caption(page, "What it is, what to do and by when, with a countdown.");
  await page.mouse.move(420, 260, { steps: 20 });
  await page.waitForTimeout(3000);

  await caption(page, "Every fact points to the sentence it came from.");
  const todos = page.getByRole("region", { name: /^To-dos & dates/ });
  const objection = todos.getByRole("listitem").filter({ hasText: "Objection deadline (Einspruchsfrist)" });
  await click(page, objection.getByRole("button", { name: /show “Objection deadline \(Einspruchsfrist\)” on the page/ }));
  await page.waitForTimeout(3200);

  await caption(page, "“Why this date?” Each step with its rule, computed by tested code, not guessed.");
  const verdict = page.getByRole("article", { name: /Income Tax Assessment 2025/ });
  await click(page, verdict.getByRole("button", { name: "Why this date?" }));
  const receipt = page.getByRole("dialog", { name: "Why this date?" });
  await receipt.waitFor();
  await page.waitForTimeout(1800);
  await click(page, receipt.getByRole("button", { name: "Show the rules" }));
  await page.waitForTimeout(4800);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(500);

  await caption(page, "The year ahead: deadlines, payments, contracts and permits in one view.");
  await nav(page, "Timeline");
  await page.mouse.move(760, 380, { steps: 24 });
  await page.waitForTimeout(3800);

  await caption(page, "Contracts: what each one costs and the last day to post a cancellation.");
  await nav(page, "Contracts");
  await page.waitForTimeout(1200);
  await scrollBy(page, 360);
  await page.waitForTimeout(2600);

  await caption(page, "Ask anything. Answers cite the letters they come from.");
  await nav(page, "Ask");
  await click(page, page.getByRole("list", { name: "Suggested questions" }).getByRole("button", { name: PHONE_QUESTION }));
  await page.getByRole("main").getByRole("status").filter({ hasText: "Answer ready." }).waitFor({ timeout: 60_000 });
  await page.waitForTimeout(4200);

  await caption(page, "Letters: the legal sentences come from fixed templates, with a translation.");
  await nav(page, "Letters");
  await click(page, page.getByRole("main").getByRole("link", { name: /FunkNetz/ }).first());
  await page.waitForURL(/\/letters\/[^/?]+$/, { timeout: 60_000 });
  await settle(page, 600);
  await page.waitForTimeout(3200);
  await scrollBy(page, 320);
  await page.waitForTimeout(1800);

  await caption(page, "Everything stays on your computer. Try it: ordnung demo (no Claude account needed).");
  await nav(page, "Today");
  await page.waitForTimeout(3600);
}

// ------------------------------------------------------------------------------------------------
// Screenshots
// ------------------------------------------------------------------------------------------------

async function shot(page, name) {
  await page.waitForTimeout(500);
  await page.screenshot({ path: join(OUT, `${name}.png`) });
  console.log(`shot → ${name}.png`);
}

async function screenshots(browser) {
  const context = await newContext(browser, { deviceScaleFactor: 1 });
  const page = await context.newPage();

  await page.goto(`${BASE}/`);
  await settle(page);
  await shot(page, "today");

  const taxId = await documentIdFor(context, /Income Tax Assessment 2025/);
  if (taxId) {
    await page.goto(`${BASE}/documents/${taxId}`);
    await settle(page);
    const todos = page.getByRole("region", { name: /^To-dos & dates/ });
    const objection = todos.getByRole("listitem").filter({ hasText: "Objection deadline (Einspruchsfrist)" });
    await objection.getByRole("button", { name: /show “Objection deadline/ }).click();
    await page.waitForTimeout(900);
    // the highlight stays on the page image; the letter's verdict card goes back to the top
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(500);
    await shot(page, "document");
    // "Why this date?" as a close-up, in a window tall enough for every rule step
    await page.setViewportSize({ width: 1440, height: 1500 });
    await page.getByRole("article", { name: /Income Tax Assessment 2025/ }).getByRole("button", { name: "Why this date?" }).click();
    const receipt = page.getByRole("dialog", { name: "Why this date?" });
    await receipt.getByRole("button", { name: "Show the rules" }).click();
    await page.waitForTimeout(700);
    await receipt.screenshot({ path: join(OUT, "why.png") });
    console.log("shot → why.png");
    await page.keyboard.press("Escape");
    await page.setViewportSize({ width: 1440, height: 900 });
  } else {
    console.warn("the tax assessment has not been read yet: record the video first (it opens the letter)");
  }

  await page.goto(`${BASE}/timeline`);
  await settle(page);
  await shot(page, "timeline");

  await page.goto(`${BASE}/contracts`);
  await settle(page);
  await shot(page, "contracts");

  await page.goto(`${BASE}/ask`);
  await settle(page);
  const question = "When does my residence permit expire, and what should I do before then?";
  await page.getByRole("list", { name: "Suggested questions" }).getByRole("button", { name: question }).click();
  await page.getByRole("main").getByRole("status").filter({ hasText: "Answer ready." }).waitFor({ timeout: 60_000 });
  await shot(page, "ask");

  const drafts = await (await context.request.get(`${BASE}/api/drafts`)).json();
  if (Array.isArray(drafts) && drafts.length) {
    await page.goto(`${BASE}/letters/${drafts[0].id}`);
    await settle(page, 1200);
    await shot(page, "letter");
  }

  const scamId = await documentIdFor(context, /Rundfunk|Beitrag/i);
  const tray = await (await context.request.get(`${BASE}/api/demo/mail`)).json();
  const scam = tray.find((t) => t.sender.startsWith("Rundfunk-Beitragsservice"));
  if (scam && !scam.opened) {
    await page.goto(`${BASE}/inbox`);
    await settle(page);
    await page
      .getByRole("region", { name: /^New mail/ })
      .getByRole("listitem")
      .filter({ hasText: "Rundfunk-Beitragsservice" })
      .first()
      .getByRole("button", { name: "Let Ordnung read it" })
      .click();
    await page.waitForURL(/\/documents\/doc_/, { timeout: 60_000 });
  } else if (scam?.doc_id || scamId) {
    await page.goto(`${BASE}/documents/${scam?.doc_id ?? scamId}`);
  }
  await settle(page, 900);
  await shot(page, "scam");
  await context.close();

  const dark = await newContext(browser, { colorScheme: "dark" });
  const darkPage = await dark.newPage();
  await darkPage.goto(`${BASE}/`);
  await darkPage.evaluate(() => localStorage.setItem("ordnung.theme", "dark"));
  await darkPage.reload();
  await settle(darkPage);
  await shot(darkPage, "today-dark");
  await dark.close();

  const phone = await newContext(browser, { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  const phonePage = await phone.newPage();
  await phonePage.goto(`${BASE}/`);
  await settle(phonePage);
  await shot(phonePage, "mobile");
  await phone.close();
}

// ------------------------------------------------------------------------------------------------

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch(process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {});
try {
  if (opts.only !== "shots") await recordVideo(browser);
  if (opts.only !== "video") await screenshots(browser);
} finally {
  await browser.close();
}
