/**
 * Letters in the queue — waiting for a missing or signed-out Claude, say, which keeps them queued instead of
 * failing them — are letters not read yet: Today never says "All clear" while any are there (final check F-M1,
 * which reopened UX U2).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import { qk } from "@/api/hooks";
import type { Brief, Dashboard, Document, Party, Profile } from "@/api/types";
import { createMockServer } from "@/mocks/server";
import { useMockApi } from "@/test/mockFetch";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { TodayView } from "./TodayView";

/** Sam's day with nothing due this week, and two of his letters back in the queue. */
async function dayWithQueuedLetters(status: Document["status"]) {
  const srv = createMockServer({ staticDemo: false, latency: 0 });
  const get = async <T,>(path: string, q = "") => (await (await srv.handle("GET", path, new URLSearchParams(q), undefined)).json()) as T;
  const qc = makeTestQueryClient();
  const dash = await get<Dashboard>("/dashboard");
  qc.setQueryData(qk.dashboard, {
    ...dash,
    attention: [],
    decisions: [],
    waiting: 0,
    upcoming: dash.upcoming.filter((i) => (i.send_by ?? i.due_date ?? "") >= "2026-10-14"),
  });
  qc.setQueryData(qk.parties.list(), await get<Party[]>("/parties"));
  qc.setQueryData(qk.documents.list({ status: "needs_review" }), []);
  qc.setQueryData(qk.documents.list({ status: "failed" }), []);
  const docs = await get<Document[]>("/documents");
  qc.setQueryData(qk.documents.list({}), docs.map((d, i) => (i < 2 ? { ...d, status } : d)));
  // no note from the server: the code writes one
  qc.setQueryData(qk.brief, { ...(await get<Brief>("/brief")), text: "" });
  qc.setQueryData(qk.profile, await get<Profile>("/profile"));
  return qc;
}

afterEach(() => vi.unstubAllGlobals());

describe("Today with letters in the queue", () => {
  it.each(["queued", "processing"] as const)("never says 'all clear' while letters are %s", async (status) => {
    useMockApi();
    const client = await dayWithQueuedLetters(status);
    renderWithProviders(<TodayView />, { client });
    const top = await screen.findByRole("region", { name: "Top 3 this week" });
    expect(within(top).getByRole("heading", { name: "Nothing due from the letters that were read" })).toBeInTheDocument();
    expect(within(top).getByText("2 letters aren't read yet — their dates show up here once they're read.")).toBeInTheDocument();
    // the code-written note says so too
    expect(await screen.findByText(/2 letters wait to be read\./)).toBeInTheDocument();
    expect(screen.queryByText(/All clear/)).toBeNull();
    expect(screen.queryByText(/Nothing needs you/)).toBeNull();
  });
});
