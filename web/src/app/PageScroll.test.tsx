/**
 * Where the window is scrolled when the address changes (PageScroll): only while the new address is drawn, never
 * later, so a page's own scroll to what its address asks for (a contract's card) is never undone; a page seen before
 * comes back where it was left, one opened new starts at its top, and a change within the page leaves it be.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, Outlet, RouterProvider } from "react-router";
import { useEffect } from "react";
import { qk } from "@/api/hooks";
import type { Profile } from "@/api/types";
import { makeTestQueryClient, TEST_HEALTH } from "@/test/render";
import { AppLayout } from "./Layout";
import { PageScroll, resetPageScroll } from "./PageScroll";

const STORAGE_KEY = "react-router-scroll-positions";
/** Every call of window.scrollTo and scrollIntoView, in order: [who, y]. */
let calls: [string, number][] = [];

/** The window as if scrolled to `y` by the person: where it is, and the scroll event. */
function scrolledTo(y: number) {
  Object.defineProperty(window, "scrollY", { value: y, configurable: true });
  window.dispatchEvent(new Event("scroll"));
}

function loadedAs(type: "navigate" | "reload" | "back_forward") {
  vi.spyOn(performance, "getEntriesByType").mockImplementation((t: string) =>
    t === "navigation" ? ([{ type }] as unknown as PerformanceEntryList) : [],
  );
}

beforeEach(() => {
  calls = [];
  resetPageScroll();
  sessionStorage.clear();
  Object.defineProperty(window, "scrollY", { value: 0, configurable: true });
  vi.stubGlobal("scrollTo", (_x: number, y: number) => {
    calls.push(["scrollTo", y]);
    Object.defineProperty(window, "scrollY", { value: y, configurable: true });
  });
  Element.prototype.scrollIntoView = function () {
    calls.push([`scrollIntoView #${this.id}`, -1]);
  };
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("in the shell, with a page that scrolls to its card as soon as it is drawn", () => {
  const PROFILE = { name: "Sam Rivera", onboarded: true } as Profile;
  /** The Contracts page as the app's: its effect brings the contract asked for into view (here at once). */
  function Contracts() {
    useEffect(() => {
      window.scrollTo(0, 6140);
    }, []);
    return <h1>Contracts</h1>;
  }

  beforeEach(() => {
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
      const body = path === "/health" ? TEST_HEALTH : path === "/profile" ? PROFILE : [];
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("EventSource", class { addEventListener() {} close() {} });
  });

  it("a link opened whole to a contract, on a page seen before in this tab: nothing scrolls after the card is in view", async () => {
    // the place left on Contracts earlier in this tab, as the router's <ScrollRestoration> kept it
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ "/contracts": 0, "/timeline": 0 }));
    loadedAs("navigate");
    const client = makeTestQueryClient();
    client.setQueryData(qk.profile, PROFILE);
    const router = createMemoryRouter([{ path: "/", element: <AppLayout />, children: [{ path: "contracts", element: <Contracts /> }] }], {
      initialEntries: ["/contracts?contract=ctr_1"],
    });
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    await screen.findByRole("heading", { name: "Contracts" });
    // the router's own restoration put its saved place through a transition, drawn after the page's effect: the
    // page was taken back to the top after the card was in view ([..., 6140, 0]); act flushes that transition, so
    // whatever the router still had to draw has been drawn before the expectations
    await act(async () => {});
    expect(calls.at(-1), "the last scroll is the page's own, to its card").toEqual(["scrollTo", 6140]);
    expect(calls.map(([, y]) => y)).toEqual([0, 6140]);
  });
});

describe("PageScroll", () => {
  function Page({ name, tall }: { name: string; tall?: boolean }) {
    return (
      <>
        <h1>{name}</h1>
        {tall ? <p id="far">far down</p> : null}
      </>
    );
  }
  function Shell() {
    return (
      <>
        <PageScroll />
        <Outlet />
      </>
    );
  }
  function app(at: string) {
    const router = createMemoryRouter(
      [
        {
          path: "/",
          element: <Shell />,
          children: [
            { path: "inbox", element: <Page name="Inbox" /> },
            { path: "documents/:id", element: <Page name="Letter" /> },
            { path: "settings", element: <Page name="Settings" tall /> },
          ],
        },
      ],
      { initialEntries: [at] },
    );
    render(<RouterProvider router={router} />);
    return router;
  }

  it("Back brings a page back where the person left it; a page opened new starts at its top", async () => {
    loadedAs("navigate");
    const router = app("/inbox");
    expect(calls).toEqual([["scrollTo", 0]]);
    scrolledTo(1500);
    await act(() => router.navigate("/documents/doc_1"));
    expect(calls.at(-1), "a letter not seen before: its top").toEqual(["scrollTo", 0]);
    scrolledTo(300);
    await act(() => router.navigate(-1));
    expect(screen.getByRole("heading", { name: "Inbox" })).toBeInTheDocument();
    expect(calls.at(-1), "the Inbox where it was left").toEqual(["scrollTo", 1500]);
    await act(() => router.navigate(1));
    expect(calls.at(-1), "Forward: the letter where it was left").toEqual(["scrollTo", 300]);
  });

  it("a change within the page (its query, its hash) leaves the window where it is: the page scrolls to what it asks for", async () => {
    loadedAs("navigate");
    const router = app("/settings?section=profile");
    scrolledTo(400);
    const before = calls.length;
    await act(() => router.navigate("/settings?section=data", { replace: true }));
    await act(() => router.navigate("/settings?section=data#far"));
    expect(calls.length).toBe(before);
  });

  it("a page opened new with a hash: that element is scrolled to", async () => {
    loadedAs("navigate");
    const router = app("/inbox");
    await act(() => router.navigate("/settings#far"));
    expect(calls.at(-1)).toEqual(["scrollIntoView #far", -1]);
  });

  it("a reload, Back or Forward from another site brings the place back at once; a new load of the page starts at its top", async () => {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ "/inbox": 1200 }));
    loadedAs("reload");
    const first = app("/inbox");
    expect(calls).toEqual([["scrollTo", 1200]]);
    first.dispose();

    resetPageScroll();
    calls = [];
    loadedAs("navigate");
    app("/inbox");
    expect(calls).toEqual([["scrollTo", 0]]);
  });

  it("keeps the places in this tab's sessionStorage when the page is left, for a reload", async () => {
    loadedAs("navigate");
    const router = app("/inbox");
    scrolledTo(700);
    await act(() => router.navigate("/documents/doc_1"));
    scrolledTo(80);
    window.dispatchEvent(new Event("pagehide"));
    expect(JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "{}")).toEqual({ "/inbox": 700, "/documents/doc_1": 80 });
    expect(window.history.scrollRestoration).toBe("auto");
    window.dispatchEvent(Object.assign(new Event("pageshow"), { persisted: true }));
    expect(window.history.scrollRestoration).toBe("manual");
  });
});
