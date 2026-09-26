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
 * focus is lost by then, so someone who has moved on is not pulled back (unless `always`: the
 * person asked for it, e.g. "Show more" moves on to the first new card).
 */
export function focusWhenReady(find: () => HTMLElement | null, ms = 5000, { always = false }: { always?: boolean } = {}): void {
  const until = performance.now() + ms;
  const tick = () => {
    const el = find();
    if (!el) {
      if (performance.now() < until) requestAnimationFrame(tick);
      return;
    }
    if (!always && !focusIsLost()) return;
    if (!el.hasAttribute("tabindex")) el.tabIndex = -1;
    el.focus();
  };
  requestAnimationFrame(tick);
}

/**
 * A card is about to leave a list: when its heading is gone, focus the heading now at its place
 * (the next card, or the last one), or `fallbackId` (the section heading) when none is left.
 */
export function focusAfterLeaving(headings: () => HTMLElement[], leavingId: string, fallbackId: string): void {
  const at = Math.max(0, headings().findIndex((h) => h.id === leavingId));
  focusWhenReady(() => {
    if (document.getElementById(leavingId)) return null;
    const rest = headings();
    return rest[Math.min(at, rest.length - 1)] ?? document.getElementById(fallbackId);
  });
}
