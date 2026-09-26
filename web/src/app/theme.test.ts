/// <reference types="node" />
/**
 * Theme plumbing outside React: the pre-paint script in index.html and `theme.ts` must agree —
 * the `.dark` class, `color-scheme` (native controls and scrollbars) and the browser-chrome
 * `theme-color` all follow the stored choice, or the OS when there is none.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const indexHtml = readFileSync(resolve(__dirname, "../../index.html"), "utf8");
const head = new DOMParser().parseFromString(indexHtml, "text/html").head;
const inlineScript = [...head.querySelectorAll("script:not([src])")].map((s) => s.textContent ?? "").join("\n");

function osPrefersDark(dark: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({ matches: dark && query.includes("dark"), media: query, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  );
}

const themeColors = () => [...document.querySelectorAll('meta[name="theme-color"]')].map((m) => m.getAttribute("content"));

beforeEach(() => {
  // a fresh <head> with the theme-color metas exactly as index.html ships them
  document.head.innerHTML = "";
  for (const meta of head.querySelectorAll('meta[name="theme-color"]')) document.head.appendChild(meta.cloneNode());
  document.documentElement.className = "";
  document.documentElement.style.colorScheme = "";
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("index.html", () => {
  it("covers the whole screen so safe-area insets resolve (notch, home indicator)", () => {
    const viewport = head.querySelector('meta[name="viewport"]')?.getAttribute("content");
    expect(viewport).toBe("width=device-width, initial-scale=1, viewport-fit=cover");
  });

  it("ships a theme-color for each OS scheme", () => {
    expect([...head.querySelectorAll('meta[name="theme-color"]')].map((m) => [m.getAttribute("media"), m.getAttribute("content")])).toEqual([
      ["(prefers-color-scheme: light)", "#f7f5f0"],
      ["(prefers-color-scheme: dark)", "#12110e"],
    ]);
  });

  it.each([
    { stored: null, os: false, dark: false },
    { stored: null, os: true, dark: true },
    { stored: "dark", os: false, dark: true },
    { stored: "light", os: true, dark: false },
  ])("pre-paint: stored $stored, OS dark $os → dark $dark", ({ stored, os, dark }) => {
    osPrefersDark(os);
    if (stored) localStorage.setItem("ordnung.theme", stored);
    new Function(inlineScript)();
    expect(document.documentElement.classList.contains("dark")).toBe(dark);
    expect(document.documentElement.style.colorScheme).toBe(dark ? "dark" : "light");
    expect(themeColors()).toEqual(dark ? ["#12110e", "#12110e"] : ["#f7f5f0", "#f7f5f0"]);
  });
});

describe("theme.ts", () => {
  it("applies a chosen theme to the class, color-scheme and every theme-color", async () => {
    osPrefersDark(false);
    const { setTheme, THEME_COLORS } = await import("./theme");
    setTheme("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.style.colorScheme).toBe("dark");
    expect(themeColors()).toEqual([THEME_COLORS.dark, THEME_COLORS.dark]);
    expect(localStorage.getItem("ordnung.theme")).toBe("dark");

    setTheme("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(document.documentElement.style.colorScheme).toBe("light");
    expect(themeColors()).toEqual([THEME_COLORS.light, THEME_COLORS.light]);
  });

  it("follows the OS when set to system", async () => {
    osPrefersDark(true);
    const { setTheme, THEME_COLORS } = await import("./theme");
    setTheme("system");
    expect(localStorage.getItem("ordnung.theme")).toBeNull();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(themeColors()).toEqual([THEME_COLORS.dark, THEME_COLORS.dark]);
  });
});
