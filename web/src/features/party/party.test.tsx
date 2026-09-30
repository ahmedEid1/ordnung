import { afterEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Document, Draft, MyNumbers } from "@/api/types";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { usePartyDrawer } from "@/lib/party-drawer";
import { item } from "@/mocks/data/helpers";
import { maskValue } from "@/features/numbers/mask";
import { PartyDrawer } from "./PartyDrawer";
import { byYear, letterTimeline, mailtoUrl, regionName, websiteUrl } from "./timeline";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("party helpers", () => {
  it("merges their letters and yours, newest first, grouped by year", () => {
    const docs = [
      { id: "doc_a", title: "Lease", filename: "a.pdf", doc_date: "2025-09-15", received_date: null, created_at: "2025-09-16T10:00:00Z", direction: "incoming", kind: "rent_lease" },
      { id: "doc_b", title: null, filename: "b.pdf", doc_date: null, received_date: "2026-09-09", created_at: "2026-09-10T10:00:00Z", direction: "incoming", kind: "utility_bill" },
    ] as Document[];
    const drafts = [{ id: "drf_a", kind: "general_reply", subject: "Belegeinsicht", sent_at: "2026-09-15T17:00:00Z", created_at: "2026-09-15T16:50:00Z", status: "sent" }] as Draft[];
    const t = letterTimeline(docs, drafts);
    expect(t.map((e) => [e.id, e.direction, e.date])).toEqual([
      ["drf_a", "out", "2026-09-15"],
      ["doc_b", "in", "2026-09-09"],
      ["doc_a", "in", "2025-09-15"],
    ]);
    expect(t[0]).toMatchObject({ title: "Your reply", subtitle: "Belegeinsicht", href: "/letters/drf_a" });
    expect(t[1]).toMatchObject({ title: "b.pdf", href: "/documents/doc_b" });
    expect(byYear(t).map((g) => [g.year, g.entries.length])).toEqual([
      ["2026", 2],
      ["2025", 1],
    ]);
  });

  it("region names and safe website links", () => {
    expect(regionName("NW")).toBe("North Rhine-Westphalia");
    expect(regionName("BE")).toBe("Berlin");
    expect(regionName(null)).toBeNull();
    expect(websiteUrl("funknetz.example")).toBe("https://funknetz.example");
    expect(websiteUrl("http://a.example/x")).toBe("https://a.example/x");
    expect(websiteUrl("javascript:alert(1)")).toBeNull();
  });

  it("mailto links only for plain e-mail addresses (they come from letters)", () => {
    expect(mailtoUrl("service@funknetz.example")).toBe("mailto:service@funknetz.example");
    expect(mailtoUrl(" kundenservice@stadtwerke-musterstadt.de ")).toBe("mailto:kundenservice@stadtwerke-musterstadt.de");
    expect(mailtoUrl("a@b.example?cc=evil@x.example&body=Pay%20now")).toBeNull();
    expect(mailtoUrl("javascript:alert(1)//@x.example")).toBeNull();
    expect(mailtoUrl(null)).toBeNull();
  });
});

describe("People & organisations drawer", () => {
  it("opens from ?party= with numbers to copy, contact, to-dos, contracts, letters and threads", async () => {
    useMockApi();
    const user = userEvent.setup();
    const writeText = vi.fn(async () => {});
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    const { router } = renderWithProviders(<PartyDrawer />, { route: "/?party=pty_wohnbau" });
    const drawer = await screen.findByRole("dialog", { name: "Wohnbau Musterstadt eG" });
    expect(await within(drawer).findByText("Landlord")).toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "Deadlines: North Rhine-Westphalia holidays" })).toBeInTheDocument();
    // your numbers (as My numbers has them) & IBANs with copy buttons
    await user.click(await within(drawer).findByRole("button", { name: "Copy Customer number" }));
    expect(writeText).toHaveBeenCalledWith("12-0412-07");
    expect(within(drawer).getByText("DE05 1234 5600 0004 4556 60")).toBeInTheDocument();
    // sections
    for (const name of ["Contact", /To-dos & dates/, /Contracts/, /Letters/, /Threads/]) {
      expect(within(drawer).getByRole("region", { name })).toBeInTheDocument();
    }
    const letters = within(drawer).getByRole("region", { name: /Letters/ });
    expect(within(letters).getByText("Utility cost statement 2025")).toBeInTheDocument();
    expect(within(letters).getAllByText("From them").length).toBeGreaterThan(0);
    // actions
    expect(within(drawer).getByRole("link", { name: /Write to them/ })).toHaveAttribute("href", "/letters?kind=general_reply&to=pty_wohnbau");
    assertNoRawEnumsInElement(drawer);
    // closing removes the URL state
    await user.click(within(drawer).getByRole("button", { name: "Close" }));
    expect(router.state.location.search).toBe("");
  });

  it("shows a calm not-found state with a neutral title and a way out", async () => {
    useMockApi();
    const { router } = renderWithProviders(<PartyDrawer />, { route: "/?party=pty_nope" });
    const drawer = await screen.findByRole("dialog", { name: "Contact" });
    expect(await within(drawer).findByRole("heading", { name: "We couldn't find this contact" })).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: /try again/i })).toBeNull();
    const closeButtons = within(drawer).getAllByRole("button", { name: "Close" });
    expect(closeButtons).toHaveLength(2); // the header's X and the one under the message
    await userEvent.setup().click(closeButtons[1]!);
    expect(router.state.location.search).toBe("");
  });

  it("tells a failed load apart from a missing contact, and offers to try again", async () => {
    const { srv } = useMockApi();
    const handle = srv.handle.bind(srv);
    let fail = true;
    srv.handle = (method, path, ...rest) =>
      fail && path.startsWith("/parties/") ? Promise.resolve(new Response(JSON.stringify({ detail: "boom" }), { status: 500 })) : handle(method, path, ...rest);
    renderWithProviders(<PartyDrawer />, { route: "/?party=pty_wohnbau" });
    const drawer = await screen.findByRole("dialog", { name: "Contact" });
    expect(await within(drawer).findByRole("heading", { name: "Couldn't load this contact" })).toBeInTheDocument();
    expect(within(drawer).queryByText("We couldn't find this contact")).toBeNull();
    fail = false;
    await userEvent.setup().click(within(drawer).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("dialog", { name: "Wohnbau Musterstadt eG" })).toBeInTheDocument();
  });

  it("keeps the bank accounts a valid list, announces a copy and shows it on the button", async () => {
    useMockApi();
    const user = userEvent.setup();
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: vi.fn(async () => {}) } });
    renderWithProviders(<PartyDrawer />, { route: "/?party=pty_wohnbau" });
    const drawer = await screen.findByRole("dialog", { name: "Wohnbau Musterstadt eG" });
    const accounts = within(drawer).getByRole("region", { name: "Bank account they use" });
    const dl = accounts.querySelector("dl")!;
    for (const group of Array.from(dl.children)) {
      expect(Array.from(group.children).map((c) => c.tagName)).toEqual(["DT", "DD"]);
    }
    const button = within(accounts).getByRole("button", { name: "Copy IBAN" });
    expect(button.closest("dd")).not.toBeNull();
    await user.click(button);
    expect(await within(drawer).findByRole("status")).toHaveTextContent("IBAN copied");
    expect(within(button).getByText("Copied")).toBeInTheDocument();
  });

  it("shows your numbers with them as My numbers does: named in English with the letter's label, hidden until Show, whose they are", async () => {
    const { srv } = useMockApi();
    // an organisation with a number of its own besides yours, as FunkNetz's Gläubiger-ID (their creditor ID)
    const handle = srv.handle.bind(srv);
    srv.handle = async (method, path, ...rest) => {
      const res = await handle(method, path, ...rest);
      if (method !== "GET" || path !== "/numbers") return res;
      const data = (await res.json()) as MyNumbers;
      const organisations = data.organisations.map((s) =>
        s.party_id === "pty_wohnbau"
          ? {
              ...s,
              their_numbers: [
                ...s.their_numbers,
                { ...s.numbers[0]!, key: "num_ci", kind: "creditor_id" as const, group: "theirs" as const, name: "Creditor ID (Gläubiger-ID)", label: "Gläubiger-ID", value: "DE53ZZZ00000204170", display: "DE53ZZZ00000204170", copy_value: "DE53ZZZ00000204170" },
              ],
            }
          : s,
      );
      return Response.json({ ...data, organisations });
    };
    const user = userEvent.setup();
    renderWithProviders(<PartyDrawer />, { route: "/?party=pty_wohnbau" });
    const drawer = await screen.findByRole("dialog", { name: "Wohnbau Musterstadt eG" });
    const numbers = within(drawer).getByRole("region", { name: "Your numbers with them" });
    // the plain-English name, the letter's own label under it, the value hidden until Show
    expect(await within(numbers).findByText("Customer number")).toBeInTheDocument();
    expect(within(numbers).getByText("Mieternummer")).toHaveAttribute("lang", "de");
    expect(within(numbers).queryByText("12-0412-07")).toBeNull();
    expect(within(numbers).getByText(maskValue("12-0412-07"))).toBeInTheDocument();
    await user.click(within(numbers).getByRole("button", { name: "Show Customer number" }));
    expect(within(numbers).getByText("12-0412-07")).toBeInTheDocument();
    // their own numbers are set apart (not "yours"), folded away; the IBAN has its own section
    const theirs = within(numbers).getByText(/Their own numbers \(1\)/).closest("details")!;
    expect(theirs.open).toBe(false);
    expect(within(theirs).getByText("Creditor ID (Gläubiger-ID)")).toBeInTheDocument();
    expect(within(theirs).queryByText(/IBAN/)).toBeNull();
    expect(within(drawer).getByRole("region", { name: "Bank account they use" })).toBeInTheDocument();
  });

  it("lists an open case's references with the numbers, and falls back to the letters' numbers — in English — for a party My numbers doesn't have", async () => {
    useMockApi();
    const first = renderWithProviders(<PartyDrawer />, { route: "/?party=pty_abh" });
    let drawer = await screen.findByRole("dialog", { name: "Ausländerbehörde Musterstadt" });
    const numbers = within(drawer).getByRole("region", { name: "Your numbers with them" });
    expect(await within(numbers).findByText(/Open case:/)).toHaveTextContent("Open case: Residence permit extension");
    expect(within(numbers).getByText("ABH-2026-18841")).toBeInTheDocument(); // a case's reference is shown, not hidden
    first.unmount();

    renderWithProviders(<PartyDrawer />, { route: "/?party=pty_verkehr" });
    drawer = await screen.findByRole("dialog", { name: /./ });
    const letters = await within(drawer).findByRole("region", { name: "Numbers on their letters" });
    expect(within(drawer).queryByRole("region", { name: "Your numbers with them" })).toBeNull();
    expect(within(letters).getByText("Customer number")).toBeInTheDocument();
    expect(within(letters).getByText("Kundennummer")).toHaveAttribute("lang", "de");
    expect(within(letters).getByRole("button", { name: "Copy Customer number" })).toBeInTheDocument();
  });

  it("keeps references whole in its letters, and uses the app's label style", async () => {
    const { srv } = useMockApi();
    const doc = srv.db.state.documents.find((d) => d.party_id === "pty_techmarkt")!;
    doc.title = "1st Payment Reminder (Mahnung) – Invoice TM-2026-0048213";
    renderWithProviders(<PartyDrawer />, { route: "/?party=pty_techmarkt" });
    const drawer = await screen.findByRole("dialog", { name: /TechMarkt/ });
    const letters = within(drawer).getByRole("region", { name: /Letters/ });
    const title = within(letters).getByText(/1st Payment Reminder/);
    expect(title).toHaveTextContent("Invoice TM‑2026‑0048213");
    expect(title).toHaveAttribute("title", "1st Payment Reminder (Mahnung) – Invoice TM-2026-0048213");
    for (const heading of within(drawer).getAllByRole("heading", { level: 3 })) expect(heading).toHaveClass("eyebrow");
  });

  it("sets apart replaced and past to-dos, and shows money coming in and repeating payments for what they are", async () => {
    const { srv } = useMockApi();
    const items = srv.db.state.items;
    // the invoice the payment reminder took over is still open, next to the reminder's own payment
    Object.assign(items.find((i) => i.id === "itm_tm_invoice")!, { status: "open", description: null, title: "Pay TechMarkt invoice TM-2026-0048213" });
    items.push(
      item({ id: "itm_tm_old", kind: "payment", title: "Security deposit (Kaution)", amount: 1560, due_date: "2025-10-01", filed_on: "2026-09-26", party_id: "pty_techmarkt" }),
      item({ id: "itm_tm_cashback", kind: "payment", direction: "in", title: "Monthly cashback", amount: 4.5, recurrence: { interval: 1, unit: "months", working_day: null }, party_id: "pty_techmarkt" }),
    );
    const user = userEvent.setup();
    renderWithProviders(<PartyDrawer />, { route: "/?party=pty_techmarkt" });
    const drawer = await screen.findByRole("dialog", { name: /TechMarkt/ });
    const todos = within(drawer).getByRole("region", { name: /To-dos & dates/ });
    const list = within(todos).getAllByRole("list")[0]!;
    // only what is to be done is listed as due, with its countdown
    expect(within(list).getByText("Pay TechMarkt reminder")).toBeInTheDocument();
    expect(within(list).queryByText(/TM.2026.0048213/)).toBeNull(); // (on screen with non-breaking hyphens)
    expect(within(list).queryByText(/Security deposit/)).toBeNull();
    expect(list).not.toHaveTextContent(/overdue/);
    // money in: a plus, "to you", and its schedule instead of "No date"
    const cashback = within(list).getByText("Monthly cashback").closest("li")!;
    expect(cashback).toHaveTextContent("Every month");
    expect(cashback).toHaveTextContent("+€4.50 to you");
    expect(cashback).not.toHaveTextContent("No date");
    // the rest sits in a closed disclosure, with the reason
    const summary = within(todos).getByText(/Older or replaced · 2/);
    const details = summary.closest("details")!;
    expect(details.open).toBe(false);
    await user.click(summary);
    expect(details.open).toBe(true);
    expect(details).toHaveTextContent("Replaced by the payment reminder of");
    expect(details).toHaveTextContent("pay that one, not both");
    expect(details).toHaveTextContent("Already in the past when the letter was added");
    expect(details).not.toHaveTextContent(/overdue/);
  });

  it("jump links move to their section; the holidays note is a real button, hidden for parties abroad", async () => {
    const { srv } = useMockApi();
    const user = userEvent.setup();
    Object.assign(srv.db.state.parties.find((p) => p.id === "pty_scholarship")!, { address: "Republic of Examplia", region: null });
    const first = renderWithProviders(<PartyDrawer />, { route: "/?party=pty_wohnbau" });
    const drawer = await screen.findByRole("dialog", { name: "Wohnbau Musterstadt eG" });
    const nav = within(drawer).getByRole("navigation", { name: "Sections" });
    await user.click(within(nav).getByRole("button", { name: /letters?$/ }));
    expect(document.activeElement).toBe(within(drawer).getByRole("heading", { name: /^Letters/ }));
    first.unmount();

    renderWithProviders(<PartyDrawer />, { route: "/?party=pty_scholarship" });
    const abroad = await screen.findByRole("dialog", { name: /Scholarship/ });
    expect(within(abroad).queryByRole("button", { name: /Deadlines:/ })).toBeNull();
  });

  it("lists the calls after the to-dos and contracts, with a jump link of their own", async () => {
    const { srv } = useMockApi();
    srv.db.state.items.push(item({ id: "itm_fw_todo", kind: "task", title: "Check the cancellation", due_date: "2026-10-05", party_id: "pty_fitwell" }));
    const user = userEvent.setup();
    renderWithProviders(<PartyDrawer />, { route: "/?party=pty_fitwell" });
    const drawer = await screen.findByRole("dialog", { name: "FitWell Studios" });
    const nav = within(drawer).getByRole("navigation", { name: "Sections" });
    const jump = await within(nav).findByRole("button", { name: "1 call" });
    const labels = within(nav)
      .getAllByRole("button")
      .map((b) => b.textContent);
    expect(labels.indexOf("1 call")).toBeGreaterThan(labels.findIndex((l) => /to-dos?$/.test(l ?? "")));
    const calls = within(drawer).getByRole("region", { name: /^Calls/ });
    const todos = within(drawer).getByRole("region", { name: /To-dos & dates/ });
    expect(todos.compareDocumentPosition(calls) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const contracts = within(drawer).queryByRole("region", { name: /Contracts/ });
    if (contracts) expect(contracts.compareDocumentPosition(calls) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await user.click(jump);
    expect(document.activeElement).toBe(within(calls).getByRole("heading", { name: /^Calls/ }));
    expect(document.activeElement).toHaveAttribute("id", "pty-calls");
  });
});

describe("drawer history", () => {
  function Opener() {
    const { open, partyId } = usePartyDrawer();
    return (
      <>
        <button type="button" onClick={() => open("pty_wohnbau")}>
          open
        </button>
        {partyId ? <PartyDrawer /> : null}
      </>
    );
  }

  it("closing a drawer opened in the app goes back, so the next Back leaves the page", async () => {
    useMockApi();
    const user = userEvent.setup();
    const { router } = renderWithProviders(<Opener />, { route: "/inbox" });
    await act(() => router.navigate("/today"));
    await user.click(screen.getByRole("button", { name: "open" }));
    const drawer = await screen.findByRole("dialog", { name: "Wohnbau Musterstadt eG" });
    expect(router.state.location.search).toBe("?party=pty_wohnbau");
    await user.click(within(drawer).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(router.state.location.search).toBe(""));
    expect(router.state.historyAction).toBe("POP");
    expect(router.state.location.pathname).toBe("/today");
    // one more Back leaves /today (no second copy of it in the history)
    await act(() => router.navigate(-1));
    expect(router.state.location.pathname).toBe("/inbox");
  });
});
