/**
 * `useStickyError`: a failed load's message stays while "Try again" runs, and a background refetch that
 * fails while data is cached (TanStack keeps `data` and sets `error`) never loops ("Too many re-renders").
 */
import { describe, expect, it, vi } from "vitest";
import { render, renderHook, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import { ApiError } from "@/api/client";
import { api } from "@/api/endpoints";
import { DRAFTS } from "@/mocks/data/drafts";
import LetterPage from "@/pages/LetterPage";
import { makeTestQueryClient } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { useStickyError } from "./hooks";

describe("useStickyError", () => {
  it("keeps a failed load's error through a retry, and settles when a refetch fails over cached data", () => {
    const failure = new Error("offline");
    const { result, rerender } = renderHook(({ error, loaded }: { error: unknown; loaded: boolean }) => useStickyError(error, loaded), {
      initialProps: { error: null as unknown, loaded: false },
    });
    expect(result.current).toBeNull();
    rerender({ error: failure, loaded: false });
    expect(result.current).toBe(failure);
    rerender({ error: null, loaded: false }); // "Try again": pending, the error forgotten by the query
    expect(result.current).toBe(failure);
    rerender({ error: null, loaded: true });
    expect(result.current).toBeNull();
    // data cached, then a background refetch fails: no state flip-flop, the error is simply current
    rerender({ error: failure, loaded: true });
    rerender({ error: failure, loaded: true });
    expect(result.current).toBe(failure);
  });

  it("a letter whose refetch fails (deleted meanwhile) doesn't crash its page", async () => {
    useMockApi();
    const draft = DRAFTS[0]!;
    const spy = vi.spyOn(api, "draft");
    const client = makeTestQueryClient();
    const router = createMemoryRouter([{ path: "/letters/:id", element: <LetterPage /> }], { initialEntries: [`/letters/${draft.id}`] });
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
    spy.mockRejectedValue(new ApiError(404, "Not found", null));
    await client.invalidateQueries();
    await waitFor(() => expect(spy).toHaveBeenCalled());
    // still the page (the delete dialog navigates away on its own), never React's "Too many re-renders"
    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
  });
});
