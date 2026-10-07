import { createElement, Fragment, type ReactNode } from "react";
import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { clientKind } from "@/api/clientKind";
import { TechnicalDetails, technicalDetails } from "@/components/ui/LoadError";
import { dismissToast, toast } from "@/components/ui/Toast";
import { PHONE_OFFLINE_DETAIL, PHONE_OFFLINE_TITLE } from "@/features/phone/copy";
import { pageLoad } from "@/features/phone/platform";

declare module "@tanstack/react-query" {
  interface Register {
    mutationMeta: {
      /** Don't show the global error toast (the caller handles errors). */
      silent?: boolean;
      /** What failed, as the toast's title ("Couldn't save your profile"); the error explains why. */
      errorTitle?: string;
    };
  }
}

/**
 * The error's sentence, and the server's own words under "Technical details" when the sentence stands in for them
 * (a server error without words for a person, an answer that isn't Ordnung's JSON — never "Internal Server Error"
 * as the sentence: UX audit U9).
 */
function sentence(err: ApiError): ReactNode {
  if (!err.technical) return err.message;
  return createElement(Fragment, null, err.message, createElement(TechnicalDetails, { text: technicalDetails(err) ?? err.technical, className: "mt-1" }));
}

function describe(err: unknown): { title: string; description?: ReactNode } {
  if (err instanceof ApiError) {
    if (err.isStaticDemo) return { title: "Not available in the online demo", description: err.message };
    if (err.isDemoLimit) return { title: "Not available in the demo", description: err.message };
    if (err.status === 0) return { title: clientKind() === "phone" ? PHONE_OFFLINE_TITLE : "Can't reach Ordnung", description: err.message };
    if (err.status === 429) return { title: "Claude needs a short break", description: err.message };
    return { title: "That didn't work", description: sentence(err) };
  }
  return { title: "Something went wrong", description: err instanceof Error ? err.message : undefined };
}

/** Worth trying the same thing again: Ordnung didn't answer or failed itself (not a refusal). */
const retryable = (err: unknown) => err instanceof ApiError && !err.isDemoLimit && (err.status === 0 || err.status >= 500);

/** Id of the one "Can't reach Ordnung" toast. */
export const OFFLINE_TOAST_ID = "offline";
let offline = false;

/**
 * Ordnung stopped answering while the page shows data: one warning that stays until it answers
 * again (showing the last known data meanwhile), with "Try again" (refetch what is on screen).
 */
export function showOffline(client: QueryClient): void {
  offline = true;
  const phone = clientKind() === "phone";
  toast({
    id: OFFLINE_TOAST_ID,
    tone: "warn",
    title: phone ? PHONE_OFFLINE_TITLE : "Can't reach Ordnung",
    description: phone ? PHONE_OFFLINE_DETAIL : "Showing what was last loaded. Is Ordnung still running on this computer?",
    duration: Infinity,
    action: { label: "Try again", onClick: () => void client.refetchQueries({ type: "active" }) },
  });
}

/** Ordnung answers again after {@link showOffline}: the warning goes, "Back online" says so. */
export function showBackOnline(): void {
  if (!offline) return;
  offline = false;
  dismissToast(OFFLINE_TOAST_ID);
  toast.success("Back online", { description: "Ordnung is answering again — everything is up to date." });
}

/** Where a phone the computer no longer knows goes: pairing again, told why. */
export const REMOVED_PHONE_PATH = "/pair?removed=1";
/** Why the computer signed a phone out, beyond "removed" (`?removed=…` of the pairing page; the gate's `removed`). */
export const REMOVED_REASONS = ["token_reuse", "code_reused", "unused"] as const;
let leaving = false;

/** The pairing page for a phone signed out because of `removed` (the 401's `removed`; anything else: removed). */
export function removedPhonePath(removed: string | null): string {
  return removed && (REMOVED_REASONS as readonly string[]).includes(removed) ? `/pair?removed=${removed}` : REMOVED_PHONE_PATH;
}

/**
 * A refusal only the phone listener gives, `phone_not_paired`: the computer removed this phone (or forgot it), so
 * every further request fails the same way. One full page load to the pairing page, which says so — it drops what
 * the phone still showed. Never from the pairing page itself, which expects this answer before pairing.
 */
export function leaveIfUnpaired(err: unknown): boolean {
  if (!(err instanceof ApiError) || err.code !== "phone_not_paired") return false;
  if (leaving || window.location.pathname === "/pair") return true;
  leaving = true;
  pageLoad.assign(removedPhonePath(err.removed));
  return true;
}

/** Test helper. */
export function __resetOfflineForTests(): void {
  offline = false;
  leaving = false;
}

/** Shared QueryClient: local API → short retries, no refetch storms, friendly error toasts. */
export function createQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      onError: (err, query) => {
        // a phone the computer removed: to the pairing page (every request would fail the same way)
        if (leaveIfUnpaired(err)) return;
        // background refetch failures of data we already show → one warning until it answers again
        if (query.state.data !== undefined && err instanceof ApiError && err.status === 0) showOffline(client);
      },
      onSuccess: () => showBackOnline(),
    }),
    mutationCache: new MutationCache({
      onError: (err, variables, _ctx, mutation) => {
        if (leaveIfUnpaired(err)) return;
        if (mutation.meta?.silent) return;
        const { title, description } = describe(err);
        // a demo's limit (the hosted demo, or `ordnung demo` asked to read a new letter): a calm note
        const demo = err instanceof ApiError && err.isDemoLimit;
        // what failed ("Couldn't save your profile"), unless the reason is the better title
        const specific = demo || (err instanceof ApiError && err.status === 429) ? title : (mutation.meta?.errorTitle ?? title);
        toast({
          tone: demo ? "info" : "danger",
          title: specific,
          description,
          action: retryable(err)
            ? {
                label: "Try again",
                // the same request with the same options (its own success and error handling included)
                onClick: () => void client.getMutationCache().build(client, mutation.options).execute(variables).catch(() => {}),
              }
            : undefined,
        });
      },
    }),
    defaultOptions: {
      queries: {
        retry: (count, err) => (err instanceof ApiError && err.status >= 400 && err.status < 500 ? false : count < 2),
        refetchOnWindowFocus: false,
        staleTime: 30_000,
      },
      mutations: { retry: false },
    },
  });
  return client;
}
