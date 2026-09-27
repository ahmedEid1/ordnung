import { useEffect, useRef, useState } from "react";
import { prefersReducedMotion } from "@/lib/utils";

export interface SpotRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

/** How far the ring sits outside the element it highlights. */
export const SPOT_PAD = 8;
/** Closest the ring comes to the sides of the screen and to the page's bars. */
const EDGE = 8;

const same = (a: SpotRect | null, b: SpotRect | null) =>
  a === b || (!!a && !!b && a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height);

/**
 * The part of the screen the page shows: below the sticky top bar and above the bottom bars (the
 * phone tab bar, the tour bar or floating card). The page's `scroll-padding` says exactly that
 * (index.css), so read it instead of repeating the bar heights.
 */
function pageArea(): { top: number; bottom: number } {
  const style = window.getComputedStyle(document.documentElement);
  const px = (v: string) => (Number.isFinite(parseFloat(v)) ? parseFloat(v) : 0);
  return { top: px(style.scrollPaddingTop), bottom: px(style.scrollPaddingBottom) };
}

/**
 * The ring around an element's rectangle `r`: {@link SPOT_PAD} outside it, kept on the visible
 * page (8 px from the screen's sides, clear of the top bar and the bottom bars, whose heights are
 * `area.top` / `area.bottom`). A tall element gets a ring around its visible part — never two
 * lines running off the screen. Null when too little of it is on screen.
 */
export function spotlightBox(r: SpotRect, view: { width: number; height: number }, area: { top: number; bottom: number } = { top: 0, bottom: 0 }): SpotRect | null {
  const top = Math.max(r.top - SPOT_PAD, area.top - EDGE, EDGE);
  const left = Math.max(r.left - SPOT_PAD, EDGE);
  const right = Math.min(r.left + r.width + SPOT_PAD, view.width - EDGE);
  const bottom = Math.min(r.top + r.height + SPOT_PAD, view.height - Math.max(area.bottom - EDGE, EDGE));
  if (right - left < 24 || bottom - top < 24) return null;
  return { top, left, width: right - left, height: bottom - top };
}

export interface SpotlightOptions {
  /** Asked when the element is found: may it be scrolled into view? (The tour allows that once per step.) */
  scroll?: () => boolean;
  /** Called when it was brought into view (or already was). */
  onScrolled?: () => void;
}

/**
 * Find `[data-tour="<target>"]` (waiting for lazy pages to render it), scroll it into view when
 * `opts.scroll()` allows, and keep the ring around it ({@link spotlightBox}) up to date while it
 * is shown. Returns null while not found or off screen.
 */
export function useSpotlight(target: string | null, enabled: boolean, opts: SpotlightOptions = {}): SpotRect | null {
  // keyed by target so a rectangle from the previous step is never shown for the next one
  const [state, setState] = useState<{ key: string; rect: SpotRect | null }>({ key: "", rect: null });
  const key = `${target ?? ""}`;
  const optsRef = useRef(opts);
  useEffect(() => {
    optsRef.current = opts;
  });

  useEffect(() => {
    if (!enabled || !target) return;
    let el: HTMLElement | null = null;
    let raf = 0;
    let scrolled = false;
    const selector = `[data-tour="${target}"]`;

    const measure = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        let next: SpotRect | null = null;
        if (el && el.isConnected) {
          const r = el.getBoundingClientRect();
          const view = { width: document.documentElement.clientWidth || window.innerWidth, height: window.innerHeight };
          if (r.width && r.height) next = spotlightBox({ top: r.top, left: r.left, width: r.width, height: r.height }, view, pageArea());
        } else {
          el = null;
        }
        setState((prev) => (prev.key === key && same(prev.rect, next) ? prev : { key, rect: next }));
      });
    };

    const attach = () => {
      const found = document.querySelector<HTMLElement>(selector);
      if (found === el) return;
      el = found;
      if (el && !scrolled && optsRef.current.scroll?.()) {
        scrolled = true;
        const r = el.getBoundingClientRect();
        const behavior: ScrollBehavior = prefersReducedMotion() ? "auto" : "smooth";
        const area = pageArea();
        const top = Math.max(area.top, EDGE);
        const bottom = Math.max(area.bottom, EDGE);
        const room = window.innerHeight - top - bottom;
        const inView = r.top >= top && r.bottom <= window.innerHeight - bottom;
        if (!inView) {
          // centred in the free area when it fits, else its top just below the top bar
          const y = r.height <= room ? r.top - top - (room - r.height) / 2 : r.top - top;
          window.scrollTo({ top: Math.max(0, window.scrollY + y), behavior });
        }
        optsRef.current.onScrolled?.();
      }
      measure();
    };

    attach();
    const mo = new MutationObserver(attach);
    mo.observe(document.body, { childList: true, subtree: true });
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    if (ro) ro.observe(document.body);
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      cancelAnimationFrame(raf);
      mo.disconnect();
      ro?.disconnect();
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [target, enabled, key]);

  return enabled && state.key === key ? state.rect : null;
}
