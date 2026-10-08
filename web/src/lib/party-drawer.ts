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
 *
 * `?party=pty_x&state=ask` opens it at the question about the sender's state (an Idea's "Answer"), with the
 * State heading focused, never Yes; `&state=choose` with the State picker focused ("Other state…" on a letter).
 */
import { useCallback } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router";

export const PARTY_PARAM = "party";
/** Open the drawer's "Note a call" form: `new`, or the id of the thread the call is about. */
export const CALL_PARAM = "call";
/** Open the drawer at the sender's state: `ask` (the question), or `choose` (the State picker). */
export const STATE_PARAM = "state";

export type StateRequest = "ask" | "choose";

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
    (id: string, opts: { noteCall?: { caseId?: string | null }; state?: StateRequest } = {}) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set(PARTY_PARAM, id);
          if (opts.noteCall) next.set(CALL_PARAM, opts.noteCall.caseId || "new");
          else next.delete(CALL_PARAM);
          if (opts.state) next.set(STATE_PARAM, opts.state);
          else next.delete(STATE_PARAM);
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
        next.delete(STATE_PARAM);
        return next;
      },
      { preventScrollReset: true, replace: true },
    );
  }, [setParams, navigate, pushed]);

  return { partyId, open, close };
}

/**
 * The drawer was opened at the sender's state (`?state=`): `asked` is `"ask"` or `"choose"` (`null`: it wasn't);
 * `done` drops the request once it was followed, so a reload doesn't do it again.
 */
export function useStateRequest(): { asked: StateRequest | null; done: () => void } {
  const [params, setParams] = useSearchParams();
  const { state } = useLocation();
  const value = params.get(STATE_PARAM);
  const asked = value === "ask" || value === "choose" ? value : null;
  const done = useCallback(() => {
    setParams(
      (prev) => {
        if (!prev.has(STATE_PARAM)) return prev;
        const next = new URLSearchParams(prev);
        next.delete(STATE_PARAM);
        return next;
      },
      // the entry keeps its mark: a drawer the app opened still closes by going back
      { preventScrollReset: true, replace: true, state },
    );
  }, [setParams, state]);
  return { asked, done };
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
