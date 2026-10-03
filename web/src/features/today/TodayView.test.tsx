import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { qk } from "@/api/hooks";
import type { Brief, Dashboard, Document, Party, Profile } from "@/api/types";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { createMockServer } from "@/mocks/server";
import { useMockApi } from "@/test/mockFetch";
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
  qc.setQueryData(qk.documents.list({ status: "failed" }), await get<Document[]>("/documents", "status=failed"));
  qc.setQueryData(qk.documents.list({}), await get<Document[]>("/documents"));
  qc.setQueryData(qk.brief, await get<Brief>("/brief"));
  qc.setQueryData(qk.profile, await get<Profile>("/profile"));
  return qc;
}

afterEach(() => vi.unstubAllGlobals());

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
    // the demo tour's ring on phones and short screens: the first Idea only (R1-tour-6)
    expect(ideas.querySelectorAll("[data-tour-part]")).toHaveLength(1);
    expect(within(ideas).getAllByRole("listitem")[0]).toHaveAttribute("data-tour-part");
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
      waiting: 0,
      upcoming: d.upcoming.filter((i) => (i.send_by ?? i.due_date ?? "") >= "2026-10-14"),
    }));
    renderWithProviders(<TodayView />, { client });
    expect(await screen.findByRole("heading", { name: "All clear until Wed 14 Oct" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /from your folder/ })).toBeNull();
  });

  it("never says 'all clear' while letters from the folder wait unread, and points to them", async () => {
    const client = await seededClient((d) => ({
      ...d,
      attention: [],
      decisions: [],
      waiting: 2,
      upcoming: d.upcoming.filter((i) => (i.send_by ?? i.due_date ?? "") >= "2026-10-14"),
    }));
    renderWithProviders(<TodayView />, { client });
    const card = await screen.findByRole("region", { name: "Not read yet: 2 letters from your folder" });
    expect(within(card).getByRole("link", { name: /Review them/ })).toHaveAttribute("href", "/inbox");
    // "not read yet" once, in the card's heading: its text says what is new, and Claude's note above gets no
    // "Not in this note: 2 letters from your folder, not read yet." (UI audit round 2)
    expect(within(card).getByText(/^Ordnung can't tell you what they ask or by when until they're read\. Nothing has been sent to Claude\.$/)).toBeInTheDocument();
    expect(screen.getByText(/Two small payments this week/)).toBeInTheDocument();
    expect(screen.queryByText(/Not in this note/)).toBeNull();
    // the Inbox's "not read yet" mark, not the deadline's hourglass
    const icon = card.querySelector("svg")!.getAttribute("class")!;
    expect(icon).toMatch(/lucide-folder-input/);
    expect(icon).not.toMatch(/hourglass/);
    expect(screen.getByRole("heading", { name: "Nothing due from the letters that were read" })).toBeInTheDocument();
    expect(screen.queryByText(/All clear/)).toBeNull();
    expect(screen.queryByText(/Nothing needs you/)).toBeNull();
  });

  it("never says 'all clear' while letters couldn't be read, and offers to try again", async () => {
    // UX U2: with two failed letters Today said "All clear" three times while the Inbox said "Please check 2"
    const { calls } = useMockApi();
    const client = await seededClient((d) => ({
      ...d,
      attention: [],
      decisions: [],
      waiting: 0,
      upcoming: d.upcoming.filter((i) => (i.send_by ?? i.due_date ?? "") >= "2026-10-14"),
    }));
    const docs = client.getQueryData<Document[]>(qk.documents.list({})) ?? [];
    const failed = docs.slice(0, 2).map((d) => ({ ...d, status: "failed" as const, error: "Claude is not signed in." }));
    client.setQueryData(qk.documents.list({ status: "failed" }), failed);
    client.setQueryData(qk.brief, undefined);
    renderWithProviders(<TodayView />, { client });
    const card = await screen.findByRole("region", { name: "2 letters couldn't be read" });
    expect(card).toHaveTextContent("Ordnung can't tell you what they ask or by when until they're read.");
    expect(within(card).getByRole("link", { name: /See them/ })).toHaveAttribute("href", "/inbox?filter=check");
    expect(screen.getByRole("heading", { name: "Nothing due from the letters that were read" })).toBeInTheDocument();
    expect(screen.getByText("2 letters aren't read yet — their dates show up here once they're read.")).toBeInTheDocument();
    expect(screen.queryByText(/All clear/)).toBeNull();
    expect(screen.queryByText(/Nothing needs you/)).toBeNull();

    const user = userEvent.setup();
    await user.click(within(card).getByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(calls.filter((c) => c.method === "POST" && c.path.endsWith("/reprocess")).map((c) => c.path)).toEqual(
        failed.map((d) => `/documents/${d.id}/reprocess`),
      ),
    );
  });

  it("names the one letter that couldn't be read and leads to it", async () => {
    const client = await seededClient();
    const [doc] = client.getQueryData<Document[]>(qk.documents.list({})) ?? [];
    client.setQueryData(qk.documents.list({ status: "failed" }), [{ ...doc!, status: "failed" as const }]);
    renderWithProviders(<TodayView />, { client });
    const card = await screen.findByRole("region", { name: "1 letter couldn't be read" });
    expect(card).toHaveTextContent("Ordnung can't tell you what it asks or by when until it's read.");
    expect(within(card).getByRole("link", { name: /Open it/ })).toHaveAttribute("href", `/documents/${doc!.id}`);
  });
});
