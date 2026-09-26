import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { toast } from "@/components/ui/Toast";

declare module "@tanstack/react-query" {
  interface Register {
    mutationMeta: {
      /** Don't show the global error toast (the caller handles errors). */
      silent?: boolean;
      /** Custom error toast title. */
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

/** Shared QueryClient: local API → short retries, no refetch storms, friendly error toasts. */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (err, query) => {
        // background refetch failures of data we already show → one quiet toast
        if (query.state.data !== undefined && err instanceof ApiError && err.status === 0) {
          toast({ id: "offline", tone: "warn", title: "Can't reach Ordnung", description: "Showing the last known data." });
        }
      },
    }),
    mutationCache: new MutationCache({
      onError: (err, _vars, _ctx, mutation) => {
        if (mutation.meta?.silent) return;
        const { title, description } = describe(err);
        toast({ tone: err instanceof ApiError && err.isStaticDemo ? "info" : "danger", title: mutation.meta?.errorTitle ?? title, description });
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
}
