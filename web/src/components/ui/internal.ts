/**
 * Internal helpers shared by overlay components (Popover, Tooltip, Menu, Dialog, Drawer).
 * Not part of the public design-system surface.
 */
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type Ref, type RefObject } from "react";

export type Placement = "bottom-start" | "bottom-end" | "bottom" | "top-start" | "top-end" | "top" | "right" | "left";

export interface FloatingPosition {
  top: number;
  left: number;
  placement: Placement;
  /** max height available on the chosen side */
  maxHeight: number;
}

const GAP = 6;
const MARGIN = 8;

/** Compute a fixed position for `floating` next to `anchor`, flipping when there is no room. */
export function computePosition(anchor: DOMRect, floating: { width: number; height: number }, placement: Placement): FloatingPosition {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  let side = placement.split("-")[0] as "top" | "bottom" | "left" | "right";
  const align = (placement.split("-")[1] ?? "center") as "start" | "end" | "center";

  if (side === "bottom" && anchor.bottom + GAP + floating.height > vh - MARGIN && anchor.top - GAP - floating.height > MARGIN) side = "top";
  else if (side === "top" && anchor.top - GAP - floating.height < MARGIN && anchor.bottom + GAP + floating.height < vh - MARGIN) side = "bottom";
  else if (side === "right" && anchor.right + GAP + floating.width > vw - MARGIN) side = "left";
  else if (side === "left" && anchor.left - GAP - floating.width < MARGIN) side = "right";

  let top: number;
  let left: number;
  if (side === "bottom" || side === "top") {
    top = side === "bottom" ? anchor.bottom + GAP : anchor.top - GAP - floating.height;
    if (align === "start") left = anchor.left;
    else if (align === "end") left = anchor.right - floating.width;
    else left = anchor.left + anchor.width / 2 - floating.width / 2;
  } else {
    left = side === "right" ? anchor.right + GAP : anchor.left - GAP - floating.width;
    top = anchor.top + anchor.height / 2 - floating.height / 2;
  }
  left = Math.max(MARGIN, Math.min(left, vw - floating.width - MARGIN));
  top = Math.max(MARGIN, Math.min(top, vh - floating.height - MARGIN));
  const maxHeight = side === "bottom" ? vh - anchor.bottom - GAP - MARGIN : side === "top" ? anchor.top - GAP - MARGIN : vh - 2 * MARGIN;
  const finalPlacement = (align === "center" || side === "left" || side === "right" ? side : `${side}-${align}`) as Placement;
  return { top, left, placement: finalPlacement, maxHeight };
}

/** First element with a layout box (skips `display: contents` wrappers). */
export function resolveBox(el: Element | null | undefined): HTMLElement | null {
  let cur: Element | null | undefined = el;
  while (cur && typeof window !== "undefined" && window.getComputedStyle(cur).display === "contents") cur = cur.firstElementChild;
  return (cur as HTMLElement | null) ?? null;
}

/**
 * Keep a floating element positioned next to its anchor while open (scroll/resize aware).
 * Pass DOM elements (e.g. from `useState` callback refs), not ref objects.
 */
export function useFloating(
  anchor: HTMLElement | null,
  floating: HTMLElement | null,
  open: boolean,
  placement: Placement,
): FloatingPosition | null {
  const [pos, setPos] = useState<FloatingPosition | null>(null);

  const update = useCallback(() => {
    const box = resolveBox(anchor);
    if (!box || !floating) return;
    const rect = box.getBoundingClientRect();
    const next = computePosition(rect, { width: floating.offsetWidth, height: floating.offsetHeight }, placement);
    setPos((prev) =>
      prev && prev.top === next.top && prev.left === next.left && prev.placement === next.placement ? prev : next,
    );
  }, [anchor, floating, placement]);

  useLayoutEffect(() => {
    if (!open || !floating) return;
    // measure after the floating element has been laid out
    const raf = requestAnimationFrame(update);
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(update) : null;
    ro?.observe(floating);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
      ro?.disconnect();
      setPos(null);
    };
  }, [open, update, floating]);

  return open ? pos : null;
}

/** Close on outside pointer-down and/or Escape. `inside` are the elements that don't count as outside. */
export function useDismiss(
  open: boolean,
  onClose: () => void,
  inside: (HTMLElement | null)[],
  opts: { escape?: boolean; outside?: boolean } = {},
): void {
  const closeRef = useRef(onClose);
  const insideRef = useRef(inside);
  useEffect(() => {
    closeRef.current = onClose;
    insideRef.current = inside;
  });
  const { escape = true, outside = true } = opts;
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!outside) return;
      const t = e.target as Node;
      if (insideRef.current.some((el) => el?.contains(t))) return;
      closeRef.current();
    };
    const onKey = (e: KeyboardEvent) => {
      if (!escape) return;
      if (e.key === "Escape") {
        e.stopPropagation();
        closeRef.current();
      }
    };
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, escape, outside]);
}

const FOCUSABLE =
  'a[href], area[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), iframe, [tabindex]:not([tabindex="-1"]), [contenteditable="true"]';

export function focusableIn(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => !el.hasAttribute("inert") && el.getAttribute("aria-hidden") !== "true" && (el.offsetParent !== null || el === document.activeElement),
  );
}

let scrollLocks = 0;
let savedOverflow = "";

/**
 * Modal behaviour: focus the dialog container (or `initialFocus`), trap Tab inside, close on
 * Escape, lock body scroll, make the app root inert and restore focus when closed.
 */
export function useModal(
  open: boolean,
  containerRef: RefObject<HTMLElement | null>,
  onClose: () => void,
  initialFocus?: RefObject<HTMLElement | null>,
): void {
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const root = document.getElementById("root");
    if (scrollLocks === 0) savedOverflow = document.body.style.overflow;
    scrollLocks += 1;
    document.body.style.overflow = "hidden";
    root?.setAttribute("inert", "");

    const focusFirst = () => {
      const c = containerRef.current;
      if (!c) return;
      if (!initialFocus?.current && c.contains(document.activeElement)) return; // e.g. an autoFocus input
      // Focus the dialog itself (announced by its label) unless a specific element was requested.
      const target = initialFocus?.current ?? c;
      target.focus({ preventScroll: true });
    };
    const raf = requestAnimationFrame(focusFirst);

    const onKey = (e: KeyboardEvent) => {
      const c = containerRef.current;
      if (!c) return;
      if (e.key === "Escape") {
        e.stopPropagation();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const items = focusableIn(c);
      if (items.length === 0) {
        e.preventDefault();
        c.focus();
        return;
      }
      const first = items[0]!;
      const last = items[items.length - 1]!;
      const active = document.activeElement;
      if (e.shiftKey && (active === first || !c.contains(active))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (active === last || !c.contains(active))) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("keydown", onKey);
      scrollLocks -= 1;
      if (scrollLocks === 0) {
        document.body.style.overflow = savedOverflow;
        root?.removeAttribute("inert");
      }
      previouslyFocused?.focus?.({ preventScroll: true });
    };
  }, [open, containerRef, initialFocus]);
}

/** Merge several refs into one callback ref. */
export function mergeRefs<T>(...refs: (Ref<T> | undefined)[]): (node: T | null) => void {
  return (node) => {
    for (const r of refs) {
      if (!r) continue;
      if (typeof r === "function") r(node);
      else (r as { current: T | null }).current = node;
    }
  };
}

/** Stable id with an optional explicit override. */
export function useStableId(explicit?: string, prefix = "o"): string {
  const id = useId().replace(/:/g, "");
  return explicit ?? `${prefix}-${id}`;
}

/** Portal target for overlays (outside #root so the app can be made inert). */
export function getOverlayRoot(): HTMLElement {
  let el = document.getElementById("overlay-root");
  if (!el) {
    el = document.createElement("div");
    el.id = "overlay-root";
    document.body.appendChild(el);
  }
  return el;
}
