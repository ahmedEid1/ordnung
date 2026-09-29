/**
 * The People & organisations drawer is URL state (`?party=pty_x`) so it is linkable, works with
 * the back button and can be opened from anywhere (party chips, search, Ask citations).
 *
 * History: opening it in the app pushes an entry (marked in `location.state`), so closing it goes
 * back to that entry — the next Back then leaves the page as expected. A drawer that came with the
 * URL (a shared link, a reload) is closed by replacing the entry instead.
 *
 * `?party=pty_x&call=new` (or `&call=<thread id>`) opens it with its "Note a call" form open (and that
 * thread chosen): "call them — and note what they say" on Waiting for comes with the way to do it.
 */
import { useCallback } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router";

export const PARTY_PARAM = "party";
/** Open the drawer's "Note a call" form: `new`, or the id of the thread the call is about. */
export const CALL_PARAM = "call";

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
    (id: string, opts: { noteCall?: { caseId?: string | null } } = {}) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set(PARTY_PARAM, id);
          if (opts.noteCall) next.set(CALL_PARAM, opts.noteCall.caseId || "new");
          else next.delete(CALL_PARAM);
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
        next.delete(CALL_PARAM);
        return next;
      },
      { preventScrollReset: true, replace: true },
    );
  }, [setParams, navigate, pushed]);

  return { partyId, open, close };
}

/**
 * The drawer was opened to note a call (`?call=`): `asked` is `"new"` or the thread's id (`null`: it
 * wasn't); `done` drops the request once the form is closed or saved, so a reload doesn't reopen it.
 */
export function useNoteCallRequest(): { asked: string | null; done: () => void } {
  const [params, setParams] = useSearchParams();
  const asked = params.get(CALL_PARAM);
  const done = useCallback(() => {
    setParams(
      (prev) => {
        if (!prev.has(CALL_PARAM)) return prev;
        const next = new URLSearchParams(prev);
        next.delete(CALL_PARAM);
        return next;
      },
      { preventScrollReset: true, replace: true },
    );
  }, [setParams]);
  return { asked, done };
}
