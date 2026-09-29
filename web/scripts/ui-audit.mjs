#!/usr/bin/env node
/**
 * UI audit: every state a person can see, at five viewports and in both themes — screenshots
 * plus automated probes (overflow, clipped text, overlapping or small targets, broken images,
 * keyboard focus, axe-core, console and network errors, tiny text).
 *
 *   node web/scripts/ui-audit.mjs --target demo --port 8811 --data /tmp/audit/demo-data --out /tmp/audit/out
 *   node web/scripts/ui-audit.mjs --target demo,fresh,static --port 8811 --data /tmp/audit/data --out /tmp/audit/out
 *
 * Options:
 *   --target demo|fresh|static (comma list; several targets use ports N, N+1, N+2 in that order
 *            and sub-folders `<data>/<target>`)
 *   --port N         where the target's server runs (started and stopped by the audit)
 *   --data DIR       data folder (demo: reset; fresh: emptied; static: the build output)
 *   --out DIR        screenshots and reports (see scripts/ui-audit/report.mjs)
 *   --only a,b       only these state ids (prefix match with a trailing *, e.g. doc-*)
 *   --viewports …    default 320x640,390x844,768x1024,1280x800,1920x1080
 *   --themes …       default light,dark
 *   --jobs N         parallel browser contexts (default 2)
 *   --reuse          use the server already running on the port
 *   --no-axe / --no-focus   skip those probes; --axe-viewports (default 390x844,1280x800)
 *   --list           print the catalog and exit
 *   --report-only    rebuild index.md / groups.json / findings-by-group from the captures in --out
 *
 * PW_CHROMIUM_PATH selects the Chromium executable. The demo and fresh targets serve the built
 * app (src/ordnung/web/dist) — run `npm run build` after changing web sources.
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync, appendFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { chromium } from "@playwright/test";
import { THEMES, VIEWPORTS } from "./ui-audit/browser.mjs";
import { captureOne } from "./ui-audit/capture.mjs";
import { demoCatalog } from "./ui-audit/catalog/demo.mjs";
import { freshCatalog } from "./ui-audit/catalog/fresh.mjs";
import { staticCatalog } from "./ui-audit/catalog/static.mjs";
import { writeIndex, writeTargetReport } from "./ui-audit/report.mjs";
import { AuditServer, apiClient } from "./ui-audit/servers.mjs";
import { sourceHash } from "./source-hash.mjs";

const WEB_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ORDER = ["demo", "fresh", "static"];

const { values: o } = parseArgs({
  options: {
    target: { type: "string", default: "demo" },
    port: { type: "string", default: "8811" },
    data: { type: "string" },
    out: { type: "string" },
    only: { type: "string" },
    viewports: { type: "string", default: Object.keys(VIEWPORTS).join(",") },
    themes: { type: "string", default: THEMES.join(",") },
    jobs: { type: "string", default: "2" },
    reuse: { type: "boolean", default: false },
    "no-axe": { type: "boolean", default: false },
    "no-focus": { type: "boolean", default: false },
    "axe-viewports": { type: "string", default: "390x844,1280x800" },
    list: { type: "boolean", default: false },
    "report-only": { type: "boolean", default: false },
  },
});

const targets = o.target.split(",").map((t) => t.trim()).filter(Boolean);
for (const t of targets) if (!ORDER.includes(t)) throw new Error(`unknown target "${t}" (demo, fresh or static)`);
targets.sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b));
if (!o.list && !(o["report-only"] && o.out) && (!o.data || !o.out)) {
  console.error("usage: node web/scripts/ui-audit.mjs --target demo|fresh|static --port N --data DIR --out DIR [--only …]");
  process.exit(2);
}
const OUT = o.out ? resolve(o.out) : null;
const viewports = o.viewports.split(",").map((v) => v.trim());
const themes = o.themes.split(",").map((t) => t.trim());
const jobs = Math.max(1, Math.min(Number(o.jobs) || 2, 4));
const axeViewports = new Set(o["axe-viewports"].split(","));
const only = o.only ? o.only.split(",").map((s) => s.trim()) : null;
const wanted = (id) => !only || only.some((p) => (p.endsWith("*") ? id.startsWith(p.slice(0, -1)) : id === p || `${p}` === id));
const opts = {
  axe: (vp) => !o["no-axe"] && axeViewports.has(vp),
  focus: () => !o["no-focus"],
  stepTimeout: 120_000,
};

let logFile = null;
/** Every server this run started, so Ctrl-C stops them too. */
const running = new Set();
const log = (msg) => {
  console.log(msg);
  if (logFile) appendFileSync(logFile, `${msg}\n`);
};

function checkBuild() {
  try {
    const info = JSON.parse(readFileSync(join(WEB_DIR, "..", "src", "ordnung", "web", "dist", "build-info.json"), "utf8"));
    if (info.sourceHash !== sourceHash()) log("! the built app (src/ordnung/web/dist) is older than web/ — run `cd web && npm run build` first to audit the current sources");
  } catch {
    log("! no build-info.json in src/ordnung/web/dist — is the app built?");
  }
}

async function pool(items, n, fn) {
  let i = 0;
  const workers = Array.from({ length: Math.min(n, items.length) }, async () => {
    while (i < items.length) {
      const item = items[i];
      i += 1;
      await fn(item);
    }
  });
  await Promise.all(workers);
}

async function auditTarget(browser, target, index) {
  const port = Number(o.port) + (targets.length > 1 ? ORDER.indexOf(target) : 0);
  const dataDir = resolve(targets.length > 1 ? join(o.data, target === "static" ? "static-build" : `${target}-data`) : o.data);
  const server = new AuditServer({ target, port, dataDir, webDir: WEB_DIR, reuse: o.reuse, log, logDir: join(OUT, "_logs") });
  running.add(server);
  const api = target === "static" ? null : apiClient(server);
  const results = [];
  const catalogStates = [];
  const started = Date.now();
  log(`\n== ${target} (${index + 1}/${targets.length}) on port ${port}`);
  await server.start();
  try {
    const catalog = target === "demo" ? await demoCatalog({ api, server }) : target === "fresh" ? await freshCatalog({ api, server }) : await staticCatalog({ webDir: WEB_DIR });
    const shared = {};
    const restart = async (name) => {
      if (o.reuse) {
        log(`  (reused server: phase "${name}" runs on the same data)`);
        return;
      }
      await server.restart({ dataDir: `${dataDir}-${name}` });
    };
    for (const phase of catalog.phases) {
      for (const s of phase.states) s.phase = phase.name;
      catalogStates.push(...phase.states);
      const states = phase.states.filter((s) => wanted(s.id));
      if (!states.length) continue;
      log(`  phase ${phase.name}: ${states.length} states × ${viewports.length} viewports × ${themes.length} themes${phase.parallel ? ` (${jobs} in parallel)` : " (one at a time)"}`);
      let beforeError = null;
      if (phase.before) {
        try {
          await phase.before({ api, server, restart, shared });
        } catch (err) {
          beforeError = err;
          log(`  ! phase ${phase.name} setup failed: ${err.message}`);
        }
      }
      const combos = states.flatMap((state) => viewports.flatMap((viewport) => themes.map((theme) => ({ state, viewport, theme }))));
      let done = 0;
      const perState = new Map();
      await pool(combos, phase.parallel ? jobs : 1, async ({ state, viewport, theme }) => {
        let r;
        if (beforeError) {
          r = { target, state: state.id, viewport, theme, status: "failed", files: [], findings: [], notes: [], error: `phase setup failed: ${beforeError.message}`, ms: 0 };
        } else {
          r = await captureOne({ browser, server, api, target, state, viewport, theme, outDir: OUT, opts, shared });
        }
        results.push(r);
        done += 1;
        const list = perState.get(state.id) ?? [];
        list.push(r);
        perState.set(state.id, list);
        if (r.status === "failed") log(`    ✗ ${state.id} ${viewport} ${theme}: ${r.error}`);
        if (list.length === viewports.length * themes.length) {
          const ok = list.filter((x) => x.status === "ok").length;
          const na = list.filter((x) => x.status === "n/a").length;
          const n = list.reduce((a, x) => a + x.findings.length, 0);
          const ms = Math.round(list.reduce((a, x) => a + x.ms, 0) / list.length);
          log(`    ${String(done).padStart(4)}/${combos.length} ${state.id}: ${ok} ok${na ? `, ${na} n/a` : ""}${list.length - ok - na ? `, ${list.length - ok - na} failed` : ""}, ${n} findings, ~${ms} ms each`);
        }
      });
      if (phase.after) await phase.after({ api, server }).catch((err) => log(`  ! phase ${phase.name} cleanup failed: ${err.message}`));
    }
  } finally {
    await server.stop();
    running.delete(server);
  }
  mkdirSync(join(OUT, target), { recursive: true });
  const { findings } = writeTargetReport({ outDir: OUT, target, catalog: catalogStates, results });
  log(`  ${target}: ${results.length} captures in ${Math.round((Date.now() - started) / 1000)} s, ${findings.length} findings in ${join(OUT, target, "findings.json")}`);
}

async function main() {
  if (o.list) {
    for (const t of targets) {
      if (t === "static") {
        const c = await staticCatalog({ webDir: WEB_DIR });
        for (const p of c.phases) for (const s of p.states) console.log(`${t}/${s.id}\t${s.group}\t${s.route}`);
      } else {
        console.log(`${t}: the catalog needs a running server (it is built from the API) — run without --list`);
      }
    }
    return;
  }
  mkdirSync(join(OUT, "_logs"), { recursive: true });
  if (o["report-only"]) {
    // rebuild index.md, groups.json and findings-by-group/ from the captures already in --out
    const full = existsSync(join(OUT, "_logs", "full-run.json")) ? JSON.parse(readFileSync(join(OUT, "_logs", "full-run.json"), "utf8")) : { command: "(unknown)", started: "?", finished: "?" };
    const res = writeIndex({ outDir: OUT, targets: ORDER.filter((t) => existsSync(join(OUT, t, "states.json"))), viewports, themes, ...full });
    console.log(`${res.states} states, ${res.findings} findings, ${res.groups.length} review groups → ${join(OUT, "index.md")}`);
    return;
  }
  logFile = join(OUT, "_logs", "audit.log");
  const started = new Date().toISOString();
  log(`UI audit → ${OUT}`);
  checkBuild();
  const browser = await chromium.launch({ executablePath: process.env.PW_CHROMIUM_PATH || undefined });
  const stopAll = async () => {
    await browser.close().catch(() => {});
    for (const s of running) await s.stop().catch(() => {});
  };
  for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => void stopAll().then(() => process.exit(130)));
  try {
    for (const [i, t] of targets.entries()) await auditTarget(browser, t, i);
  } finally {
    await stopAll();
  }
  // a partial re-run (--only) keeps the command and times of the last full run
  const finished = new Date().toISOString();
  let command = `node web/scripts/ui-audit.mjs ${process.argv.slice(2).join(" ")}`;
  let run = { started, finished };
  const fullFile = join(OUT, "_logs", "full-run.json");
  if (!only) writeFileSync(fullFile, JSON.stringify({ command, started, finished, partials: [] }, null, 2));
  else if (existsSync(fullFile)) {
    const full = JSON.parse(readFileSync(fullFile, "utf8"));
    full.partials = [...(full.partials ?? []), { command, started, finished }];
    writeFileSync(fullFile, JSON.stringify(full, null, 2));
    run = { started: full.started, finished: full.finished, partials: full.partials };
    command = full.command;
  }
  const allTargets = ORDER.filter((t) => existsSync(join(OUT, t, "states.json")));
  const { groups, findings, states } = writeIndex({ outDir: OUT, targets: allTargets, command, viewports, themes, ...run });
  writeFileSync(join(OUT, "_logs", "last-command.txt"), `${command}\n`);
  log(`\n${states} states, ${findings} findings, ${groups.length} review groups → ${join(OUT, "index.md")}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
