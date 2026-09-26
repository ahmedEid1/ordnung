import { describe, expect, it } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";
import { qk } from "@/api/hooks";
import type { Contract, Party } from "@/api/types";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { createMockServer } from "@/mocks/server";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { ContractsView } from "./ContractsView";

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
    expect(screen.getByText("Fixed costs per month").nextElementSibling).toHaveTextContent("€987/month");
    expect(screen.getByText("Per year").nextElementSibling).toHaveTextContent("€11,844");

    const decide = screen.getByRole("region", { name: /Decide by/ });
    const callouts = within(decide).getAllByRole("listitem");
    expect(callouts).toHaveLength(1);
    expect(within(callouts[0]!).getByRole("heading", { name: /FunkNetz Allnet L/ })).toBeInTheDocument();
    expect(within(callouts[0]!).getByText(/Decide by Thu 8 Oct/)).toBeInTheDocument();
    expect(within(callouts[0]!).getByText("Kündigung (cancellation / notice)")).toBeInTheDocument();
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
    expect(within(cards[0]!).getByText("Post it by")).toBeInTheDocument();
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
    expect(within(pop).getByText("Post it by")).toBeInTheDocument();
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
    expect(screen.getByText("Fixed costs per month").nextElementSibling).toHaveTextContent("€957.10/month");
    fireEvent.click(screen.getByRole("tab", { name: /Cancelled/ }));
    const cards = screen.getAllByRole("article");
    expect(cards).toHaveLength(1);
    expect(within(cards[0]!).getByText("Cancelled")).toBeInTheDocument();
    expect(within(cards[0]!).queryByRole("link", { name: /Draft cancellation/ })).not.toBeInTheDocument();
  });
});
