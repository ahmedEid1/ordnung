import { afterEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { qk } from "@/api/hooks";
import type { Contract, Party } from "@/api/types";
import { AddLettersProvider } from "@/components/shell/AddLetters";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { createMockServer } from "@/mocks/server";
import { useMockApi } from "@/test/mockFetch";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { ContractsView } from "./ContractsView";
import { NoticePeriodForm, noticeBases, noticeValueError } from "./NoticePeriodForm";

async function seededClient(mutate?: (c: Contract[]) => Contract[]) {
  const srv = createMockServer({ staticDemo: false, latency: 0 });
  const get = async <T,>(path: string) => (await (await srv.handle("GET", path, new URLSearchParams(), undefined)).json()) as T;
  const qc = makeTestQueryClient();
  const contracts = await get<Contract[]>("/contracts");
  qc.setQueryData(qk.contracts.list({}), mutate ? mutate(contracts) : contracts);
  qc.setQueryData(qk.parties.list(), await get<Party[]>("/parties"));
  qc.setQueryData(qk.rules, []);
  return qc;
}

describe("Contracts page", () => {
  it("shows fixed costs, the decision to make, lanes and a card per contract — in plain words", async () => {
    const client = await seededClient();
    const { container } = renderWithProviders(<ContractsView />, { client, route: "/contracts" });

    expect(screen.getByRole("heading", { level: 1, name: "Contracts" })).toBeInTheDocument();
    // "/month" once (not in the label too); the year in whole euros says it is rounded
    expect(screen.getByText("Fixed costs").nextElementSibling).toHaveTextContent("€987/month");
    expect(screen.getByText("Per year").nextElementSibling).toHaveTextContent("≈ €11,844");

    const decide = screen.getByRole("region", { name: /Decide by/ });
    const callouts = within(decide).getAllByRole("listitem");
    expect(callouts).toHaveLength(1);
    expect(within(callouts[0]!).getByRole("heading", { name: /FunkNetz Allnet L/ })).toBeInTheDocument();
    // the countdown's parts are separate spans (so it can wrap between them); one word for the
    // date across the page: "Send by", like the chart and its legend
    expect(within(callouts[0]!).getByText((_, el) => el?.tagName === "TIME" && /^Send by Thu 8 Oct/.test(el.textContent ?? ""))).toBeInTheDocument();
    // only the German word is marked German; the translation beside it is English
    const term = within(callouts[0]!).getByText("Kündigung");
    expect(term).toHaveAttribute("lang", "de");
    expect(term.parentElement).toHaveTextContent(/^Kündigung \(cancellation \/ notice\)$/);
    expect(within(callouts[0]!).getByRole("link", { name: /Draft cancellation/ })).toHaveAttribute(
      "href",
      "/letters?kind=cancellation&contract=ctr_phone",
    );

    const chart = screen.getByRole("group", { name: "Contract terms and notice windows" });
    expect(within(within(chart).getByRole("list", { name: "Lanes" })).getAllByRole("listitem")).toHaveLength(10);
    expect(within(chart).getByRole("button", { name: /Send by · Thu 8 Oct/ })).toBeInTheDocument();

    const cards = screen.getAllByRole("article");
    expect(cards).toHaveLength(10);
    expect(within(cards[0]!).getByRole("heading", { name: "FunkNetz Allnet L" })).toBeInTheDocument();
    expect(within(cards[0]!).getByText(/after that cancellable any time with 1 month's notice/)).toBeInTheDocument();
    expect(within(cards[0]!).getByText("Send by")).toBeInTheDocument();
    const gym = cards.find((c) => within(c).queryByRole("heading", { name: "FitWell Flex" }))!;
    expect(within(gym).getByText(/Cancellable any time with 1 month's notice \(consumer contract since March 2022\)/)).toBeInTheDocument();
    const job = cards.find((c) => within(c).queryByRole("heading", { name: /Werkstudent/ }))!;
    expect(within(job).getByRole("link", { name: /Draft resignation/ })).toBeInTheDocument();
    expect(within(job).getByRole("link", { name: /Open letter/ })).toHaveAttribute("href", "/documents/doc_job");

    assertNoRawEnumsInElement(container);
  });

  it("explains the dates in a popover with the rules and the disclaimer", async () => {
    const client = await seededClient();
    renderWithProviders(<ContractsView />, { client, route: "/contracts" });
    const card = screen.getAllByRole("article")[0]!;
    fireEvent.click(within(card).getByRole("button", { name: /Why these dates\?/ }));
    const pop = await screen.findByRole("dialog", { name: /Why these dates\? FunkNetz Allnet L/ });
    expect(within(pop).getByText(/Minimum term ends Sat 14 Nov 2026/)).toBeInTheDocument();
    expect(within(pop).getByText("Send by")).toBeInTheDocument();
    expect(within(pop).getByText(/Phone & internet contract/)).toBeInTheDocument();
    fireEvent.click(within(pop).getByRole("button", { name: "Show the rules" }));
    expect(within(pop).getByText("§ 56 Abs. 3 TKG")).toBeInTheDocument();
    expect(within(pop).getByText(/Not legal advice/)).toBeInTheDocument();
  });

  it("selects a contract from the URL and when its lane is clicked", async () => {
    const client = await seededClient();
    const { router } = renderWithProviders(<ContractsView />, { client, route: "/contracts?contract=ctr_gym" });
    const gym = document.getElementById("contract-ctr_gym")!;
    expect(gym.className).toMatch(/border-accent/);

    const chart = screen.getByRole("group", { name: "Contract terms and notice windows" });
    fireEvent.click(within(chart).getByRole("button", { name: /^Insurance year\./ }));
    expect(router.state.location.search).toContain("contract=ctr_liability");
    expect(document.getElementById("contract-ctr_liability")!.className).toMatch(/border-accent/);
  });

  it("filters by status", async () => {
    const client = await seededClient((list) => list.map((c) => (c.id === "ctr_gym" ? { ...c, status: "cancelled" as const } : c)));
    renderWithProviders(<ContractsView />, { client, route: "/contracts" });
    expect(screen.getAllByRole("article")).toHaveLength(9);
    expect(screen.getByText("Fixed costs").nextElementSibling).toHaveTextContent("€957.10/month");
    fireEvent.click(screen.getByRole("tab", { name: /Cancelled/ }));
    const cards = screen.getAllByRole("article");
    expect(cards).toHaveLength(1);
    expect(within(cards[0]!).getByText("Cancelled")).toBeInTheDocument();
    expect(within(cards[0]!).queryByRole("link", { name: /Draft cancellation/ })).not.toBeInTheDocument();
  });
});

/** UI audit round 1 (contracts): layout, states and wording. */
describe("Contracts page — fits every width, honest states", () => {
  afterEach(() => vi.unstubAllGlobals());

  const card = (name: string | RegExp) => screen.getAllByRole("article").find((a) => within(a).queryByRole("heading", { name }))!;

  it("cost summary: nothing cut off, four across only when the column has room, and says why the job isn't counted", async () => {
    const client = await seededClient();
    renderWithProviders(<ContractsView />, { client, route: "/contracts" });
    const summary = screen.getByText("Fixed costs").closest("dl")!;
    // columns by the content column's width (a container query), not the window's
    expect(summary.parentElement!.className).toContain("@container");
    expect(summary.className).toContain("@4xl:grid-cols-4");
    expect(summary.className).not.toMatch(/(^|\s)lg:/);
    // no ellipsis on a figure ("€982.3…", "Thu 8 …"): it scales with the column instead
    expect(summary.innerHTML).not.toContain("truncate");
    expect(summary.querySelector("[data-part=value]")!.className).toContain("clamp(");
    // the figures of a row line up even when a label wraps
    expect(summary.querySelector("dt")!.parentElement!.className).toContain("grid-rows-subgrid");
    expect(screen.getByText("Fixed costs").nextElementSibling).toHaveTextContent("from 9 contracts · your job isn't a cost");
    const next = screen.getByText("Next decision").nextElementSibling!;
    expect(next).toHaveTextContent("Thu 8 Oct");
    expect(next).toHaveTextContent("Send by then to leave FunkNetz Allnet L");
  });

  it("offers only the statuses that have contracts, on their own row; an empty status is one empty state with a way back", async () => {
    const client = await seededClient();
    const { router } = renderWithProviders(<ContractsView />, { client, route: "/contracts" });
    const tabs = screen.getByRole("tablist", { name: "Show contracts" });
    expect(within(tabs).getAllByRole("tab").map((t) => t.textContent)).toEqual(["Active10", "All10"]);
    // the whole row on a phone, not squeezed beside the section title
    expect(tabs.parentElement!.className).toContain("max-sm:w-full");
    expect(screen.getByRole("heading", { level: 2, name: /Your contracts/ }).closest("div")!.parentElement).not.toContainElement(tabs);

    // a link can still ask for a status without contracts: its tab shows, the page says so once
    act(() => void router.navigate("/contracts?status=ended"));
    expect(await screen.findByRole("tab", { name: /Ended/, selected: true })).toBeInTheDocument();
    const empty = screen.getByRole("heading", { level: 3, name: "No ended contracts" });
    expect(empty).toBeInTheDocument();
    expect(screen.getByText("Contracts you cancel, or that run out, show up here.")).toBeInTheDocument();
    // no empty chart with its legend and disclaimer
    expect(screen.queryByRole("group", { name: "Contract terms and notice windows" })).toBeNull();
    expect(screen.queryByText(/Try another filter/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show active contracts" }));
    expect(await screen.findByRole("group", { name: "Contract terms and notice windows" })).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(10);
  });

  it("while loading: no tabs and no zero counts", () => {
    vi.stubGlobal("fetch", () => new Promise<Response>(() => {}));
    renderWithProviders(<ContractsView />, { route: "/contracts" });
    expect(document.querySelector("[aria-busy=true]")).toBeTruthy();
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.queryByText("0")).toBeNull();
    expect(screen.getByRole("heading", { level: 2, name: "Your contracts" })).toHaveTextContent(/^Your contracts$/);
  });

  it("a load error replaces the page (no 'No contracts yet') and stays put while retrying", async () => {
    let calls = 0;
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      if (String(input).includes("/api/contracts") && ++calls > 1) return new Promise<Response>(() => {});
      return new Response(JSON.stringify({ detail: "Internal error" }), { status: 500, headers: { "Content-Type": "application/json" } });
    });
    renderWithProviders(<ContractsView />, { route: "/contracts" });
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByRole("heading", { level: 2, name: "Couldn't load your contracts" })).toBeInTheDocument();
    expect(screen.queryByText("No contracts yet")).toBeNull();
    expect(screen.queryByRole("tablist")).toBeNull();
    fireEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(within(alert).getByRole("button", { name: "Try again" })).toHaveAttribute("aria-busy", "true"));
    expect(screen.getByRole("alert")).toBe(alert);
  });

  it("on a first run asks for a contract letter (an h2 under the page's h1)", async () => {
    const client = await seededClient(() => []);
    renderWithProviders(
      <AddLettersProvider>
        <ContractsView />
      </AddLettersProvider>,
      { client, route: "/contracts" },
    );
    expect(screen.getByRole("heading", { level: 2, name: "No contracts yet" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add a contract letter" })).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.queryByText("Fixed costs")).toBeNull();
  });

  it("cards: rows wrap instead of squeezing the label, the key date stays ink, no date twice, one layout for any-month contracts", async () => {
    // the rent as the demo has it: the notice for 31 Dec must arrive by Mon 5 Oct — or it ends a month later
    const rentAsInDemo = (c: Contract): Contract => ({
      ...c,
      name: "Mietvertrag Wohnung 05-2-03, Beispielweg 5",
      computed: { ...c.computed!, cancel_by: "2026-10-05", send_by: "2026-09-29" },
    });
    const client = await seededClient((list) => list.map((c) => (c.id === "ctr_rent" ? rentAsInDemo(c) : c)));
    renderWithProviders(<ContractsView />, { client, route: "/contracts" });
    // the grid follows the content column; a card is never wider than a phone's
    expect(screen.getByRole("list", { name: "10 contracts" }).className).toContain("grid-cols-[repeat(auto-fill,minmax(min(100%,22rem),1fr))]");

    const liability = card(/Privathaftpflicht/);
    const sendRow = within(liability).getByText("Send by").parentElement!;
    expect(sendRow.className).toContain("flex-wrap");
    expect(sendRow.querySelector("dd")!.className).toContain("ml-auto");
    // eleven months out, but the date to act on: ink, not muted grey
    expect(within(sendRow).getByText((_, el) => el?.tagName === "TIME")).toHaveAttribute("data-urgency", "ink");

    const job = card(/Werkstudent/);
    expect(within(job).getByText(/^Fixed term until 31 Mar 2027 — it ends by itself/)).toBeInTheDocument();
    expect(within(job).getAllByText("Wed 31 Mar 2027")).toHaveLength(1);
    expect(within(job).queryByText("Earliest end if you cancel now")).toBeNull();

    // the flat number never breaks at its hyphens
    const rent = card(/Mietvertrag/);
    expect(within(rent).getByRole("heading", { level: 3 }).textContent).toContain("05‑2‑03");
    expect(within(rent).getByText("Earliest end if you cancel now")).toBeInTheDocument();
    expect(within(rent).getByText("Notice must arrive by")).toBeInTheDocument();
    expect(within(rent).getByTestId("rolling-note")).toHaveTextContent("You can cancel any month");
  });

  it("a contract picked in the chart takes the keyboard focus along", async () => {
    const client = await seededClient();
    renderWithProviders(<ContractsView />, { client, route: "/contracts" });
    const chart = screen.getByRole("group", { name: "Contract terms and notice windows" });
    const bar = within(chart).getByRole("button", { name: /^Insurance year\./ });
    bar.focus();
    fireEvent.click(bar);
    await waitFor(() => expect(document.activeElement).toBe(document.getElementById("contract-ctr_liability")));
  });

  it("terms it couldn't work out: drawn as unclear, and the card asks to check the letter", async () => {
    const client = await seededClient((list) =>
      list.map((c) =>
        c.id === "ctr_bank"
          ? {
              ...c,
              computed: { ...c.computed!, confidence: "low" as const, summary: "We couldn't compute a cancellation date: the contract's notice period is missing." },
            }
          : c,
      ),
    );
    renderWithProviders(<ContractsView />, { client, route: "/contracts" });
    const chart = screen.getByRole("group", { name: "Contract terms and notice windows" });
    const lane = within(chart).getByRole("listitem", { name: "Musterbank Girokonto" });
    expect(within(lane).getByRole("button", { name: /^Terms unclear\./ })).toBeInTheDocument();
    expect(lane).toHaveTextContent("Check the letter");
    const bank = card("Musterbank Girokonto");
    expect(within(bank).getByRole("link", { name: /Check the letter/ })).toHaveAttribute("href", "/documents/doc_bank");
    expect(within(bank).queryByRole("link", { name: /Open letter/ })).toBeNull();
  });

  it("Decide by: the stripe, the leaf and the countdown follow the one urgency scale", async () => {
    const soon = (days: string) => async () =>
      seededClient((list) => list.map((c) => (c.id === "ctr_phone" ? { ...c, computed: { ...c.computed!, send_by: days } } : c)));
    for (const [sendBy, level, stripe] of [
      ["2026-10-08", "ink", "bg-line-strong"],
      ["2026-10-02", "warn", "bg-warn"],
    ] as const) {
      const { unmount } = renderWithProviders(<ContractsView />, { client: await soon(sendBy)(), route: "/contracts" });
      const item = within(screen.getByRole("region", { name: /Decide by/ })).getByRole("listitem");
      expect(item).toHaveAttribute("data-urgency", level);
      expect(item.querySelector("[data-part=stripe]")!.className).toContain(stripe);
      for (const t of item.querySelectorAll("time[data-urgency]")) expect(t).toHaveAttribute("data-urgency", level);
      unmount();
    }
  });
});

/** UI audit round 1 (leftovers): terms we couldn't work out — the notice period entered on the card. */
describe("Contracts page — adding a notice period by hand", () => {
  afterEach(() => {
    act(() => __clearToasts());
    vi.unstubAllGlobals();
  });

  const card = (name: string | RegExp) => screen.getAllByRole("article").find((a) => within(a).queryByRole("heading", { name }))!;

  it("checks the number and offers only the ways that give dates", () => {
    expect(noticeValueError("", "months")).toBe("Enter the notice period, e.g. 1 or 3");
    expect(noticeValueError("2,5", "months")).toBe("Enter a whole number, e.g. 1 or 3");
    expect(noticeValueError("0", "weeks")).toBe("At least 1 week");
    expect(noticeValueError("25", "months")).toBe("Up to 24 months");
    expect(noticeValueError(" 3 ", "months")).toBeNull();
    expect(noticeValueError("730", "days")).toBeNull();
    const noTerm = { initial_term_months: null, start_date: null, concluded_date: null, notice_basis: null };
    expect(noticeBases(noTerm)).toEqual(["any_time", "end_of_month"]);
    expect(noticeBases({ ...noTerm, initial_term_months: 12, start_date: "2025-01-01" })).toEqual(["any_time", "end_of_month", "end_of_term"]);
    expect(noticeBases({ ...noTerm, notice_basis: "end_of_term" })).toContain("end_of_term");
  });

  it("validates, saves through the API, shows the new dates and can be undone", async () => {
    const { srv, calls } = useMockApi();
    const bank = srv.db.state.contracts.find((c) => c.id === "ctr_bank")!;
    bank.computed = { ...bank.computed!, confidence: "low", summary: "We couldn't compute a cancellation date: the contract's notice period is missing." };
    renderWithProviders(
      <>
        <ContractsView />
        <Toaster />
      </>,
      { route: "/contracts" },
    );
    await screen.findByRole("heading", { level: 3, name: "Musterbank Girokonto" });
    fireEvent.click(within(card("Musterbank Girokonto")).getByRole("button", { name: /^Add notice period/ }));

    const form = within(card("Musterbank Girokonto")).getByRole("form", { name: "Notice period for Musterbank Girokonto" });
    const value = within(form).getByLabelText("Notice period");
    await waitFor(() => expect(value).toHaveFocus());
    const basis = within(form).getByLabelText("Can be cancelled");
    // no term to count from: "to the end of the term" would give no dates
    expect(within(basis).getAllByRole("option").map((o) => o.textContent)).toEqual(["Choose…", "at any time", "to the end of a month"]);

    fireEvent.click(within(form).getByRole("button", { name: "Save notice period" }));
    expect(value).toHaveAttribute("aria-invalid", "true");
    expect(value).toHaveAccessibleDescription("Enter the notice period, e.g. 1 or 3");
    expect(within(form).getByText("Choose how it can be cancelled")).toBeInTheDocument();
    expect(value).toHaveFocus();

    fireEvent.change(value, { target: { value: "30" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save notice period" }));
    expect(value).toHaveAccessibleDescription("Up to 24 months");

    fireEvent.change(value, { target: { value: "1" } });
    // "1 month", not "1 months"
    expect(within(form).getByLabelText("Unit")).toHaveDisplayValue("month");
    fireEvent.click(within(form).getByRole("button", { name: "Save notice period" }));
    expect(basis).toHaveFocus();
    expect(basis).toHaveAttribute("aria-invalid", "true");
    fireEvent.change(basis, { target: { value: "end_of_month" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save notice period" }));

    expect(await screen.findByText("Notice period saved")).toBeInTheDocument();
    expect(screen.getByText("To leave on Sat 31 Oct 2026, your notice must arrive by Wed 30 Sep 2026; send it by Mon 28 Sep.")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PATCH")).toEqual({ method: "PATCH", path: "/contracts/ctr_bank", body: { notice_value: 1, notice_unit: "months", notice_basis: "end_of_month" } });
    // the card shows the dates the engine worked out, and the focus stays on the card
    await waitFor(() => expect(within(card("Musterbank Girokonto")).queryByRole("button", { name: /notice period/ })).toBeNull());
    const saved = card("Musterbank Girokonto");
    expect(within(saved).getByText(/As written in the contract: 1 month's notice to the end of a month/)).toBeInTheDocument();
    // cancellable any month: when notice must arrive, never an urgent "Send by"
    expect(within(saved).getByText("Notice must arrive by")).toBeInTheDocument();
    expect(within(saved).queryByRole("form")).toBeNull();
    await waitFor(() => expect(saved).toHaveFocus());

    // Undo puts the old (missing) terms back, and the button that is back takes the focus
    const undo = screen.getByRole("button", { name: /^Undo/ });
    act(() => undo.focus());
    fireEvent.click(undo);
    const again = await within(card("Musterbank Girokonto")).findByRole("button", { name: /^Add notice period/ });
    expect(calls.filter((c) => c.method === "PATCH").at(-1)?.body).toEqual({ notice_value: null, notice_unit: null, notice_basis: null });
    await waitFor(() => expect(again).toHaveFocus());
  });

  // on the real demo the refreshed contract list came before the call's own answer: the form had
  // gone with it, and mutate's callbacks with the form — no "saved" toast, no Undo, focus lost
  it("says it was saved and closes even when the form has gone before the answer came", async () => {
    const { srv } = useMockApi();
    const bank = srv.db.state.contracts.find((c) => c.id === "ctr_bank")!;
    bank.computed = { ...bank.computed!, confidence: "low" };
    let release = () => {};
    const held = new Promise<void>((r) => (release = r));
    const mocked = globalThis.fetch;
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PATCH") await held;
      return mocked(input, init);
    });
    const onClose = vi.fn();
    function Harness() {
      const [shown, setShown] = useState(true);
      return (
        <>
          {shown ? <NoticePeriodForm contract={bank} onClose={onClose} onUndone={() => {}} /> : null}
          <button onClick={() => setShown(false)}>Gone</button>
          <Toaster />
        </>
      );
    }
    renderWithProviders(<Harness />);
    fireEvent.change(screen.getByLabelText("Notice period"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Can be cancelled"), { target: { value: "any_time" } });
    fireEvent.click(screen.getByRole("button", { name: "Save notice period" }));
    fireEvent.click(screen.getByRole("button", { name: "Gone" }));
    expect(screen.queryByRole("form")).toBeNull();
    release();
    expect(await screen.findByText("Notice period saved")).toBeInTheDocument();
    expect(onClose).toHaveBeenCalledWith(expect.objectContaining({ id: "ctr_bank", notice_value: 1, notice_basis: "any_time" }));
    expect(screen.getByRole("button", { name: /^Undo/ })).toBeInTheDocument();
  });

  it("Escape closes the form and hands the focus back to its button", async () => {
    const { srv } = useMockApi();
    const bank = srv.db.state.contracts.find((c) => c.id === "ctr_bank")!;
    bank.computed = { ...bank.computed!, confidence: "low" };
    renderWithProviders(<ContractsView />, { route: "/contracts" });
    await screen.findByRole("heading", { level: 3, name: "Musterbank Girokonto" });
    fireEvent.click(within(card("Musterbank Girokonto")).getByRole("button", { name: /Add notice period/ }));
    const form = within(card("Musterbank Girokonto")).getByRole("form");
    fireEvent.keyDown(within(form).getByLabelText("Notice period"), { key: "Escape" });
    expect(within(card("Musterbank Girokonto")).queryByRole("form")).toBeNull();
    await waitFor(() => expect(within(card("Musterbank Girokonto")).getByRole("button", { name: /Add notice period/ })).toHaveFocus());
  });
});
