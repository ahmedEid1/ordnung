/**
 * One capture = one state at one viewport in one theme: a fresh context, the state's steps,
 * the viewport screenshot, the full page in tiles of at most 1600 px, then the probes
 * (layout a–g/k, axe-core, the keyboard walk) and the console/network log.
 */
import { mkdirSync, readdirSync, rmSync } from "node:fs";
import { join, relative } from "node:path";
import { VIEWPORTS, intentional, newAuditContext, parseViewport, pinToasts, settle, trackNetwork } from "./browser.mjs";
import { axeFindings, focusFindings, layoutFindings, watchPage } from "./probes.mjs";
import { NotApplicable, stepContext } from "./steps.mjs";

export const TILE_HEIGHT = 1600;
const MAX_TILES = 16;

function withTimeout(promise, ms, what) {
  let t;
  return Promise.race([promise, new Promise((_, reject) => (t = setTimeout(() => reject(new Error(`${what} took longer than ${ms / 1000}s`)), ms)))]).finally(() =>
    clearTimeout(t),
  );
}

/**
 * Lay fixed and sticky elements out for a full-page capture (Chromium draws them where they sit in
 * the viewport, i.e. in the middle of a long page): sticky bars go back to their place in the flow,
 * full-width bars fixed to the bottom (tab bar, tour bar) go to the end of the page — where they
 * sit once scrolled to the bottom — and every other fixed element (dialogs, popovers, toasts)
 * stays where it is relative to the content. `restore` undoes it.
 */
function flattenInPage() {
  const vw = document.documentElement.clientWidth;
  const vh = document.documentElement.clientHeight;
  const sy = window.scrollY;
  const sx = window.scrollX;
  const docH = Math.max(document.documentElement.scrollHeight, document.body.scrollHeight);
  const saved = [];
  const set = (el, css) => {
    saved.push([el, el.getAttribute("style")]);
    for (const [k, v] of Object.entries(css)) el.style.setProperty(k, v, "important");
  };
  const all = Array.from(document.body.getElementsByTagName("*"));
  const fixed = [];
  for (const el of all) {
    const s = getComputedStyle(el);
    if (s.position === "sticky") set(el, { position: "relative", top: "auto", bottom: "auto" });
    else if (s.position === "fixed") fixed.push([el, s, el.getBoundingClientRect()]);
  }
  const rootStyle = document.documentElement.getAttribute("style");
  document.documentElement.style.setProperty("position", "relative", "important");
  for (const [el, s, r] of fixed) {
    if (r.width === 0 && r.height === 0) continue;
    if (fixed.some(([o]) => o !== el && o.contains(el))) continue; // moves with its fixed parent
    const bottomBar = s.bottom !== "auto" && r.bottom >= vh - 120 && r.height < vh * 0.3 && r.width >= vw * 0.6;
    const top = bottomBar ? docH - (vh - r.top) : r.top + sy;
    set(el, { position: "absolute", top: `${Math.round(top)}px`, left: `${Math.round(r.left + sx)}px`, right: "auto", bottom: "auto", width: `${r.width}px`, height: `${r.height}px`, transform: "none", margin: "0" });
  }
  window.__uiAuditRestore = () => {
    for (const [el, style] of saved.reverse()) {
      if (style === null) el.removeAttribute("style");
      else el.setAttribute("style", style);
    }
    if (rootStyle === null) document.documentElement.removeAttribute("style");
    else document.documentElement.setAttribute("style", rootStyle);
    window.scrollTo(sx, sy);
  };
}

/** Screenshot the whole page in horizontal bands (full scroll width, at most 1600 px each, equal height). */
async function fullPageTiles(page, dir, stem) {
  const size = await page.evaluate(() => ({
    w: Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth ?? 0),
    h: Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight ?? 0),
    vw: window.innerWidth,
    vh: window.innerHeight,
  }));
  if (size.h <= size.vh + 1 && size.w <= size.vw + 1) return { files: [], height: size.h, width: size.w, truncated: false };
  const width = Math.max(size.w, size.vw);
  const total = Math.ceil(size.h / TILE_HEIGHT);
  const tile = Math.ceil(size.h / total);
  const n = Math.min(total, MAX_TILES);
  const files = [];
  await page.evaluate(flattenInPage);
  try {
    for (let i = 0; i < n; i += 1) {
      const y = i * tile;
      const file = join(dir, `${stem}-tile${i + 1}.png`);
      await page.screenshot({ path: file, fullPage: true, clip: { x: 0, y, width, height: Math.min(tile, size.h - y) }, animations: "disabled", caret: "hide" });
      files.push(file);
    }
  } finally {
    await page.evaluate(() => window.__uiAuditRestore?.()).catch(() => {});
  }
  return { files, height: size.h, width: size.w, truncated: total > MAX_TILES };
}

/**
 * Capture `state` at `viewport` × `theme`. Returns `{ status: ok|n/a|failed, files, findings, … }`;
 * findings carry target, state, viewport and theme.
 */
export async function captureOne({ browser, server, api, target, state, viewport, theme, outDir, opts, shared }) {
  const vp = VIEWPORTS[viewport] ?? parseViewport(viewport);
  const dir = join(outDir, target, state.id);
  mkdirSync(dir, { recursive: true });
  const stem = `${viewport}-${theme}`;
  for (const f of readdirSync(dir)) if (f === `${stem}.png` || f.startsWith(`${stem}-`)) rmSync(join(dir, f), { force: true });

  const t0 = Date.now();
  const timings = {};
  let mark = t0;
  const lap = (name) => {
    const now = Date.now();
    timings[name] = now - mark;
    mark = now;
  };
  const result = { target, state: state.id, viewport, theme, status: "ok", files: [], findings: [], notes: [], error: null, ms: 0, url: null, fullHeight: null };
  let context;
  let watcher;
  let ctx;
  try {
    context = await newAuditContext(browser, { viewport, theme, base: server.base, token: server.token(), storage: state.storage });
    const page = await context.newPage();
    trackNetwork(page);
    page.setDefaultTimeout(15_000);
    page.setDefaultNavigationTimeout(30_000);
    watcher = watchPage(page, { base: server.base, isIntentional: (r) => intentional.has(r) });
    ctx = stepContext({ page, server, api, target, viewport, theme, vp, shared, hash: target === "static" });

    lap("setup");
    await withTimeout(state.run(ctx), opts.stepTimeout ?? 120_000, `the steps of ${state.id}`);
    await settle(page, { idle: state.idle !== false });
    if (state.pinToasts) await pinToasts(page);
    lap("steps");
    result.url = page.url().replace(server.base, "");

    const crashed = await page.getByRole("heading", { name: "Something went wrong on this page" }).count();
    if (crashed && !(state.expectErrorScreen || ctx.expectErrorScreen)) {
      result.findings.push({ probe: "page-error", kind: "error-screen", selector: "h1", text: "The page shows “Something went wrong on this page”", rect: null, detail: {} });
    }

    const shot = join(dir, `${stem}.png`);
    await page.screenshot({ path: shot, animations: "disabled", caret: "hide" });
    result.files.push(shot);
    lap("screenshot");
    const layout = await layoutFindings(page);
    result.findings.push(...layout.findings);
    lap("layout");
    if (opts.axe(viewport, theme)) {
      try {
        result.findings.push(...(await axeFindings(page)));
      } catch (err) {
        ctx.note(`axe failed: ${err.message.split("\n")[0]}`);
      }
      lap("axe");
    }
    // the full page last before the keyboard walk: it re-lays out fixed/sticky bars (and restores them)
    const tiles = await fullPageTiles(page, dir, stem);
    result.files.push(...tiles.files);
    result.fullHeight = tiles.height;
    if (tiles.truncated) ctx.note(`page is ${tiles.height}px tall: only the first ${MAX_TILES} tiles were saved`);
    lap("tiles");

    if (opts.focus(viewport, theme)) {
      try {
        const focus = await focusFindings(page, { max: 40 });
        result.findings.push(...focus.findings);
        result.focusStops = focus.stops;
      } catch (err) {
        ctx.note(`focus walk failed: ${err.message.split("\n")[0]}`);
      }
      lap("focus");
    }
  } catch (err) {
    if (err instanceof NotApplicable) {
      result.status = "n/a";
      result.error = err.message;
    } else {
      result.status = "failed";
      result.error = String(err.message ?? err).split("\n")[0].slice(0, 400);
      try {
        const pages = context?.pages() ?? [];
        if (pages[0]) {
          const f = join(dir, `${stem}-FAILED.png`);
          await pages[0].screenshot({ path: f, timeout: 5000 });
          result.files.push(f);
        }
      } catch {
        /* nothing to show */
      }
    }
  } finally {
    if (watcher) {
      // a state that crashes the page on purpose logs React's error: expected, not a finding
      const logged = watcher.stop();
      result.findings.push(...(state.expectErrorScreen ? logged.filter((f) => f.probe !== "console") : logged));
    }
    if (ctx) result.notes = ctx.notes;
    await context?.close().catch(() => {});
    result.ms = Date.now() - t0;
    result.timings = timings;
  }
  if (result.status === "n/a") result.findings = [];
  result.files = result.files.map((f) => relative(outDir, f));
  result.findings = result.findings.map((f) => ({ target, state: `${target}/${state.id}`, viewport, theme, ...f }));
  return result;
}
