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
 * How far below the top bar a card taller than the room may start and still count as in view: its scroll margins
 * land it 4 px below the bar (room for its focus ring), and this leaves as much again for rounding.
 */
export const TALL_START_SLACK = 8;

/**
 * Whether an element at `box` (viewport pixels) is in view in `band`, and how to bring it there. One the band can
 * hold is in view whole; one taller than the band is in view when it starts just below the top bar, so that its name
 * is the first thing under the bar and it fills the room (anywhere in the upper half was once enough: a card the
 * page then pushed 50 px down counted as in view and stayed there). It comes into view centred, or from its top
 * when it is too tall.
 */
export function revealPlan(box: { top: number; bottom: number }, band: Band): { shown: boolean; block: "center" | "start" } {
  const room = band.bottom - band.top;
  const tall = box.bottom - box.top > room;
  const shown = tall ? box.top >= band.top - 1 && box.top <= band.top + TALL_START_SLACK : box.top >= band.top - 1 && box.bottom <= band.bottom + 1;
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

/** Whether a wheel at `target` scrolls a box of its own that can still go that way (a list, a chart), not the page. */
function scrollsInside(target: EventTarget | null, dy: number): boolean {
  for (let e = target instanceof Element ? target : null; e && e !== document.body && e !== document.documentElement; e = e.parentElement) {
    const overflow = getComputedStyle(e).overflowY;
    if (overflow !== "auto" && overflow !== "scroll") continue;
    if (dy < 0 ? e.scrollTop > 0 : e.scrollTop + e.clientHeight < e.scrollHeight - 1) return true;
  }
  return false;
}

/** Keys that scroll the page: pressed during a reveal's smooth scroll, the person's scroll wins over it. */
const SCROLL_KEYS = new Set(["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "]);
/** Keys that do nothing on their own (the start of Shift+Tab, Control to quiet a screen reader): they change nothing. */
const MODIFIER_KEYS = new Set(["Shift", "Control", "Alt", "AltGraph", "Meta"]);

/** Whether the person's input scrolls the page: a wheel, a touch, or a key that scrolls when no field takes it. */
function scrollsThePage(event: Event): boolean {
  if (event instanceof KeyboardEvent) {
    if (!SCROLL_KEYS.has(event.key) || event.ctrlKey || event.altKey || event.metaKey) return false;
    const t = event.target;
    return !(t instanceof HTMLElement && (t.isContentEditable || t.matches("input, textarea, select")));
  }
  return event.type === "wheel" || event.type === "touchstart";
}

/** How many frames in a row nothing may move (the element, the page's height, its scroll) before it is revealed. */
const STILL_FRAMES = 4;
/** How long a revealed element is kept in view while the page still grows around it. */
const REVEAL_WATCH_MS = 6000;
/** When the watch ends in any case (a page that never stands still). */
const REVEAL_GIVE_UP_MS = 20_000;

/**
 * Bring `el` into view once the page has been still for a few frames (a page that opens with it still loads what is
 * above it: scrolled at once, it ended short of it), and again while the page goes on changing, for a few seconds:
 * content arriving above it, or a bar arriving late over the window's edge (the demo's tour bar loads on its own and
 * can come after the card was placed: a card that fitted then no longer does). In view means between the bars
 * ({@link freeBand}, {@link revealPlan}), measured again each time the page stands still; where the page cannot
 * scroll that far (a card near its end), it is left where its own reveal put it until something changes. As soon as the person scrolls, the watch
 * stops for good: their scroll wins. A wheel, a touch, a key or a press stops it (a modifier key on its own does
 * not); a wheel, a touch or a key that scrolls also stops a smooth scroll of its own still under way, where it is.
 * A scroll that comes with none of those (the scroll bar dragged, an assistive technology scrolling) stops the watch
 * too, seen as the page moving while nothing changed its height and no reveal of its own was under way, or, during
 * one, moving back against it (a scroll of its own never turns round). Returns a stop for the caller (an effect's
 * cleanup).
 */
export function revealWhenStill(el: HTMLElement, { reducedMotion = false }: { reducedMotion?: boolean } = {}): () => void {
  let stopped = false;
  let frame = 0;
  const since = performance.now();
  /** A reveal of its own is under way: from its scrollIntoView until the page is still again. */
  let revealing = false;
  /** Where the page stood still last (its scroll and height), while no reveal of its own was under way. */
  let rest: { y: number; height: number } | null = null;
  /** Where the page stood when it last revealed the card (the card, the scroll, the height and the band). */
  let triedFrom: string | null = null;
  /**
   * During a reveal of its own: the page's height when it began, its scroll a frame ago, and which way the reveal
   * scrolls (1 down, -1 up). Null once the height changed: the browser may then keep the card's place by scrolling
   * either way.
   */
  let own: { height: number; y: number; way: number } | null = null;
  const events = ["wheel", "touchstart", "keydown", "pointerdown"] as const;
  const stop = () => {
    stopped = true;
    cancelAnimationFrame(frame);
    for (const type of events) window.removeEventListener(type, byPerson, true);
  };
  /**
   * The person acts, and the watch stops. If they scroll (a wheel, a touch, a key that scrolls), a smooth scroll of
   * its own still under way stops where it is too (it went on to the card, against their scroll). Stopping it that
   * way, Chromium drops the wheel's own scroll too, so an up-and-down wheel that would scroll the page is done here,
   * from where the page stopped; a sideways one (the lanes chart) goes on as it came. Any other key or press leaves
   * that scroll to reach the card, and a modifier on its own changes nothing at all.
   */
  const byPerson = (event: Event) => {
    if (event instanceof KeyboardEvent && MODIFIER_KEYS.has(event.key)) return;
    if (revealing && !reducedMotion && scrollsThePage(event)) {
      let top = window.scrollY;
      if (
        event instanceof WheelEvent &&
        event.cancelable &&
        !event.ctrlKey &&
        event.deltaY !== 0 &&
        Math.abs(event.deltaY) >= Math.abs(event.deltaX) &&
        !scrollsInside(event.target, event.deltaY)
      ) {
        event.preventDefault();
        top += event.deltaY * (event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 40 : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? window.innerHeight : 1);
      }
      window.scrollTo?.({ top, behavior: "instant" });
    }
    stop();
  };
  // not passive, so that the wheel can be done here (only while the watch runs: a few seconds)
  for (const type of events) window.addEventListener(type, byPerson, { capture: true, passive: false });
  let last = "";
  let still = 0;
  const tick = () => {
    if (stopped) return;
    if (!el.isConnected || performance.now() - since > REVEAL_GIVE_UP_MS) return stop();
    const y = window.scrollY;
    const height = document.documentElement.scrollHeight;
    if (rest && !revealing) {
      // the page moved by a scroll it did not make, its height unchanged: the person's
      if (height === rest.height && Math.abs(y - rest.y) > 1) return stop();
      if (height !== rest.height) rest = null;
    }
    if (own && revealing) {
      if (height !== own.height) own = null;
      else {
        const dy = y - own.y;
        // a scroll of its own goes one way to the card: one that goes back, with no input event (an assistive
        // technology, a script), is someone else's, and wins as the person's wheel does
        if (dy * own.way < -1) return stop();
        own.y = y;
      }
    }
    const box = el.getBoundingClientRect();
    const now = `${box.top} ${box.height} ${y} ${height}`;
    still = now === last ? still + 1 : 0;
    last = now;
    if (still >= STILL_FRAMES) {
      still = 0;
      const x = Math.min(Math.max(box.left + box.width / 2, 0), window.innerWidth - 1);
      const band = freeBand(x);
      const { shown, block } = revealPlan(box, band);
      const where = `${now} ${band.top} ${band.bottom}`;
      revealing = false;
      rest = { y, height };
      // not where it belongs, but its last reveal from here moved nothing: the page goes no further (until it changes)
      const asCloseAsCanBe = !shown && where === triedFrom;
      if ((shown || asCloseAsCanBe) && performance.now() - since > REVEAL_WATCH_MS) return stop();
      if (!shown && !asCloseAsCanBe && el.scrollIntoView) {
        revealing = true;
        rest = null;
        triedFrom = where;
        // which way it goes, known before it moves (a scroll in its first frame is seen too): a card below where it
        // belongs comes up (the page scrolls down), one above it comes down
        const below = block === "start" ? box.top > band.top : box.top >= band.top - 1;
        own = { height, y, way: below ? 1 : -1 };
        el.scrollIntoView({ block, behavior: reducedMotion ? "auto" : "smooth" });
      }
    }
    frame = requestAnimationFrame(tick);
  };
  frame = requestAnimationFrame(tick);
  return stop;
}
