/**
 * The People & organisations drawer whose code can't load (Ordnung restarted or upgraded under an open tab), when the
 * app did not reload for it: a toast says so and offers a reload, so a click on a name is never left unanswered.
 */
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import { qk } from "@/api/hooks";
import type { Profile } from "@/api/types";
import { __clearToasts } from "@/components/ui/Toast";
import { makeTestQueryClient, TEST_HEALTH } from "@/test/render";
import { AppLayout } from "./Layout";

// the app reloaded for a new build a minute ago: it does not again
vi.mock("./staleChunks", () => ({ reloadIfServing: vi.fn(async () => {}) }));
vi.mock("@/features/party/PartyDrawer", () => {
  throw new TypeError("Failed to fetch dynamically imported module");
});

const PROFILE = { name: "Sam Rivera", onboarded: true } as Profile;

beforeEach(() => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
    return new Response(JSON.stringify(path === "/profile" ? PROFILE : []), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("EventSource", class { addEventListener() {} close() {} });
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

it("says the drawer couldn't open, offers a reload, and leaves the page in place", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const client = makeTestQueryClient();
  client.setQueryData(qk.health, { ...TEST_HEALTH, demo: false });
  client.setQueryData(qk.profile, PROFILE);
  const router = createMemoryRouter([{ path: "/", element: <AppLayout />, children: [{ path: "inbox", element: <h1>Inbox</h1> }] }], {
    initialEntries: ["/inbox"],
  });
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { level: 1, name: "Inbox" });
  await act(() => router.navigate("/inbox?party=pty_1"));
  expect(await screen.findByText("Couldn't open this person or organisation")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByRole("heading", { level: 1, name: "Inbox" })).toBeInTheDocument();
});
