/**
 * What the shell loads for every page: the demo's tour only in the demo (and with it the Ideas it reads), the People
 * & organisations drawer only once it is first opened (and with it the letters it lists). Outside the demo neither
 * asks the API for anything until then.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import { qk } from "@/api/hooks";
import type { Health, Profile } from "@/api/types";
import { makeTestQueryClient, TEST_HEALTH } from "@/test/render";
import { AppLayout } from "./Layout";

const PROFILE = { name: "Sam Rivera", onboarded: true } as Profile;
let asked: string[] = [];

beforeEach(() => {
  asked = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
    asked.push(path);
    const body = path === "/profile" ? PROFILE : path.startsWith("/parties/") ? null : [];
    return new Response(JSON.stringify(body), { status: path.startsWith("/parties/") ? 404 : 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("EventSource", class { addEventListener() {} close() {} });
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => vi.unstubAllGlobals());

function renderShell(health: Health) {
  const client = makeTestQueryClient();
  client.setQueryData(qk.health, health);
  client.setQueryData(qk.profile, PROFILE);
  const router = createMemoryRouter([{ path: "/", element: <AppLayout />, children: [{ path: "inbox", element: <h1>Inbox</h1> }] }], {
    initialEntries: ["/inbox"],
  });
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("the shell's own parts", () => {
  it("outside the demo: no tour, no Ideas, and no drawer until a person or organisation is opened", async () => {
    const router = renderShell({ ...TEST_HEALTH, demo: false });
    await screen.findByRole("heading", { level: 1, name: "Inbox" });
    // what the shell asks for on its own, in the commit that drew it, has been asked (the sidebar's counts)
    await waitFor(() => expect(asked).toContain("/documents"));
    expect(asked).not.toContain("/suggestions");
    expect(asked).not.toContain("/drafts");
    expect(asked.filter((p) => p.startsWith("/parties/"))).toEqual([]);
    expect(screen.queryByRole("dialog")).toBeNull();

    await act(() => router.navigate("/inbox?party=pty_1"));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await waitFor(() => expect(asked).toContain("/parties/pty_1"));
    expect(asked).toContain("/drafts");
    expect(asked).not.toContain("/suggestions");
  });

  it("in the demo: the tour comes, with the Ideas of the new mail", async () => {
    renderShell({ ...TEST_HEALTH, demo: true });
    await screen.findByRole("heading", { level: 1, name: "Inbox" });
    await waitFor(() => expect(asked).toContain("/suggestions"));
    expect(asked).toContain("/demo/tour");
  });
});
