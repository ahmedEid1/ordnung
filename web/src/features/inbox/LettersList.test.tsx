/**
 * The Inbox letters list on the mock server (the static demo's data): what a row says and how it
 * is built — to-do counts in words, full titles, arrival dates, headings, "Just read" and "New".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { createMockServer, type MockServer } from "@/mocks/server";
import { AddLettersProvider } from "@/components/shell/AddLetters";
import InboxPage from "@/pages/InboxPage";
import { LettersList } from "./LettersList";
import { markLetterSeen, resetSeenLetters } from "./seen";

let srv: MockServer;

beforeEach(() => {
  resetSeenLetters();
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

const rowOf = (link: HTMLElement) => link.closest("li")!;

describe("Inbox letters list", () => {
  it("says what the to-do count counts, in a chip that is not a tab stop", async () => {
    renderInbox();
    const link = await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" });
    const row = rowOf(link);
    const chips = within(row).getAllByText("1 to-do");
    expect(chips.length).toBeGreaterThan(0);
    for (const chip of chips) {
      // a plain Badge: one line, never shrinks, no focus stop of its own
      const badge = chip.closest("span.rounded-full")!;
      expect(badge).toHaveClass("whitespace-nowrap", "shrink-0");
      expect(badge).not.toHaveAttribute("tabindex");
      expect(badge.getAttribute("title")).toMatch(/^1 open to-do · next: /);
    }
    // moving from letter to letter, a screen reader hears the count with the title
    expect(link).toHaveAccessibleDescription("1 open to-do");
    // the only tab stops in a row: the letter and its sender
    const focusable = row.querySelectorAll("a, button, [tabindex]");
    expect([...focusable].map((el) => el.tagName)).toEqual(["A", "BUTTON"]);
  });

  it("keeps every title readable: two lines in stacked rows, one line with the full title in the table", async () => {
    renderInbox();
    const link = await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" });
    expect(link).toHaveAttribute("title", "Parking fine (Verwarnungsgeld)");
    expect(link).toHaveClass("line-clamp-2", "break-words", "@4xl:truncate");
    // the table columns only appear once the list itself is wide enough (container query)
    const grid = rowOf(link).firstElementChild!;
    expect(grid.className).toMatch(/@4xl:grid-cols-\[/);
    expect(grid.className).not.toMatch(/(^|\s)md:grid-cols/);
  });

  it("shows the arrival date the groups are built from, with the letter's date in its tooltip", async () => {
    renderInbox();
    // arrived Fri 25 Sep, dated Thu 24 Sep
    const row = rowOf(await screen.findByRole("link", { name: "Dentist appointment reminder" }));
    const dates = within(row).getAllByTitle("Arrived Fri 25 Sep · letter dated Thu 24 Sep");
    expect(dates.length).toBeGreaterThan(0);
    for (const d of dates) expect(d).toHaveTextContent(/^Arrived 25 Sep$/);
    expect(within(row).queryByText("24 Sep")).toBeNull();
    // no arrival date: when it was added
    const parking = rowOf(screen.getByRole("link", { name: "Parking fine (Verwarnungsgeld)" }));
    expect(within(parking).getAllByTitle(/^Added .* · letter dated Tue 22 Sep$/).length).toBeGreaterThan(0);
  });

  it("counts no to-do its payment reminder took over, and shows it as no next step (R2-inbox-timeline-contracts-2)", async () => {
    // the invoice payment still open, as on the real demo: "Pay by Thu 3 Sep · 25 days overdue", "1 to-do"
    srv.db.state.items.find((i) => i.id === "itm_tm_invoice")!.status = "open";
    renderInbox();
    const invoice = rowOf(await screen.findByRole("link", { name: "TechMarkt invoice — USB-C dock" }));
    expect(within(invoice).queryByText(/to-do/)).toBeNull();
    expect(within(invoice).queryByText(/overdue|Pay by/)).toBeNull();
    // the reminder that replaced it is the one to pay
    const reminder = rowOf(screen.getByRole("link", { name: "TechMarkt payment reminder" }));
    expect(within(reminder).getAllByText("1 to-do").length).toBeGreaterThan(0);
  });

  it("says 'No sender' only for a letter that was read: one kept private unread has no sender line (R2-inbox-timeline-contracts-4)", async () => {
    await srv.handle("POST", "/documents/held/keep-private", new URLSearchParams(), { doc_ids: ["doc_folder_scan"] });
    renderInbox();
    const link = await screen.findByRole("link", { name: "Scan_2026-09-28_0914.pdf" });
    const row = rowOf(link);
    expect(within(row).getAllByText("Private").length).toBeGreaterThan(0);
    expect(within(row).queryByText("No sender")).toBeNull();
  });

  it("spells out an appointment's day and time; the dot stays with the title", async () => {
    renderInbox();
    const row = rowOf(await screen.findByRole("link", { name: "Dentist appointment reminder" }));
    const next = within(row).getByText(/^Dentist: check-up & cleaning/).closest("p")!;
    expect(next.textContent).toBe("Dentist: check-up & cleaning · Thu 8 Oct, 09:15 · in 10 days");
  });

  it("nests the groups under an h2, with or without the New-mail tray", async () => {
    renderInbox();
    await screen.findByRole("link", { name: "Parking fine (Verwarnungsgeld)" });
    expect(screen.getByRole("heading", { level: 2, name: "Your letters" })).toBeInTheDocument();
    const groups = screen.getAllByRole("heading", { level: 3 });
    expect(groups.length).toBeGreaterThan(1);
    expect(groups[0]).toHaveClass("eyebrow");
    expect(groups[0]).toHaveAccessibleName(/^Last 7 days ?\(\d+ letters?\)$/);
    // the h2 comes after the tray's h2 and before every group
    const order = [...document.querySelectorAll("h2, h3")].map((h) => h.textContent);
    expect(order.indexOf("Your letters")).toBeLessThan(order.findIndex((t) => t?.startsWith("Last 7 days")));
  });

  it("shows a letter being read with its stepper on a line of its own, so the title never moves", async () => {
    srv.db.state.documents.find((d) => d.id === "doc_library")!.status = "processing";
    renderInbox();
    const link = await screen.findByRole("link", { name: "Library: overdue books" });
    expect(screen.getAllByRole("heading", { level: 3 })[0]).toHaveTextContent(/^Being read/);
    const row = rowOf(link);
    const stepper = within(row).getByRole("list", { name: /^Reading / });
    expect(link.parentElement!.contains(stepper)).toBe(false);
    expect(within(row).getByText("Reading…")).toHaveClass("line-clamp-2");
    // no countdown to act on while it is still being read
    expect(within(row).queryByText(/transfer by|send by/)).toBeNull();
  });

  it("puts letters read from New mail on top ('Just read'), marked New until their page was opened", async () => {
    // the Library letter came out of the tray
    const mail = srv.db.state.tray[0]!;
    mail.opened = true;
    mail.doc_id = "doc_library";
    renderInbox();
    const link = await screen.findByRole("link", { name: "Library: overdue books" });
    const groups = screen.getAllByRole("heading", { level: 3 });
    expect(groups[0]).toHaveTextContent(/^Just read/);
    const justRead = groups[0]!.closest("section")!;
    expect(within(justRead).getAllByRole("link", { name: /./ }).filter((a) => a.getAttribute("href")?.startsWith("/documents/"))).toEqual([link]);
    await waitFor(() => expect(within(rowOf(link)).getAllByText("New").length).toBeGreaterThan(0));

    act(() => markLetterSeen("doc_library"));
    expect(within(rowOf(link)).queryByText("New")).toBeNull();
    // still on top: it did just arrive
    expect(screen.getAllByRole("heading", { level: 3 })[0]).toHaveTextContent(/^Just read/);
  });

  it("adds a page's own note as the last line of a letter's row, only where the page has one", async () => {
    const [tax, other] = [srv.db.document("doc_payslip")!, srv.db.document("doc_library")!];
    renderWithProviders(
      <LettersList
        groups={[{ key: "y2025", label: "Tax letters", docs: [tax, other] }]}
        parties={new Map()}
        open={new Map()}
        note={(d) => (d.id === tax.id ? <span>Wage tax certificate attached</span> : null)}
      />,
    );
    const row = rowOf(await screen.findByRole("link", { name: tax.title! }));
    // one line under everything else in the row, in both the stacked and the table layout
    const line = within(row).getByText("Wage tax certificate attached").closest("[data-letter-note]")!;
    expect(line).not.toBeNull();
    expect(line.parentElement!.lastElementChild).toBe(line);
    expect(within(row).getAllByText("Wage tax certificate attached")).toHaveLength(1);
    expect(rowOf(screen.getByRole("link", { name: other.title! })).querySelector("[data-letter-note]")).toBeNull();
  });
});
