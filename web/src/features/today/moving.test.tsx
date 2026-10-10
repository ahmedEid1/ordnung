/**
 * The moving checklist on Today: after the person said they moved (Settings → Profile → "I moved"), its own card
 * lists who needs the new address — native checkboxes that tick a row off (Undo in the toast), focus that moves on
 * to the next row, "Not needed", and "Write the letter" (or "Open your draft"). It never sends anything; the general
 * Ideas list leaves its rows out.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Draft, Suggestion } from "@/api/types";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { renderWithProviders, TEST_TODAY } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import type { MockServer } from "@/mocks/server";
import { MOVING_RULE, moveDayError, moveDayRange, movedLine, moveStanding, movingRows, openDraftFor } from "./moving";
import { selectIdeas } from "./selection";
import { TodayView } from "./TodayView";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

function row(over: Partial<Suggestion> & Pick<Suggestion, "id" | "title">): Suggestion {
  return {
    kind: "hygiene",
    body: "",
    rationale: null,
    priority: "low",
    status: "new",
    rule_id: MOVING_RULE,
    due_date: null,
    savings_estimate: null,
    refs: [],
    fingerprint: `moved_house:${over.id}:2026-09-21`,
    action: { type: "open", draft_kind: null, target_type: "party", target_id: "pty_funknetz", label: "Write the letter" },
    source: "rule",
    snoozed_until: null,
    created_at: "2026-09-21T10:00:00Z",
    updated_at: "2026-09-21T10:00:00Z",
    ...over,
  };
}

describe("the moving checklist's rows", () => {
  it("are the new moving Ideas only, registering first, then by title", () => {
    const register = row({ id: "reg", title: "Register your new address by Mon 5 Oct", kind: "deadline", priority: "high", action: null });
    const bank = row({ id: "bank", title: "Tell Musterbank your new address" });
    const fee = row({ id: "fee", title: "Tell the broadcasting fee office your new address" });
    const done = row({ id: "done", title: "Tell FunkNetz your new address", status: "done" });
    const other = row({ id: "other", title: "Check the letter", rule_id: "please_check" });
    expect(movingRows([fee, other, bank, done, register]).map((r) => r.id)).toEqual(["reg", "bank", "fee"]);
    // the general Ideas list leaves them out, as it does the calendar Idea
    const { shown, more } = selectIdeas([fee, other, bank, register], { max: 10 });
    expect([...shown, ...more].map((s) => s.id)).toEqual(["other"]);
  });

  it("find a new-address letter already started to the row's sender", () => {
    const tell = row({ id: "tell", title: "Tell FunkNetz your new address" });
    const draft = (over: Partial<Draft>) => ({ id: "drf", kind: "address_change", party_id: "pty_funknetz", status: "draft", created_at: "2026-09-22T09:00:00Z", ...over }) as Draft;
    expect(openDraftFor(tell, [draft({ id: "drf_a" }), draft({ id: "drf_b", created_at: "2026-09-23T09:00:00Z" })])?.id).toBe("drf_b");
    expect(openDraftFor(tell, [draft({ status: "sent" })])).toBeNull();
    expect(openDraftFor(tell, [draft({ created_at: "2026-09-01T09:00:00Z" })])).toBeNull(); // older than the row
    expect(openDraftFor(tell, [draft({ party_id: "pty_other" })])).toBeNull();
    expect(openDraftFor(tell, [draft({ kind: "general_reply" })])).toBeNull();
    expect(openDraftFor(row({ id: "reg", title: "Register", action: null }), [draft({})])).toBeNull();
  });

  it("know whether a move still has its checklist, and which days one may be told for", () => {
    expect(moveStanding({ moved_on: null }, TEST_TODAY)).toBe(false);
    expect(moveStanding({ moved_on: "2026-04-01" }, TEST_TODAY)).toBe(true);
    expect(moveStanding({ moved_on: "2026-03-31" }, TEST_TODAY)).toBe(false);
    expect(moveStanding({ moved_on: "2026-11-01" }, TEST_TODAY)).toBe(true);
    expect(moveDayRange(TEST_TODAY)).toEqual({ min: "2026-04-01", max: "2026-12-27" });
    expect(moveDayError("2026-09-21", TEST_TODAY)).toBeNull();
    expect(moveDayError("", TEST_TODAY)).toBe("Enter the day you moved in.");
    expect(moveDayError("2026-12-28", TEST_TODAY)).toMatch(/last six months or the next three/);
    expect(movedLine("2026-09-21", TEST_TODAY)).toBe("You moved in on Mon 21 Sep.");
    expect(movedLine("2026-10-02", TEST_TODAY)).toBe("You move in on Fri 2 Oct.");
  });
});

async function moved(srv: MockServer, body: Record<string, unknown> = {}) {
  const res = await srv.handle("PUT", "/profile", new URLSearchParams(), { moved_on: "2026-09-21", old_address: "Beispielweg 5\n12345 Musterstadt", ...body });
  expect(res.status).toBe(200);
}

async function renderToday() {
  const user = userEvent.setup();
  renderWithProviders(
    <>
      <TodayView />
      <Toaster />
    </>,
  );
  await screen.findByRole("region", { name: "Top 3 this week" });
  return { user };
}

const card = () => screen.getByRole("region", { name: "Moving checklist" });
const checks = () => within(card()).getAllByRole("checkbox");

describe("the Moving checklist card", () => {
  it("isn't there until the person says they moved", async () => {
    useMockApi();
    await renderToday();
    expect(screen.queryByRole("region", { name: "Moving checklist" })).not.toBeInTheDocument();
  });

  it("lists who needs the new address above the Ideas, five rows at first, and never in the Ideas", async () => {
    const { srv } = useMockApi();
    await moved(srv);
    const { user } = await renderToday();
    const section = await screen.findByRole("region", { name: "Moving checklist" });
    expect(section).toHaveAttribute("id", "moving-checklist");
    expect(within(section).getByRole("heading", { level: 2, name: "Moving checklist" })).toBeInTheDocument();
    expect(section).toHaveTextContent("Ordnung never sends anything for you.");
    expect(section).toHaveTextContent("11 to go");
    expect(checks()).toHaveLength(5);
    expect(checks()[0]).toHaveAccessibleName("Register your new address by Mon 5 Oct");
    expect(checks()[0]).not.toBeChecked();
    // the section comes before the Ideas
    const ideas = screen.getByRole("region", { name: "Ideas from your secretary" });
    expect(section.compareDocumentPosition(ideas) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(ideas).queryByText(/your new address/)).not.toBeInTheDocument();

    await user.click(within(section).getByRole("button", { name: "Show 6 more" }));
    expect(checks()).toHaveLength(11);
    expect(within(section).getByText(/Also think of your doctor/)).toBeInTheDocument();
  });

  it("ticks a row off, hands focus to the next one, and Undo brings it back", async () => {
    const { srv, calls } = useMockApi();
    await moved(srv);
    const { user } = await renderToday();
    await screen.findByRole("region", { name: "Moving checklist" });
    const first = checks()[0]!;
    const second = checks()[1]!;
    const id = srv.db.state.suggestions.find((s) => s.title === "Register your new address by Mon 5 Oct")!.id;
    first.focus();
    await user.keyboard(" ");
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH" && c.path === `/suggestions/${id}`)).toBe(true));
    expect(calls.find((c) => c.method === "PATCH" && c.path === `/suggestions/${id}`)?.body).toEqual({ status: "done" });
    await waitFor(() => expect(within(card()).queryByRole("checkbox", { name: "Register your new address by Mon 5 Oct" })).not.toBeInTheDocument());
    await waitFor(() => expect(second).toHaveFocus());
    expect(card()).toHaveTextContent("10 to go");

    const toast = await screen.findByText("Ticked off");
    await user.click(within(toast.closest("[data-toast]") as HTMLElement).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.filter((c) => c.path === `/suggestions/${id}`).map((c) => c.body)).toEqual([{ status: "done" }, { status: "new" }]));
    const back = await within(card()).findByRole("checkbox", { name: "Register your new address by Mon 5 Oct" });
    expect(back).not.toBeChecked();
    await waitFor(() => expect(back).toHaveFocus());
  });

  it("hides a row that isn't needed, with Undo", async () => {
    const { srv, calls } = useMockApi();
    await moved(srv);
    const { user } = await renderToday();
    await screen.findByRole("region", { name: "Moving checklist" });
    await user.click(within(card()).getByRole("button", { name: "Show 6 more" }));
    const bank = srv.db.state.suggestions.find((s) => s.rule_id === MOVING_RULE && s.action?.target_id === "pty_musterbank")!;
    const item = within(card()).getByRole("checkbox", { name: bank.title }).closest("li")!;
    // the button names the row it is about
    expect(within(item).getByRole("button", { name: "Not needed" })).toHaveAccessibleDescription(bank.title);
    await user.click(within(item).getByRole("button", { name: "Not needed" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH" && c.path === `/suggestions/${bank.id}`)?.body).toEqual({ status: "dismissed" }));
    const toast = await screen.findByText("Hidden");
    await waitFor(() => expect(within(card()).queryByRole("checkbox", { name: bank.title })).not.toBeInTheDocument());
    await user.click(within(toast.closest("[data-toast]") as HTMLElement).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.filter((c) => c.path === `/suggestions/${bank.id}`).map((c) => c.body)).toEqual([{ status: "dismissed" }, { status: "new" }]));
    expect(await within(card()).findByRole("checkbox", { name: bank.title })).not.toBeChecked();
  });

  it("opens a new-address letter to the sender, or the one already started", async () => {
    const { srv } = useMockApi();
    await moved(srv);
    const telecom = srv.db.state.suggestions.find((s) => s.rule_id === MOVING_RULE && s.action?.target_id === "pty_funknetz")!;
    srv.db.state.drafts.push({ ...srv.db.state.drafts[0]!, id: "drf_move", kind: "address_change", party_id: "pty_funknetz", status: "draft", sent_at: null, created_at: "2026-09-28T09:00:00Z" });
    const { user } = await renderToday();
    await screen.findByRole("region", { name: "Moving checklist" });
    await user.click(within(card()).getByRole("button", { name: "Show 6 more" }));
    const items = (title: string) => within(card()).getByRole("checkbox", { name: title }).closest("li")!;
    expect(await within(items(telecom.title)).findByRole("link", { name: "Open your draft" })).toHaveAttribute("href", "/letters/drf_move");
    const bank = srv.db.state.suggestions.find((s) => s.rule_id === MOVING_RULE && s.action?.target_id === "pty_musterbank")!;
    expect(within(items(bank.title)).getByRole("link", { name: "Write the letter" })).toHaveAttribute("href", "/letters?kind=address_change&to=pty_musterbank");
    // registering acts in place: no letter to write
    expect(within(items("Register your new address by Mon 5 Oct")).queryByRole("link")).not.toBeInTheDocument();
  });

  it("says everyone has the new address once the last row is ticked off", async () => {
    const { srv } = useMockApi();
    srv.db.state.contracts = [];
    await moved(srv);
    const { user } = await renderToday();
    await screen.findByRole("region", { name: "Moving checklist" });
    expect(checks()).toHaveLength(2); // registering, and the broadcasting fee office
    await user.click(checks()[0]!);
    await waitFor(() => expect(checks()).toHaveLength(1));
    await user.click(checks()[0]!);
    expect(await within(card()).findByText("Everyone on the list has your new address.")).toBeInTheDocument();
    expect(within(card()).queryByRole("checkbox")).not.toBeInTheDocument();
    await waitFor(() => expect(within(card()).getByRole("heading", { level: 2, name: "Moving checklist" })).toHaveFocus());
  });
});
