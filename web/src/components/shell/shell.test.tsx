/**
 * The app shell (audit round 1, bucket "shell-a"): the skip link keeps its padding, one content
 * column that the top bar and banner line up with, letter pages with a back button and an active
 * nav item, a top bar that doesn't repeat a visible h1, a labelled rail, one sidebar toggle that
 * keeps focus, the profile link, 12 px tab labels with a ring inside the bar, room under the page
 * for overlays, a retry that keeps the "isn't running" card, the paused banner and the demo badge.
 * Layout itself (positions, overflow) is checked on real pages in `e2e/shell.spec.ts`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, Outlet, RouterProvider, useNavigate } from "react-router";
import type { ReactNode } from "react";
import { qk } from "@/api/hooks";
import { handleServerEvent, __resetEventsForTests } from "@/api/sse";
import { ApiError } from "@/api/client";
import type { Job, Profile } from "@/api/types";
import { makeTestQueryClient, renderWithProviders, TEST_HEALTH } from "@/test/render";
import { HealthUnreachable } from "@/app/screens";
import { AddLettersProvider } from "./AddLetters";
import { DemoBadge } from "./DemoBadge";
import { MobileTabBar } from "./MobileTabBar";
import { NAV_ITEMS, isNavItemActive, sectionAt } from "./nav";
import { recordLocation, resetOrigins, useOriginParent } from "./origin";
import { Page } from "./Page";
import { PageMetaProvider } from "./page-meta";
import { PausedBanner, pauseEnds } from "./PausedBanner";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { PAGE_WIDTHS, SHELL_GUTTERS } from "./layout";

const PROFILE = { name: "Sam Rivera", onboarded: true } as Profile;

function stubFetch(routes: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, "http://localhost").pathname.replace(/^\/api/, "");
      const body = path in routes ? routes[path] : [];
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
}

/** matchMedia that answers `matches` for min-width queries up to `width`. */
function viewport(width: number) {
  vi.stubGlobal("matchMedia", (query: string) => {
    const min = /min-width:\s*(\d+)px/.exec(query);
    return { matches: min ? width >= Number(min[1]) : false, media: query, addEventListener: () => {}, removeEventListener: () => {} };
  });
}

/** The shell's frame around a page: meta provider, top bar, main, tab bar. */
function Shell({ children }: { children?: ReactNode }) {
  return (
    <PageMetaProvider>
      <AddLettersProvider>
        <TopBar />
        <main id="main">{children ?? <Outlet />}</main>
        <MobileTabBar />
      </AddLettersProvider>
    </PageMetaProvider>
  );
}

beforeEach(() => {
  stubFetch();
  resetOrigins();
  localStorage.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  __resetEventsForTests();
});

describe("nav: which item is current", () => {
  const inbox = NAV_ITEMS.find((i) => i.to === "/inbox")!;
  const today = NAV_ITEMS.find((i) => i.to === "/")!;

  it("makes Inbox the home of every letter page, and Today of / and the weekly session", () => {
    expect(isNavItemActive(inbox, "/documents/doc_1")).toBe(true);
    expect(isNavItemActive(inbox, "/inbox")).toBe(true);
    expect(isNavItemActive(inbox, "/documentsx")).toBe(false);
    expect(isNavItemActive(today, "/")).toBe(true);
    expect(isNavItemActive(today, "/week")).toBe(true);
    expect(isNavItemActive(today, "/weekly")).toBe(false);
    expect(isNavItemActive(today, "/documents/doc_1")).toBe(false);
    expect(NAV_ITEMS.filter((item) => isNavItemActive(item, "/week"))).toEqual([today]);
  });

  it("knows the section pages by their exact path", () => {
    expect(sectionAt("/timeline")?.label).toBe("Timeline");
    expect(sectionAt("/settings")?.label).toBe("Settings");
    expect(sectionAt("/documents/doc_1")).toBeUndefined();
  });

  it("marks Inbox current in the tab bar on a letter page", () => {
    renderWithProviders(<MobileTabBar />, { route: "/documents/doc_1" });
    expect(screen.getByRole("link", { name: "Inbox" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Today" })).not.toHaveAttribute("aria-current");
  });
});

describe("tab bar", () => {
  it("uses 12 px labels (11 px below 360 px) and draws the focus ring round the pill, inside the bar", () => {
    renderWithProviders(<MobileTabBar />, { route: "/" });
    const link = screen.getByRole("link", { name: "Timeline" });
    expect(link.className).toMatch(/\btext-xs\b/);
    expect(link.className).toContain("max-[360px]:text-2xs");
    expect(link.className).toContain("outline-none");
    const pill = link.firstElementChild!;
    expect(pill.className).toContain("group-focus-visible:ring-2");
    expect(link.className).not.toMatch(/text-\[10\.5px\]/);
  });

  it("shows the number to check in a CountBadge (at least 11 px), named on the link", async () => {
    const qc = makeTestQueryClient();
    qc.setQueryData(qk.documents.list({ status: "needs_review" }), [{ id: "a" }, { id: "b" }]);
    renderWithProviders(<MobileTabBar />, { client: qc });
    const inbox = screen.getByRole("link", { name: "Inbox, 2 to check" });
    const badge = within(inbox).getByText("2");
    expect(badge.className).toContain("text-2xs");
  });

  it("counts the letters waiting from the watched folder too, and names both", () => {
    const qc = makeTestQueryClient();
    qc.setQueryData(qk.documents.list({ status: "needs_review" }), [{ id: "a" }]);
    qc.setQueryData(qk.documents.list({ status: "held" }), [{ id: "b" }, { id: "c" }, { id: "d" }]);
    renderWithProviders(<MobileTabBar />, { client: qc });
    const inbox = screen.getByRole("link", { name: "Inbox, 1 to check, 3 waiting for you" });
    expect(within(inbox).getByText("4")).toBeInTheDocument();
  });

  it("with only letters waiting, the bubble is not the warning colour", () => {
    const qc = makeTestQueryClient();
    qc.setQueryData(qk.documents.list({ status: "held" }), [{ id: "b" }, { id: "c" }]);
    renderWithProviders(<MobileTabBar />, { client: qc });
    const inbox = screen.getByRole("link", { name: "Inbox, 2 waiting for you" });
    expect(within(inbox).getByText("2").className).toContain("bg-accent");
  });

  it("is nearly opaque, so page text doesn't show through", () => {
    renderWithProviders(<MobileTabBar />);
    expect(screen.getByRole("navigation", { name: "Primary" }).className).toContain("bg-surface/95");
  });
});

describe("origin: a letter's parent is where it was opened from", () => {
  function Parent() {
    const p = useOriginParent({ to: "/inbox", label: "Inbox" });
    return <span data-testid="parent">{`${p.label} ${p.to}`}</span>;
  }

  it("pins the last section page to the letter's history entry, and falls back to Inbox", () => {
    recordLocation({ pathname: "/timeline", search: "?filter=money", key: "k1" });
    recordLocation({ pathname: "/documents/doc_1", search: "", key: "k2" });
    // another section later doesn't change the pinned entry
    recordLocation({ pathname: "/contracts", search: "", key: "k3" });

    const router = createMemoryRouter([{ path: "*", element: <Parent /> }], {
      initialEntries: [{ pathname: "/documents/doc_1", key: "k2" }],
    });
    render(<RouterProvider router={router} />);
    expect(screen.getByTestId("parent")).toHaveTextContent("Timeline /timeline?filter=money");
    expect(JSON.parse(sessionStorage.getItem("ordnung.nav-origin")!)).toEqual({ k2: "/timeline?filter=money" });
  });

  it("uses the letter's home when opened directly (first page of a load)", () => {
    recordLocation({ pathname: "/", search: "", key: "k9" });
    const router = createMemoryRouter([{ path: "*", element: <Parent /> }], { initialEntries: ["/documents/doc_1"] });
    render(<RouterProvider router={router} />);
    expect(screen.getByTestId("parent")).toHaveTextContent("Inbox /inbox");
  });
});

describe("top bar", () => {
  function DetailPage() {
    return (
      <Page title="1st Payment Reminder (Mahnung) – Invoice TM-2026-0048213" parent={{ to: "/", label: "Today" }}>
        <h1>1st Payment Reminder</h1>
      </Page>
    );
  }

  it("gives letter pages a breadcrumb with a phone back button, and the full title on hover", async () => {
    renderWithProviders(
      <Shell>
        <DetailPage />
      </Shell>,
      { route: "/documents/doc_1" },
    );
    const crumb = await screen.findByRole("navigation", { name: "Breadcrumb" });
    const back = within(crumb).getByRole("link", { name: "Back to Today" });
    expect(back).toHaveAttribute("href", "/");
    expect(back.closest("li")!.className).toContain("sm:hidden");
    expect(back.className).toContain("size-9");
    const current = within(crumb).getByText(/^1st Payment Reminder \(Mahnung\)/);
    expect(current).toHaveAttribute("aria-current", "page");
    expect(current).toHaveAttribute("title", "1st Payment Reminder (Mahnung) – Invoice TM-2026-0048213");
    // the logo gives way to the back button on phones
    expect(screen.getByRole("link", { name: "Ordnung — Today" }).className).toContain("max-sm:hidden");
  });

  it("lines its content up with the page column and is nearly opaque", () => {
    renderWithProviders(<Shell />, { route: "/inbox" });
    const header = screen.getByRole("banner");
    expect(header.className).toContain("bg-canvas/95");
    const row = header.firstElementChild!;
    for (const cls of [...SHELL_GUTTERS.split(" "), PAGE_WIDTHS.default, "mx-auto"]) expect(row.className).toContain(cls);
  });

  it("keeps a section page's title out of sight while the page's h1 is on screen", async () => {
    const observers: { cb: IntersectionObserverCallback; el?: Element }[] = [];
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        entry: { cb: IntersectionObserverCallback; el?: Element };
        constructor(cb: IntersectionObserverCallback) {
          this.entry = { cb };
          observers.push(this.entry);
        }
        observe(el: Element) {
          this.entry.el = el;
        }
        disconnect() {}
      },
    );
    renderWithProviders(
      <Shell>
        <Page title="Inbox">
          <h1>Inbox</h1>
        </Page>
      </Shell>,
      { route: "/inbox" },
    );
    const title = () => screen.getByRole("banner").querySelector("[data-state]")!;
    await waitFor(() => expect(observers.at(-1)?.el?.textContent).toBe("Inbox"));
    expect(title()).toHaveAttribute("data-state", "hidden");
    expect(title()).toHaveAttribute("aria-hidden", "true");
    expect(title()).not.toHaveAttribute("aria-current");

    const fire = (isIntersecting: boolean, bottom: number) =>
      act(() =>
        observers.at(-1)!.cb(
          [{ isIntersecting, boundingClientRect: { bottom }, rootBounds: { top: 56 } } as unknown as IntersectionObserverEntry],
          {} as IntersectionObserver,
        ),
      );
    fire(false, 20); // scrolled up under the bar
    expect(title()).toHaveAttribute("data-state", "shown");
    expect(title()).not.toHaveAttribute("aria-hidden");
    fire(true, 120); // back in view
    expect(title()).toHaveAttribute("data-state", "hidden");
  });
});

describe("page widths", () => {
  it("gives every section page the shell column by default, with the shared gutters", () => {
    const { container } = renderWithProviders(
      <PageMetaProvider>
        <Page title="Today">x</Page>
      </PageMetaProvider>,
    );
    const page = container.firstElementChild!;
    expect(page.className).toContain(PAGE_WIDTHS.default);
    expect(PAGE_WIDTHS.default).toBe("max-w-7xl");
    for (const cls of SHELL_GUTTERS.split(" ")) expect(page.className).toContain(cls);
  });
});

describe("sidebar", () => {
  function renderSidebar(route = "/", client = makeTestQueryClient()) {
    return renderWithProviders(<Sidebar />, { route, client });
  }

  it("is a 'Sidebar' landmark (not a second 'Main'), with Inbox current on a letter page", () => {
    viewport(1280);
    const qc = makeTestQueryClient();
    qc.setQueryData(qk.profile, PROFILE);
    renderSidebar("/documents/doc_1", qc);
    expect(screen.getByRole("complementary", { name: "Sidebar" })).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Main" })).toBeNull();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByRole("link", { name: "Inbox" })).toHaveAttribute("aria-current", "page");
  });

  it("links the profile row to Settings › Profile without a second current link", () => {
    viewport(1280);
    const qc = makeTestQueryClient();
    qc.setQueryData(qk.profile, PROFILE);
    renderSidebar("/settings", qc);
    const profile = screen.getByRole("link", { name: "Sam Rivera — your profile" });
    expect(profile).toHaveAttribute("href", "/settings?section=profile");
    expect(profile).not.toHaveAttribute("aria-current");
    expect(screen.getAllByRole("link").filter((a) => a.getAttribute("aria-current") === "page")).toHaveLength(1);
    expect(within(profile).getByText("Your data stays local").className).toContain("text-xs");
  });

  it("holds the profile's place while it loads, with the theme button on the right", () => {
    viewport(1280);
    renderSidebar();
    expect(screen.getByTestId("profile-loading")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Theme:/ }).className).toContain("ml-auto");
  });

  it("names every rail item under its icon and shows the count as a number (tablets)", () => {
    viewport(900);
    const qc = makeTestQueryClient();
    qc.setQueryData(qk.documents.list({ status: "needs_review" }), [{ id: "a" }]);
    renderSidebar("/", qc);
    const nav = screen.getByRole("navigation", { name: "Primary" });
    for (const item of NAV_ITEMS) expect(within(nav).getByText(item.short ?? item.label)).toBeVisible();
    const inbox = within(nav).getByRole("link", { name: "Inbox, 1 letter to check" });
    expect(within(inbox).getByText("1")).toBeInTheDocument();
    // no toggle on tablets: the rail always has its labels
    expect(screen.queryByRole("button", { name: /sidebar$/ })).toBeNull();
  });

  it("collapses and expands with one button that keeps focus", async () => {
    viewport(1280);
    renderSidebar();
    const user = userEvent.setup();
    const toggle = screen.getByRole("button", { name: "Collapse sidebar" });
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(document.activeElement).toBe(toggle);
    await user.keyboard("{Enter}");
    expect(document.activeElement).toHaveAccessibleName("Collapse sidebar");
    expect(localStorage.getItem("ordnung.sidebar.collapsed")).toBe("false");
  });
});

describe("demo badge", () => {
  it("is a named button that opens 'About the demo' with a way to close it", async () => {
    viewport(1280);
    renderWithProviders(<DemoBadge />);
    const user = userEvent.setup();
    const badge = screen.getByRole("button", { name: "Demo · 28 Sep 2026 — about the demo" });
    expect(badge.tagName).toBe("BUTTON");
    await user.click(badge);
    const dialog = await screen.findByRole("dialog", { name: "About the demo" });
    expect(within(dialog).getByText(/sample life/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(badge).toHaveFocus();
  });

  it("is hidden when not in the demo", () => {
    const qc = makeTestQueryClient();
    qc.setQueryData(qk.health, { ...TEST_HEALTH, demo: false, simulated_today: null });
    renderWithProviders(<DemoBadge compact />, { client: qc });
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("paused banner", () => {
  const now = new Date(2026, 8, 28, 10, 0); // Mon 28 Sep 2026, 10:00

  it("says when the break ends without an ambiguous weekday", () => {
    expect(pauseEnds(new Date(2026, 8, 28, 15, 30).toISOString(), now)).toBe("until 15:30 today");
    expect(pauseEnds(new Date(2026, 8, 29, 9, 5).toISOString(), now)).toBe("until 09:05 tomorrow");
    expect(pauseEnds(new Date(2026, 9, 5, 15, 30).toISOString(), now)).toBe("until Mon 5 Oct, 15:30");
    expect(pauseEnds("not a date", now)).toBeNull();
  });

  it("counts the letters waiting and lines up with the page column", async () => {
    const jobs = [
      { id: "j1", doc_id: "doc_a", status: "queued" },
      { id: "j2", doc_id: "doc_b", status: "queued" },
      { id: "j3", doc_id: "doc_b", status: "waiting" },
    ] as Job[];
    stubFetch({ "/jobs": jobs });
    const { client } = renderWithProviders(
      <PageMetaProvider>
        <PausedBanner />
      </PageMetaProvider>,
    );
    const until = new Date(2099, 0, 5, 15, 30).toISOString();
    act(() => handleServerEvent(client, { type: "llm.paused", data: { until, reason: "Usage limit reached." } }));
    const banner = await screen.findByRole("status");
    expect(await within(banner).findByText("· 2 letters waiting")).toBeInTheDocument();
    expect(banner).toHaveTextContent(/^Claude is taking a break until Mon 5 Jan 2099, 15:30 · 2 letters waiting\. Usage limit reached\./);
    const row = banner.firstElementChild!;
    for (const cls of [...SHELL_GUTTERS.split(" "), PAGE_WIDTHS.default]) expect(row.className).toContain(cls);
  });
});

describe("'isn't running' card", () => {
  it("stays up while 'Try again' runs, keeps focus on it and says when it still fails", async () => {
    const onRetry = vi.fn();
    const error = new ApiError(401, "no session");
    const { rerender } = render(<HealthUnreachable error={error} retrying={false} failures={1} onRetry={onRetry} />);
    // "Try again" can't help without the link: the button says what to do first
    const button = screen.getByRole("button", { name: "I opened the link — check again" });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Please open Ordnung from its link");
    button.focus();

    // TanStack clears the error while it refetches: the card keeps its message and its button
    rerender(<HealthUnreachable error={null} retrying failures={1} onRetry={onRetry} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Please open Ordnung from its link");
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).not.toBeDisabled();
    expect(button).toHaveFocus();
    await userEvent.setup().click(button);
    expect(onRetry).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent("Trying again…");

    rerender(<HealthUnreachable error={error} retrying={false} failures={2} onRetry={onRetry} />);
    expect(screen.getByRole("status")).toHaveTextContent("Still no access from this tab.");
    expect(button).toHaveFocus();
  });

  it("names the network case", () => {
    render(<HealthUnreachable error={new TypeError("Failed to fetch")} retrying={false} failures={2} onRetry={() => {}} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Ordnung isn't running");
    expect(screen.getByRole("status")).toHaveTextContent("Still can't reach Ordnung.");
    expect(screen.getByRole("main")).toContainElement(screen.getByRole("button", { name: "Try again" }));
  });
});

describe("skip link and main", () => {
  it("moves focus to main without changing the route (the static demo uses hash routes)", async () => {
    // the real layout needs the whole API; render its skip link and main the same way
    const { AppLayout } = await import("@/app/Layout");
    stubFetch({ "/health": TEST_HEALTH, "/profile": PROFILE });
    const client = makeTestQueryClient();
    client.setQueryData(qk.profile, PROFILE);
    function Nav() {
      const navigate = useNavigate();
      return <button onClick={() => navigate("/inbox")}>go</button>;
    }
    const router = createMemoryRouter([{ path: "/", element: <AppLayout />, children: [{ path: "*", element: <Nav /> }] }], { initialEntries: ["/x"] });
    vi.stubGlobal("EventSource", class { addEventListener() {} close() {} });
    vi.stubGlobal("scrollTo", () => {}); // ScrollRestoration
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    const skip = await screen.findByRole("link", { name: "Skip to content" });
    expect(skip.className).not.toMatch(/\bsr-only\b/);
    expect(skip.className).toContain("-translate-y-[150%]");
    expect(skip.className).toContain("focus:translate-y-0");
    expect(skip.className).toContain("px-3");
    expect(skip.className).toContain("whitespace-nowrap");
    const main = screen.getByRole("main");
    expect(main.className).toContain("room-for-overlays");
    await userEvent.setup().click(skip);
    expect(main).toHaveFocus();
    expect(router.state.location.pathname).toBe("/x");
    expect(router.state.location.hash).toBe("");
  });
});
