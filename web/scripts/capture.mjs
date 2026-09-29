#!/usr/bin/env node
/**
 * README screenshots and the demo video, captured from a running demo (`make capture`).
 *
 *   ordnung demo --serve --no-browser --reset --port 8797 --data-dir /tmp/ordnung-capture
 *   node web/scripts/capture.mjs --data /tmp/ordnung-capture --port 8797 --out docs/assets
 *
 * Start from a fresh demo (--reset): the video reads the tax assessment from the New-mail tray, and
 * Ask's recorded answers replay only against the ledger they were recorded from, so the Ask shot comes
 * first and the proof of sending is set up after the video's question.
 *
 * `ordnung demo`'s recorded letters include no court letter, so the court payment order comes from the
 * app's mock mode (`?mock=full`, the static web demo's data): the same app on hand-written sample
 * letters whose dates, receipts and advice card come from the rules engine
 * (scripts/gen_mock_high_stakes.py, scripts/gen_mock_advice.py). `?mock=0` returns to the demo.
 *
 * It writes `<out>/video/demo.webm` and `<out>/video/cut` (the seconds where the video starts and the
 * GIF ends); `make capture` turns them into `demo.mp4` and `demo.gif`.
 * Set PW_CHROMIUM_PATH to use a Chromium that is already installed.
 */
import { mkdirSync, readFileSync, readdirSync, renameSync, rmSync, writeFileSync } from "node:fs";
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
const MONEY_QUESTION = "What do I have to pay in the next four weeks?";
const TAX_TITLE = /Income Tax Assessment 2025/;
const STATEMENT_TITLE = /Operating and Heating Cost Statement/;
/** An Einschreiben number with a correct check digit (the e2e suite's). */
const TRACKING = "RT 123 456 785 DE";
/** The mock world's court payment order (web/src/mocks/data/documents.ts), opened by `?mock=full`. */
const COURT_ORDER = `/documents/doc_mahnbescheid?mock=full`;

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

/** The demo tour's card stays out of the pictures: the API ends it in the demo, but mock mode starts its own. */
function hideDemoTour() {
  const install = () => {
    const style = document.createElement("style");
    style.textContent = '[aria-label="Demo tour"], [aria-label^="Demo tour ·"] { display: none !important; }';
    document.head.appendChild(style);
  };
  if (document.head) install();
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
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "en-GB", timezoneId: "Europe/Berlin", ...extra });
  await context.addCookies([{ name: "ordnung_token", value: TOKEN, url: BASE, httpOnly: true, sameSite: "Strict" }]);
  await context.request.patch(`${BASE}/api/demo/tour`, { data: { active: false, completed: true }, headers: CLIENT });
  return context;
}

async function settle(page, ms = 600) {
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(ms);
}

async function apiGet(context, path) {
  const res = await context.request.get(`${BASE}${path}`);
  if (!res.ok()) throw new Error(`GET ${path} → ${res.status()}`);
  return res.json();
}

async function documentIdFor(context, title) {
  const docs = await apiGet(context, "/api/documents");
  return docs.find((d) => d.title && title.test(d.title))?.id;
}

/** The New-mail letter from `sender`, read if it wasn't yet (in the page, as a person would): its letter id. */
async function readMail(page, sender) {
  const tray = await apiGet(page.context(), "/api/demo/mail");
  const item = tray.find((t) => t.sender.startsWith(sender));
  if (!item) throw new Error(`no New-mail letter from ${sender}`);
  if (item.opened && item.doc_id) return item.doc_id;
  await page.goto(`${BASE}/inbox`);
  await settle(page);
  await page
    .getByRole("region", { name: /^New mail/ })
    .getByRole("listitem")
    .filter({ hasText: sender })
    .first()
    .getByRole("button", { name: "Let Ordnung read it" })
    .click();
  await page.waitForURL(/\/documents\/doc_/, { timeout: 60_000 });
  return new URL(page.url()).pathname.split("/").pop();
}

/** The tax assessment's objection to-do: its "show it on the page" button. */
function objectionEvidence(page) {
  return page
    .getByRole("region", { name: /^To-dos & dates/ })
    .getByRole("listitem")
    .filter({ hasText: /objection/i })
    .first()
    .getByRole("button", { name: /on the page$/ })
    .first();
}

/** A step of the weekly review, in its list of steps. */
function weekStep(page, name) {
  return page.getByRole("main").getByRole("button", { name: new RegExp(`^${name}`) }).first();
}

/** A small, well-formed one-page PDF standing in for the scan of the posting receipt. */
function receiptPdf() {
  const text = `BT /F1 16 Tf 30 150 Td (Einlieferungsbeleg ${TRACKING}) Tj 0 -24 Td (28.09.2026 11:05) Tj ET`;
  const objects = [
    "<</Type/Catalog/Pages 2 0 R>>",
    "<</Type/Pages/Kids[3 0 R]/Count 1>>",
    "<</Type/Page/Parent 2 0 R/MediaBox[0 0 420 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
    `<</Length ${text.length}>>\nstream\n${text}\nendstream`,
    "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
  ];
  let out = "%PDF-1.4\n";
  const offsets = [];
  objects.forEach((body, i) => {
    offsets.push(out.length);
    out += `${i + 1} 0 obj\n${body}\nendobj\n`;
  });
  const xref = out.length;
  out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("")}`;
  out += `trailer\n<</Size ${objects.length + 1}/Root 1 0 R>>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(out, "latin1");
}

/**
 * The demo's FunkNetz cancellation, sent today by Einschreiben with its tracking number and the
 * posting receipt as proof (what "Mark as sent" and "Add proof" save). Once per demo; its draft id.
 * After Ask's recorded answers: it changes the ledger they are checked against.
 */
async function sendCancellation(context) {
  const contracts = await apiGet(context, "/api/contracts");
  const contract = contracts.find((c) => /FunkNetz/.test(c.name ?? ""));
  if (!contract) throw new Error("no FunkNetz contract in the demo");
  const drafts = await apiGet(context, "/api/drafts");
  const sent = drafts.find((d) => d.contract_id === contract.id && d.status === "sent" && d.tracking_number);
  if (sent) return sent.id;
  let draft = drafts.find((d) => d.contract_id === contract.id && d.kind === "cancellation");
  if (!draft) {
    const made = await context.request.post(`${BASE}/api/drafts`, { data: { kind: "cancellation", contract_id: contract.id }, headers: CLIENT });
    if (made.status() !== 201) throw new Error(`draft the cancellation → ${made.status()}`);
    draft = await made.json();
  }
  const marked = await context.request.post(`${BASE}/api/drafts/${draft.id}/sent`, {
    data: { channel: "registered_letter", date: "2026-09-28", tracking_number: TRACKING },
    headers: CLIENT,
  });
  if (!marked.ok()) throw new Error(`mark it sent → ${marked.status()} ${await marked.text()}`);
  const proof = await context.request.post(`${BASE}/api/drafts/${draft.id}/proofs`, {
    multipart: {
      file: { name: "Einlieferungsbeleg.pdf", mimeType: "application/pdf", buffer: receiptPdf() },
      kind: "posting_receipt",
      on_date: "2026-09-28",
      note: "Post office Musterstadt-Mitte, 11:05",
    },
    headers: CLIENT,
  });
  if (proof.status() !== 201) throw new Error(`add the posting receipt → ${proof.status()} ${await proof.text()}`);
  return draft.id;
}

// ------------------------------------------------------------------------------------------------
// The video: a tour of the golden path, the first part of which is the README's GIF
// ------------------------------------------------------------------------------------------------

async function recordVideo(browser) {
  const dir = join(OUT, "video");
  rmSync(dir, { recursive: true, force: true });
  const size = { width: 1280, height: 800 };
  const context = await newContext(browser, { viewport: size, recordVideo: { dir, size } });
  await context.addInitScript(overlay);
  await context.addInitScript(hideDemoTour);
  const page = await context.newPage();
  page.on("pageerror", (err) => console.error(`page error: ${err.stack ?? err}`));
  page.on("console", (m) => m.type() === "error" && console.error(`console: ${m.text()}`));
  let cut;
  try {
    cut = await tour(page);
  } catch (err) {
    await page.screenshot({ path: join(OUT, "capture-error.png") }).catch(() => {});
    await context.close();
    throw err;
  }
  const video = page.video();
  await context.close();
  const recorded = await video.path();
  renameSync(recorded, join(dir, "demo.webm"));
  for (const name of readdirSync(dir)) if (name !== "demo.webm") rmSync(join(dir, name));
  // `make capture` starts the video and the GIF once Today is on screen (the recording starts with a blank
  // page), and ends the README's GIF after the court order, before the tour moves on
  writeFileSync(join(dir, "cut"), `${cut.start.toFixed(2)} ${cut.gifEnd.toFixed(2)}\n`);
  console.log(`video → ${join(dir, "demo.webm")} (from ${cut.start.toFixed(1)} s; GIF to ${cut.gifEnd.toFixed(1)} s)`);
}

/** The tour; returns when Today is first on screen and when the GIF ends, in seconds of the video. */
async function tour(page) {
  const started = Date.now();
  const seconds = () => (Date.now() - started) / 1000;
  const mark = (what) => console.log(`  ${seconds().toFixed(1).padStart(5)} s  ${what}`);
  await page.goto(`${BASE}/`);
  await settle(page, 400);
  const start = seconds();

  mark("Today");
  await caption(page, "Ordnung is a private secretary for your paperwork. This is Sam's “Today”.");
  await page.mouse.move(640, 300, { steps: 20 });
  await page.waitForTimeout(2400);
  await scrollBy(page, 420);
  await page.waitForTimeout(1100);
  await scrollBy(page, -420);

  mark("a letter arrives");
  await caption(page, "A photographed tax assessment just arrived.");
  await nav(page, "Inbox");
  const letter = page
    .getByRole("region", { name: /^New mail/ })
    .getByRole("listitem")
    .filter({ hasText: FINANZAMT })
    .first();
  await pointAt(page, letter);
  await page.waitForTimeout(900);
  await caption(page, "Claude reads it. Code checks every fact and computes the dates.");
  await click(page, letter.getByRole("button", { name: "Let Ordnung read it" }));
  await page.waitForURL(/\/documents\/doc_/, { timeout: 60_000 });
  await settle(page, 900);

  mark("the letter");
  await caption(page, "What it is, what to do and by when.");
  await page.mouse.move(1000, 300, { steps: 20 });
  await page.waitForTimeout(2400);

  await caption(page, "Every fact points to the sentence it came from.");
  await click(page, objectionEvidence(page));
  await page.waitForTimeout(2800);

  mark("why this date");
  await caption(page, "“Why this date?” Each step with its rule, computed by tested code, not guessed.");
  const verdict = page.getByRole("article", { name: TAX_TITLE });
  await click(page, verdict.getByRole("button", { name: "Why this date?" }));
  const receipt = page.getByRole("dialog", { name: "Why this date?" });
  await receipt.waitFor();
  await page.waitForTimeout(1300);
  await click(page, receipt.getByRole("button", { name: "Show the rules" }));
  await page.waitForTimeout(3800);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);

  mark("a court order (mock mode)");
  await page.goto(`${BASE}${COURT_ORDER}`);
  await settle(page, 300);
  await caption(page, "A court payment order: the law's two weeks, and where to get free advice.");
  await page.mouse.move(1000, 400, { steps: 20 });
  await page.waitForTimeout(2200);
  await pointAt(page, page.getByText("Act now — and get advice", { exact: false }).first());
  await page.waitForTimeout(1200);
  await scrollBy(page, 360);
  await page.waitForTimeout(2600);

  const gifEnd = seconds();
  mark("pay by scan");
  const statement = await documentIdFor(page.context(), STATEMENT_TITLE);
  await page.goto(`${BASE}/documents/${statement}?mock=0`);
  await settle(page, 600);
  await caption(page, "A bill to pay by transfer: scan the GiroCode with your banking app. Nothing is paid for you.");
  await click(page, page.getByRole("main").getByRole("article").first().getByRole("button", { name: /^Pay €/ }));
  await page.getByRole("region", { name: "GiroCode (EPC-QR)" }).waitFor();
  await page.waitForTimeout(3600);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);

  mark("my numbers");
  await caption(page, "My numbers: tax ID, insurance and customer numbers, check digits tested, hidden until you choose.");
  await nav(page, "My numbers");
  await page.mouse.move(760, 380, { steps: 24 });
  await page.waitForTimeout(3200);

  mark("ask");
  await caption(page, "Ask about your letters. Every date and amount is checked against your records.");
  await nav(page, "Ask");
  await click(page, page.getByRole("list", { name: "Suggested questions" }).getByRole("button", { name: PHONE_QUESTION }));
  await page.getByRole("main").getByRole("status").filter({ hasText: "Answer ready." }).waitFor({ timeout: 60_000 });
  await page.waitForTimeout(3800);

  mark("weekly review");
  await caption(page, "The weekly review: ten minutes, one step at a time. Nothing is paid or sent for you.");
  await page.goto(`${BASE}/week`);
  await settle(page, 600);
  await page.mouse.move(420, 380, { steps: 24 });
  await page.waitForTimeout(1400);
  await click(page, weekStep(page, "Pay this week"));
  await page.waitForTimeout(3000);

  mark("timeline");
  await caption(page, "The year ahead: deadlines, payments, contracts and permits in one view.");
  await nav(page, "Timeline");
  await page.mouse.move(760, 380, { steps: 24 });
  await page.waitForTimeout(3200);

  mark("contracts");
  await caption(page, "Contracts: what each one costs and the last day to post a cancellation.");
  await nav(page, "Contracts");
  await page.waitForTimeout(1000);
  await scrollBy(page, 300);
  await page.waitForTimeout(2200);

  mark("proof of sending");
  const draftId = await sendCancellation(page.context());
  await caption(page, "Sent by registered post: the tracking number is checked and the receipt kept as proof.");
  await nav(page, "Letters");
  await click(page, page.getByRole("main").getByRole("link", { name: /FunkNetz/ }).first());
  await page.waitForURL(new RegExp(`/letters/${draftId}$`), { timeout: 60_000 });
  await settle(page, 600);
  await pointAt(page, page.getByRole("region", { name: "Proof of sending" }));
  await page.waitForTimeout(3400);

  mark("how it was read");
  const tax = await documentIdFor(page.context(), TAX_TITLE);
  await caption(page, "How it was read: what Claude was asked, and what code checked and decided.");
  await page.goto(`${BASE}/documents/${tax}?view=trace`);
  await settle(page, 600);
  const steps = page.getByRole("list", { name: "Steps of this reading" });
  await click(page, steps.getByRole("button", { name: /^Claude reads the letter/ }).first());
  await page.waitForTimeout(2600);
  await click(page, steps.getByRole("button", { name: /^Dates computed/ }).first());
  await page.waitForTimeout(2600);

  mark("the end");
  await caption(page, "Everything stays on your computer. Try it: ordnung demo (no Claude account needed).");
  await nav(page, "Today");
  await page.waitForTimeout(3400);
  mark("done");
  return { start, gifEnd };
}

// ------------------------------------------------------------------------------------------------
// Screenshots
// ------------------------------------------------------------------------------------------------

async function shot(page, name, options = {}) {
  // the pointer rests on the sidebar's empty space: no hover tooltip in the picture
  if ((page.viewportSize()?.width ?? 0) >= 1024) await page.mouse.move(120, 600);
  await page.waitForTimeout(500);
  await page.screenshot({ path: join(OUT, `${name}.png`), ...options });
  console.log(`shot → ${name}.png`);
}

/**
 * Ask, on the untouched demo (before the video reads a letter): a recorded answer replays only
 * against the ledger it was recorded from (`ledger_fingerprint`), and this one's check has work to do.
 */
async function askShot(browser) {
  const context = await newContext(browser, { viewport: { width: 1440, height: 1500 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await page.goto(`${BASE}/ask`);
  await settle(page);
  await page.getByRole("list", { name: "Suggested questions" }).getByRole("button", { name: MONEY_QUESTION }).click();
  await page.getByRole("main").getByRole("status").filter({ hasText: "Answer ready." }).waitFor({ timeout: 60_000 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await settle(page);
  await shot(page, "ask");
  await context.close();
}

async function screenshots(browser) {
  const context = await newContext(browser, { deviceScaleFactor: 1 });
  const page = await context.newPage();
  page.on("pageerror", (err) => console.error(`page error: ${err.stack ?? err}`));

  await page.goto(`${BASE}/`);
  await settle(page);
  await shot(page, "today");

  const taxId = await readMail(page, FINANZAMT);
  await page.goto(`${BASE}/documents/${taxId}`);
  await settle(page);
  await objectionEvidence(page).click();
  await page.waitForTimeout(900);
  // the highlight stays on the page image; the letter's verdict card goes back to the top
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(500);
  await shot(page, "document");
  // "Why this date?" as a close-up, in a window tall enough for every rule step
  await page.setViewportSize({ width: 1440, height: 1500 });
  await page.getByRole("article", { name: TAX_TITLE }).getByRole("button", { name: "Why this date?" }).click();
  const receipt = page.getByRole("dialog", { name: "Why this date?" });
  await receipt.getByRole("button", { name: "Show the rules" }).click();
  await page.waitForTimeout(700);
  await receipt.screenshot({ path: join(OUT, "why.png") });
  console.log("shot → why.png");
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 1440, height: 900 });

  // How it was read, with Claude's call and the computed dates opened
  await page.goto(`${BASE}/documents/${taxId}?view=trace`);
  await settle(page);
  const steps = page.getByRole("list", { name: "Steps of this reading" });
  await steps.getByRole("button", { name: /^Claude reads the letter/ }).first().click();
  await steps.getByRole("button", { name: /^Dates computed/ }).first().click();
  await page.waitForTimeout(400);
  await steps.evaluate((el) => window.scrollBy(0, el.getBoundingClientRect().top - 80));
  await settle(page);
  await shot(page, "trace");

  // the Pay panel's GiroCode (a bill read from a PDF: no comparison with the paper letter needed)
  const statementId = await documentIdFor(context, STATEMENT_TITLE);
  await page.goto(`${BASE}/documents/${statementId}`);
  await settle(page);
  await page.getByRole("main").getByRole("article").first().getByRole("button", { name: /^Pay €/ }).click();
  await page.getByRole("region", { name: "GiroCode (EPC-QR)" }).waitFor();
  await settle(page, 800);
  await shot(page, "pay");
  await page.keyboard.press("Escape");

  await page.goto(`${BASE}/week`);
  await settle(page);
  await weekStep(page, "Pay this week").click();
  await settle(page);
  await shot(page, "week");

  for (const [path, name] of [
    ["/numbers", "numbers"],
    ["/timeline", "timeline"],
    ["/contracts", "contracts"],
  ]) {
    await page.goto(`${BASE}${path}`);
    await settle(page);
    await shot(page, name);
  }

  const draftId = await sendCancellation(context);
  await page.goto(`${BASE}/letters/${draftId}`);
  await settle(page, 1000);
  const proof = page.getByRole("region", { name: "Proof of sending" });
  await proof.scrollIntoViewIfNeeded();
  await proof.evaluate((el) => window.scrollBy(0, el.getBoundingClientRect().top - 90));
  await settle(page);
  await shot(page, "proof");

  const scamId = await readMail(page, "Rundfunk-Beitragsservice");
  await page.goto(`${BASE}/documents/${scamId}`);
  await settle(page, 900);
  await shot(page, "scam");
  await context.close();

  const court = await newContext(browser);
  await court.addInitScript(hideDemoTour);
  const courtPage = await court.newPage();
  await courtPage.goto(`${BASE}${COURT_ORDER}`);
  await settle(courtPage, 1200);
  const byWhen = courtPage.getByRole("main").getByText("By when", { exact: true }).first();
  await byWhen.evaluate((el) => window.scrollBy(0, el.getBoundingClientRect().top - 90));
  await settle(courtPage);
  await shot(courtPage, "court-order");
  await court.close();

  const dark = await newContext(browser, { colorScheme: "dark" });
  const darkPage = await dark.newPage();
  await darkPage.goto(`${BASE}/`);
  await darkPage.evaluate(() => localStorage.setItem("ordnung.theme", "dark"));
  await darkPage.reload();
  await settle(darkPage);
  await shot(darkPage, "today-dark");
  await dark.close();

  const phoneOptions = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true };
  const phone = await newContext(browser, phoneOptions);
  const phonePage = await phone.newPage();
  await phonePage.goto(`${BASE}/`);
  await settle(phonePage);
  await shot(phonePage, "mobile");
  await phone.close();

  const phoneDark = await newContext(browser, { ...phoneOptions, colorScheme: "dark" });
  const phoneDarkPage = await phoneDark.newPage();
  await phoneDarkPage.goto(`${BASE}/documents/${taxId}`);
  await phoneDarkPage.evaluate(() => localStorage.setItem("ordnung.theme", "dark"));
  await phoneDarkPage.reload();
  await settle(phoneDarkPage, 900);
  await shot(phoneDarkPage, "mobile-dark");
  await phoneDark.close();
}

// ------------------------------------------------------------------------------------------------

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch(process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {});
try {
  if (opts.only !== "video") await askShot(browser);
  if (opts.only !== "shots") await recordVideo(browser);
  if (opts.only !== "video") await screenshots(browser);
} finally {
  await browser.close();
}
