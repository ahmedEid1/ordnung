/**
 * The letter search (audit round 1, bucket "shell-b"): results that show whole titles (two lines,
 * the query highlighted, the full title on hover), a visible and scrolled-to active option, a clear
 * focus ring, every state said (hint, searching, nothing found, no letters yet, error with "Try
 * again", how many were found), "See all" when there are more, recent letters in the empty phone
 * sheet, and Escape that clears before it closes. Layout (panel width, the sheet at 320 px) is
 * checked on real pages in `e2e/shell.spec.ts`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/render";
import { createMockServer, type MockServer } from "@/mocks/server";
import { SEARCH_LIMIT } from "@/api/hooks";
import { AddLettersProvider } from "./AddLetters";
import { Highlight, SearchBox } from "./SearchBox";

let srv: MockServer;
/** Answers `/api/documents?q=` from the mock server unless a test overrides it. */
let searchOverride: ((q: string) => Response | Promise<Response>) | null = null;
let listOverride: (() => Response) | null = null;

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

beforeEach(() => {
  srv = createMockServer({ staticDemo: false, latency: 0 });
  searchOverride = null;
  listOverride = null;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace(/^\/api/, "");
    if (path === "/documents" && url.searchParams.get("q") && searchOverride) return searchOverride(url.searchParams.get("q")!);
    if (path === "/documents" && !url.searchParams.get("q") && listOverride) return listOverride();
    return srv.handle(init?.method ?? "GET", path, url.searchParams, undefined);
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function renderSearch() {
  return renderWithProviders(
    <AddLettersProvider>
      <main>
        <SearchBox />
      </main>
    </AddLettersProvider>,
  );
}

/** The top-bar field (the phone sheet has its own, inside its dialog). */
const topField = () => screen.getAllByRole("combobox", { name: "Search your letters" })[0]!;

describe("Highlight", () => {
  it("marks every word of the query, in any case, and nothing for one letter", () => {
    const { container, rerender } = renderWithProviders(<Highlight text="Stadt Musterstadt – Ordnungsamt" query="muster ordnung" />);
    expect(Array.from(container.querySelectorAll("mark")).map((m) => m.textContent)).toEqual(["Muster", "Ordnung"]);
    expect(container.querySelector("mark")).toHaveClass("marker");
    rerender(<Highlight text="Musterstadt" query="M" />);
    expect(container.querySelector("mark")).toBeNull();
  });

  it("treats the query as text, not as a pattern", () => {
    const { container } = renderWithProviders(<Highlight text="Invoice (RE-2026) 34.99 €" query="(RE-2026)" />);
    expect(container.querySelector("mark")).toHaveTextContent("(RE-2026)");
  });
});

describe("search results", () => {
  it("show two-line titles with the query marked, the full title on hover, and a link to all when there are more", async () => {
    renderSearch();
    const user = userEvent.setup();
    await user.click(topField());
    await user.type(topField(), "Muster");
    const list = await screen.findByRole("listbox", { name: "Matching letters" });
    const options = within(list).getAllByRole("option");
    expect(options.length).toBeGreaterThan(0);
    expect(options.length).toBeLessThanOrEqual(SEARCH_LIMIT);
    for (const o of options) {
      expect(o.getAttribute("title")).toBeTruthy();
      // the title is clamped to two lines, not cut to one
      expect(o.querySelector(".line-clamp-2")).not.toBeNull();
    }
    expect(list.querySelector("mark")).toHaveTextContent(/muster/i);
    // how many were found is said, once the search has settled
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/letters? found/));
  });

  it("links to every match in the Inbox when there are more than it lists", async () => {
    const many = Array.from({ length: SEARCH_LIMIT + 1 }, (_, i) => ({ ...srv.db.state.documents[0]!, id: `doc_many_${i}`, title: `Musterbrief ${i + 1}` }));
    searchOverride = () => json(many);
    renderSearch();
    const user = userEvent.setup();
    await user.click(topField());
    await user.type(topField(), "Muster");
    const all = await screen.findByRole("link", { name: "See all letters matching “Muster”" });
    expect(all).toHaveAttribute("href", "/inbox?q=Muster");
    expect(screen.getAllByRole("option")).toHaveLength(SEARCH_LIMIT);
    expect(screen.getByRole("status")).toHaveTextContent(`More than ${SEARCH_LIMIT} letters found`);
  });

  it("marks the active option clearly and scrolls it into view with the arrow keys", async () => {
    const many = Array.from({ length: SEARCH_LIMIT }, (_, i) => ({ ...srv.db.state.documents[0]!, id: `doc_many_${i}`, title: `Musterbrief ${i + 1}` }));
    searchOverride = () => json(many);
    // (jsdom has no layout, so no scrollIntoView: record which option asks to be shown)
    const scrolled: string[] = [];
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value(this: HTMLElement) {
        scrolled.push(this.id);
      },
    });
    renderSearch();
    const user = userEvent.setup();
    await user.click(topField());
    await user.type(topField(), "Muster");
    await screen.findByRole("listbox", { name: "Matching letters" });
    const first = screen.getAllByRole("option")[0]!;
    expect(first).toHaveAttribute("aria-selected", "true");
    expect(first).toHaveClass("bg-accent-soft", "ring-1", "ring-inset", "ring-accent");
    for (let i = 0; i < 7; i++) await user.keyboard("{ArrowDown}");
    const last = screen.getAllByRole("option")[7]!;
    expect(last).toHaveAttribute("aria-selected", "true");
    expect(topField()).toHaveAttribute("aria-activedescendant", last.id);
    expect(scrolled.at(-1)).toBe(last.id);
    delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView;
  });

  it("is a dropdown as wide as the field for a message, and up to 30rem for results", async () => {
    renderSearch();
    const user = userEvent.setup();
    await user.click(topField());
    await user.type(topField(), "M");
    const panel = () => document.querySelector("[data-search-panel]")!;
    expect(panel()).toHaveTextContent("Keep typing");
    expect(panel()).toHaveClass("min-w-full", "w-full");
    await user.type(topField(), "uster");
    await screen.findByRole("listbox", { name: "Matching letters" });
    expect(panel()).toHaveClass("min-w-full", "w-[min(30rem,calc(100vw-2rem))]");
  });
});

describe("search field", () => {
  it("has a clear focus ring, names its shortcut, and hides the key hint while focused", async () => {
    renderSearch();
    const field = topField();
    expect(field).toHaveClass("focus:ring-2", "focus:ring-accent/60");
    expect(field).toHaveAttribute("aria-keyshortcuts", expect.stringContaining("/"));
    const hint = screen.getByText("/", { selector: "kbd" });
    expect(hint.parentElement).toHaveAttribute("aria-hidden", "true");
    await userEvent.setup().click(field);
    expect(screen.queryByText("/", { selector: "kbd" })).toBeNull();
  });
});

describe("search states", () => {
  it("says it is searching while the first answer is on its way", async () => {
    let answer: (r: Response) => void = () => {};
    searchOverride = () => new Promise<Response>((resolve) => (answer = resolve));
    renderSearch();
    const user = userEvent.setup();
    await user.click(topField());
    await user.type(topField(), "Muster");
    expect(await screen.findByText("Searching…")).toBeInTheDocument();
    await act(async () => answer(json([])));
  });

  it("tells a failed search from no matches, with a way to try again", async () => {
    let calls = 0;
    searchOverride = () => {
      calls += 1;
      return json({ detail: "boom" }, 500);
    };
    renderSearch();
    const user = userEvent.setup();
    await user.click(topField());
    await user.type(topField(), "Muster");
    expect(await screen.findByText(/Couldn't search — Ordnung isn't answering/)).toBeInTheDocument();
    expect(screen.queryByText(/No letters match/)).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Couldn't search");
    const before = calls;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(calls).toBeGreaterThan(before));
  });

  it("says when nothing matches", async () => {
    searchOverride = () => json([]);
    renderSearch();
    const user = userEvent.setup();
    await user.click(topField());
    await user.type(topField(), "Quittung 1999");
    expect(await screen.findByText("No letters match “Quittung 1999”.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("No letters match “Quittung 1999”");
  });

  it("on a new install, offers to add letters instead of 'no match'", async () => {
    searchOverride = () => json([]);
    listOverride = () => json([]);
    renderSearch();
    const user = userEvent.setup();
    await user.click(topField());
    await user.type(topField(), "Muster");
    expect(await screen.findByText("You haven't added any letters yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add letters" })).toBeInTheDocument();
  });
});

describe("Escape", () => {
  it("in the phone sheet: the first Escape clears the words, the next one closes the sheet", async () => {
    renderSearch();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Search letters" }));
    const sheet = await screen.findByRole("dialog", { name: "Search letters" });
    const field = within(sheet).getByRole("combobox", { name: "Search your letters" });
    await waitFor(() => expect(field).toHaveFocus());
    await user.type(field, "Muster");
    await user.keyboard("{Escape}");
    expect(field).toHaveValue("");
    expect(screen.getByRole("dialog", { name: "Search letters" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Search letters" })).toBeNull());
  });

  it("on the top bar: Escape clears, and focus stays in the field", async () => {
    renderSearch();
    const user = userEvent.setup();
    await user.click(topField());
    await user.type(topField(), "Muster");
    await user.keyboard("{Escape}");
    expect(topField()).toHaveValue("");
    expect(topField()).toHaveAttribute("aria-expanded", "false");
    await user.keyboard("{Escape}");
    expect(topField()).toHaveFocus();
  });
});

describe("the empty phone sheet", () => {
  it("shows the hint and the recent letters (none highlighted until the arrow keys)", async () => {
    renderSearch();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Search letters" }));
    const sheet = await screen.findByRole("dialog", { name: "Search letters" });
    expect(within(sheet).getByText(/Search senders, subjects, amounts or reference numbers/)).toBeInTheDocument();
    const recent = await within(sheet).findByRole("listbox", { name: "Recent letters" });
    const options = within(recent).getAllByRole("option");
    expect(options.length).toBeGreaterThan(0);
    for (const o of options) expect(o).toHaveAttribute("aria-selected", "false");
    // the date sits in the meta line; the kind is the icon's name
    expect(options[0]!.querySelector("time")).not.toBeNull();
    expect(within(options[0]!).getByRole("img")).toHaveAccessibleName();
    const field = within(sheet).getByRole("combobox", { name: "Search your letters" });
    await waitFor(() => expect(field).toHaveFocus());
    await user.keyboard("{ArrowDown}");
    expect(options[0]).toHaveAttribute("aria-selected", "true");
  });
});
