import { useEffect, useState } from "react";
import { useLocation } from "react-router";

/**
 * Whether the page's `<h1>` (in `#main`) is out of sight under the sticky top bar — or the page
 * has none (yet): the bar then shows the page title, so it never repeats a heading that is still
 * on screen. Follows the heading when it changes (a page loads, Ask starts a thread).
 *
 * Without IntersectionObserver (old browsers, jsdom) it answers `true`: the title always shows.
 */
export function useHeadingUnderBar(bar: HTMLElement | null, enabled: boolean): boolean {
  const { pathname } = useLocation();
  // a new page starts with its heading in view: no flash of the title while it is being observed
  const [state, setState] = useState<{ pathname: string; under: boolean }>({ pathname, under: false });
  const supported = typeof IntersectionObserver !== "undefined";

  useEffect(() => {
    const main = document.getElementById("main");
    if (!enabled || !bar || !main || typeof IntersectionObserver === "undefined") return;
    let heading: Element | null | undefined;
    let io: IntersectionObserver | null = null;
    const set = (under: boolean) => setState((s) => (s.pathname === pathname && s.under === under ? s : { pathname, under }));
    const follow = () => {
      const next = main.querySelector("h1");
      if (next === heading) return;
      heading = next;
      io?.disconnect();
      io = null;
      if (!next) {
        set(true);
        return;
      }
      io = new IntersectionObserver(
        ([entry]) => {
          if (!entry) return;
          // above the bar's bottom edge = scrolled under it; below the fold still counts as "in view"
          const barBottom = entry.rootBounds ? entry.rootBounds.top : bar.getBoundingClientRect().bottom;
          set(!entry.isIntersecting && entry.boundingClientRect.bottom <= barBottom + 1);
        },
        { rootMargin: `-${bar.offsetHeight}px 0px 0px 0px`, threshold: 0 },
      );
      io.observe(next);
    };
    const raf = requestAnimationFrame(follow);
    const mo = new MutationObserver(follow);
    mo.observe(main, { childList: true, subtree: true });
    return () => {
      cancelAnimationFrame(raf);
      mo.disconnect();
      io?.disconnect();
    };
  }, [bar, enabled, pathname]);

  if (!enabled || !supported) return true;
  return state.pathname === pathname ? state.under : false;
}
