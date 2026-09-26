/**
 * The People & organisations drawer is URL state (`?party=pty_x`) so it is linkable, works with
 * the back button and can be opened from anywhere (party chips, search, Ask citations).
 */
import { useCallback } from "react";
import { useSearchParams } from "react-router";

export const PARTY_PARAM = "party";

export function usePartyDrawer() {
  const [params, setParams] = useSearchParams();
  const partyId = params.get(PARTY_PARAM);

  const open = useCallback(
    (id: string) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set(PARTY_PARAM, id);
          return next;
        },
        { preventScrollReset: true },
      );
    },
    [setParams],
  );

  const close = useCallback(() => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete(PARTY_PARAM);
        return next;
      },
      { preventScrollReset: true, replace: true },
    );
  }, [setParams]);

  return { partyId, open, close };
}
