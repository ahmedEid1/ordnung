/**
 * Changing the list of people (`PUT /api/household`) from Settings and from a letter's *Add … to your household*:
 * a refusal of a name is said under its field, not in a toast — so this save is quiet, and {@link refusal} says
 * what the app's error toast would otherwise say. The household it answers is kept, and the letters' pages say again
 * who each is for (as `useSaveHousehold` does).
 */
import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { api } from "@/api/endpoints";
import { qk } from "@/api/hooks";
import type { Household, HouseholdChange, MemberIn } from "@/api/types";
import { toast } from "@/components/ui/Toast";

/** A name's length as the API counts it: as typed, on one line. */
export const MAX_NAME_CHARS = 120;
/** At most this many people (the API's policy). */
export const MAX_PEOPLE = 12;
/** Where Settings keeps the household: Profile & address, its second card. */
export const MANAGE_HOUSEHOLD_HREF = "/settings?section=profile#set-household";

/**
 * The id of every toast that follows a change of the list (added, saved, removed): each one replaces the one before,
 * so only the newest *Undo* is offered. An older one could never work: it names the list as it was before the later
 * change (`base`), and a removed person's letters wait for the next change only.
 */
export const HOUSEHOLD_CHANGE_TOAST = "household-change";

/** `PUT /api/household` without the app's error toast: the caller says what went wrong ({@link refusal}). */
export function useChangeHousehold() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: HouseholdChange) => api.saveHousehold(body),
    meta: { silent: true },
    onSuccess: (household: Household) => {
      qc.setQueryData(qk.household, household);
      return qc.invalidateQueries({ queryKey: ["documents", "detail"] });
    },
  });
}

/** The people as a change sends them back: id, name and whether they sign (never their letters' count). */
export function membersOf(h: Household): MemberIn[] {
  return h.members.map(({ id, name, signs }) => ({ id, name, signs }));
}

/** A typed name on one line, without stray spaces (the API keeps it so). */
export function oneLine(name: string): string {
  return name.split(/\s+/).filter(Boolean).join(" ");
}

/** What is wrong with a typed name before asking the API (the API says the rest, in the same words). */
export function nameProblem(name: string): string | null {
  const line = oneLine(name);
  if (!line) return "Type a name.";
  if ([...line].length > MAX_NAME_CHARS) return `Use at most ${MAX_NAME_CHARS} characters.`;
  return null;
}

/**
 * What a refused change says. A name the API refuses (422): its reason, for under the field. Otherwise a toast: the
 * list changed in another window, or a newer Ordnung saved it (409) — the household is loaded again — or why the save
 * failed; `null` then.
 */
export function refusal(err: unknown, qc: QueryClient): string | null {
  if (err instanceof ApiError && err.status === 422 && typeof err.detail === "string") return err.message;
  if (err instanceof ApiError && err.status === 409 && !err.isStandby) {
    void qc.invalidateQueries({ queryKey: qk.household });
    toast({ tone: "danger", title: err.message });
    return null;
  }
  toast({ tone: "danger", title: "Couldn't save your household", description: err instanceof Error ? err.message : undefined });
  return null;
}

/** "4 letters", "1 letter". */
export function lettersLabel(n: number): string {
  return n === 1 ? "1 letter" : `${n} letters`;
}

/**
 * What a removal does to a person's letters: "Their 4 letters are in your own letters again." It says whose list they
 * show in; their dates, reminders and numbers were the person's all along.
 */
export function backToYours(n: number): string {
  return n === 1 ? "Their 1 letter is in your own letters again." : `Their ${n} letters are in your own letters again.`;
}
