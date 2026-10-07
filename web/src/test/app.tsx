/**
 * Test helper: the whole app — its real routes, the shell and the lazy pages — at one path, against the mock API
 * (`useMockApi` first; `useMockApi({ client: "phone" })` makes it a paired phone's). Waits until the page has drawn
 * its heading and every query it started has answered.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import { expect, vi } from "vitest";
import { routes } from "@/app/router";
import { makeTestQueryClient } from "./render";

/** The browser APIs the shell uses that jsdom lacks (call in `beforeEach`; `vi.unstubAllGlobals` undoes it). */
export function stubShellGlobals(): void {
  vi.stubGlobal("EventSource", class { addEventListener() {} close() {} });
  vi.stubGlobal("scrollTo", () => {});
}

/** Render the app at `path`; with `heading`, wait for that h1 (else any page h1 that isn't a loading stand-in). */
export async function renderAppAt(path: string, heading?: RegExp | string): Promise<{ client: QueryClient; router: ReturnType<typeof createMemoryRouter> }> {
  const client = makeTestQueryClient();
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  if (heading) await screen.findByRole("heading", { level: 1, name: heading }, { timeout: 8_000 });
  else await waitFor(() => expect(document.querySelector("main#main h1:not([data-loading])")).toBeTruthy(), { timeout: 8_000 });
  await waitFor(() => expect(client.isFetching()).toBe(0), { timeout: 8_000 });
  return { client, router };
}
