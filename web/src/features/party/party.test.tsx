import { afterEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Document, Draft, MyNumbers, PartyDetail } from "@/api/types";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { usePartyDrawer } from "@/lib/party-drawer";
import { item } from "@/mocks/data/helpers";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { maskValue } from "@/features/numbers/mask";
import { BUNDESLAENDER } from "@/features/onboarding/options";
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
    // reading letters never tells Ordnung a sender's state: only the person does (the State section)
    expect(within(drawer).getByRole("button", { name: "Deadlines: nationwide holidays" })).toBeInTheDocument();
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
      item({ id: "itm_tm_cashback", kind: "payment", direction: "in", title: "Monthly cashback", amount: 4.5, recurrence: { interval: 1, unit: "months", working_day: 2, day_of_month: null }, party_id: "pty_techmarkt" }),
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
    // money in: a plus, "to you", and its schedule — with the working day it names — instead of "No date"
    const cashback = within(list).getByText("Monthly cashback").closest("li")!;
    expect(cashback).toHaveTextContent("Every month on the 2nd working day");
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
    expect(within(abroad).queryByRole("combobox", { name: "Which state is this sender in?" })).toBeNull();
  });

  it("asks which state a sender is in — the 16 Länder and Don't know — and saves the answer on change", async () => {
    const { srv } = useMockApi();
    const user = userEvent.setup();
    const region = () => srv.db.state.parties.find((p) => p.id === "pty_wohnbau")!.region;
    renderWithProviders(
      <>
        <PartyDrawer />
        <Toaster />
      </>,
      { route: "/?party=pty_wohnbau" },
    );
    const drawer = await screen.findByRole("dialog", { name: "Wohnbau Musterstadt eG" });
    const picker = within(drawer).getByRole("combobox", { name: "Which state is this sender in?" });
    expect(picker).toHaveValue("");
    expect(picker).toHaveAccessibleDescription(/Until you choose, Ordnung uses nationwide holidays and the 3-day delivery rule/);
    expect(within(picker).getAllByRole("option").map((o) => o.textContent)).toEqual(["Don't know", ...BUNDESLAENDER.map((b) => b.name)]);
    expect(BUNDESLAENDER).toHaveLength(16);

    await user.selectOptions(picker, "SN");
    await waitFor(() => expect(region()).toBe("SN"));
    expect(picker).toHaveValue("SN");
    expect(await within(drawer).findByRole("button", { name: "Deadlines: Saxony holidays" })).toBeInTheDocument();
    expect(await screen.findByText("Saved: Wohnbau Musterstadt eG is in Saxony")).toBeInTheDocument();
    expect(screen.getByText("Their dates now skip the public holidays of Saxony.")).toBeInTheDocument();

    await user.selectOptions(picker, "");
    await waitFor(() => expect(region()).toBeNull());
    expect(picker).toHaveValue("");
    expect(await within(drawer).findByRole("button", { name: "Deadlines: nationwide holidays" })).toBeInTheDocument();
    __clearToasts();
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

describe("a sender's state, suggested from the postcode on their letter (ADR 0019)", () => {
  /** The question the mock asks about FunkNetz, as the real demo does: their letter shows a Berlin postcode. */
  const FUNKNETZ = "Is FunkNetz Mobil GmbH in Berlin? (12351 on their letter)";

  /** FunkNetz's drawer (or `id`'s) with the toasts, on the mock API. */
  async function openDrawer(route = "/?party=pty_funknetz", name = "FunkNetz Mobil GmbH") {
    const user = userEvent.setup();
    const view = renderWithProviders(
      <>
        <PartyDrawer />
        <Toaster />
      </>,
      { route },
    );
    const drawer = await screen.findByRole("dialog", { name });
    await within(drawer).findByRole("heading", { name: "State" });
    return { user, drawer, picker: within(drawer).getByRole("combobox", { name: "Which state is this sender in?" }), ...view };
  }

  afterEach(() => act(() => __clearToasts()));

  it("asks above the State picker, with the postcode it comes from; the picker stays unchosen and Yes is never focused by itself", async () => {
    const { srv } = useMockApi();
    const { drawer, picker } = await openDrawer();
    const question = within(drawer).getByRole("group", { name: FUNKNETZ });
    // none of their dates waits for it (as in the demo): only what it decides
    expect(question).toHaveTextContent("Their state's public holidays can move the dates in their letters.");
    // without their Idea there is nothing to dismiss: Yes and Other state… only
    expect(within(question).getAllByRole("button").map((b) => b.textContent)).toEqual(["Yes", "Other state…"]);
    expect(question.compareDocumentPosition(picker) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(picker).toHaveValue("");
    await waitFor(() => expect(drawer.contains(document.activeElement)).toBe(true));
    expect(within(question).getByRole("button", { name: "Yes" })).not.toHaveFocus();
    // asking set nothing
    expect(srv.db.state.parties.find((p) => p.id === "pty_funknetz")!.region).toBeNull();
  });

  it("says how many of your dates may change, and when one may be late until you answer", async () => {
    const { srv } = useMockApi();
    const answer = globalThis.fetch;
    let suggestion = { waiting: 2, may_be_late: false };
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const response = await answer(input, init);
      if (!String(input).endsWith("/api/parties/pty_funknetz")) return response;
      const detail = (await response.json()) as PartyDetail;
      const body = { ...detail, region_suggestion: detail.region_suggestion && { ...detail.region_suggestion, ...suggestion } };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    expect(srv.db.state.parties.find((p) => p.id === "pty_funknetz")!.region).toBeNull();
    const first = await openDrawer();
    expect(within(first.drawer).getByRole("group", { name: FUNKNETZ })).toHaveTextContent(
      "This may change 2 of your dates with them. Until you answer, Ordnung counts only nationwide holidays, so they may be a day or two early.",
    );
    first.unmount();
    suggestion = { waiting: 1, may_be_late: true };
    const second = await openDrawer();
    expect(within(second.drawer).getByRole("group", { name: FUNKNETZ })).toHaveTextContent(
      "This may change 1 of your dates with them. Until you answer, act a working day before it: a holiday in their state could make it earlier.",
    );
  });

  it("is not asked once their state is set, without a suggestion, or for a sender abroad", async () => {
    const { srv } = useMockApi();
    Object.assign(srv.db.state.parties.find((p) => p.id === "pty_funknetz")!, { region: "BE" });
    const set = await openDrawer();
    expect(within(set.drawer).queryByRole("group", { name: /^Is FunkNetz/ })).toBeNull();
    expect(set.picker).toHaveValue("BE");
    set.unmount();
    // the postcode on Wohnbau's letters suggests nothing (as in the demo: it is the person's own town)
    const none = await openDrawer("/?party=pty_wohnbau", "Wohnbau Musterstadt eG");
    expect(within(none.drawer).queryByRole("group", { name: /^Is Wohnbau/ })).toBeNull();
  });

  it("keeps the State section for a sender whose stored address has no postcode when a later letter of theirs suggests one", async () => {
    const { srv } = useMockApi();
    // the stored address is the first letter's: without a postcode the sender looked abroad
    Object.assign(srv.db.state.parties.find((p) => p.id === "pty_funknetz")!, { address: "Wellenweg 7, Beispielhausen" });
    const { drawer } = await openDrawer();
    expect(within(drawer).getByRole("group", { name: FUNKNETZ })).toBeInTheDocument();
  });

  it("Yes saves their state, says so with an Undo that takes it back, and gives the keyboard to the State heading", async () => {
    const { srv, calls } = useMockApi();
    const region = () => srv.db.state.parties.find((p) => p.id === "pty_funknetz")!.region;
    const { user, drawer, picker } = await openDrawer();
    await user.click(within(within(drawer).getByRole("group", { name: FUNKNETZ })).getByRole("button", { name: "Yes" }));
    await waitFor(() => expect(region()).toBe("BE"));
    expect(calls.filter((c) => c.method !== "GET")).toEqual([{ method: "PATCH", path: "/parties/pty_funknetz", body: { region: "BE" } }]);
    expect(await screen.findByText("Saved: FunkNetz Mobil GmbH is in Berlin")).toBeInTheDocument();
    expect(screen.getByText("Their dates now skip the public holidays of Berlin.")).toBeInTheDocument();
    await waitFor(() => expect(within(drawer).queryByRole("group", { name: FUNKNETZ })).toBeNull());
    expect(picker).toHaveValue("BE");
    // not the picker: it saves on change, so a stray arrow key there would save a state nobody chose
    await waitFor(() => expect(within(drawer).getByRole("heading", { name: "State" })).toHaveFocus());

    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(region()).toBeNull());
    expect(calls.filter((c) => c.method !== "GET").at(-1)).toEqual({ method: "PATCH", path: "/parties/pty_funknetz", body: { region: null } });
    // not known again: asked again
    expect(await within(drawer).findByRole("group", { name: FUNKNETZ })).toBeInTheDocument();
    expect(picker).toHaveValue("");
  });

  it("“Other state…” leaves the question for this visit and focuses the State picker; nothing is saved", async () => {
    const { calls } = useMockApi();
    const { user, drawer, picker } = await openDrawer();
    await user.click(within(within(drawer).getByRole("group", { name: FUNKNETZ })).getByRole("button", { name: "Other state…" }));
    expect(picker).toHaveFocus();
    expect(picker).toHaveValue("");
    expect(within(drawer).queryByRole("group", { name: FUNKNETZ })).toBeNull();
    expect(calls.filter((c) => c.method !== "GET")).toEqual([]);
  });

  it("offers “Don't know” while their Idea stands: it dismisses the Idea, keeps the question and has an Undo", async () => {
    const { srv, calls } = useMockApi();
    srv.db.state.suggestions.push({
      ...srv.db.state.suggestions[0]!,
      id: "sug_land_funknetz",
      kind: "deadline",
      title: "Is FunkNetz Mobil GmbH in Berlin?",
      status: "new",
      rule_id: "sender_land",
      refs: [{ type: "party", id: "pty_funknetz" }],
      action: { type: "open", draft_kind: null, target_type: "party", target_id: "pty_funknetz", label: "Answer" },
    });
    const idea = () => srv.db.state.suggestions.find((s) => s.id === "sug_land_funknetz")!;
    const { user, drawer } = await openDrawer();
    const question = within(drawer).getByRole("group", { name: FUNKNETZ });
    expect(within(question).getAllByRole("button").map((b) => b.textContent)).toEqual(["Yes", "Other state…", "Don't know"]);
    await user.click(within(question).getByRole("button", { name: "Don't know" }));
    await waitFor(() => expect(idea().status).toBe("dismissed"));
    expect(calls.filter((c) => c.method !== "GET")).toEqual([{ method: "PATCH", path: "/suggestions/sug_land_funknetz", body: { status: "dismissed" } }]);
    expect(await screen.findByText("Okay — nationwide holidays for FunkNetz Mobil GmbH")).toBeInTheDocument();
    expect(screen.getByText("Their dates stay the earlier ones. You can choose their state any time in their details.")).toBeInTheDocument();
    // the drawer keeps asking, without "Don't know"; nothing was set; the keyboard is on the State heading, not on Yes
    await waitFor(() => expect(within(question).queryByRole("button", { name: "Don't know" })).toBeNull());
    expect(within(drawer).getByRole("group", { name: FUNKNETZ })).toBeInTheDocument();
    expect(srv.db.state.parties.find((p) => p.id === "pty_funknetz")!.region).toBeNull();
    await waitFor(() => expect(within(drawer).getByRole("heading", { name: "State" })).toHaveFocus());

    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(idea().status).toBe("new"));
    expect(await within(question).findByRole("button", { name: "Don't know" })).toBeInTheDocument();
  });

  it("“Don't know” never calls a date that may be late the earlier one: it says to act a working day before it", async () => {
    const { srv } = useMockApi();
    srv.db.state.suggestions.push({
      ...srv.db.state.suggestions[0]!,
      id: "sug_land_funknetz",
      kind: "deadline",
      title: "Is FunkNetz Mobil GmbH in Berlin?",
      status: "new",
      rule_id: "sender_land",
      refs: [{ type: "party", id: "pty_funknetz" }],
      action: { type: "open", draft_kind: null, target_type: "party", target_id: "pty_funknetz", label: "Answer" },
    });
    const answer = globalThis.fetch;
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const response = await answer(input, init);
      if ((init?.method ?? "GET") !== "GET" || !String(input).endsWith("/api/parties/pty_funknetz")) return response;
      const detail = (await response.json()) as PartyDetail;
      const late = detail.region_suggestion && { ...detail.region_suggestion, waiting: 1, may_be_late: true, idea_id: "sug_land_funknetz" };
      return new Response(JSON.stringify({ ...detail, region_suggestion: late }), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    const { user, drawer } = await openDrawer();
    await user.click(within(within(drawer).getByRole("group", { name: FUNKNETZ })).getByRole("button", { name: "Don't know" }));
    expect(await screen.findByText("Okay — nationwide holidays for FunkNetz Mobil GmbH")).toBeInTheDocument();
    expect(
      screen.getByText("A holiday in their state could make a date earlier: act a working day before it. You can choose their state any time in their details."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/stay the earlier ones/)).toBeNull();
  });

  it("another sender's drawer is another visit: asked again after “Other state…”, in one State section", async () => {
    useMockApi();
    const { user, drawer, router } = await openDrawer();
    await user.click(within(within(drawer).getByRole("group", { name: FUNKNETZ })).getByRole("button", { name: "Other state…" }));
    await act(() => router.navigate("/?party=pty_techmarkt"));
    const other = await screen.findByRole("dialog", { name: "TechMarkt Online GmbH" });
    expect(await within(other).findByRole("group", { name: "Is TechMarkt Online GmbH in Berlin? (12353 on their letter)" })).toBeInTheDocument();
    expect(within(other).getAllByRole("heading", { name: "State" })).toHaveLength(1);
  });

  it("opened to answer (`state=ask`) focuses the State heading, never Yes; to choose (`state=choose`) the picker", async () => {
    useMockApi();
    const ask = await openDrawer("/?party=pty_funknetz&state=ask");
    await waitFor(() => expect(within(ask.drawer).getByRole("heading", { name: "State" })).toHaveFocus());
    expect(within(ask.drawer).getByRole("group", { name: FUNKNETZ })).toBeInTheDocument();
    // read once: a reload doesn't do it again
    await waitFor(() => expect(ask.router.state.location.search).toBe("?party=pty_funknetz"));
    ask.unmount();

    const choose = await openDrawer("/?party=pty_funknetz&state=choose");
    await waitFor(() => expect(choose.picker).toHaveFocus());
    expect(within(choose.drawer).queryByRole("group", { name: FUNKNETZ })).toBeNull(); // they said "Other state…"
    await waitFor(() => expect(choose.router.state.location.search).toBe("?party=pty_funknetz"));
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

  it("opens at their state with `state` (to answer or to choose), and another opening drops it", async () => {
    function StateOpener() {
      const { open } = usePartyDrawer();
      return (
        <>
          <button type="button" onClick={() => open("pty_funknetz", { state: "choose" })}>
            choose
          </button>
          <button type="button" onClick={() => open("pty_funknetz", { state: "ask" })}>
            ask
          </button>
          <button type="button" onClick={() => open("pty_wohnbau")}>
            plain
          </button>
        </>
      );
    }
    const user = userEvent.setup();
    const { router } = renderWithProviders(<StateOpener />, { route: "/documents/doc_phone" });
    await user.click(screen.getByRole("button", { name: "choose" }));
    expect(router.state.location.search).toBe("?party=pty_funknetz&state=choose");
    await user.click(screen.getByRole("button", { name: "ask" }));
    expect(router.state.location.search).toBe("?party=pty_funknetz&state=ask");
    await user.click(screen.getByRole("button", { name: "plain" }));
    expect(router.state.location.search).toBe("?party=pty_wohnbau");
  });
});
