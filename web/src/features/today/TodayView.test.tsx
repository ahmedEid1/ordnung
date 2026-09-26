import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import { qk } from "@/api/hooks";
import type { Brief, Dashboard, Document, Party, Profile } from "@/api/types";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { createMockServer } from "@/mocks/server";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { TodayView } from "./TodayView";

async function seededClient(mutate?: (d: Dashboard) => Dashboard) {
  const srv = createMockServer({ staticDemo: false, latency: 0 });
  const get = async <T,>(path: string, q = "") => (await (await srv.handle("GET", path, new URLSearchParams(q), undefined)).json()) as T;
  const qc = makeTestQueryClient();
  const dash = await get<Dashboard>("/dashboard");
  qc.setQueryData(qk.dashboard, mutate ? mutate(dash) : dash);
  qc.setQueryData(qk.parties.list(), await get<Party[]>("/parties"));
  qc.setQueryData(qk.documents.list({ status: "needs_review" }), await get<Document[]>("/documents", "status=needs_review"));
  qc.setQueryData(qk.documents.list({}), await get<Document[]>("/documents"));
  qc.setQueryData(qk.brief, await get<Brief>("/brief"));
  qc.setQueryData(qk.profile, await get<Profile>("/profile"));
  return qc;
}

describe("Today page", () => {
  it("renders the day for Sam without raw enum values", async () => {
    const client = await seededClient();
    const { container } = renderWithProviders(<TodayView />, { client });

    expect(await screen.findByRole("heading", { level: 1, name: "Good morning, Sam" })).toBeInTheDocument();
    // the note's own greeting is dropped (the page already greets)
    expect(screen.getByText(/Two small payments this week/)).toBeInTheDocument();

    const top = screen.getByRole("region", { name: "Top 3 this week" });
    const cards = within(top).getAllByRole("article");
    expect(cards.map((c) => within(c).getByRole("heading").textContent)).toEqual([
      "Pay the parking fine",
      "Pay TechMarkt reminder",
      "Pay library fee",
    ]);
    expect(within(top).getAllByRole("button", { name: /Why this date\?/ })).toHaveLength(3);
    expect(within(cards[0]!).getByRole("button", { name: /^Check/ })).toBeInTheDocument();
    expect(within(cards[1]!).getByRole("button", { name: /^Pay/ })).toBeInTheDocument();
    expect(within(cards[0]!).getByText("Please check")).toBeInTheDocument();

    const coming = screen.getByRole("region", { name: /Coming up/ });
    expect(within(coming).getByText("Cancel phone contract — if you want to switch")).toBeInTheDocument();
    // the leaf shows the day; the row says what it means and who it is with
    expect(within(coming).getByRole("link", { name: /Thursday 8 October.*Cancel phone contract.*Send · / })).toBeInTheDocument();

    const ideas = screen.getByRole("region", { name: "Ideas from your secretary" });
    expect(ideas).toHaveAttribute("data-tour", "today-ideas");
    expect(within(ideas).getAllByRole("article")).toHaveLength(3);
    expect(within(ideas).getAllByRole("button", { name: "Remind me in a week" })).toHaveLength(3);
    expect(within(ideas).getByText(/Could save about €756/)).toBeInTheDocument();
    // an Idea that repeats a Top-3 card is not shown twice
    expect(within(ideas).queryByText(/Pay TechMarkt reminder 94,99/)).not.toBeInTheDocument();

    expect(screen.getByRole("heading", { name: /3 new dates since your last calendar update/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Please check · 1 letter/ })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Life at a glance" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Recent letters/ })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getAllByText(/Not legal advice/).length).toBeGreaterThan(0);

    assertNoRawEnumsInElement(container);
  });

  it("shows 'All clear until …' when nothing is due this week", async () => {
    const client = await seededClient((d) => ({
      ...d,
      attention: [],
      decisions: [],
      upcoming: d.upcoming.filter((i) => (i.send_by ?? i.due_date ?? "") >= "2026-10-14"),
    }));
    renderWithProviders(<TodayView />, { client });
    expect(await screen.findByRole("heading", { name: "All clear until Wed 14 Oct" })).toBeInTheDocument();
  });
});
