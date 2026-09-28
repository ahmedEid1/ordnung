/**
 * The Today page's layout and states (UI audit round 1, today-a): Coming up beside only the small
 * side cards (Ideas below at full width), no Idea that repeats the "Please check" card, a first
 * run that asks for letters instead of showing zeros, a loading page shaped like the real one, a
 * load error worded by cause that stays put while retrying, status in words on Life at a glance,
 * and a calendar card that stays (with focus) after the download.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { qk } from "@/api/hooks";
import type { Brief, Dashboard, Document, Party, Profile, Suggestion } from "@/api/types";
import { AddLettersProvider } from "@/components/shell/AddLetters";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { createMockServer } from "@/mocks/server";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { checkReason, repeatsPleaseCheck } from "./SideCards";
import { TodayView, dayErrorDescription } from "./TodayView";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

async function seededClient(mutate?: (d: Dashboard) => Dashboard, review?: Document[]): Promise<QueryClient> {
  const srv = createMockServer({ staticDemo: false, latency: 0 });
  const get = async <T,>(path: string, q = "") => (await (await srv.handle("GET", path, new URLSearchParams(q), undefined)).json()) as T;
  const qc = makeTestQueryClient();
  const dash = await get<Dashboard>("/dashboard");
  qc.setQueryData(qk.dashboard, mutate ? mutate(dash) : dash);
  qc.setQueryData(qk.parties.list(), await get<Party[]>("/parties"));
  qc.setQueryData(qk.documents.list({ status: "needs_review" }), review ?? (await get<Document[]>("/documents", "status=needs_review")));
  qc.setQueryData(qk.documents.list({}), await get<Document[]>("/documents"));
  qc.setQueryData(qk.brief, await get<Brief>("/brief"));
  qc.setQueryData(qk.profile, await get<Profile>("/profile"));
  return qc;
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("layout", () => {
  it("puts only Please check and the calendar beside Coming up, and Ideas below at full width", async () => {
    const client = await seededClient();
    renderWithProviders(<TodayView />, { client });
    const coming = await screen.findByRole("region", { name: /Coming up/ });
    const check = screen.getByRole("region", { name: /Please check/ });
    const calendar = screen.getByRole("region", { name: /calendar/i });
    const ideas = screen.getByRole("region", { name: "Ideas from your secretary" });

    const grid = coming.parentElement!;
    const side = check.parentElement!;
    expect(side.parentElement).toBe(grid);
    expect(side).toContainElement(calendar);
    expect(grid).not.toContainElement(ideas);
    // split by the page's own width (a container query), not the viewport's
    expect(grid.className).toContain("@[56rem]:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]");
    expect(grid.className).not.toMatch(/(^|\s)lg:/);
    // the side column starts level with Coming up's card, under its header
    expect(side.className).toMatch(/@\[56rem\]:pt-/);
    // Ideas: one column, two once there's room
    expect(ideas.parentElement!.className).toContain("@[40rem]:[&>section>ul]:grid-cols-2");
  });

  it("leaves the side column out when there is nothing for it", async () => {
    const client = await seededClient((d) => ({ ...d, suggestions: d.suggestions.filter((s) => s.rule_id !== "calendar_outdated") }), []);
    renderWithProviders(<TodayView />, { client });
    const coming = await screen.findByRole("region", { name: /Coming up/ });
    expect(coming.parentElement!.className).not.toContain("grid");
    expect(screen.queryByRole("region", { name: /Please check/ })).toBeNull();
  });
});

describe("Please check", () => {
  it("shows the letter's whole name and why, and no Idea repeats it", async () => {
    const user = userEvent.setup();
    const client = await seededClient();
    renderWithProviders(<TodayView />, { client });
    const check = await screen.findByRole("region", { name: /Please check · 1 letter/ });
    const title = within(check).getByText("Parking fine (Verwarnungsgeld)");
    expect(title.className).not.toContain("truncate");
    expect(within(check).getByText(/^We don't know when this letter arrived/)).not.toHaveClass("line-clamp-2");

    // "When did the parking fine arrive?" is the please_check Idea for the same letter
    const ideas = screen.getByRole("region", { name: "Ideas from your secretary" });
    const more = within(ideas).queryByRole("button", { name: /^Show \d+ more Ideas?/ });
    if (more) await user.click(more);
    expect(within(ideas).queryByText("When did the parking fine arrive?")).toBeNull();
    expect(within(ideas).getAllByRole("article").length).toBeGreaterThan(0);
  });

  it("knows which Idea only repeats the card, and drops a leading 'Please check:'", () => {
    const listed = new Set(["doc_a"]);
    const idea: Pick<Suggestion, "rule_id" | "action" | "refs"> = {
      rule_id: "please_check",
      action: { type: "open", draft_kind: null, target_type: "document", target_id: "doc_a", label: null },
      refs: [],
    };
    expect(repeatsPleaseCheck(idea, listed)).toBe(true);
    expect(repeatsPleaseCheck({ ...idea, action: null, refs: [{ type: "document", id: "doc_a" }] }, listed)).toBe(true);
    expect(repeatsPleaseCheck({ ...idea, rule_id: "expiry_soon" }, listed)).toBe(false);
    expect(repeatsPleaseCheck(idea, new Set(["doc_b"]))).toBe(false);
    expect(checkReason("Please check: 1 date could not be confirmed against the letter's text.")).toBe("1 date could not be confirmed against the letter's text.");
    expect(checkReason("please check – the amount")).toBe("The amount");
    expect(checkReason("We don't know when it arrived.")).toBe("We don't know when it arrived.");
  });
});

describe("first run", () => {
  it("asks for the first letters instead of showing zeros and 'All clear'", async () => {
    const client = await seededClient(
      (d) => ({
        ...d,
        attention: [],
        upcoming: [],
        decisions: [],
        suggestions: [],
        areas: [],
        recent_documents: [],
        waiting: 0,
        money: { ...d.money, fixed_costs_monthly: 0, fixed_costs_monthly_other_currencies: {} },
        stats: { ...d.stats, documents: 0, contracts: 0, open_items: 0 },
      }),
      [],
    );
    renderWithProviders(
      <AddLettersProvider>
        <TodayView />
      </AddLettersProvider>,
      { client },
    );
    expect(await screen.findByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening), Sam$/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Add your first letters" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add letters" })).toBeInTheDocument();
    expect(screen.getByText("Your files stay on this computer.")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    // nothing that only makes sense with letters
    expect(screen.queryByRole("link", { name: /To pay/ })).toBeNull();
    expect(screen.queryByText(/€0/)).toBeNull();
    expect(screen.queryByRole("region", { name: "Top 3 this week" })).toBeNull();
    expect(screen.queryByRole("region", { name: /Coming up/ })).toBeNull();
    expect(screen.queryByRole("region", { name: "Ideas from your secretary" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Write a new note" })).toBeNull();
    expect(screen.queryByText(/All clear/)).toBeNull();
  });
});

describe("loading and errors", () => {
  it("loads with the real greeting and the page's own shape", async () => {
    vi.stubGlobal("fetch", () => new Promise<Response>(() => {}));
    renderWithProviders(<TodayView />);
    const busy = document.querySelector("[aria-busy=true]")!;
    expect(busy).toBeTruthy();
    expect(within(busy as HTMLElement).getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening)$/ })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading your day…");
    // the same split as the loaded page
    expect(busy.innerHTML).toContain("@[56rem]:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]");
  });

  it("says what went wrong in words that fit the cause, and stays put while retrying", async () => {
    let dashboardCalls = 0;
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/dashboard")) {
        dashboardCalls += 1;
        // the retry hangs, so we can look at the page while it runs
        if (dashboardCalls > 1) return new Promise<Response>(() => {});
      }
      return json({ detail: "Internal error" }, 500);
    });
    const user = userEvent.setup();
    renderWithProviders(<TodayView />);
    const alert = await screen.findByRole("alert");
    expect(screen.getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening)$/ })).toBeInTheDocument();
    expect(within(alert).getByRole("heading", { level: 2, name: "Couldn't load your day" })).toBeInTheDocument();
    expect(alert).toHaveTextContent("Ordnung ran into a problem while putting your day together");
    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    // the same message, not the loading page, while the retry runs
    await waitFor(() => expect(within(alert).getByRole("button", { name: "Try again" })).toHaveAttribute("aria-busy", "true"));
    expect(dashboardCalls).toBe(2);
    expect(alert).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBe(alert);
    expect(alert).toHaveTextContent("Ordnung ran into a problem while putting your day together");
    expect(screen.queryByText("Loading your day…")).toBeNull();
  });

  it("words the error by cause", () => {
    expect(dayErrorDescription(new ApiError(500, "boom"))).toMatch(/ran into a problem/);
    expect(dayErrorDescription(new ApiError(0, "unreachable"))).toMatch(/didn't answer/);
    expect(dayErrorDescription(new ApiError(404, "gone"))).toMatch(/couldn't put your day together/);
  });
});

describe("life at a glance", () => {
  it("says the status in words and an icon, one tile per row on the smallest phones", async () => {
    const client = await seededClient();
    renderWithProviders(<TodayView />, { client });
    const areas = await screen.findByRole("region", { name: "Life at a glance" });
    const list = within(areas).getByRole("list");
    expect(list.className).toMatch(/(^|\s)grid-cols-1(\s|$)/);
    expect(list.className).toContain("min-[360px]:grid-cols-2");
    const tiles = within(list).getAllByRole("link");
    const flagged = tiles.filter((t) => t.querySelector("[data-status]"));
    expect(flagged.length).toBeGreaterThan(0);
    for (const tile of flagged) {
      const badge = tile.querySelector<HTMLElement>("[data-status]")!;
      expect(badge).toHaveTextContent(badge.dataset.status === "urgent" ? "Urgent" : "Needs attention");
      expect(badge.querySelector("svg")).toBeTruthy();
    }
    // an area that is fine stays quiet on screen and says so to screen readers
    for (const tile of tiles.filter((t) => !t.querySelector("[data-status]"))) expect(within(tile).getByText("All good")).toHaveClass("sr-only");
  });
});

describe("greeting", () => {
  it("keeps the money figures whole: labels on one line, '/month' as its own part", async () => {
    const client = await seededClient();
    renderWithProviders(<TodayView />, { client });
    const fixed = await screen.findByRole("link", { name: /Fixed costs/ });
    expect(fixed.className).not.toContain("min-w-0");
    expect(within(fixed).getByText("Fixed costs")).toHaveClass("whitespace-nowrap");
    expect(within(fixed).getByText("/month")).toHaveClass("whitespace-nowrap");
    expect(fixed.querySelector("wbr")).toBeTruthy();
    // beside the greeting only when the page is wide enough for both (a container query)
    expect(fixed.closest("header")!.className).toContain("@container");
  });
});

describe("calendar card", () => {
  it("stays after the download, with focus on its button", async () => {
    useMockApi();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <TodayView />
        <Toaster />
      </>,
    );
    const card = await screen.findByRole("region", { name: /calendar/i });
    await user.click(within(card).getByRole("button", { name: "Add to calendar" }));
    expect(click).toHaveBeenCalled();
    await screen.findByText("Calendar file downloaded", { selector: "[data-toast] *" });
    const done = screen.getByRole("region", { name: "Calendar file downloaded" });
    expect(document.activeElement).toBe(within(done).getByRole("button", { name: "Download again" }));
    click.mockRestore();
  });
});
