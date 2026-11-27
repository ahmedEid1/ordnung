/**
 * Where the window is scrolled when the address changes: a page seen before in this tab comes back where the person
 * left it, a page not seen before starts at its top, and a change within the same page (`?contract=`, `?section=`, a
 * filter) leaves the page where it is, for the page itself to scroll to what the address asks for.
 *
 * In place of React Router's `<ScrollRestoration>`, which decides the same but can scroll LATE: on a page load it
 * puts the saved place through a React transition, which a slowed phone draws only once every query has answered.
 * Its scroll then came after the Contracts page had brought the contract asked for into view, and took the page
 * back (measured at 8x CPU: 458 ms after the card was placed). Here the scroll happens only while the change of
 * address is drawn, before any effect of the new page runs, so a page's own scroll to its card always comes after it
 * and nothing undoes it.
 *
 * Places are kept by pathname (as the router's `getKey` here kept them) in sessionStorage, under the router's own
 * key, so places saved before this change still come back.
 *
 * The router's `preventScrollReset` is no longer read: every navigation that passes it stays on the same pathname,
 * and a change within the same pathname never scrolls here.
 */
import { useLayoutEffect, useRef } from "react";
import { useLocation } from "react-router";

const STORAGE_KEY = "react-router-scroll-positions";

/** The place on each page (by pathname) the person last scrolled to; read once per page load. */
let places: Record<string, number> | null = null;
/** An address was drawn in this page load (the shell can be drawn again: after the standing-by screen). */
let drawnOnce = false;

function saved(): Record<string, number> {
  if (places) return places;
  try {
    const parsed: unknown = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "{}");
    places = parsed && typeof parsed === "object" ? (parsed as Record<string, number>) : {};
  } catch {
    places = {};
  }
  return places;
}

/**
 * The load of this document was a reload, or Back or Forward from another site: its place comes back. A new load
 * (an address typed, a bookmark, a link opened whole) starts at the top, as a page opened new does in the app.
 */
function loadKeepsPlace(): boolean {
  try {
    const load = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
    return load?.type === "reload" || load?.type === "back_forward";
  } catch {
    return false;
  }
}

/** Only for tests: start over, as a new page load would. */
export function resetPageScroll(): void {
  places = null;
  drawnOnce = false;
}

/** Scroll the window for the page now drawn at `pathname` (+ `hash`), arriving with or without its saved place. */
function arrive(pathname: string, hash: string, keepPlace: boolean) {
  const y = keepPlace ? saved()[pathname] : undefined;
  if (typeof y === "number") {
    window.scrollTo(0, y);
    return;
  }
  if (hash) {
    let el: HTMLElement | null = null;
    try {
      el = document.getElementById(decodeURIComponent(hash.slice(1)));
    } catch {
      /* not an id: the top, as for any other page */
    }
    if (el) {
      el.scrollIntoView();
      return;
    }
  }
  window.scrollTo(0, 0);
}

/**
 * Rendered by the shell BEFORE the page, so its layout effect runs first in the commit that draws a new address: a
 * page's own scroll (in a later effect, or once its data has come) always comes after it.
 */
export function PageScroll() {
  const { pathname, hash } = useLocation();
  /** the page the window shows now: its scrolls are its own place */
  const showing = useRef<string | null>(null);

  useLayoutEffect(() => {
    // the browser would put back its own place on a reload, at a moment of its choosing
    window.history.scrollRestoration = "manual";
    const onScroll = () => {
      if (showing.current !== null) saved()[showing.current] = window.scrollY;
    };
    const onHide = () => {
      try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(saved()));
      } catch {
        /* storage full or blocked: places are not kept across loads */
      }
      // a page left for another site and kept by the browser comes back where it was
      window.history.scrollRestoration = "auto";
    };
    const onShow = (e: PageTransitionEvent) => {
      if (e.persisted) window.history.scrollRestoration = "manual";
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("pagehide", onHide);
    window.addEventListener("pageshow", onShow);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("pagehide", onHide);
      window.removeEventListener("pageshow", onShow);
      window.history.scrollRestoration = "auto";
    };
  }, []);

  useLayoutEffect(() => {
    const before = showing.current;
    showing.current = pathname;
    // the same page with another query or hash: the page scrolls to what it asks for, if anything
    if (before === pathname) return;
    // the first address drawn in this load of the document: its place only on a reload, Back or Forward; any
    // later one (a page left within the app, the shell drawn again): its place whenever it was seen before
    arrive(pathname, hash, drawnOnce || loadKeepsPlace());
    drawnOnce = true;
  }, [pathname, hash]);

  return null;
}
