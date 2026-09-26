/**
 * The design tokens and base rules in `index.css` (jsdom has no layout, so these check the
 * stylesheet itself; the Playwright suite checks focus visibility on real pages):
 * scroll padding for the fixed bars, text wrapping, the type scale, the focus ring colour, the
 * identifier font, and a kind palette that is readable and never borrows the danger colour.
 */
/// <reference types="node" />
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { cn } from "@/lib/utils";

// Vitest stubs CSS imports (even `?raw`), so read the stylesheet from disk
const css = readFileSync(resolve(__dirname, "index.css"), "utf8");

/** Body of the `{ … }` block `selector` opens (its last `{`, or the first one after it). */
function block(selector: string): string {
  const at = css.indexOf(selector);
  expect(at, `${selector} in index.css`).toBeGreaterThanOrEqual(0);
  const start = selector.endsWith("{") ? at + selector.length - 1 : css.indexOf("{", at);
  let depth = 0;
  for (let i = start; i < css.length; i++) {
    if (css[i] === "{") depth++;
    else if (css[i] === "}" && --depth === 0) return css.slice(start + 1, i);
  }
  throw new Error(`unbalanced ${selector}`);
}

/** `--name: value;` declarations of a block (nested blocks included). */
function vars(body: string): Record<string, string> {
  return Object.fromEntries([...body.matchAll(/--([\w-]+):\s*([^;]+);/g)].map((m) => [m[1]!, m[2]!.replace(/\/\*.*?\*\//g, "").trim()]));
}

const light = vars(block("@theme"));
const dark = { ...light, ...vars(block("\n.dark {")) };
const base = block("@layer base");

// WCAG relative luminance / contrast
function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
}

describe("scroll padding (focus and jumps stay clear of the fixed bars — WCAG 2.4.11)", () => {
  const html = block("@layer base {\n  html {");

  it("keeps targets below the sticky top bar", () => {
    // TopBar is h-14 (3.5rem) + breathing room
    expect(html).toMatch(/scroll-padding-top:\s*4\.5rem;/);
  });

  it("keeps targets above the phone tab bar, the home indicator and the tour bar", () => {
    expect(html).toMatch(/scroll-padding-bottom:\s*calc\(5rem \+ env\(safe-area-inset-bottom, 0px\) \+ var\(--ordnung-tour-bar, 0px\)\);/);
  });

  it("from tablets up (no tab bar) only leaves room for the tour card", () => {
    expect(html).toMatch(/@variant md\s*{\s*scroll-padding-bottom:\s*calc\(1\.5rem \+ var\(--ordnung-tour-clearance, 0px\)\);/);
  });
});

describe("room under the page for what floats over its bottom edge (<main> — the last buttons scroll clear)", () => {
  const room = block(".room-for-overlays {");

  it("on phones clears the tab bar, the home indicator and the taller of the tour bar and the toasts", () => {
    expect(room).toMatch(
      /padding-bottom:\s*calc\(\s*5rem \+ env\(safe-area-inset-bottom, 0px\) \+\s*max\(var\(--ordnung-tour-bar, 0px\), calc\(var\(--ordnung-toast-lift, 0px\) \+ var\(--ordnung-toast-space, 0px\)\)\)\s*\);/,
    );
  });

  it("from tablets up clears the floating tour card and the (lifted) toast column", () => {
    expect(room).toMatch(
      /@variant md\s*{\s*padding-bottom:\s*max\(\s*1\.5rem,\s*var\(--ordnung-tour-clearance, 0px\),\s*calc\(1\.25rem \+ var\(--ordnung-toast-lift, 0px\) \+ var\(--ordnung-toast-space, 0px\)\)\s*\);/,
    );
  });
});

describe("base rules", () => {
  it("balances headings and avoids one-word last lines in running text, with longhands only", () => {
    expect(base).toMatch(/h1,\s*h2,\s*h3\s*{\s*text-wrap-style:\s*balance;/);
    expect(base).toMatch(/p,\s*dd,\s*li,\s*figcaption,\s*blockquote\s*{\s*text-wrap-style:\s*pretty;/);
    // the `text-wrap` shorthand would also reset text-wrap-mode and undo `truncate`/`whitespace-nowrap`
    expect(base).not.toMatch(/\btext-wrap:/);
  });

  it("gives every element the accent outline colour at rest, so the focus ring never fades in from ink", () => {
    expect(base).toMatch(/\*,\s*::before,\s*::after\s*{\s*outline-color:\s*var\(--color-accent\);/);
    expect(base).toMatch(/:focus-visible\s*{\s*outline:\s*2px solid var\(--color-accent\);/);
  });

  it("lets native controls follow the app theme and keeps content out of the notch", () => {
    expect(block("@layer base {\n  html {")).toMatch(/color-scheme:\s*light;/);
    expect(block("html.dark")).toMatch(/color-scheme:\s*dark;/);
    expect(block("  body {")).toMatch(/padding-inline:\s*env\(safe-area-inset-left, 0px\) env\(safe-area-inset-right, 0px\);/);
  });
});

describe("type scale", () => {
  const px = (rem: string) => parseFloat(rem) * 16;

  it("has one token per step, each with a line height", () => {
    for (const [name, size] of [
      ["2xs", 11],
      ["xs", 12],
      ["sm", 13],
      ["base", 14],
      ["md", 15],
      ["lg", 17],
      ["title", 22],
    ] as const) {
      expect(px(light[`text-${name}`]!), `--text-${name}`).toBe(size);
      expect(light[`text-${name}--line-height`], `--text-${name}--line-height`).toBeTruthy();
    }
    expect(light["text-h1"]).toBe("clamp(1.875rem, 1.25rem + 2.5vw, 2.375rem)");
    expect(light["text-h1--line-height"]).toBe("1.1");
  });

  it("has shared eyebrow and card-title classes built from the scale", () => {
    const components = block("@layer components");
    expect(components).toMatch(/\.eyebrow\s*{\s*@apply text-xs font-semibold uppercase tracking-\[0\.07em\] text-muted;/);
    expect(components).toMatch(/\.card-title\s*{\s*@apply text-md font-semibold leading-snug text-ink;/);
  });

  it("is known to cn(): sizes don't swallow colours and vice versa", () => {
    expect(cn("text-h1", "text-ink")).toBe("text-h1 text-ink");
    expect(cn("text-title", "text-muted")).toBe("text-title text-muted");
    expect(cn("text-2xs text-md", "text-accent")).toBe("text-md text-accent");
    expect(cn("text-sm", "text-base")).toBe("text-base");
    expect(cn("font-sans", "font-ident", "font-semibold")).toBe("font-ident font-semibold");
  });
});

describe("fonts", () => {
  it("sets IBANs and references in the UI face, literally (no contextual arrows)", () => {
    expect(light["font-ident"]).toBe("var(--font-sans)");
    expect(light["font-ident--font-feature-settings"]).toContain('"calt" 0');
  });

  it("prefers a sans monospace over the Courier look-alike for code", () => {
    const stack = light["font-mono"]!;
    expect(stack.indexOf('"DejaVu Sans Mono"')).toBeLessThan(stack.indexOf('"Liberation Mono"'));
    expect(stack).not.toMatch(/Courier/);
    expect(stack.endsWith("monospace")).toBe(true);
  });
});

describe("colour tokens", () => {
  const KINDS = ["deadline", "payment", "appointment", "task", "expiry", "contract", "document", "milestone"];

  it.each([
    ["light", light],
    ["dark", dark],
  ])("%s: a deadline is not an error — its colours differ from danger", (_, t) => {
    expect(t["color-k-deadline"]).not.toBe(t["color-danger"]);
    expect(t["color-k-deadline-soft"]).not.toBe(t["color-danger-soft"]);
    expect(t["color-k-deadline-ink"]).not.toBe(t["color-danger-ink"]);
  });

  it.each([
    ["light", light],
    ["dark", dark],
  ])("%s: kind and status colours are readable (text 4.5:1, icons 3:1)", (_, t) => {
    for (const k of [...KINDS.map((k) => `k-${k}`), "ok", "warn", "danger"]) {
      const ink = t[`color-${k}-ink`]!;
      const soft = t[`color-${k}-soft`]!;
      const icon = t[`color-${k}`]!;
      expect(contrast(ink, soft), `${k}-ink on ${k}-soft`).toBeGreaterThanOrEqual(4.5);
      expect(contrast(ink, t["color-surface"]!), `${k}-ink on surface`).toBeGreaterThanOrEqual(4.5);
      expect(contrast(ink, t["color-canvas"]!), `${k}-ink on canvas`).toBeGreaterThanOrEqual(4.5);
      expect(contrast(icon, t["color-surface"]!), `${k} icon on surface`).toBeGreaterThanOrEqual(3);
      expect(contrast(icon, soft), `${k} icon on ${k}-soft`).toBeGreaterThanOrEqual(3);
    }
  });

  it.each([
    ["light", light],
    ["dark", dark],
  ])("%s: field edges are visible (3:1) and field text and placeholders readable (4.5:1) wherever a field sits", (_, t) => {
    for (const bg of ["surface", "canvas", "surface-2"]) {
      expect(contrast(t["color-control-border"]!, t[`color-${bg}`]!), `control-border on ${bg}`).toBeGreaterThanOrEqual(3);
      expect(contrast(t["color-muted"]!, t[`color-${bg}`]!), `muted (placeholder) on ${bg}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("disabled buttons can be told from busy ones", () => {
    expect(css).toMatch(/@custom-variant inactive \(&:is\(:disabled, \[aria-disabled="true"\]\):not\(\[aria-busy="true"\]\)\);/);
  });

  it("the scrim behind dialogs, drawers and sheets dims the page in both themes", () => {
    const alpha = (v: string) => Number(/\/\s*([\d.]+)\)/.exec(v)?.[1]);
    const channels = (v: string) => (/rgb\((\d+) (\d+) (\d+)/.exec(v) ?? []).slice(1).map(Number);
    for (const t of [light, dark]) {
      expect(t["color-scrim"]).toMatch(/^rgb\(\d+ \d+ \d+ \/ [\d.]+\)$/);
      // a dark tint (never ink, which turns light in dark mode and would lighten the page)
      expect(Math.max(...channels(t["color-scrim"]!))).toBeLessThan(40);
      expect(alpha(t["color-scrim"]!)).toBeGreaterThanOrEqual(0.35);
    }
    expect(dark["color-scrim"]).not.toBe(light["color-scrim"]);
    expect(alpha(dark["color-scrim"]!)).toBeGreaterThan(alpha(light["color-scrim"]!));
  });

  it("the browser-chrome colours match the canvas of each theme", async () => {
    const { THEME_COLORS } = await import("@/app/theme");
    expect(THEME_COLORS.light).toBe(light["color-canvas"]);
    expect(THEME_COLORS.dark).toBe(dark["color-canvas"]);
  });
});
