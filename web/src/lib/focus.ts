/**
 * Where keyboard focus goes when a Today card leaves (paid, done, hidden, snoozed) or comes back
 * (Undo): Top 3 and Ideas both hand it to the card now in its place, never to <body>.
 */

/**
 * Focus sits on nothing in particular: <body>, <main> (where a closing toast hands it back), a
 * removed node, or a toast (its Undo was just used and it is on its way out).
 */
export function focusIsLost(): boolean {
  const a = document.activeElement;
  return !a || a === document.body || a.tagName === "MAIN" || !a.isConnected || Boolean(a.closest("[data-toast]"));
}

/**
 * Once `find` returns an element (checked every frame for up to `ms`), focus it — but only when
 * focus is lost by then, so someone who has moved on is not pulled back. `from` (read with
 * {@link focusOrigin} as the action starts): focus also moves while it is still there (the button
 * they pressed), but not once they have gone on to type or choose somewhere else while the answer
 * was on its way. `always`: focus moves wherever it is — only for a failed action's error, which
 * needs reading before anything else (as a refused form's field takes focus). `preventScroll`: the page scrolls
 * to it by itself (smoothly), which a focus scroll would cut short.
 */
export function focusWhenReady(
  find: () => HTMLElement | null,
  ms = 5000,
  { always = false, from = null, preventScroll = false }: { always?: boolean; from?: Element | null; preventScroll?: boolean } = {},
): void {
  const until = performance.now() + ms;
  const tick = () => {
    const el = find();
    if (!el) {
      if (performance.now() < until) requestAnimationFrame(tick);
      return;
    }
    if (!always && !focusIsLost() && !(from && document.activeElement === from)) return;
    if (!el.hasAttribute("tabindex")) el.tabIndex = -1;
    el.focus({ preventScroll });
  };
  requestAnimationFrame(tick);
}

/** Where a toast that holds focus hands it back when it closes (told by `components/ui/Toast`). */
let toastHandsFocusTo: () => Element | null = () => null;

/** For `components/ui/Toast` only: how to find where a closing toast hands focus back. */
export function setToastHandBack(find: () => Element | null): void {
  toastHandsFocusTo = find;
}

/**
 * Where focus is as an action starts, to pass as `from` to {@link focusWhenReady}. An Undo pressed in a
 * toast: the toast closes and hands focus back before the answer is in, so that place is the origin.
 */
export function focusOrigin(): Element | null {
  const a = document.activeElement;
  return a?.closest("[data-toast]") ? toastHandsFocusTo() : a;
}

/**
 * A card is about to leave a list: when its heading is gone, focus the heading now at its place
 * (the next card, or the last one), or `fallbackId` (the section heading) when none is left.
 *
 * Returns `settled`, to call once the change is saved and the lists are refreshed: a card that is
 * still there then (a date of your own that repeats every week moved on to its next day, still
 * among these cards) gets the focus its busy button dropped, on its own heading. If it leaves
 * later after all, the card now in its place takes over as above.
 */
export function focusAfterLeaving(headings: () => HTMLElement[], leavingId: string, fallbackId: string): () => void {
  const at = Math.max(0, headings().findIndex((h) => h.id === leavingId));
  focusWhenReady(
    () => {
      if (document.getElementById(leavingId)) return null;
      const rest = headings();
      return rest[Math.min(at, rest.length - 1)] ?? document.getElementById(fallbackId);
    },
    // watched from the click: the card leaves once the change is saved and the lists
    // are refreshed, which on a busy machine takes longer than the default window. Waiting longer never pulls
    // back someone who moved on — only lost focus is moved.
    LEAVING_WAIT_MS,
  );
  // two frames: the refreshed list is drawn by then (the query cache tells React on a timer)
  return () =>
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        const stayed = document.getElementById(leavingId);
        if (!stayed || !focusIsLost()) return;
        if (!stayed.hasAttribute("tabindex")) stayed.tabIndex = -1;
        stayed.focus();
      }),
    );
}

/** How long a leaving card's successor is waited for (:func:`focusAfterLeaving`). */
export const LEAVING_WAIT_MS = 30_000;

/** The band of the window the bars leave free, in viewport pixels: below the top bar, above the phone's tab bar. */
export interface Band {
  top: number;
  bottom: number;
}

/**
 * Whether an element at `box` (viewport pixels) is in view in `band`, and how to bring it there. One the band can
 * hold is in view whole; one taller than the band is in view when its top is, in the band's upper half (its name
 * and first lines show, under no bar). It comes into view centred, or from its top when it is too tall.
 */
export function revealPlan(box: { top: number; bottom: number }, band: Band): { shown: boolean; block: "center" | "start" } {
  const room = band.bottom - band.top;
  const tall = box.bottom - box.top > room;
  const shown = tall ? box.top >= band.top - 1 && box.top < band.top + room / 2 : box.top >= band.top - 1 && box.bottom <= band.bottom + 1;
  return { shown, block: tall ? "start" : "center" };
}

/**
 * The room the bars really leave, measured where `x` is: from the bottom of a sticky or fixed bar that sits at the
 * top of the window (the top bar, 56 px; none once it scrolls away on a short window), to the top of the fixed bars
 * over its bottom edge (the phone's tab bar, and a tour bar or toast column above it). Not the root's scroll
 * padding: it keeps 16 px more at each edge, so a card that fits between the bars would count as too tall.
 */
export function freeBand(x: number): Band {
  const h = window.innerHeight;
  /** The sticky or fixed box `el` is in, unless it covers half the window or more (a backdrop, not a bar). */
  const barOf = (el: Element): DOMRect | null => {
    for (let e: Element | null = el; e && e !== document.body; e = e.parentElement) {
      const position = getComputedStyle(e).position;
      if (position !== "fixed" && position !== "sticky") continue;
      const r = e.getBoundingClientRect();
      return r.height > 0 && r.height < h / 2 ? r : null;
    }
    return null;
  };
  let top = 0;
  // (jsdom has no elementsFromPoint: no bars there)
  const at = (y: number) => document.elementsFromPoint?.(x, y) ?? [];
  for (const el of at(0.5)) {
    const r = barOf(el);
    if (r && r.top <= 0.5) top = Math.max(top, r.bottom);
  }
  let bottom = h;
  // a bar may float a little above another (the tour bar 0.75rem over the tab bar): look again in that gap above
  // each one found. Whole pixels inside the window: Chromium finds nothing at all at innerHeight - 0.5.
  const gap = parseFloat(getComputedStyle(document.documentElement).fontSize || "16") || 16;
  for (let tries = 0; tries < 4; tries++) {
    let next = bottom;
    const from = Math.min(Math.ceil(bottom), h) - 1;
    for (let y = from; y >= bottom - gap - 1 && next >= bottom; y -= 4) {
      for (const el of at(y)) {
        const r = barOf(el);
        if (r && r.bottom >= bottom - gap - 1 && r.top < next) next = r.top;
      }
    }
    if (next >= bottom) break;
    bottom = next;
  }
  return { top, bottom: Math.max(bottom, top) };
}

/** How many frames in a row nothing may move (the element, the page's height, its scroll) before it is revealed. */
const STILL_FRAMES = 4;
/** How long a revealed element is kept in view while the page still grows around it. */
const REVEAL_WATCH_MS = 6000;
/** When the watch ends in any case (a page that never stands still). */
const REVEAL_GIVE_UP_MS = 20_000;

/**
 * Bring `el` into view once the page has been still for a few frames (a page that opens with it still loads what is
 * above it: scrolled at once, it ended short of it), and again while the page goes on growing, for a few seconds.
 * In view means between the bars ({@link freeBand}, {@link revealPlan}). As soon as the person scrolls (wheel,
 * touch, a key, a press), the watch stops for good: their scroll wins. Returns a stop for the caller (an effect's
 * cleanup).
 */
export function revealWhenStill(el: HTMLElement, { reducedMotion = false }: { reducedMotion?: boolean } = {}): () => void {
  let stopped = false;
  let frame = 0;
  const since = performance.now();
  const events = ["wheel", "touchstart", "keydown", "pointerdown"] as const;
  const stop = () => {
    stopped = true;
    cancelAnimationFrame(frame);
    for (const type of events) window.removeEventListener(type, stop, true);
  };
  for (const type of events) window.addEventListener(type, stop, { capture: true, passive: true });
  let last = "";
  let still = 0;
  const tick = () => {
    if (stopped) return;
    if (!el.isConnected || performance.now() - since > REVEAL_GIVE_UP_MS) return stop();
    const box = el.getBoundingClientRect();
    const now = `${box.top} ${box.height} ${window.scrollY} ${document.documentElement.scrollHeight}`;
    still = now === last ? still + 1 : 0;
    last = now;
    if (still >= STILL_FRAMES) {
      still = 0;
      const x = Math.min(Math.max(box.left + box.width / 2, 0), window.innerWidth - 1);
      const { shown, block } = revealPlan(box, freeBand(x));
      if (shown && performance.now() - since > REVEAL_WATCH_MS) return stop();
      if (!shown) el.scrollIntoView?.({ block, behavior: reducedMotion ? "auto" : "smooth" });
    }
    frame = requestAnimationFrame(tick);
  };
  frame = requestAnimationFrame(tick);
  return stop;
}
