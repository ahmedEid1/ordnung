/**
 * The People & organisations drawer is URL state (`?party=pty_x`) so it is linkable, works with
 * the back button and can be opened from anywhere (party chips, search, Ask citations).
 *
 * History: opening it in the app pushes an entry (marked in `location.state`), so closing it goes
 * back to that entry — the next Back then leaves the page as expected. A drawer that came with the
 * URL (a shared link, a reload) is closed by replacing the entry instead.
 */
import { useCallback } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router";

export const PARTY_PARAM = "party";

/** `location.state` flag of a history entry the app pushed to open the drawer. */
export const PARTY_PUSHED = "partyPushed";

function pushedHere(state: unknown): boolean {
  return typeof state === "object" && state !== null && (state as Record<string, unknown>)[PARTY_PUSHED] === true;
}

export function usePartyDrawer() {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const partyId = params.get(PARTY_PARAM);
  const pushed = pushedHere(location.state);

  const open = useCallback(
    (id: string) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set(PARTY_PARAM, id);
          return next;
        },
        // a drawer already open (another party) is swapped in place, so one Back still closes it
        { preventScrollReset: true, state: { [PARTY_PUSHED]: true }, replace: pushed },
      );
    },
    [setParams, pushed],
  );

  const close = useCallback(() => {
    if (pushed) {
      void navigate(-1);
      return;
    }
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete(PARTY_PARAM);
        return next;
      },
      { preventScrollReset: true, replace: true },
    );
  }, [setParams, navigate, pushed]);

  return { partyId, open, close };
}
