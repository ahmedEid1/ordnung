/**
 * Internal helpers shared by overlay components (Popover, Tooltip, Menu, Dialog, Drawer).
 * Not part of the public design-system surface.
 */
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type Ref, type RefObject } from "react";

export type Placement = "bottom-start" | "bottom-end" | "bottom" | "top-start" | "top-end" | "top" | "right" | "left";
export type Side = "top" | "bottom" | "left" | "right";

export interface FloatingPosition {
  /** CSS `top` (fixed). Unset for the `top` side, which hangs from `bottom` so it grows upwards. */
  top?: number;
  /** CSS `bottom` (fixed), for the `top` side. */
  bottom?: number;
  left: number;
  placement: Placement;
  side: Side;
  /** Height available on the chosen side (between the anchor and the collision insets). */
  maxHeight: number;
}

/** Space a floating element keeps from the viewport edges. */
export interface Insets {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

const GAP = 6;
const MARGIN = 8;
const EDGES: Insets = { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN };
const OPPOSITE: Record<Side, Side> = { top: "bottom", bottom: "top", left: "right", right: "left" };

/** Viewport size without scrollbars (what `position: fixed` is laid out in). */
function viewport(): { width: number; height: number } {
  const el = document.documentElement;
  return { width: el.clientWidth || window.innerWidth, height: el.clientHeight || window.innerHeight };
}

/**
 * The page's collision insets: panels stay clear of the sticky top bar and the fixed bottom bars.
 * Those are exactly what the page's `scroll-padding` keeps focus clear of (index.css), so read it
 * from there instead of repeating the bar heights.
 */
export function pageInsets(): Insets {
  const style = window.getComputedStyle(document.documentElement);
  const px = (v: string) => (Number.isFinite(parseFloat(v)) ? parseFloat(v) : 0);
  return { top: Math.max(MARGIN, px(style.scrollPaddingTop)), right: MARGIN, bottom: Math.max(MARGIN, px(style.scrollPaddingBottom)), left: MARGIN };
}

/** How far the anchor can move by scrolling its container: `up` (scrolling up moves it down, making room above) and `down`. */
export interface ScrollRoom {
  up: number;
  down: number;
}

/**
 * Fixed position for `floating` next to `anchor`. `floating.height` is its natural height (not
 * capped by an earlier max-height). The panel never overlaps its anchor. The side, in order: the
 * preferred side if the panel fits there, the other side if it fits there, then the same two
 * counting what scrolling the page (`scroll`) would free up, else the side with more room.
 * The result has the `maxHeight` of that side as it is now. Pass `side` to keep a side chosen
 * earlier, so a panel doesn't jump while it is open.
 */
export function computePosition(
  anchor: DOMRect,
  floating: { width: number; height: number },
  placement: Placement,
  opts: { insets?: Insets; side?: Side; scroll?: ScrollRoom } = {},
): FloatingPosition {
  const { width: vw, height: vh } = viewport();
  const ins = opts.insets ?? EDGES;
  const preferred = placement.split("-")[0] as Side;
  const align = (placement.split("-")[1] ?? "center") as "start" | "end" | "center";
  const room: Record<Side, number> = {
    top: anchor.top - GAP - ins.top,
    bottom: vh - ins.bottom - anchor.bottom - GAP,
    left: anchor.left - GAP - ins.left,
    right: vw - ins.right - anchor.right - GAP,
  };
  const scrolled: Record<Side, number> = { top: opts.scroll?.up ?? 0, bottom: opts.scroll?.down ?? 0, left: 0, right: 0 };

  let side = opts.side ?? preferred;
  if (!opts.side && (side === "left" || side === "right")) {
    // beside it, or on the other side; with no room on either (a phone), below or above it
    if (room[side] < floating.width) {
      if (room[OPPOSITE[side]] >= floating.width) side = OPPOSITE[side];
      else side = room.bottom >= floating.height || room.bottom >= room.top ? "bottom" : "top";
    }
  } else if (!opts.side) {
    const need = floating.height;
    const other = OPPOSITE[side];
    const most = (s: Side) => room[s] + scrolled[s];
    if (room[side] >= need) side = preferred;
    else if (room[other] >= need) side = other;
    else if (most(side) >= need) side = preferred;
    else if (most(other) >= need || most(other) > most(side)) side = other;
  }

  const clampX = (x: number) => Math.max(ins.left, Math.min(x, vw - ins.right - floating.width));
  const clampY = (y: number) => Math.max(ins.top, Math.min(y, vh - ins.bottom - floating.height));
  const pos: FloatingPosition = { left: 0, side, placement: side, maxHeight: Math.max(0, room[side]) };
  if (side === "bottom" || side === "top") {
    const x = align === "start" ? anchor.left : align === "end" ? anchor.right - floating.width : anchor.left + anchor.width / 2 - floating.width / 2;
    // (a left/right placement that moved below or above is centred: `align` is "center" for those)
    pos.left = clampX(x);
    if (side === "bottom") pos.top = anchor.bottom + GAP;
    else pos.bottom = vh - anchor.top + GAP;
    pos.placement = (align === "center" ? side : `${side}-${align}`) as Placement;
  } else {
    pos.left = clampX(side === "right" ? anchor.right + GAP : anchor.left - GAP - floating.width);
    pos.top = clampY(anchor.top + anchor.height / 2 - floating.height / 2);
    pos.maxHeight = Math.max(0, vh - ins.top - ins.bottom);
  }
  return pos;
}

/** CSS for a computed position (off-screen until the first measurement). */
export function floatingStyle(pos: FloatingPosition | null): { position: "fixed"; top?: number; bottom?: number; left: number } {
  if (!pos) return { position: "fixed", top: -9999, left: -9999 };
  return { position: "fixed", top: pos.top, bottom: pos.bottom, left: pos.left };
}

/** Is `el` a `display: contents` wrapper (the overlays' trigger wrappers carry the `contents` class)? */
function isContents(el: Element): boolean {
  return el.classList.contains("contents") || (typeof window !== "undefined" && window.getComputedStyle(el).display === "contents");
}

/** First element with a layout box (skips `display: contents` wrappers) — e.g. a popover's trigger. */
export function resolveBox(el: Element | null | undefined): HTMLElement | null {
  let cur: Element | null | undefined = el;
  while (cur && isContents(cur)) cur = cur.firstElementChild;
  return (cur as HTMLElement | null) ?? null;
}

/** Natural size of a (possibly max-height-capped, scrolling) element. */
function naturalSize(el: HTMLElement): { width: number; height: number } {
  return { width: el.offsetWidth, height: el.scrollHeight + (el.offsetHeight - el.clientHeight) };
}

/** Nearest ancestor that scrolls vertically (or the page). */
function scrollParent(el: HTMLElement): Element | null {
  for (let n = el.parentElement; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
    const { overflowY } = window.getComputedStyle(n);
    if ((overflowY === "auto" || overflowY === "scroll") && n.scrollHeight > n.clientHeight) return n;
  }
  return document.scrollingElement;
}

/**
 * How far scrolling the anchor's container can move it while it stays in view (below the top bar,
 * above the bottom bars, inside its own scroll area).
 */
function scrollRoom(anchor: HTMLElement, ins: Insets): ScrollRoom & { container: Element | null } {
  const container = scrollParent(anchor);
  if (!container) return { container, up: 0, down: 0 };
  const { height: vh } = viewport();
  const rect = anchor.getBoundingClientRect();
  const page = container === document.scrollingElement;
  const box = page ? { top: 0, bottom: vh } : container.getBoundingClientRect();
  const canDown = container.scrollHeight - container.clientHeight - container.scrollTop;
  const canUp = container.scrollTop;
  return {
    container,
    down: Math.max(0, Math.min(canDown, rect.top - Math.max(ins.top, box.top))),
    up: Math.max(0, Math.min(canUp, Math.min(vh - ins.bottom, box.bottom) - rect.bottom)),
  };
}

/**
 * When the panel is taller than the room on its side, scroll the anchor's container so the whole
 * panel fits — as far as the anchor itself stays in view. Whatever is still missing scrolls
 * inside the panel (which shows scroll shadows).
 */
function scrollToFit(pos: FloatingPosition, height: number, room: ScrollRoom & { container: Element | null }): void {
  if ((pos.side !== "top" && pos.side !== "bottom") || !room.container) return;
  const short = height - pos.maxHeight;
  if (short <= 1) return;
  const delta = pos.side === "bottom" ? Math.min(short, room.down) : -Math.min(short, room.up);
  if (Math.abs(delta) < 1) return;
  const reduce = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  room.container.scrollBy({ top: delta, behavior: reduce ? "instant" : "smooth" });
}

function samePosition(a: FloatingPosition | null, b: FloatingPosition): boolean {
  return Boolean(a && a.top === b.top && a.bottom === b.bottom && a.left === b.left && a.placement === b.placement && a.maxHeight === b.maxHeight);
}

export interface FloatingOptions {
  /** Viewport insets to stay clear of (default: 8 px from every edge; see `pageInsets`). */
  insets?: () => Insets;
  /** Scroll the anchor's container when the panel doesn't fit (default false). */
  scrollToFit?: boolean;
}

/**
 * Keep a floating element positioned next to its anchor while open (scroll/resize aware). The side
 * is chosen once, when it opens; if the content grows later (a section expands, data arrives) the
 * panel keeps its side, and with `scrollToFit` the page scrolls to make room.
 * Pass DOM elements (e.g. from `useState` callback refs), not ref objects.
 */
export function useFloating(
  anchor: HTMLElement | null,
  floating: HTMLElement | null,
  open: boolean,
  placement: Placement,
  options: FloatingOptions = {},
): FloatingPosition | null {
  const [pos, setPos] = useState<FloatingPosition | null>(null);
  const side = useRef<Side | null>(null);
  const lastHeight = useRef(0);
  const optsRef = useRef(options);
  useEffect(() => {
    optsRef.current = options;
  });

  const update = useCallback(
    (measure: boolean) => {
      const box = resolveBox(anchor);
      if (!box || !floating) return;
      const ins = optsRef.current.insets?.() ?? EDGES;
      const size = naturalSize(floating);
      // only when the panel opens or its content changes size — never in reaction to scrolling
      const fit = measure && optsRef.current.scrollToFit && size.height !== lastHeight.current;
      const room = fit ? scrollRoom(box, ins) : null;
      const next = computePosition(box.getBoundingClientRect(), size, placement, { insets: ins, side: side.current ?? undefined, scroll: room ?? undefined });
      side.current = next.side;
      setPos((prev) => (samePosition(prev, next) ? prev : next));
      if (room) scrollToFit(next, size.height, room);
      lastHeight.current = size.height;
    },
    [anchor, floating, placement],
  );

  useLayoutEffect(() => {
    if (!open || !floating) return;
    const measure = () => update(true);
    const follow = () => update(false);
    // measure after the floating element has been laid out
    const raf = requestAnimationFrame(measure);
    window.addEventListener("resize", follow);
    window.addEventListener("scroll", follow, true);
    // the panel and its content: a panel capped by max-height doesn't resize when its content grows
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    ro?.observe(floating);
    for (const child of Array.from(floating.children)) ro?.observe(child);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", follow);
      window.removeEventListener("scroll", follow, true);
      ro?.disconnect();
      side.current = null;
      lastHeight.current = 0;
      setPos(null);
    };
  }, [open, update, floating]);

  return open ? pos : null;
}

// ------------------------------------------------------------------------------------------------
// Escape: only the overlay opened last closes
// ------------------------------------------------------------------------------------------------

const escapeStack: { close: () => void }[] = [];

function onEscapeKey(e: KeyboardEvent): void {
  if (e.key !== "Escape" || e.defaultPrevented) return;
  const top = escapeStack[escapeStack.length - 1];
  if (!top) return;
  e.preventDefault();
  e.stopPropagation();
  top.close();
}

/**
 * Close on Escape while `active`. Overlays stack: Escape closes only the one opened last (a
 * tooltip inside a drawer closes, the drawer stays). Keys a control already handled
 * (`defaultPrevented`) are left alone.
 */
export function useEscape(active: boolean, onEscape: () => void): void {
  const ref = useRef(onEscape);
  useEffect(() => {
    ref.current = onEscape;
  });
  useEffect(() => {
    if (!active) return;
    const entry = { close: () => ref.current() };
    if (escapeStack.length === 0) document.addEventListener("keydown", onEscapeKey);
    escapeStack.push(entry);
    return () => {
      const i = escapeStack.indexOf(entry);
      if (i >= 0) escapeStack.splice(i, 1);
      if (escapeStack.length === 0) document.removeEventListener("keydown", onEscapeKey);
    };
  }, [active]);
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
  useEscape(open && escape, onClose);
  useEffect(() => {
    if (!open || !outside) return;
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (insideRef.current.some((el) => el?.contains(t))) return;
      closeRef.current();
    };
    document.addEventListener("pointerdown", onDown, true);
    return () => document.removeEventListener("pointerdown", onDown, true);
  }, [open, outside]);
}

// ------------------------------------------------------------------------------------------------
// Focus
// ------------------------------------------------------------------------------------------------

const FOCUSABLE =
  'a[href], area[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), iframe, [tabindex]:not([tabindex="-1"]), [contenteditable="true"]';

/** Elements that can take focus (visible, not inert). */
export function focusableIn(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => !el.closest("[inert]") && el.getAttribute("aria-hidden") !== "true" && (el.offsetParent !== null || el === document.activeElement),
  );
}

/** Elements Tab stops on (focusable without a negative tabindex, e.g. not a roving menu item). */
export function tabbableIn(root: HTMLElement): HTMLElement[] {
  return focusableIn(root).filter((el) => el.tabIndex >= 0);
}

/**
 * The Tab stop that follows `el` (popover panels skipped; inert content, e.g. the page behind a
 * dialog, never counts) — where Tab goes when it leaves a panel portaled away from its trigger.
 */
export function tabbableAfter(el: HTMLElement): HTMLElement | null {
  return (
    tabbableIn(document.body).find(
      (t) => !t.closest("[data-popover]") && !el.contains(t) && Boolean(el.compareDocumentPosition(t) & Node.DOCUMENT_POSITION_FOLLOWING),
    ) ?? null
  );
}

/** Panels (e.g. a menu) → the trigger that opened them: where focus goes back when the panel is gone. */
const panelTriggers = new WeakMap<Element, HTMLElement>();

/** Remember which trigger opened `panel`, so a dialog opened from inside it can return focus there. */
export function setPanelTrigger(panel: Element | null, trigger: HTMLElement | null): void {
  if (panel && trigger) panelTriggers.set(panel, trigger);
}

/** The element to return focus to when an overlay opened now closes (read before it takes focus). */
function captureOpener(): HTMLElement[] {
  const active = document.activeElement as HTMLElement | null;
  if (!active || active === document.body) return [];
  const panel = active.closest("[data-popover]");
  const trigger = panel ? panelTriggers.get(panel) : undefined;
  return trigger ? [active, trigger] : [active];
}

/** Focus the first candidate that is still in the page and can take focus. */
function focusFirstOf(candidates: (HTMLElement | null | undefined)[]): void {
  for (const el of candidates) {
    if (!el?.isConnected || el.closest("[inert]")) continue;
    el.focus({ preventScroll: true });
    if (document.activeElement === el) return;
  }
}

let scrollLocks = 0;
let savedOverflow = "";

export interface ModalOptions {
  /** Element to focus first (default: the container itself, announced by its label). */
  initialFocus?: RefObject<HTMLElement | null> | (() => HTMLElement | null | undefined);
  /**
   * Where focus goes on close when the element that opened the modal is gone (e.g. a "Read all"
   * button that disappeared). Default: the page's `<main>`.
   */
  returnFocus?: RefObject<HTMLElement | null>;
}

/**
 * Modal behaviour: focus the dialog container (or `initialFocus`), trap Tab inside, close on
 * Escape, lock body scroll, make the app root inert and restore focus when closed — to the element
 * that had focus when it opened, or to `returnFocus` / `<main>` when that element is gone.
 */
export function useModal(open: boolean, containerRef: RefObject<HTMLElement | null>, onClose: () => void, opts: ModalOptions = {}): void {
  const optsRef = useRef(opts);
  useEffect(() => {
    optsRef.current = opts;
  });

  // Read the opener while rendering the opening — before the commit, where a child's `autoFocus`
  // would already have moved focus into the dialog.
  const [wasOpen, setWasOpen] = useState(false);
  const [opener, setOpener] = useState<HTMLElement[]>([]);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) setOpener(captureOpener());
  }
  const openerRef = useRef(opener);
  useEffect(() => {
    openerRef.current = opener;
  });

  useEscape(open, onClose);

  useEffect(() => {
    if (!open) return;
    const root = document.getElementById("root");
    if (scrollLocks === 0) savedOverflow = document.body.style.overflow;
    scrollLocks += 1;
    document.body.style.overflow = "hidden";
    root?.setAttribute("inert", "");

    const focusFirst = () => {
      const c = containerRef.current;
      if (!c) return;
      const { initialFocus } = optsRef.current;
      const wanted = typeof initialFocus === "function" ? initialFocus() : initialFocus?.current;
      if (!wanted && c.contains(document.activeElement)) return; // e.g. an autoFocus input
      // Focus the dialog itself (announced by its label) unless a specific element was requested.
      (wanted ?? c).focus({ preventScroll: true });
    };
    const raf = requestAnimationFrame(focusFirst);

    const onKey = (e: KeyboardEvent) => {
      const c = containerRef.current;
      if (!c || e.key !== "Tab" || e.defaultPrevented) return;
      // a popover opened from inside the dialog handles its own Tab
      const active = document.activeElement;
      if (active?.closest("[data-popover]") && !c.contains(active)) return;
      const items = tabbableIn(c);
      if (items.length === 0) {
        e.preventDefault();
        c.focus();
        return;
      }
      const first = items[0]!;
      const last = items[items.length - 1]!;
      if (e.shiftKey && (active === first || active === c || !c.contains(active))) {
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
      focusFirstOf([...openerRef.current, optsRef.current.returnFocus?.current, document.querySelector<HTMLElement>("main")]);
    };
  }, [open, containerRef]);
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
