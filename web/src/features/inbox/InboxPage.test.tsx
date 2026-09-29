import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { QueryClient } from "@tanstack/react-query";
import { renderWithProviders } from "@/test/render";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { handleServerEvent, __resetEventsForTests } from "@/api/sse";
import type { JobProgressEvent } from "@/api/types";
import { createMockServer, type MockServer } from "@/mocks/server";
import { AddLettersProvider } from "@/components/shell/AddLetters";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import InboxPage from "@/pages/InboxPage";

let srv: MockServer;
/** Requests answered with HTTP 500 instead of the mock server (`GET /documents` → the list failed). */
let failing: Set<string>;

beforeEach(() => {
  srv = createMockServer({ staticDemo: false, latency: 0 });
  failing = new Set();
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    const path = url.pathname.replace(/^\/api/, "");
    if (failing.has(`${init?.method ?? "GET"} ${path}`)) return new Response(JSON.stringify({ detail: "Internal error" }), { status: 500, headers: { "Content-Type": "application/json" } });
    return srv.handle(init?.method ?? "GET", path, url.searchParams, body);
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  __resetEventsForTests();
  act(() => __clearToasts());
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

/** A `job.progress` event, as the server sends it while a letter is read. */
function progress(client: QueryClient, doc_id: string, status: JobProgressEvent["status"], error: string | null = null) {
  act(() =>
    handleServerEvent(client, {
      type: "job.progress",
      data: { job_id: `job_${doc_id}`, doc_id, stage: status === "done" ? "done" : "extract", progress: status === "done" ? 1 : 0.4, status, error },
    }),
  );
}

describe("Inbox", () => {
  it("shows the New-mail tray and the letters list with sender, kind, status and to-dos", async () => {
    const { container } = renderInbox();
    const tray = await screen.findByRole("region", { name: /New mail/ });
    expect(within(tray).getAllByRole("button", { name: "Let Ordnung read it" })).toHaveLength(5);
    expect(within(tray).getByText("Finanzamt Musterstadt")).toBeInTheDocument();
    expect(within(tray).getByRole("button", { name: "Read all 5" })).toBeInTheDocument();

    const parking = await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" });
    expect(parking).toHaveAttribute("href", "/documents/doc_parking");
    const row = parking.closest("li")!;
    expect(within(row).getAllByText("Please check").length).toBeGreaterThan(0);
    expect(within(row).getByRole("button", { name: /Ordnungsamt Musterstadt/ })).toBeInTheDocument();
    expect(within(row).getAllByText("1 to-do").length).toBeGreaterThan(0);
    assertNoRawEnumsInElement(container);
  });

  it("stamps each New-mail envelope with the day it arrived, and says it in words (R1-inbox-b-10)", async () => {
    renderInbox();
    const tray = await screen.findByRole("region", { name: /New mail/ });
    const card = within(tray).getByText("Stadtwerke Musterstadt").closest("li")!;
    expect(within(card).getByText("Arrived Mon 28 Sep")).toBeInTheDocument();
    expect(within(card).getByTestId("postmark-date")).toHaveTextContent("28SEP");
    // a letter without a known arrival day gets a postmark without a date, never today's
    const court = within(tray).getByText("Amtsgericht Hagen").closest("li")!;
    expect(within(court).queryByTestId("postmark-date")).toBeNull();
    expect(within(court).queryByText(/^Arrived/)).toBeNull();
  });

  it("filters to the letters that need checking", async () => {
    renderInbox();
    await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" });
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: /Please check/ }));
    await waitFor(() => expect(screen.queryByRole("link", { name: "Library: overdue books" })).toBeNull());
    expect(screen.getByRole("link", { name: "Parking fine (Verwarnungsgeld)" })).toBeInTheDocument();
  });

  it("filters by kind from the URL and offers to clear filters when nothing matches", async () => {
    renderInbox("/inbox?kind=tax_assessment");
    expect(await screen.findByText("No letters here")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" })).toBeInTheDocument();
  });

  it("takes the words from the top-bar search's 'See all letters matching …' (?q=) and keeps them in the URL", async () => {
    const { router } = renderInbox("/inbox?q=Parking");
    const field = await screen.findByRole("searchbox", { name: "Search letters" });
    expect(field).toHaveValue("Parking");
    expect(await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("link", { name: "Library: overdue books" })).toBeNull());
    // what the list shows, said (and announced) under the toolbar
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("1 letter matches “Parking”"));
    // typed words settle into the URL, so Back to the Inbox finds the search again
    const user = userEvent.setup();
    await user.clear(field);
    await user.type(field, "Library");
    await waitFor(() => expect(router.state.location.search).toBe("?q=Library"));
    expect(field).toHaveValue("Library");
    // another "See all letters matching …" while the Inbox is open takes over the field
    await act(() => router.navigate("/inbox?q=Parking"));
    await waitFor(() => expect(field).toHaveValue("Parking"));
  });

  it("asks for one more letter instead of ignoring a 1-character search", async () => {
    renderInbox();
    const field = await screen.findByRole("searchbox", { name: "Search letters" });
    await userEvent.setup().type(field, "P");
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Type one more letter to search."));
  });

  it("counts the tabs within the kind picked, and says how many of all letters show", async () => {
    renderInbox("/inbox?kind=dunning");
    await screen.findByRole("link", { name: "Library: overdue books" });
    expect(screen.getByRole("tab", { name: /^All/ })).toHaveTextContent(/^All2$/);
    // no "0" on phones' crowded tabs; "Please check" is the accessible name even where it shows "Check"
    expect(screen.getByRole("tab", { name: "Please check" })).not.toHaveTextContent("0");
    expect(screen.getByRole("status")).toHaveTextContent(/^Showing 2 of \d+ letters$/);
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();
  });

  it("explains Private when it is empty, without a second 'drop letters' box under it", async () => {
    renderInbox("/inbox?filter=private");
    expect(await screen.findByRole("heading", { name: "No private letters" })).toBeInTheDocument();
    expect(screen.getByText(/“Keep private — no AI”.*Claude never reads them/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add letters" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Drop letters|phone photos/ })).toBeNull();
  });

  it("doesn't ask a touch screen to drop letters", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query === "(pointer: coarse)", media: query, addEventListener() {}, removeEventListener() {} }));
    renderInbox();
    expect(await screen.findByRole("button", { name: /^Add letters — PDFs, phone photos or saved e\u2011mails/ })).toBeInTheDocument();
    expect(screen.queryByText(/Drop letters anywhere/)).toBeNull();
  });

  it("offers to clear just the search when only the search found nothing", async () => {
    const { router } = renderInbox("/inbox?q=Quittung%201999");
    const heading = await screen.findByRole("heading", { name: "No letters match “Quittung 1999”" });
    await userEvent.setup().click(within(heading.parentElement!).getByRole("button", { name: "Clear search" }));
    expect(await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" })).toBeInTheDocument();
    await waitFor(() => expect(router.state.location.search).toBe(""));
  });

  it("says the letters couldn't be loaded (never 'No letters yet') and tries again", async () => {
    failing.add("GET /documents");
    renderInbox();
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByRole("heading", { name: "Couldn't load your letters" })).toBeInTheDocument();
    expect(screen.queryByText("No letters yet")).toBeNull();
    expect(screen.queryByRole("button", { name: "Add letters" })).toBeNull();
    expect(screen.queryByRole("searchbox")).toBeNull();
    // the tray still works
    expect(await screen.findByRole("region", { name: /New mail/ })).toBeInTheDocument();
    failing.clear();
    await userEvent.setup().click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps a New-mail letter that couldn't be read actionable, names it in one alert and keeps focus on it", async () => {
    const { client } = renderInbox();
    const tray = await screen.findByRole("region", { name: /New mail, 5 letters/ });
    const card = within(tray).getByText("Finanzamt Musterstadt").closest("li")!;
    const user = userEvent.setup();
    await user.click(within(card).getByRole("button", { name: "Let Ordnung read it" }));
    // the button is gone: its envelope holds focus
    const envelope = within(card).getByRole("group", { name: "Letter from Finanzamt Musterstadt" });
    expect(envelope).toHaveFocus();
    await waitFor(() => expect(srv.db.state.tray.find((t) => t.id === "mail_finanzamt")?.doc_id).toBeTruthy());
    const docId = srv.db.state.tray.find((t) => t.id === "mail_finanzamt")!.doc_id!;
    progress(client, docId, "running");
    progress(client, docId, "failed", "Claude couldn't read this photo — it is too blurry.");

    expect(await within(card).findByText("Claude couldn't read this photo — it is too blurry.")).toBeInTheDocument();
    // one announcement (the toast), not a second alert on the card
    expect(within(card).queryByRole("alert")).toBeNull();
    expect(within(card).getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Add a sharper photo" })).toBeInTheDocument();
    const toastItem = (await screen.findByText("Couldn't read the letter from Finanzamt Musterstadt")).closest("li")!;
    await user.click(within(toastItem).getByRole("button", { name: "Show" }));
    expect(envelope).toHaveFocus();

    // taken out of New mail: focus moves to the next envelope, not to the page
    await user.click(within(card).getByRole("button", { name: "Remove from New mail" }));
    await waitFor(() => expect(card).not.toBeInTheDocument());
    expect(within(tray).getByRole("group", { name: "Letter from Stadtwerke Musterstadt" })).toHaveFocus();
    expect(within(tray).getByRole("heading", { name: /New mail, 4 letters/ })).toBeInTheDocument();
  });

  it("recaps a batch with the letters that couldn't be read, the tile's count matching Please check, then returns focus to the letters", async () => {
    const { client } = renderInbox();
    await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" });
    const ids = ["doc_parking", "doc_dentist", "doc_library"];
    ids.forEach((id) => progress(client, id, "running"));
    progress(client, "doc_parking", "done");
    progress(client, "doc_dentist", "done");
    progress(client, "doc_library", "failed", "Couldn't read this letter.");

    const dialog = await screen.findByRole("dialog", { name: "I read 2 of 3 letters" });
    const tile = await within(dialog).findByRole("link", { name: /needs you now/ });
    expect(tile).toHaveAttribute("href", "/inbox?filter=check");
    expect(tile).toHaveTextContent(/^1/); // the parking fine: the one letter Please check lists here
    const letters = within(dialog).getByRole("heading", { name: "The letters" }).nextElementSibling as HTMLElement;
    expect(within(letters).getAllByRole("link")).toHaveLength(3);
    expect(within(letters).getByRole("link", { name: /Parking fine/ })).toHaveTextContent("Please check");

    await userEvent.setup().click(within(dialog).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toHaveAttribute("href", expect.stringMatching(/^\/documents\//));
  });

  it("opens a tray letter and files it", async () => {
    renderInbox();
    const tray = await screen.findByRole("region", { name: /New mail/ });
    const user = userEvent.setup();
    const card = within(tray).getByText("Stadtwerke Musterstadt").closest("li")!;
    await user.click(within(card).getByRole("button", { name: "Let Ordnung read it" }));
    await waitFor(() => expect(srv.db.state.tray.find((t) => t.id === "mail_stadtwerke")?.opened).toBe(true));
    // the letter appears in the list right away (being read — titled from the tray, never the file name — or filed)
    expect(await screen.findByRole("link", { name: /— Stadtwerke Musterstadt|Electricity price increase from 1 Nov/ })).toHaveAttribute(
      "href",
      "/documents/doc_power_price",
    );
  });
});
