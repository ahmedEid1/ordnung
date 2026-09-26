/**
 * Evidence geometry and the "anchors" that link facts / to-dos to highlights on the page images.
 *
 * Boxes come from the API in relative page coordinates (0..1, origin top-left). They are drawn as
 * percentage-positioned rectangles over the page image, so they stay aligned at every zoom level.
 * Everything here is pure (unit-tested in `evidence.test.ts`).
 */
import type { Box, DocumentDetail, Evidence, Grounding } from "@/api/types";
import { formatFactValue } from "@/lib/format";

// ------------------------------------------------------------------------------------------------
// Geometry
// ------------------------------------------------------------------------------------------------

const clamp01 = (n: number) => Math.min(1, Math.max(0, Number.isFinite(n) ? n : 0));
const round4 = (n: number) => Math.round(n * 1e4) / 1e4;

/** A well-formed box: corners ordered (x0 ≤ x1, y0 ≤ y1) and clamped to the page. */
export function normalizeBox(b: Box): Box {
  const f = (n: number) => (Number.isFinite(n) ? n : 0);
  const [x0, x1, y0, y1] = [f(b.x0), f(b.x1), f(b.y0), f(b.y1)];
  return {
    page: b.page,
    x0: clamp01(Math.min(x0, x1)),
    y0: clamp01(Math.min(y0, y1)),
    x1: clamp01(Math.max(x0, x1)),
    y1: clamp01(Math.max(y0, y1)),
  };
}

export interface BoxStyle {
  left: string;
  top: string;
  width: string;
  height: string;
}

/**
 * CSS position (percentages of the page) for a highlight rectangle.
 * `padX` / `padY` grow the box by a fraction of the page on each side (a highlighter is a little
 * wider than the glyphs); the result never leaves the page.
 */
export function boxToStyle(box: Box, padX = 0, padY = 0): BoxStyle {
  const b = normalizeBox(box);
  const x0 = clamp01(b.x0 - padX);
  const y0 = clamp01(b.y0 - padY);
  const x1 = clamp01(b.x1 + padX);
  const y1 = clamp01(b.y1 + padY);
  return {
    left: `${round4(x0 * 100)}%`,
    top: `${round4(y0 * 100)}%`,
    width: `${round4((x1 - x0) * 100)}%`,
    height: `${round4((y1 - y0) * 100)}%`,
  };
}

/** Smallest box containing all `boxes` (assumed to be on one page). Null for none. */
export function unionBox(boxes: Box[]): Box | null {
  if (!boxes.length) return null;
  const n = boxes.map(normalizeBox);
  return {
    page: n[0]!.page,
    x0: Math.min(...n.map((b) => b.x0)),
    y0: Math.min(...n.map((b) => b.y0)),
    x1: Math.max(...n.map((b) => b.x1)),
    y1: Math.max(...n.map((b) => b.y1)),
  };
}

/** Group boxes by page number (keeps order within a page). */
export function boxesByPage(boxes: Box[]): Map<number, Box[]> {
  const out = new Map<number, Box[]>();
  for (const b of boxes) {
    const list = out.get(b.page);
    if (list) list.push(b);
    else out.set(b.page, [b]);
  }
  return out;
}

export interface ScrollGeometry {
  /** Page element offset inside the scroll container's content (px). */
  pageTop: number;
  pageLeft: number;
  /** Rendered page size (px). */
  pageWidth: number;
  pageHeight: number;
  /** Visible size of the scroll container (px). */
  viewportWidth: number;
  viewportHeight: number;
  /** Total scrollable content size (px) — used to clamp. */
  contentWidth: number;
  contentHeight: number;
}

/**
 * Scroll position that centres `box` in the scroll container (clamped to the scrollable range).
 * Used when a fact is clicked: the page scrolls so the highlight sits in the middle.
 */
export function centerScrollOffset(box: Box, g: ScrollGeometry): { top: number; left: number } {
  const b = normalizeBox(box);
  const cx = g.pageLeft + ((b.x0 + b.x1) / 2) * g.pageWidth;
  const cy = g.pageTop + ((b.y0 + b.y1) / 2) * g.pageHeight;
  const maxTop = Math.max(0, g.contentHeight - g.viewportHeight);
  const maxLeft = Math.max(0, g.contentWidth - g.viewportWidth);
  return {
    top: Math.round(Math.min(maxTop, Math.max(0, cy - g.viewportHeight / 2))),
    left: Math.round(Math.min(maxLeft, Math.max(0, cx - g.viewportWidth / 2))),
  };
}

// ------------------------------------------------------------------------------------------------
// Anchors: every fact / to-do quote that can be shown on the page
// ------------------------------------------------------------------------------------------------

export type AnchorSource = "fact" | "item";

export interface EvidenceAnchor {
  /** Stable id: `fact:<index>` or `item:<itemId>:<index>`. */
  id: string;
  source: AnchorSource;
  /** Short label shown on the highlight ("Refund", "Pay the parking fine"). */
  label: string;
  /** Optional value ("€324.00"). */
  value?: string;
  evidence: Evidence;
  /** Key of the highlight group this anchor belongs to (anchors with the same boxes share one). */
  group: string;
}

/** Key for "the same highlight": page + rounded box coordinates, or the normalised quote. */
export function highlightKey(e: Evidence): string {
  const boxes = e.boxes.map(normalizeBox);
  if (boxes.length) {
    return boxes.map((b) => `${b.page}:${b.x0.toFixed(3)},${b.y0.toFixed(3)},${b.x1.toFixed(3)},${b.y1.toFixed(3)}`).join("|");
  }
  return `q:${e.page ?? "?"}:${e.quote.replace(/\s+/g, " ").trim().toLowerCase()}`;
}

/** Collect the anchors of a document: key facts first, then the evidence of its to-dos & dates. */
export function collectAnchors(detail: DocumentDetail): EvidenceAnchor[] {
  const docId = detail.document.id;
  const out: EvidenceAnchor[] = [];
  detail.document.key_facts.forEach((f, i) => {
    if (!f.evidence || f.evidence.doc_id !== docId || !f.evidence.quote) return;
    out.push({ id: `fact:${i}`, source: "fact", label: f.label, value: formatFactValue(f.value), evidence: f.evidence, group: highlightKey(f.evidence) });
  });
  for (const it of detail.items) {
    it.evidence.forEach((e, i) => {
      if (e.doc_id !== docId || !e.quote) return;
      out.push({ id: `item:${it.id}:${i}`, source: "item", label: it.title, evidence: e, group: highlightKey(e) });
    });
  }
  return out;
}

export interface HighlightGroup {
  key: string;
  page: number;
  boxes: Box[];
  /** Union of the boxes (the clickable / focusable area). */
  bounds: Box;
  anchors: EvidenceAnchor[];
  grounding: Grounding;
}

/**
 * Drawable highlights: anchors with boxes, de-duplicated (a fact and a to-do quoting the same
 * sentence share one highlight) and split per page.
 */
export function highlightGroups(anchors: EvidenceAnchor[]): HighlightGroup[] {
  const byKey = new Map<string, EvidenceAnchor[]>();
  for (const a of anchors) {
    if (!a.evidence.boxes.length) continue;
    const list = byKey.get(a.group);
    if (list) list.push(a);
    else byKey.set(a.group, [a]);
  }
  const groups: HighlightGroup[] = [];
  for (const [key, list] of byKey) {
    const perPage = boxesByPage(list[0]!.evidence.boxes);
    for (const [page, boxes] of perPage) {
      const bounds = unionBox(boxes)!;
      groups.push({ key: perPage.size > 1 ? `${key}#${page}` : key, page, boxes: boxes.map(normalizeBox), bounds, anchors: list, grounding: list[0]!.evidence.grounding });
    }
  }
  return groups.sort((a, b) => a.page - b.page || a.bounds.y0 - b.bounds.y0);
}

/** Pages that carry at least one highlight (for the thumbnail strip dots). */
export function pagesWithHighlights(groups: HighlightGroup[]): Set<number> {
  return new Set(groups.map((g) => g.page));
}

/** True when an anchor can be shown as a rectangle on the page (vs. a quote callout). */
export function hasBoxes(a: EvidenceAnchor | null | undefined): boolean {
  return Boolean(a && a.evidence.boxes.length > 0);
}
