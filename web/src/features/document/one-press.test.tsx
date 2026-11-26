/**
 * A to-do's buttons on the letter page take one press at a time: two presses before the button is drawn busy (a
 * double click, Enter twice) send one request, and a failed one takes the next press. "Done" on a repeating to-do
 * names the date it was for, so the server moves it on once however often the same press reaches it.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { qk } from "@/api/hooks";
import type { Item } from "@/api/types";
import { Toaster } from "@/components/ui/Toast";
import { expectOnePressAtATime } from "@/test/busyButton";
import { holdRequests, useMockApi } from "@/test/mockFetch";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { ItemsList } from "./ItemsList";
import { VerdictCard } from "./VerdictCard";
import { DocumentWarnings } from "./Warnings";
import { selectPrimaryItem } from "./verdict";
import { makeDetail, makeDoc, makeItem } from "./fixtures";

const MONTHLY = { interval: 1, unit: "months" as const, working_day: null, day_of_month: null };

function client() {
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.rules, []);
  return qc;
}

const patchOf = (id: string) => (call: { method: string; path: string }) => call.method === "PATCH" && call.path === `/items/${id}`;

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("a to-do's tick", () => {
  it("takes one press at a time, and the next once its change failed", async () => {
    useMockApi();
    const held = holdRequests(patchOf("itm_form"));
    renderWithProviders(<ItemsList items={[makeItem({ id: "itm_form", title: "Send the form" })]} docId="doc_1" />, { client: client() });
    await expectOnePressAtATime({ user: userEvent.setup(), button: () => screen.getByRole("button", { name: "Mark “Send the form” as done" }), held });
  });

  it("names the date a repeating to-do was done for, and its Undo the date it moved to", async () => {
    const ticket = makeItem({ id: "itm_ticket", kind: "payment", title: "Monthly ticket", due_date: "2026-10-01", recurrence: MONTHLY });
    const bodies: unknown[] = [];
    vi.stubGlobal("fetch", async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = init?.method === "PATCH" ? (JSON.parse(String(init.body)) as { status: string }) : null;
      if (body) bodies.push(body);
      const moved = body?.status === "done" ? { ...ticket, due_date: "2026-11-01" } : ticket;
      return new Response(JSON.stringify(body ? moved : {}), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    renderWithProviders(
      <>
        <ItemsList items={[ticket]} docId="doc_1" />
        <Toaster />
      </>,
      { client: client() },
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Mark “Monthly ticket” as done" }));
    const toast = (await screen.findByText("Marked as done")).closest<HTMLElement>("[data-toast]")!;
    await user.click(within(toast).getByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(bodies).toEqual([
        { status: "done", seen_due_date: "2026-10-01" },
        { status: "open", seen_due_date: "2026-11-01" },
      ]),
    );
  });
});

describe("the to-do's menu", () => {
  for (const name of ["Mark done", "Not a real to-do"]) {
    it(`sends “${name}” once for two presses in one go`, async () => {
      useMockApi();
      const held = holdRequests(patchOf("itm_form"));
      renderWithProviders(<ItemsList items={[makeItem({ id: "itm_form", title: "Send the form" })]} docId="doc_1" />, { client: client() });
      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: "More actions for Send the form" }));
      const entry = await screen.findByRole("menuitem", { name });
      act(() => {
        entry.click();
        entry.click();
      });
      await waitFor(() => expect(held.count).toBe(1));
      await act(async () => {});
      expect(held.count).toBe(1);
      await act(async () => held.fail());
    });
  }
});

describe("“Mark done” in the verdict card", () => {
  it("in the band takes one press at a time, and the next once its change failed", async () => {
    useMockApi();
    const held = holdRequests(patchOf("itm_form"));
    const form = makeItem({ id: "itm_form", kind: "deadline", title: "Send the form back", action: "Send the signed form back.", due_date: "2026-10-19" });
    const detail = makeDetail({ items: [form] });
    renderWithProviders(<VerdictCard detail={detail} primary={selectPrimaryItem(detail.items, detail.set_aside)} />, { client: client() });
    await expectOnePressAtATime({ user: userEvent.setup(), button: () => screen.getAllByRole("button", { name: /^Mark done/ })[0]!, held });
  });

  it("in a “Still open?” row takes one press at a time, and the next once its change failed", async () => {
    useMockApi();
    const held = holdRequests(patchOf("dep"));
    const deposit = makeItem({ id: "dep", kind: "payment", title: "Security deposit (Kaution)", amount: 1560, direction: "out", due_date: "2025-10-01" });
    const detail = makeDetail({ items: [deposit], set_aside: [{ item_id: "dep", reason: "history", replaced_by: null }] });
    renderWithProviders(<VerdictCard detail={detail} primary={selectPrimaryItem(detail.items, detail.set_aside)} />, { client: client() });
    await expectOnePressAtATime({ user: userEvent.setup(), button: () => screen.getByRole("button", { name: "Mark done: “Security deposit (Kaution)”" }), held });
  });

  it("“Mark as paid” in the Pay panel sends one request for two presses in one go", async () => {
    useMockApi();
    const held = holdRequests(patchOf("itm_fee"));
    const fee = makeItem({ id: "itm_fee", kind: "payment", title: "Broadcasting fee", amount: 55.08, direction: "out", due_date: "2026-11-15", recurrence: { ...MONTHLY, interval: 3 } });
    const detail = makeDetail({ items: [fee] });
    renderWithProviders(<VerdictCard detail={detail} primary={selectPrimaryItem(detail.items, detail.set_aside)} />, { client: client() });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Pay/ }));
    const paid = within(await screen.findByRole("dialog", { name: /Pay/ })).getByRole("button", { name: "Mark as paid" });
    act(() => {
      paid.click();
      paid.click();
    });
    await waitFor(() => expect(held.count).toBe(1));
    await act(async () => {});
    expect(held.count).toBe(1);
    await act(async () => held.fail());
  });
});

describe("a “Please check” card", () => {
  const unconfirmed = (): Item =>
    makeItem({
      id: "itm_fine",
      title: "Pay the fine",
      due_date: "2026-10-20",
      evidence: [{ doc_id: "doc_1", page: 1, quote: "Zahlbar bis 20.10.2026", grounding: "verified", value_consistent: false, score: 90, boxes: [] }],
    });
  for (const [name, method] of [
    ["Correct", "POST"],
    ["Not a real to-do", "PATCH"],
  ] as const) {
    it(`takes one press at a time on “${name}”, and the next once it failed`, async () => {
      useMockApi();
      const held = holdRequests((call) => call.method === method && call.path.startsWith("/items/itm_fine"));
      renderWithProviders(<DocumentWarnings detail={makeDetail({ document: makeDoc({ status: "needs_review" }), items: [unconfirmed()] })} />, { client: client() });
      await expectOnePressAtATime({ user: userEvent.setup(), button: () => screen.getByRole("button", { name }), held });
    });
  }
});
