import { useEffect, useState } from "react";
import { prefersReducedMotion } from "@/lib/utils";

export interface SpotRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

const same = (a: SpotRect | null, b: SpotRect | null) =>
  a === b || (!!a && !!b && a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height);

/**
 * Find `[data-tour="<target>"]` (waiting for lazy pages to render it), scroll it into view once
 * and keep its viewport rectangle up to date while it is shown. Returns null while not found.
 */
export function useSpotlight(target: string | null, enabled: boolean): SpotRect | null {
  // keyed by target so a rectangle from the previous step is never shown for the next one
  const [state, setState] = useState<{ key: string; rect: SpotRect | null }>({ key: "", rect: null });
  const key = `${target ?? ""}`;

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
          if (r.width && r.height) next = { top: r.top, left: r.left, width: r.width, height: r.height };
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
      if (el && !scrolled) {
        scrolled = true;
        const r = el.getBoundingClientRect();
        const behavior: ScrollBehavior = prefersReducedMotion() ? "auto" : "smooth";
        const topBar = 72; // sticky top bar + breathing room
        const fits = r.height < window.innerHeight - topBar - 140; // leave room for the tour card
        const inView = r.top >= topBar && r.bottom <= window.innerHeight - 140;
        if (!inView) {
          const y = fits ? r.top - (window.innerHeight - r.height) / 2 + topBar / 2 : r.top - topBar;
          window.scrollTo({ top: Math.max(0, window.scrollY + y), behavior });
        }
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

/** Left edge of the main content column (so the tour card sits beside the sidebar, not over it). */
export function useMainLeft(): number {
  const [left, setLeft] = useState(0);
  useEffect(() => {
    const update = () => setLeft(document.getElementById("main")?.getBoundingClientRect().left ?? 0);
    const raf = requestAnimationFrame(update);
    const main = document.getElementById("main");
    const ro = typeof ResizeObserver !== "undefined" && main ? new ResizeObserver(update) : null;
    if (ro && main) ro.observe(main);
    window.addEventListener("resize", update);
    return () => {
      cancelAnimationFrame(raf);
      ro?.disconnect();
      window.removeEventListener("resize", update);
    };
  }, []);
  return left;
}
