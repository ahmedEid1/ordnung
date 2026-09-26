import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { dismissToast, toast } from "@/components/ui/Toast";

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

function describe(err: unknown): { title: string; description?: string } {
  if (err instanceof ApiError) {
    if (err.isStaticDemo) return { title: "Not available in the online demo", description: err.message };
    if (err.status === 0) return { title: "Can't reach Ordnung", description: err.message };
    if (err.status === 429) return { title: "Claude needs a short break", description: err.message };
    return { title: "That didn't work", description: err.message };
  }
  return { title: "Something went wrong", description: err instanceof Error ? err.message : undefined };
}

/** Worth trying the same thing again: Ordnung didn't answer or failed itself (not a refusal). */
const retryable = (err: unknown) => err instanceof ApiError && !err.isStaticDemo && (err.status === 0 || err.status >= 500);

/** Id of the one "Can't reach Ordnung" toast. */
export const OFFLINE_TOAST_ID = "offline";
let offline = false;

/**
 * Ordnung stopped answering while the page shows data: one warning that stays until it answers
 * again (showing the last known data meanwhile), with "Try again" (refetch what is on screen).
 */
export function showOffline(client: QueryClient): void {
  offline = true;
  toast({
    id: OFFLINE_TOAST_ID,
    tone: "warn",
    title: "Can't reach Ordnung",
    description: "Showing what was last loaded. Is Ordnung still running on this computer?",
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

/** Test helper. */
export function __resetOfflineForTests(): void {
  offline = false;
}

/** Shared QueryClient: local API → short retries, no refetch storms, friendly error toasts. */
export function createQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      onError: (err, query) => {
        // background refetch failures of data we already show → one warning until it answers again
        if (query.state.data !== undefined && err instanceof ApiError && err.status === 0) showOffline(client);
      },
      onSuccess: () => showBackOnline(),
    }),
    mutationCache: new MutationCache({
      onError: (err, variables, _ctx, mutation) => {
        if (mutation.meta?.silent) return;
        const { title, description } = describe(err);
        const demo = err instanceof ApiError && err.isStaticDemo;
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
