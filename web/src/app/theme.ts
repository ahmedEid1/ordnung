/**
 * Light / dark / system theme. Stored in localStorage `ordnung.theme` ("light" | "dark"; absent
 * means "system" — matching the pre-paint script in index.html). Applies `.dark` on <html>.
 */
import { useSyncExternalStore } from "react";

export type ThemePref = "light" | "dark" | "system";
const KEY = "ordnung.theme";

const listeners = new Set<() => void>();

function readPref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

function systemDark(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

let pref: ThemePref = typeof window === "undefined" ? "system" : readPref();

/** Browser-chrome colours: the `--color-canvas` of each theme (index.css). */
export const THEME_COLORS = { light: "#f7f5f0", dark: "#12110e" } as const;

function apply() {
  if (typeof document === "undefined") return;
  const dark = pref === "dark" || (pref === "system" && systemDark());
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
  // index.html has one theme-color per OS scheme (media queries); a chosen theme overrides both
  for (const meta of document.querySelectorAll('meta[name="theme-color"]')) {
    meta.setAttribute("content", dark ? THEME_COLORS.dark : THEME_COLORS.light);
  }
}

/** Set the theme preference (persisted) and apply it. */
export function setTheme(next: ThemePref): void {
  pref = next;
  try {
    if (next === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, next);
  } catch {
    /* storage unavailable */
  }
  apply();
  listeners.forEach((l) => l());
}

/** Call once at start-up: applies the stored preference and follows OS changes in "system". */
export function initTheme(): void {
  apply();
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
    if (pref === "system") {
      apply();
      listeners.forEach((l) => l());
    }
  });
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Current preference + resolved theme. */
export function useTheme(): { pref: ThemePref; resolved: "light" | "dark"; setTheme: typeof setTheme } {
  const p = useSyncExternalStore(subscribe, () => pref, () => "system" as ThemePref);
  const resolved = p === "dark" || (p === "system" && systemDark()) ? "dark" : "light";
  return { pref: p, resolved, setTheme };
}
