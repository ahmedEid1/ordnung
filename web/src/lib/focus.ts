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
