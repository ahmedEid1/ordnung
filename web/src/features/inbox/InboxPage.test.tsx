import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/render";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { createMockServer, type MockServer } from "@/mocks/server";
import { AddLettersProvider } from "@/components/shell/AddLetters";
import InboxPage from "@/pages/InboxPage";

let srv: MockServer;

beforeEach(() => {
  srv = createMockServer({ staticDemo: false, latency: 0 });
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    return srv.handle(init?.method ?? "GET", url.pathname.replace(/^\/api/, ""), url.searchParams, body);
  });
});
afterEach(() => vi.unstubAllGlobals());

function renderInbox(route = "/inbox") {
  return renderWithProviders(
    <AddLettersProvider>
      <InboxPage />
    </AddLettersProvider>,
    { route },
  );
}

describe("Inbox", () => {
  it("shows the New-mail tray and the letters list with sender, kind, status and to-dos", async () => {
    const { container } = renderInbox();
    const tray = await screen.findByRole("region", { name: /New mail/ });
    expect(within(tray).getAllByRole("button", { name: "Let Ordnung read it" })).toHaveLength(3);
    expect(within(tray).getByText("Finanzamt Musterstadt")).toBeInTheDocument();
    expect(within(tray).getByRole("button", { name: "Read all 3" })).toBeInTheDocument();

    const parking = await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" });
    expect(parking).toHaveAttribute("href", "/documents/doc_parking");
    const row = parking.closest("li")!;
    expect(within(row).getAllByText("Please check").length).toBeGreaterThan(0);
    expect(within(row).getByRole("button", { name: /Ordnungsamt Musterstadt/ })).toBeInTheDocument();
    expect(within(row).getAllByLabelText("1 open to-do").length).toBeGreaterThan(0);
    assertNoRawEnumsInElement(container);
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
