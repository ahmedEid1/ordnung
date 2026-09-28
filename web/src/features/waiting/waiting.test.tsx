import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { WaitingEntry } from "@/api/types";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { doc } from "@/mocks/data/helpers";
import WaitingPage from "@/pages/WaitingPage";
import LettersPage from "@/pages/LettersPage";
import { asksForACall, groupWaiting, waitingSummary } from "./model";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

const entry = (id: string, status: WaitingEntry["status"]): WaitingEntry =>
  ({ id, status, source: "letter", title: id, about: "", note: "", since: null, expected_by: null }) as unknown as WaitingEntry;

describe("grouping", () => {
  it("groups by status in the server's order and never lists closed ones", () => {
    const groups = groupWaiting([entry("a", "overdue"), entry("b", "waiting"), entry("c", "answered"), entry("d", "waiting"), entry("e", "closed")]);
    expect(groups.overdue.map((e) => e.id)).toEqual(["a"]);
    expect(groups.waiting.map((e) => e.id)).toEqual(["b", "d"]);
    expect(groups.answered.map((e) => e.id)).toEqual(["c"]);
  });

  it("counts what is open and what is overdue", () => {
    expect(waitingSummary([entry("a", "overdue"), entry("b", "waiting"), entry("e", "closed")])).toEqual({ count: 2, overdue: 1 });
    expect(waitingSummary([])).toEqual({ count: 0, overdue: 0 });
  });
});

function renderWaiting() {
  return renderWithProviders(
    <>
      <WaitingPage />
      <Toaster />
    </>,
    { route: "/letters/waiting" },
  );
}

describe("Note a call", () => {
  it("is offered where the note says to call them — an overdue letter or promise with a known sender", () => {
    const base = { party_id: "pty_x" } as const;
    expect(asksForACall({ ...base, source: "letter", status: "overdue" })).toBe(true);
    expect(asksForACall({ ...base, source: "call", status: "overdue" })).toBe(true);
    expect(asksForACall({ ...base, source: "letter", status: "waiting" })).toBe(false);
    expect(asksForACall({ ...base, source: "money", status: "overdue" })).toBe(false);
    expect(asksForACall({ party_id: null, source: "letter", status: "overdue" })).toBe(false);
  });

  it("opens who they called with the form, from an overdue row", async () => {
    const { srv } = useMockApi();
    srv.db.state.calls[0]!.case_id = "cas_flat";
    const user = userEvent.setup();
    const { router } = renderWaiting();
    const overdue = await screen.findByRole("region", { name: /Overdue/ });
    await user.click(within(overdue).getByRole("button", { name: "Note a call" }));
    const params = new URLSearchParams(router.state.location.search);
    expect([params.get("party"), params.get("call")]).toEqual(["pty_fitwell", "cas_flat"]);
    // nothing to chase on a row that is only waiting
    expect(within(screen.getByRole("region", { name: /^Waiting/ })).queryByRole("button", { name: "Note a call" })).not.toBeInTheDocument();
  });
});

describe("Waiting for page", () => {
  it("lists replies, money and callbacks, overdue first", async () => {
    useMockApi();
    const { container } = renderWaiting();
    expect(await screen.findByRole("heading", { level: 1, name: "Waiting for" })).toBeInTheDocument();
    const overdue = await screen.findByRole("region", { name: /Overdue/ });
    expect(within(overdue).getByText("Written confirmation of the cancellation")).toBeInTheDocument();
    expect(within(overdue).getByText(/Call them again and note what they say/)).toBeInTheDocument();
    const waiting = screen.getByRole("region", { name: /^Waiting/ });
    expect(within(waiting).getByText("A written confirmation of the end date")).toBeInTheDocument();
    expect(within(waiting).getByText(/Tracking number RT 123 456 785 DE/)).toBeInTheDocument(); // (no-break spaces)
    expect(within(waiting).getByText("Deposit back from the student hall")).toBeInTheDocument();
    expect(within(waiting).getByText(/can't see your bank account/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /A letter may have answered/ })).not.toBeInTheDocument();
    assertNoRawEnumsInElement(container);
  });

  it("says when a letter in the thread may have answered — and closes it only when asked", async () => {
    const { srv, calls } = useMockApi();
    srv.db.upsertDocument(
      doc({ id: "doc_wohnbau_answer", filename: "Antwort_Wohnbau.pdf", title: "Antwort zu Ihrer Nachricht", case_id: "cas_flat", party_id: "pty_wohnbau", doc_date: "2026-09-24" }),
    );
    const user = userEvent.setup();
    renderWaiting();
    const answered = await screen.findByRole("region", { name: /A letter may have answered/ });
    expect(within(answered).getByText("An answer to your letter")).toBeInTheDocument();
    expect(within(answered).getByText(/Their letter “Antwort zu Ihrer Nachricht” of Thu 24 Sep is in the same thread/)).toBeInTheDocument();
    expect(within(answered).getByRole("link", { name: "Read their letter" })).toHaveAttribute("href", "/documents/doc_wohnbau_answer");
    // nothing is closed until the person says so
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
    await user.click(within(answered).getByRole("button", { name: "It's the answer — close this" }));
    // the person's word, naming the letter: only now does the Nachweis say "answer received"
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.path === "/drafts/drf_wohnbau/answered")?.body).toEqual({ doc_id: "doc_wohnbau_answer" }));
    expect(await screen.findByText("Marked as answered")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("region", { name: /A letter may have answered/ })).not.toBeInTheDocument());
    // the row is gone: focus is on the row now in its place, never on <body>
    await waitFor(() => expect(document.activeElement?.hasAttribute("data-waiting-heading") || document.activeElement?.tagName === "H1").toBe(true));
  });

  it("closes a letter that is waiting or overdue when the answer came by phone or e-mail — with Undo", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderWaiting();
    const letter = (await screen.findByText("A written confirmation of the end date")).closest("li")!;
    await user.click(within(letter as HTMLElement).getByRole("button", { name: "I got an answer — close this" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.path === "/drafts/drf_gym/answered")?.body).toEqual({ doc_id: null }));
    await waitFor(() => expect(screen.queryByText("A written confirmation of the end date")).not.toBeInTheDocument());
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/drafts/drf_gym/answered")).toBe(true));
    expect(await screen.findByText("A written confirmation of the end date")).toBeInTheDocument();
    // back in its place, with focus on it
    await waitFor(() => expect(screen.getByRole("heading", { name: "A written confirmation of the end date" })).toHaveFocus());
  });

  it("marks money as received and a phone promise as kept", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderWaiting();
    const deposit = (await screen.findByText("Deposit back from the student hall")).closest("li")!;
    await user.click(within(deposit as HTMLElement).getByRole("button", { name: "It arrived" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH" && c.path === "/items/itm_deposit_hall")?.body).toEqual({ status: "done" }));
    expect(await screen.findByText("Marked as received")).toBeInTheDocument();
    // gone from the list (the toast still names it, with Undo), focus on the row now in its place
    await waitFor(() => expect(within(screen.getByRole("region", { name: /^Waiting/ })).queryByText("Deposit back from the student hall")).not.toBeInTheDocument());
    await waitFor(() => expect(document.activeElement?.hasAttribute("data-waiting-heading")).toBe(true));

    const call = screen.getByText("Written confirmation of the cancellation").closest("li")!;
    await user.click(within(call as HTMLElement).getByRole("button", { name: "They kept it" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH" && c.path === "/calls/cal_fitwell")?.body).toEqual({ kept: true }));
    await waitFor(() => expect(screen.queryByRole("region", { name: /Overdue/ })).not.toBeInTheDocument());
  });

  it("shows a calm empty state when nothing is owed", async () => {
    const { srv } = useMockApi();
    srv.db.state.calls = [];
    srv.db.state.drafts = srv.db.state.drafts.filter((d) => d.status !== "sent");
    srv.db.state.items = srv.db.state.items.filter((i) => !(i.kind === "payment" && i.direction === "in"));
    renderWaiting();
    expect(await screen.findByText("Nothing to wait for")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to your letters" })).toHaveAttribute("href", "/letters");
  });
});

describe("Letters page", () => {
  it("links to Waiting for with how many are open and overdue", async () => {
    useMockApi();
    renderWithProviders(<LettersPage />, { route: "/letters" });
    const link = await screen.findByRole("link", { name: /Waiting for/ });
    expect(link).toHaveAttribute("href", "/letters/waiting");
    await waitFor(() => expect(link).toHaveTextContent("4"));
    expect(link).toHaveAccessibleName(/1 overdue/);
    // overdue is red here as on the Waiting page (the Inbox's count does the same)
    expect(link.querySelector("[class*='danger']")).not.toBeNull();
  });
});
