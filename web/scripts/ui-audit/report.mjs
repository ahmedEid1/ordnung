/**
 * Output of an audit run:
 *
 *   <out>/<target>/<state>/<viewport>-<theme>.png          the viewport as the person sees it
 *   <out>/<target>/<state>/<viewport>-<theme>-tile<N>.png  the full page, ≤ 1600 px per tile
 *   <out>/<target>/findings.json                           every automated finding
 *   <out>/<target>/findings-summary.json                   the same, merged across viewports/themes
 *   <out>/<target>/states.json                             id, group, route, how it was reached, captures
 *   <out>/groups.json                                      review groups (≤ 25 states each)
 *   <out>/index.md                                         counts per group and probe, failed captures
 *
 * A partial run (`--only`) merges into the files of earlier runs.
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { PROBES } from "./probes.mjs";

export const GROUP_ORDER = [
  "today",
  "inbox",
  "document",
  "timeline",
  "contracts",
  "letters",
  "ask",
  "settings",
  "onboarding-and-empty",
  "shell-and-overlays",
  "tour",
  "static-demo",
];
const MAX_GROUP = 25;

const readJson = (file, fallback) => {
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch {
    return fallback;
  }
};

/** Merge this run's results into `<out>/<target>/{states,findings,findings-summary}.json`. */
export function writeTargetReport({ outDir, target, catalog, results }) {
  const dir = join(outDir, target);
  const key = (r) => `${r.state}|${r.viewport}|${r.theme}`;
  const rerun = new Set(results.map(key));
  const rerunStates = new Set(results.map((r) => `${target}/${r.state}`));

  // states.json
  const prev = readJson(join(dir, "states.json"), []);
  const byId = new Map(prev.map((s) => [s.id, s]));
  for (const s of catalog) {
    const id = `${target}/${s.id}`;
    const old = byId.get(id);
    const captures = (old?.captures ?? []).filter((c) => !rerun.has(`${s.id}|${c.viewport}|${c.theme}`));
    for (const r of results.filter((x) => x.state === s.id)) {
      captures.push({ viewport: r.viewport, theme: r.theme, status: r.status, files: r.files, url: r.url, fullHeight: r.fullHeight, notes: r.notes, error: r.error, ms: r.ms, timings: r.timings, findings: r.findings.length });
    }
    captures.sort((a, b) => a.viewport.localeCompare(b.viewport, "en", { numeric: true }) || a.theme.localeCompare(b.theme));
    byId.set(id, { id, folder: `${target}/${s.id}`, target, group: s.group, phase: s.phase, route: s.route, how: s.how, description: s.description, captures });
  }
  // states never captured (a partial run with --only) are left out
  const states = [...byId.values()].filter((s) => s.captures.length);
  writeFileSync(join(dir, "states.json"), JSON.stringify(states, null, 2));

  // findings.json
  const prevFindings = readJson(join(dir, "findings.json"), []).filter((f) => !rerun.has(`${f.state.slice(target.length + 1)}|${f.viewport}|${f.theme}`));
  const findings = [...prevFindings, ...results.flatMap((r) => r.findings)];
  findings.sort((a, b) => a.state.localeCompare(b.state) || a.probe.localeCompare(b.probe) || a.viewport.localeCompare(b.viewport, "en", { numeric: true }) || a.theme.localeCompare(b.theme));
  writeFileSync(join(dir, "findings.json"), JSON.stringify(findings, null, 1));

  // findings-summary.json: one entry per state × probe × element, with where it happens
  const merged = new Map();
  for (const f of findings) {
    const k = `${f.state}|${f.probe}|${f.kind ?? ""}|${f.selector}|${f.probe === "console" || f.probe === "request-failed" ? f.text : ""}`;
    let m = merged.get(k);
    if (!m) {
      m = { state: f.state, probe: f.probe, kind: f.kind ?? null, selector: f.selector, text: f.text, count: 0, where: [], example: { viewport: f.viewport, theme: f.theme, rect: f.rect, detail: f.detail } };
      merged.set(k, m);
    }
    m.count += 1;
    m.where.push(`${f.viewport}-${f.theme}`);
  }
  writeFileSync(join(dir, "findings-summary.json"), JSON.stringify([...merged.values()], null, 1));
  void rerunStates;
  return { states, findings };
}

/** Review groups across targets: every state in exactly one; groups of more than 25 are split. */
export function buildGroups(allStates) {
  const base = new Map();
  for (const g of GROUP_ORDER) base.set(g, []);
  for (const s of allStates) {
    if (!base.has(s.group)) base.set(s.group, []);
    base.get(s.group).push(s.id);
  }
  const groups = [];
  for (const [name, ids] of base) {
    if (!ids.length) continue;
    if (ids.length <= MAX_GROUP) {
      groups.push({ name, states: ids });
      continue;
    }
    const parts = Math.ceil(ids.length / MAX_GROUP);
    const size = Math.ceil(ids.length / parts);
    for (let i = 0; i < parts; i += 1) groups.push({ name: `${name}-${i + 1}`, states: ids.slice(i * size, (i + 1) * size) });
  }
  return groups;
}

const DESCRIPTIONS = {
  today: "Today page: greeting, note, Top 3, Pay panel, receipts, toasts.",
  inbox: "Inbox: New-mail tray (reading, failed, batch recap), filters, search.",
  document: "Letter viewer: every demo letter, the New-mail letters, and its popovers, menus, evidence and page viewer.",
  timeline: "Timeline: life lanes, filters, tooltips, calendar export.",
  contracts: "Contracts: cost summary, Decide by, lanes, tabs, “why these dates”.",
  letters: "Letters: list, composer for each kind, drafts, dialogs, sent letters.",
  ask: "Ask: empty thread, streamed answers with tool traces, citations.",
  settings: "Settings: every section, unsaved changes, validation, confirmations.",
  "onboarding-and-empty": "First run: the onboarding wizard at every step, then every page empty.",
  "shell-and-overlays": "Shell: sidebar, top bar, tab bar, search, add letters, upload progress, drawers, toasts, loading/error screens, 404, design gallery.",
  tour: "The guided demo tour at every step and form.",
  "static-demo": "The zero-install static demo (mock data, hash routes).",
};

export function writeIndex({ outDir, targets, command, viewports, themes, started, finished, partials = [] }) {
  const allStates = [];
  const allFindings = [];
  for (const t of targets) {
    allStates.push(...readJson(join(outDir, t, "states.json"), []));
    allFindings.push(...readJson(join(outDir, t, "findings.json"), []));
  }
  const groups = buildGroups(allStates);
  const stateGroup = new Map();
  for (const g of groups) for (const id of g.states) stateGroup.set(id, g.name);
  writeFileSync(
    join(outDir, "groups.json"),
    JSON.stringify(
      groups.map((g) => ({ name: g.name, description: DESCRIPTIONS[g.name.replace(/-\d+$/, "")] ?? "", states: g.states })),
      null,
      2,
    ),
  );

  // target-size is split: really too small vs. small but spaced far enough apart (WCAG 2.5.8 exception)
  const keyOf = (f) => (f.probe === "target-size" && f.kind !== "undersized" ? "target-size-spaced" : f.probe);
  const probes = Object.keys(PROBES).filter((p) => allFindings.some((f) => keyOf(f) === p));
  const extraProbes = [...new Set(allFindings.map(keyOf))].filter((p) => !probes.includes(p));
  const cols = [...probes, ...extraProbes];
  const count = (fs, p) => fs.filter((f) => keyOf(f) === p).length;

  const lines = [];
  lines.push("# Ordnung UI audit");
  lines.push("");
  lines.push(`Run ${started} → ${finished}${partials.length ? ` (then ${partials.length} partial re-capture${partials.length > 1 ? "s" : ""}, below)` : ""}. Targets: ${targets.join(", ")}. Viewports: ${viewports.join(", ")}. Themes: ${themes.join(", ")}.`);
  lines.push("");
  lines.push("Re-run:");
  lines.push("");
  lines.push("```sh");
  lines.push(command);
  for (const p of partials) lines.push(`# re-captured ${p.started}:`, p.command);
  lines.push("```");
  lines.push("");
  lines.push("## How to read this");
  lines.push("");
  lines.push("- `<target>/<state>/<viewport>-<theme>.png` is the viewport as the person sees it after the state's steps (top of the page unless the steps scrolled).");
  lines.push("- `…-tile<N>.png` is the whole page in bands of at most 1600 px (only when the page is taller or wider than the viewport).");
  lines.push("- In the tiles, fixed and sticky bars are laid out once: the top bar and the sidebar at the top of the page (the sidebar only as tall as the viewport), bottom bars (tab bar, tour bar) at the end of the page where they sit once scrolled down, dialogs/popovers/toasts where they were on screen.");
  lines.push("- `…-FAILED.png` is what was on screen when a capture failed.");
  lines.push("- `<target>/findings.json` has every automated finding (state, viewport, theme, probe, CSS path, text, rect in page px, detail); `findings-summary.json` merges the same element across viewports/themes.");
  lines.push("- `<target>/states.json` says how each state was reached; `groups.json` lists the review groups; `findings-by-group/<group>.json` has each group's findings merged across viewports and themes, most telling probes first.");
  lines.push("- axe-core runs at 390×844 and 1280×800 in both themes; the keyboard walk (40 Tab stops) and the layout probes run everywhere.");
  lines.push("- `truncated` findings are deliberate ellipsis/line-clamp: check `detail.fullText` and whether the full value is available (title, tooltip, elsewhere).");
  lines.push("");
  lines.push("## Probes");
  lines.push("");
  for (const p of cols) lines.push(`- \`${p}\` — ${PROBES[p] ?? p}`);
  lines.push("");

  lines.push("## Findings per target and probe");
  lines.push("");
  lines.push(`| target | states | captures | findings | ${cols.join(" | ")} |`);
  lines.push(`|---|---:|---:|---:|${cols.map(() => "---:").join("|")}|`);
  for (const t of targets) {
    const ss = allStates.filter((s) => s.target === t);
    const fs = allFindings.filter((f) => f.target === t);
    const caps = ss.reduce((n, s) => n + s.captures.filter((c) => c.status === "ok").length, 0);
    lines.push(`| ${t} | ${ss.length} | ${caps} | ${fs.length} | ${cols.map((p) => count(fs, p)).join(" | ")} |`);
  }
  lines.push("");

  lines.push("## Review groups");
  lines.push("");
  lines.push(`| group | states | findings | ${cols.join(" | ")} |`);
  lines.push(`|---|---:|---:|${cols.map(() => "---:").join("|")}|`);
  for (const g of groups) {
    const ids = new Set(g.states);
    const fs = allFindings.filter((f) => ids.has(f.state));
    lines.push(`| ${g.name} | ${g.states.length} | ${fs.length} | ${cols.map((p) => count(fs, p)).join(" | ")} |`);
  }
  lines.push("");
  for (const g of groups) {
    lines.push(`### ${g.name}`);
    lines.push("");
    lines.push(DESCRIPTIONS[g.name.replace(/-\d+$/, "")] ?? "");
    lines.push("");
    for (const id of g.states) {
      const s = allStates.find((x) => x.id === id);
      const fs = allFindings.filter((f) => f.state === id);
      const byProbe = cols.filter((p) => count(fs, p)).map((p) => `${p} ${count(fs, p)}`).join(", ");
      const bad = s.captures.filter((c) => c.status !== "ok");
      lines.push(`- \`${id}\` — ${s.description} _(${s.how})_${byProbe ? ` · ${byProbe}` : ""}${bad.length ? ` · ${bad.length} not captured` : ""}`);
    }
    lines.push("");
  }

  lines.push("## Not captured");
  lines.push("");
  const missing = [];
  for (const s of allStates) for (const c of s.captures) if (c.status !== "ok") missing.push({ s, c });
  const failed = missing.filter((m) => m.c.status === "failed");
  const na = missing.filter((m) => m.c.status === "n/a");
  if (!missing.length) lines.push("Everything was captured.");
  if (failed.length) {
    lines.push(`### Failed (${failed.length})`);
    lines.push("");
    for (const { s, c } of failed) lines.push(`- \`${s.id}\` ${c.viewport} ${c.theme}: ${c.error}`);
    lines.push("");
  }
  if (na.length) {
    lines.push(`### Not applicable at that viewport (${na.length})`);
    lines.push("");
    const byState = new Map();
    for (const { s, c } of na) {
      const k = `${s.id}: ${c.error}`;
      byState.set(k, [...(byState.get(k) ?? []), `${c.viewport} ${c.theme}`]);
    }
    for (const [k, where] of byState) lines.push(`- \`${k.split(": ")[0]}\` (${[...new Set(where.map((w) => w.split(" ")[0]))].join(", ")}): ${k.slice(k.indexOf(": ") + 2)}`);
    lines.push("");
  }
  const notes = new Map();
  for (const s of allStates)
    for (const c of s.captures)
      for (const n of c.notes ?? []) {
        const k = `${s.id}\u0000${n}`;
        notes.set(k, [...(notes.get(k) ?? []), `${c.viewport} ${c.theme}`]);
      }
  if (notes.size) {
    lines.push("### Notes from the steps");
    lines.push("");
    for (const [k, where] of notes) {
      const [id, n] = k.split("\u0000");
      const all = where.length === s_captures(allStates, id);
      lines.push(`- \`${id}\` (${all ? "every capture" : where.join(", ")}): ${n}`);
    }
    lines.push("");
  }
  writeFileSync(join(outDir, "index.md"), lines.join("\n"));
  writeGroupFindings({ outDir, targets, groups });
  return { groups, findings: allFindings.length, states: allStates.length };
}

function s_captures(states, id) {
  return states.find((s) => s.id === id)?.captures.length ?? 0;
}

/** Most telling first; the high-volume, low-signal probes last. */
const PROBE_ORDER = [
  "page-error",
  "page-overflow",
  "offscreen",
  "clipped-text",
  "clipped-content",
  "text-overflow",
  "covered",
  "overlap",
  "focus-hidden",
  "focus-invisible",
  "focus-offscreen",
  "focus-obscured",
  "axe",
  "broken-image",
  "empty-icon",
  "console",
  "request-failed",
  "structure",
  "target-size",
  "truncated",
  "small-text",
];

/**
 * `<out>/findings-by-group/<group>.json`: the group's findings merged across viewports and themes
 * (one entry per state × probe × element, with where it happens), most telling probes first.
 */
export function writeGroupFindings({ outDir, targets, groups }) {
  const dir = join(outDir, "findings-by-group");
  mkdirSync(dir, { recursive: true });
  const all = targets.flatMap((t) => readJson(join(outDir, t, "findings.json"), []));
  const rank = (p) => (PROBE_ORDER.includes(p) ? PROBE_ORDER.indexOf(p) : PROBE_ORDER.length);
  for (const g of groups) {
    const ids = new Set(g.states);
    const merged = new Map();
    for (const f of all) {
      if (!ids.has(f.state)) continue;
      const k = `${f.state}|${f.probe}|${f.kind ?? ""}|${f.selector}|${f.probe === "console" || f.probe === "request-failed" || f.probe === "structure" ? f.text : ""}`;
      let m = merged.get(k);
      if (!m) {
        m = { state: f.state, probe: f.probe, kind: f.kind ?? null, selector: f.selector, text: f.text, where: [], example: { viewport: f.viewport, theme: f.theme, rect: f.rect, detail: f.detail } };
        merged.set(k, m);
      }
      m.where.push(`${f.viewport}-${f.theme}`);
    }
    const list = [...merged.values()].sort((a, b) => rank(a.probe) - rank(b.probe) || a.state.localeCompare(b.state) || b.where.length - a.where.length);
    writeFileSync(join(dir, `${g.name}.json`), JSON.stringify({ group: g.name, states: g.states, findings: list }, null, 1));
  }
}

export function loadExisting(outDir, target) {
  return existsSync(join(outDir, target, "states.json")) ? readJson(join(outDir, target, "states.json"), []) : [];
}
