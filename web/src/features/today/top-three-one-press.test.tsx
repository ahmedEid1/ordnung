/**
 * Top 3's "Mark done" and "Mark as paid" take one press at a time: two presses before the button is drawn busy send
 * one request (a repeating to-do moved on twice and skipped a date), and a failed one takes the next press.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { item } from "@/mocks/data/helpers";
import { expectOnePressAtATime } from "@/test/busyButton";
import { holdRequests, useMockApi } from "@/test/mockFetch";
import { renderWithProviders } from "@/test/render";
import { TodayView } from "./TodayView";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

async function renderToday() {
  renderWithProviders(
    <>
      <TodayView />
      <Toaster />
    </>,
  );
  const top = await screen.findByRole("region", { name: "Top 3 this week" });
  await within(top).findAllByRole("article");
  return top;
}

describe("Top 3", () => {
  it("“Mark done” takes one press at a time, and the next once its change failed", async () => {
    const { srv } = useMockApi();
    srv.db.state.items = srv.db.state.items.filter((i) => i.id === "itm_tm_dunning");
    srv.db.state.items.push(
      item({ id: "itm_weekly", kind: "task", title: "Water the plants", due_date: "2026-09-28", origin: "manual", recurrence: { interval: 1, unit: "weeks", working_day: null, day_of_month: null } }),
    );
    const held = holdRequests((call) => call.method === "PATCH" && call.path === "/items/itm_weekly");
    const top = await renderToday();
    await expectOnePressAtATime({ user: userEvent.setup(), button: () => within(top).getByRole("button", { name: "Mark done: Water the plants" }), held });
    await act(async () => held.release());
  });

  it("“Mark as paid” takes one press at a time, and names the date a repeating payment was paid for", async () => {
    const { srv, calls } = useMockApi();
    Object.assign(srv.db.state.items.find((i) => i.id === "itm_tm_dunning")!, { origin: "manual", recurrence: { interval: 1, unit: "months", working_day: null, day_of_month: null } });
    const due = srv.db.state.items.find((i) => i.id === "itm_tm_dunning")!.due_date;
    const held = holdRequests((call) => call.method === "PATCH" && call.path === "/items/itm_tm_dunning");
    const top = await renderToday();
    const user = userEvent.setup();
    await user.click(within(top).getByRole("button", { name: "Pay: TechMarkt reminder" }));
    const panel = await screen.findByRole("dialog", { name: "Pay: TechMarkt reminder" });
    await expectOnePressAtATime({ user, button: () => within(panel).getByRole("button", { name: "Mark as paid" }), held });
    await act(async () => held.release());
    await waitFor(() => expect(calls.filter((c) => c.method === "PATCH").map((c) => c.body)).toEqual([{ status: "done", seen_due_date: due }]));
  });
});
