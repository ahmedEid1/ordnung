/**
 * A new page is said (UX audit U10): focus that went with the old page moves to the new page's heading; focus
 * still on a control outside the page stays there, and the new page's title is said in a polite live region.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider, useNavigate } from "react-router";
import { useEffect, useState } from "react";
import { qk } from "@/api/hooks";
import type { Profile } from "@/api/types";
import { makeTestQueryClient, TEST_HEALTH } from "@/test/render";
import { AppLayout } from "./Layout";

const PROFILE = { name: "Sam Rivera", onboarded: true } as Profile;

beforeEach(() => {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
    const body = path === "/health" ? TEST_HEALTH : path === "/profile" ? PROFILE : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("EventSource", class { addEventListener() {} close() {} });
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => vi.unstubAllGlobals());

/** The Inbox: a row that opens a letter and is gone once it has (focus goes with it). */
function Inbox() {
  const navigate = useNavigate();
  return (
    <>
      <h1>Inbox</h1>
      <button onClick={() => navigate("/documents/doc_1")}>Parking fine</button>
    </>
  );
}

/** A letter's page: its heading comes with its data, a moment later. */
function Letter() {
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setLoaded(true), 30);
    return () => clearTimeout(t);
  }, []);
  return loaded ? <h1>Parking fine</h1> : <p>Loading the letter…</p>;
}

function renderApp() {
  const client = makeTestQueryClient();
  client.setQueryData(qk.profile, PROFILE);
  const router = createMemoryRouter(
    [
      {
        path: "/",
        element: <AppLayout />,
        children: [
          { path: "inbox", element: <Inbox /> },
          { path: "documents/:id", element: <Letter /> },
          { path: "timeline", element: <h1>Timeline</h1> },
        ],
      },
    ],
    { initialEntries: ["/inbox"] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("a new page", () => {
  it("takes focus to its heading once drawn, when focus went with the old page (Enter on an Inbox row)", async () => {
    renderApp();
    const user = userEvent.setup();
    const row = await screen.findByRole("button", { name: "Parking fine" });
    // the first page is the browser's: nothing moved
    expect(screen.getByRole("heading", { level: 1, name: "Inbox" })).not.toHaveFocus();
    row.focus();
    await user.keyboard("{Enter}");
    const h1 = await screen.findByRole("heading", { level: 1, name: "Parking fine" });
    await waitFor(() => expect(h1).toHaveFocus());
    expect(h1).toHaveAttribute("tabindex", "-1");
  });

  it("says its title, and leaves focus where it is, when focus is on a control outside the page (a sidebar link)", async () => {
    const router = renderApp();
    await screen.findByRole("heading", { level: 1, name: "Inbox" });
    // a link outside the page, as the sidebar's
    const outside = document.createElement("button");
    outside.textContent = "Timeline";
    document.body.prepend(outside);
    outside.focus();
    await act(() => router.navigate("/timeline"));
    await waitFor(() => expect(screen.getAllByRole("status").map((s) => s.textContent)).toContain("Timeline"));
    expect(outside).toHaveFocus();
    outside.remove();
  });
});
