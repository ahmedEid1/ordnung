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
import { formatDate } from "@/lib/format";

export function useItemActions() {
  const update = useUpdateItem();
  const confirm = useConfirmItem();

  const markDone = useCallback(
    (item: Item) =>
      update.mutate(
        { id: item.id, patch: { status: "done" } },
        {
          onSuccess: () =>
            toast.success("Marked as done", {
              description: item.title,
              undo: () => update.mutate({ id: item.id, patch: { status: "open" } }),
            }),
        },
      ),
    [update],
  );

  const reopen = useCallback((item: Item) => update.mutate({ id: item.id, patch: { status: "open" } }), [update]);

  const dismiss = useCallback(
    (item: Item) =>
      update.mutate(
        { id: item.id, patch: { status: "dismissed" } },
        {
          onSuccess: () =>
            toast({
              title: "Removed from your to-dos",
              description: `“${item.title}” won't remind you. The letter stays filed.`,
              undo: () => update.mutate({ id: item.id, patch: { status: "open" } }),
            }),
        },
      ),
    [update],
  );

  const changeDate = useCallback(
    (item: Item, date: string, onDone?: () => void) =>
      update.mutate(
        { id: item.id, patch: { due_date: date } },
        {
          onSuccess: () => {
            onDone?.();
            toast.success(`Date changed to ${formatDate(date, { style: "short" })}`, {
              description: "You set this date yourself, so Ordnung won't overwrite it.",
              undo: item.due_date ? () => update.mutate({ id: item.id, patch: { due_date: item.due_date } }) : undefined,
            });
          },
        },
      ),
    [update],
  );

  const confirmItem = useCallback(
    (item: Item) =>
      confirm.mutate(item.id, {
        onSuccess: () => toast.success("Thanks — confirmed", { description: `“${item.title}” is marked as checked by you.` }),
      }),
    [confirm],
  );

  return { markDone, reopen, dismiss, changeDate, confirmItem, pending: update.isPending || confirm.isPending };
}

/** Create a draft letter (objection / cancellation / reply) and open it in Letters. */
export function useStartDraft() {
  const create = useCreateDraft();
  const navigate = useNavigate();
  const [looking, setLooking] = useState(false);
  const start = useCallback(
    async (kind: DraftKind, refs: { doc_id?: string | null; contract_id?: string | null; party_id?: string | null; case_id?: string | null }) => {
      // a second click opens the letter already being drafted for this letter/contract instead of a copy
      setLooking(true);
      const drafts = await api.drafts().catch(() => []);
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
      create.mutate(
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
  return { start: (...args: Parameters<typeof start>) => void start(...args), pending: create.isPending || looking };
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
