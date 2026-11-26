import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { __resetEventsForTests } from "@/api/sse";
import type { DocumentRow } from "@/api/types";
import { createMockServer, type MockServer } from "@/mocks/server";
import { AddLettersProvider } from "@/components/shell/AddLetters";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { makeRow } from "@/features/document/fixtures";
import { renderWithProviders } from "@/test/render";
import InboxPage from "@/pages/InboxPage";
import { firstRows } from "./rows";

let srv: MockServer;
/** The letters `GET /documents` answers. */
let listed: DocumentRow[];

const json = (data: unknown) => new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });

/** `n` letters, one a day back from the day before the app's today: "Letter 1" is the newest; the first `invoices` are invoices. */
function letters(n: number, invoices = 0): DocumentRow[] {
  const day = Date.UTC(2026, 8, 27);
  return Array.from({ length: n }, (_, i) => {
    const date = new Date(day - i * 86_400_000).toISOString().slice(0, 10);
    return makeRow({
      id: `doc_${String(i + 1).padStart(4, "0")}`,
      title: `Letter ${i + 1}`,
      kind: i < invoices ? "invoice" : "other",
      received_date: date,
      doc_date: date,
      created_at: `${date}T09:00:00Z`,
      party_id: null,
    });
  });
}

beforeEach(() => {
  srv = createMockServer({ staticDemo: false, latency: 0 });
  listed = letters(250);
  window.history.replaceState(null, "", "/inbox");
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace(/^\/api/, "");
    const method = init?.method ?? "GET";
    if (method === "GET" && path === "/documents" && !url.searchParams.get("q")) return json(listed);
    return srv.handle(method, path, url.searchParams, typeof init?.body === "string" ? JSON.parse(init.body) : undefined);
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  __resetEventsForTests();
  act(() => __clearToasts());
  window.history.replaceState(null, "", "/");
});

function renderInbox(route = "/inbox") {
  return renderWithProviders(
    <AddLettersProvider>
      <InboxPage />
      <Toaster />
    </AddLettersProvider>,
    { route },
  );
}

/** The letter rows drawn. */
const drawnRows = () => document.querySelectorAll("section[aria-labelledby^='grp-'] > ul > li");
const rowLink = (i: number) => drawnRows()[i]!.querySelector<HTMLElement>("a[href^='/documents/']")!;
const live = () => screen.getByRole("status");

describe("a long Inbox draws its first rows", () => {
  it("draws the first 100 letters, counts every letter in its groups, and says how many are shown", async () => {
    renderInbox();
    expect(await screen.findByRole("link", { name: "Letter 1" })).toBeInTheDocument();
    expect(drawnRows()).toHaveLength(100);
    expect(screen.queryByRole("link", { name: "Letter 101" })).toBeNull();
    // the group cut short (June) still counts all of its letters: 30 days, 11 of them drawn (30 June back to 20 June)
    const june = screen.getByRole("heading", { level: 3, name: /^June/ });
    expect(june).toHaveTextContent("(30 letters)");
    expect(june.closest("section")!.querySelectorAll(":scope > ul > li")).toHaveLength(11);
    expect(screen.getByText(/^Showing 100 of 250 letters\. The search looks through all of them; your browser’s own find only through the ones shown\.$/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show 100 more" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show all 250" })).toBeInTheDocument();
    expect(live()).toHaveTextContent(/^Showing 100 of 250 letters\.$/);
    // the kinds count every letter
    expect(within(screen.getByRole("combobox", { name: /Kind/ })).getByRole("option", { name: / \(250\)$/ })).toBeInTheDocument();
  });

  it("from the keyboard, focus goes to the first new letter; when the last rows come, never to the page", async () => {
    const user = userEvent.setup();
    renderInbox();
    await screen.findByRole("link", { name: "Letter 1" });
    screen.getByRole("button", { name: "Show 100 more" }).focus();
    await user.keyboard("{Enter}");
    expect(drawnRows()).toHaveLength(200);
    await waitFor(() => expect(screen.getByRole("link", { name: "Letter 101" })).toHaveFocus());
    expect(live()).toHaveTextContent(/^Showing 200 of 250 letters\.$/);
    // 50 left: one button for all of them
    expect(screen.queryByRole("button", { name: /more$/ })).toBeNull();

    // with the mouse the button goes with the last rows: focus goes to the first new letter, not to the page
    await user.click(screen.getByRole("button", { name: "Show all 250" }));
    expect(drawnRows()).toHaveLength(250);
    await waitFor(() => expect(rowLink(200)).toHaveFocus());
    expect(rowLink(200)).toHaveAccessibleName("Letter 201");
    expect(screen.queryByRole("button", { name: /^Show / })).toBeNull();
    expect(screen.queryByText(/^Showing \d+ of/)).toBeNull();
    // said once: the whole Inbox's line says nothing itself
    expect(live()).toHaveTextContent(/^Showing all 250 letters\.$/);
  });

  it("with the mouse, focus stays on the button while it stays", async () => {
    listed = letters(350);
    const user = userEvent.setup();
    renderInbox();
    await screen.findByRole("link", { name: "Letter 1" });
    const more = screen.getByRole("button", { name: "Show 100 more" });
    await user.click(more);
    expect(drawnRows()).toHaveLength(200);
    // a frame later, still there (focus is moved, when it is, on the next frames)
    await act(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    expect(more).toHaveFocus();
    expect(screen.getByText(/^Showing 200 of 350 letters\. The search/)).toBeInTheDocument();
  });

  it("a narrowed view says what it holds, and how many of them show, each sentence with its full stop", async () => {
    listed = letters(250, 150);
    renderInbox("/inbox?kind=invoice");
    await screen.findByRole("link", { name: "Letter 1" });
    expect(drawnRows()).toHaveLength(100);
    // what the view holds (never "Showing 150" while 100 rows are drawn), then the rows drawn of it
    expect(screen.getByText("150 of 250 letters in this view.")).toBeInTheDocument();
    expect(live()).toHaveTextContent(/^150 of 250 letters in this view\. Showing 100 of 150 letters\.$/);
    expect(screen.getByRole("button", { name: "Show all 150" })).toBeInTheDocument();
  });

  it("another view starts at 100 again", async () => {
    listed = letters(250, 150);
    const user = userEvent.setup();
    renderInbox();
    await screen.findByRole("link", { name: "Letter 1" });
    await user.click(screen.getByRole("button", { name: "Show all 250" }));
    expect(drawnRows()).toHaveLength(250);
    await user.selectOptions(screen.getByRole("combobox", { name: /Kind/ }), "invoice");
    await waitFor(() => expect(drawnRows()).toHaveLength(100));
    expect(screen.getByRole("button", { name: "Show all 150" })).toBeInTheDocument();
  });

  it("keeps the rows in the history entry: the same entry draws them again, a new load of the page starts at 100", async () => {
    const user = userEvent.setup();
    const first = renderInbox();
    await screen.findByRole("link", { name: "Letter 1" });
    await user.click(screen.getByRole("button", { name: "Show all 250" }));
    expect(drawnRows()).toHaveLength(250);
    expect((window.history.state as { inboxRows?: { rows: number } }).inboxRows?.rows).toBe(Infinity);
    first.unmount();

    // the same entry again (Back, Forward, a reload): all of them
    const same = renderInbox();
    await screen.findByRole("link", { name: "Letter 1" });
    expect(drawnRows()).toHaveLength(250);
    same.unmount();

    // a new load (a typed address, a bookmark): a new entry, whose router key is "default" again, as every first
    // entry's is — 100 rows
    window.history.pushState(null, "", "/inbox");
    renderInbox();
    await screen.findByRole("link", { name: "Letter 1" });
    expect(drawnRows()).toHaveLength(100);
    expect(sessionStorage.length).toBe(0);
  });

  it("a list of 100 letters or fewer looks as it always did", async () => {
    listed = letters(100);
    renderInbox();
    await screen.findByRole("link", { name: "Letter 1" });
    expect(drawnRows()).toHaveLength(100);
    expect(screen.queryByRole("button", { name: /^Show / })).toBeNull();
    expect(screen.queryByText(/^Showing/)).toBeNull();
    expect(live()).toHaveTextContent(/^$/);
  });
});

describe("firstRows", () => {
  it("keeps the order, cuts the group where the rows end and counts all of its letters", () => {
    const docs = letters(5);
    const groups = [
      { key: "a", label: "A", docs: docs.slice(0, 2) },
      { key: "b", label: "B", docs: docs.slice(2, 5) },
    ];
    expect(firstRows(groups, 3).map((g) => [g.key, g.docs.map((d) => d.title), g.count])).toEqual([
      ["a", ["Letter 1", "Letter 2"], 2],
      ["b", ["Letter 3"], 3],
    ]);
    expect(firstRows(groups, Infinity).map((g) => g.docs.length)).toEqual([2, 3]);
  });
});
