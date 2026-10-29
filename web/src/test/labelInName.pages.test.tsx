/**
 * Label in Name (WCAG 2.5.3) on every page of the app, as axe 4.14 checks it (`label-content-name-mismatch`, see
 * `labelInName`): each link, button or tab named by `aria-label` holds the words it shows, in order. The pages are
 * the real routes against the mock API — the static demo's data — with the Inbox's counts showing (letters to
 * check and letters from the watched folder). jsdom applies no styles, so this reads every text a page holds, also
 * text a breakpoint would hide: stricter than the browser, never looser. axe runs on the real pages in the e2e
 * suite and the UI audit; this keeps a name from drifting from its text between those runs.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup } from "@testing-library/react";
import { __clearToasts } from "@/components/ui/Toast";
import { renderAppAt, stubShellGlobals } from "./app";
import { labelInName } from "./labelInName";
import { useMockApi } from "./mockFetch";

/**
 * The controls axe checks: widgets named from their content. A switch's, checkbox's or radio's name may differ from
 * its text (axe leaves those to a person to judge), so a `<button role="radio">` is not one of them.
 */
const CHECKED = ["a[href]", "button", '[role="button"]', '[role="link"]', '[role="tab"]', '[role="menuitem"]', '[role="option"]', '[role="treeitem"]']
  .map((s) => `${s}[aria-label]:not([role="radio"], [role="switch"], [role="checkbox"], [role="menuitemradio"], [role="menuitemcheckbox"])`)
  .join(", ");

const PAGES = [
  "/",
  "/inbox",
  "/inbox/taxes",
  "/timeline",
  "/contracts",
  "/numbers",
  "/numbers?tab=organisations",
  "/week",
  "/letters",
  "/letters/waiting",
  "/letters/drf_wohnbau",
  "/ask",
  ...["profile", "region", "reminders", "calendar", "folder", "phone", "ai", "claude", "privacy", "rules", "computers", "data"].map((s) => `/settings?section=${s}`),
  ...["doc_tm_dunning", "doc_tm_invoice", "doc_nebenkosten", "doc_parking", "doc_lease", "doc_power", "doc_dismissal", "doc_mahnbescheid", "doc_folder_mail", "doc_scam", "doc_phone"].map((id) => `/documents/${id}`),
];

beforeEach(stubShellGlobals);
afterEach(() => {
  act(() => __clearToasts());
  cleanup();
  vi.unstubAllGlobals();
});

describe("Label in Name on every page", () => {
  for (const width of [390, 1280]) {
    it.each(PAGES)(`%s at ${width} px: every control named by aria-label holds the words it shows`, async (path) => {
      vi.stubGlobal("innerWidth", width);
      vi.stubGlobal("matchMedia", (query: string) => {
        const min = Number(/min-width:\s*(\d+)px/.exec(query)?.[1] ?? 0);
        const max = Number(/max-width:\s*(\d+(?:\.\d+)?)px/.exec(query)?.[1] ?? Infinity);
        return { matches: width >= min && width <= max, media: query, addEventListener() {}, removeEventListener() {} };
      });
      useMockApi();
      await renderAppAt(path);
      const misses = [...document.querySelectorAll(CHECKED)]
        .map((el) => ({ el, ...labelInName(el) }))
        .filter((r) => !r.ok)
        .map((r) => `<${r.el.tagName.toLowerCase()}> shows “${r.shown}”, named “${r.name}”`);
      expect(misses).toEqual([]);
    });
  }
});
