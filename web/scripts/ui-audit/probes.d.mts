/**
 * Types for `probes.mjs`, so the e2e specs (TypeScript) can reuse the UI audit's probes.
 */
import type { Page } from "@playwright/test";

/** Where a finding sits, in page coordinates (CSS px, scroll offset included). */
export interface FindingRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Finding {
  probe: string;
  kind?: string;
  selector: string;
  text: string;
  rect: FindingRect | null;
  detail: Record<string, unknown>;
}

export const AXE_TAGS: string[];
export const PROBES: Record<string, string>;

/** Layout probes a–g and k for the page as it is now (the covered check scrolls, then restores). */
export function layoutFindings(page: Page, opts?: { max?: number }): Promise<{ findings: Finding[]; meta: { interactive: number; scrollHeight: number } }>;

/** Tab through up to `max` stops and check each one's focus indicator and visibility. */
export function focusFindings(page: Page, opts?: { max?: number }): Promise<{ findings: Finding[]; stops: number }>;

/** axe-core with the WCAG 2.2 A/AA tags (one finding per failing node). */
export function axeFindings(page: Page, opts?: { tags?: string[] }): Promise<Finding[]>;

/** Listen for console errors, page errors and failed requests until `stop()`. */
export function watchPage(
  page: Page,
  opts?: { base?: string; isIntentional?: (request: import("@playwright/test").Request) => boolean },
): { stop(): Finding[] };
