/**
 * A "Please check" card leaves once it is answered — "Correct", a date of the person's own, "Not a real to-do"
 * (UX audit U4): focus goes to the card now in its place, or to the to-dos' heading when none is left, never to
 * <body>.
 */
import { useEffect, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { qk } from "@/api/hooks";
import type { DocumentDetail, Item } from "@/api/types";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { DocumentWarnings } from "./Warnings";
import { makeDetail, makeDoc, makeItem } from "./fixtures";

const unconfirmed = (id: string, title: string): Item =>
  makeItem({
    id,
    title,
    due_date: "2026-10-20",
    evidence: [{ doc_id: "doc_1", page: 1, quote: "Zahlbar bis 20.10.2026", grounding: "verified", value_consistent: false, score: 90, boxes: [] }],
  });

let saved: string[] = [];
let answered: (id: string) => void = () => {};

beforeEach(() => {
  saved = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method && init.method !== "GET") saved.push(`${init.method} ${new URL(String(input), "http://localhost").pathname}`);
    return new Response(JSON.stringify({}), { status: 200, headers: { "Content-Type": "application/json" } });
  });
});
afterEach(() => vi.unstubAllGlobals());

/** The letter's warnings, then its to-dos; an answered to-do no longer needs checking once saved (`answered`). */
function Letter({ items }: { items: Item[] }) {
  const [detail, setDetail] = useState<DocumentDetail>(() => makeDetail({ document: makeDoc({ status: "needs_review" }), items }));
  useEffect(() => {
    answered = (id) => setDetail((d) => ({ ...d, items: d.items.map((i) => (i.id === id ? { ...i, grounding: "user" } : i)) }));
  }, []);
  return (
    <>
      <DocumentWarnings detail={detail} />
      <section aria-labelledby="todos-title">
        <h2 id="todos-title">To-dos & dates</h2>
      </section>
    </>
  );
}

function render(items: Item[]) {
  const client = makeTestQueryClient();
  client.setQueryData(qk.rules, []);
  renderWithProviders(<Letter items={items} />, { client });
}

/** The "Please check" card of the to-do `title`. */
const card = (title: string) => screen.getByText(title).closest<HTMLElement>(".rounded-2xl")!;

describe("a 'Please check' card that was answered", () => {
  it("hands focus to the card now in its place after “Correct”", async () => {
    render([unconfirmed("itm_fine", "Pay the fine"), unconfirmed("itm_form", "Send the form")]);
    const user = userEvent.setup();
    within(card("Pay the fine")).getByRole("button", { name: "Correct" }).focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(saved).toEqual(["POST /api/items/itm_fine/confirm"]));
    act(() => answered("itm_fine"));
    await waitFor(() => expect(within(card("Send the form")).getByRole("heading", { name: "Please check" })).toHaveFocus());
  });

  it("hands focus to the to-dos' heading when it was the last one (“Not a real to-do”)", async () => {
    render([unconfirmed("itm_fine", "Pay the fine")]);
    const user = userEvent.setup();
    within(card("Pay the fine")).getByRole("button", { name: "Not a real to-do" }).focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(saved).toEqual(["PATCH /api/items/itm_fine"]));
    act(() => answered("itm_fine"));
    expect(screen.queryByRole("region", { name: "Warnings and things to check" })).toBeNull();
    await waitFor(() => expect(screen.getByRole("heading", { name: "To-dos & dates" })).toHaveFocus());
  });

  it("hands focus on after a date of the person's own is saved", async () => {
    render([unconfirmed("itm_fine", "Pay the fine")]);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Change date" }));
    await user.clear(screen.getByLabelText("New date for Pay the fine"));
    await user.type(screen.getByLabelText("New date for Pay the fine"), "2026-10-22{Enter}");
    await waitFor(() => expect(saved).toEqual(["PATCH /api/items/itm_fine"]));
    act(() => answered("itm_fine"));
    await waitFor(() => expect(screen.getByRole("heading", { name: "To-dos & dates" })).toHaveFocus());
  });

  it("keeps focus on its button while it stays (the answer wasn't saved)", async () => {
    render([unconfirmed("itm_fine", "Pay the fine")]);
    const user = userEvent.setup();
    const correct = screen.getByRole("button", { name: "Correct" });
    correct.focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(saved).toHaveLength(1));
    expect(correct).toHaveFocus();
  });
});
