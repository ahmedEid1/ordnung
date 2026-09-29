/**
 * Lightweight mock-mode detection (kept separate from the mock data so the production bundle
 * doesn't include it unless mocks are enabled).
 *
 * `?mock=1` enables mocks for this tab (remembered in sessionStorage), `?mock=full` also opens
 * all New-mail letters, `?mock=0` turns mocks off. A build with `VITE_STATIC_DEMO=1` (the
 * zero-install hosted demo) always uses them.
 */
const KEY = "ordnung.mock";

/**
 * How a note from the online demo about itself starts, in a letter's `warnings` (the mock server writes it: a
 * letter filed as another kind keeps the dates of the kind it was read as). The letter's page shows such a
 * note at the top of its verdict, next to what it is about; the real server never writes one.
 */
export const DEMO_NOTE = "Online demo:";

export function isStaticDemo(): boolean {
  return import.meta.env.VITE_STATIC_DEMO === "1";
}

/** Decide (and remember for this tab) whether to use mocks. */
export function mockMode(): "off" | "on" | "full" {
  if (isStaticDemo()) return "on";
  if (typeof window === "undefined") return "off";
  const param = new URLSearchParams(window.location.search).get("mock");
  try {
    if (param === "0" || param === "off") {
      sessionStorage.removeItem(KEY);
      return "off";
    }
    if (param === "1" || param === "on" || param === "full") {
      sessionStorage.setItem(KEY, param === "full" ? "full" : "on");
      return param === "full" ? "full" : "on";
    }
    const stored = sessionStorage.getItem(KEY);
    return stored === "full" ? "full" : stored === "on" ? "on" : "off";
  } catch {
    return param === "full" ? "full" : param === "1" ? "on" : "off";
  }
}

export function shouldUseMocks(): boolean {
  return mockMode() !== "off";
}
