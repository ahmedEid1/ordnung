/**
 * Mutations used across the Document viewer, wrapped with calm confirmation toasts and "Undo".
 * Nothing is ever changed without an explicit click (SPEC §21).
 */
import { useCallback, useState } from "react";
import { useNavigate } from "react-router";
import type { DraftKind, Item } from "@/api/types";
import { api } from "@/api/endpoints";
import { useConfirmItem, useCreateDraft, useUpdateItem } from "@/api/hooks";
import { toast } from "@/components/ui/Toast";
import { doneLine } from "@/features/items/repeat";
import { formatDate } from "@/lib/format";
import { useTodayISO } from "@/lib/today";
import { ignoreFailedRequest } from "@/api/client";
import { focusOrigin } from "@/lib/focus";
import { useOnePress } from "@/lib/hooks";

/**
 * The date a repeating to-do stood at when "done" or "open again" was pressed (`seen_due_date`): the server leaves it
 * as it is when it has moved since, so the same press sent twice moves it once. Only a repeating to-do moves on: one
 * that doesn't sends what it always sent.
 */
export function seenAt(item: Pick<Item, "recurrence">, date: string | null): { seen_due_date?: string | null } {
  return item.recurrence ? { seen_due_date: date } : {};
}

/**
 * The to-do actions of one place (a list row, the verdict card, a letter's warnings), one press at a time: a second
 * press while the first one's request is on its way does nothing, also one that comes before the button is drawn
 * busy (`useOnePress`). `pressed` is the to-do whose change is on its way (show its buttons busy), until the answer
 * is in, worked or failed. A "done" and its "open again" name the date the to-do stood at (`seenAt`): the server then
 * moves a repeating to-do on once, however often the same press reaches it (another tab, the phone).
 */
export function useItemActions() {
  const update = useUpdateItem();
  const confirm = useConfirmItem();
  const today = useTodayISO();
  const { pressed, once } = useOnePress<string>();

  // Each Undo returns its request's promise: the toast stays busy until it is done, and knows when it failed (focus
  // then stays near the change instead of dropping to the top of the page).

  /**
   * Done, with Undo; `title` names what was done ("Marked as paid" after the Pay panel, as on Today). `onDone`
   * runs once it is saved and the letter's to-dos are refreshed: where focus goes when the button pressed has gone.
   * `focusAfterUndo`: where focus goes when the Undo's refresh takes away the place the toast handed it back to.
   */
  const markDone = useCallback(
    (
      item: Item,
      {
        title = "Marked as done",
        onDone,
        onFailed,
        focusAfterUndo,
      }: { title?: string; onDone?: () => void; onFailed?: () => void; focusAfterUndo?: () => HTMLElement | null } = {},
    ) =>
      once(
        () =>
          update.mutateAsync(
            { id: item.id, patch: { status: "done", ...seenAt(item, item.due_date) } },
            {
              onError: () => onFailed?.(),
              onSuccess: (moved) => {
                onDone?.();
                toast.success(title, {
                  description: doneLine(item, moved, today),
                  // back from the date it moved to: an Undo that comes again once it is back changes nothing
                  undo: () => update.mutateAsync({ id: item.id, patch: { status: "open", ...seenAt(item, moved.due_date) } }).then(() => undefined),
                  focusAfterUndo,
                });
              },
            },
          ),
        item.id,
      ),
    [update, today, once],
  );

  const reopen = useCallback(
    (item: Item) => once(() => update.mutateAsync({ id: item.id, patch: { status: "open", ...seenAt(item, item.due_date) } }), item.id),
    [update, once],
  );

  /**
   * "Not a real to-do", with Undo; `onUndone` runs once the Undo is saved (to give the to-do back its focus), with
   * where focus was as the Undo was pressed (`focusOrigin`: from the toast, where the closing toast hands it back).
   */
  const dismiss = useCallback(
    (item: Item, { onUndone }: { onUndone?: (from: Element | null) => void } = {}) =>
      once(
        () =>
          update.mutateAsync(
            { id: item.id, patch: { status: "dismissed" } },
            {
              onSuccess: () =>
                toast({
                  title: "Removed from your to-dos",
                  description: `“${item.title}” won't remind you. The letter stays filed.`,
                  undo: () => {
                    const from = focusOrigin();
                    return update.mutateAsync({ id: item.id, patch: { status: "open" } }).then(() => onUndone?.(from));
                  },
                }),
            },
          ),
        item.id,
      ),
    [update, once],
  );

  const changeDate = useCallback(
    (item: Item, date: string, onDone?: () => void) =>
      once(
        () =>
          update.mutateAsync(
            { id: item.id, patch: { due_date: date } },
            {
              onSuccess: () => {
                onDone?.();
                toast.success(`Date changed to ${formatDate(date, { style: "short" })}`, {
                  // a repeating to-do's new date stands in for this one only (ordnung.recurrence, point 7)
                  description: item.recurrence ? "Only this one moves — the ones after keep their day." : "You set this date yourself, so Ordnung won't overwrite it.",
                  undo: item.due_date ? () => update.mutateAsync({ id: item.id, patch: { due_date: item.due_date } }).then(() => undefined) : undefined,
                });
              },
            },
          ),
        item.id,
      ),
    [update, once],
  );

  const confirmItem = useCallback(
    (item: Item) =>
      once(
        () =>
          confirm.mutateAsync(item.id, {
            onSuccess: () => toast.success("Thanks — confirmed", { description: `“${item.title}” is marked as checked by you.` }),
          }),
        item.id,
      ),
    [confirm, once],
  );

  return { markDone, reopen, dismiss, changeDate, confirmItem, pressed, pending: pressed !== null };
}

/** Create a draft letter (objection / cancellation / reply) and open it in Letters. */
export function useStartDraft() {
  const create = useCreateDraft();
  const navigate = useNavigate();
  const [looking, setLooking] = useState(false);
  // one letter per press: two presses before the button is drawn busy both looked for a letter being drafted, found
  // none, and wrote two
  const { busy, once } = useOnePress();
  const start = useCallback(
    async (kind: DraftKind, refs: { doc_id?: string | null; contract_id?: string | null; party_id?: string | null; case_id?: string | null }) => {
      // a second click opens the letter already being drafted for this letter/contract instead of a copy
      setLooking(true);
      // a failed request: start a new letter (one being drafted already is then not found)
      const drafts = await api.drafts().catch((err: unknown) => (ignoreFailedRequest(err), []));
      setLooking(false);
      const open = drafts.find(
        (d) =>
          d.status === "draft" &&
          d.kind === kind &&
          (refs.contract_id ? d.contract_id === refs.contract_id : true) &&
          (refs.doc_id ? d.doc_id === refs.doc_id || (Boolean(refs.contract_id) && d.contract_id === refs.contract_id) : true),
      );
      if (open) {
        navigate(`/letters/${open.id}`);
        return;
      }
      await create.mutateAsync(
        { kind, ...refs },
        {
          onSuccess: (draft) => {
            toast.success("Draft ready", { description: "Check the German letter and its English translation before sending." });
            navigate(`/letters/${draft.id}`);
          },
        },
      );
    },
    [create, navigate],
  );
  return { start: (...args: Parameters<typeof start>) => once(() => start(...args)), pending: create.isPending || looking || busy };
}

/**
 * Whether a to-do's date fits a calendar: its event ends by 31 Dec 9999, the last day a calendar holds
 * (`ordnung.calendar.ics.fits_a_calendar`; an hour from 23:00 on that day doesn't). The server refuses the
 * calendar file of any other date (a misread year), so "Add to calendar" isn't offered for it.
 */
export function fitsACalendar(item: Pick<Item, "due_date" | "due_time">): boolean {
  if (!item.due_date) return false;
  if (item.due_date < "9999-12-31") return true;
  return Boolean(item.due_time) && item.due_time! < "23:00";
}

/** Download link for one to-do as an .ics file ("Add to calendar"). */
export function icsHref(item: Item): string {
  return api.itemIcsUrl(item.id);
}

/** A readable file name for a to-do's .ics download. */
export function icsFileName(item: Item): string {
  const slug = item.title
    .normalize("NFKD")
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-")
    .toLowerCase()
    .slice(0, 48);
  return `${slug || "ordnung-date"}.ics`;
}

/** Copy text to the clipboard with a small confirmation. */
export async function copyText(text: string, what: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`${what} copied`);
  } catch {
    toast.warn("Couldn't copy", { description: "Your browser blocked the clipboard. Select the text and copy it by hand." });
  }
}
