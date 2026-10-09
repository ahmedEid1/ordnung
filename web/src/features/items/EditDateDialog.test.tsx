/**
 * "Edit your date" (audit item 26): a date of the person's own, changed later — what it says, how it repeats, and
 * which dates move — or removed (dismissed, with Undo; a paired phone may do that, unlike deleting it).
 */
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Item, Recurrence } from "@/api/types";
import { Toaster, __clearToasts, toast } from "@/components/ui/Toast";
import { makeItem } from "@/features/document/fixtures";
import { useMockApi } from "@/test/mockFetch";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { EditDateDialog, draftOf, patchFor } from "./AddDateDialog";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: /min-width/.test(query), media: query, addEventListener() {}, removeEventListener() {} }));
});
afterEach(() => {
  __clearToasts();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const MONTHLY: Recurrence = { interval: 1, unit: "months", working_day: null, day_of_month: null };
const THIRD_WORKING_DAY: Recurrence = { ...MONTHLY, working_day: 3 };

/** A date of the person's own, as the server keeps it: its schedule starts at `date_spec.date`. */
function own(i: Partial<Item> = {}): Item {
  return makeItem({
    id: "itm_own",
    kind: "reminder",
    title: "UStVA",
    origin: "manual",
    grounding: "user",
    due_date: "2026-10-10",
    due_date_source: "manual",
    recurrence: MONTHLY,
    date_spec: { type: "fixed", date: "2026-10-10", time: null, anchor: null, anchor_date: null, amount: null, unit: null, delivery_rule: "none", shift_rule: "auto", nature: "other", legal_basis: null, text: "" },
    evidence: [],
    ...i,
  });
}

describe("what Save sends: only what changed", () => {
  const item = own({ amount: 50 });
  const draft = draftOf(item);

  it("starts from the date as it is, and sends nothing when nothing changed", () => {
    expect(draft).toMatchObject({ title: "UStVA", date: "2026-10-10", amount: "50,00", repeat: "month", moves: "this" });
    expect(patchFor(draft, item)).toEqual({});
  });

  it("sends its words and amount as typed", () => {
    expect(patchFor({ ...draft, title: "  UStVA  October " }, item)).toEqual({ title: "UStVA October" });
    expect(patchFor({ ...draft, amount: "" }, item)).toEqual({ amount: null });
    expect(patchFor({ ...draft, amount: "60" }, item)).toEqual({ amount: 60 });
  });

  it("a new rule starts at the date shown; no rule stops it", () => {
    expect(patchFor({ ...draft, repeat: "quarter" }, item)).toEqual({ recurrence: { ...MONTHLY, interval: 3 } });
    expect(patchFor({ ...draft, repeat: "quarter", date: "2026-10-15" }, item)).toEqual({ due_date: "2026-10-15", recurrence: { ...MONTHLY, interval: 3 } });
    expect(patchFor({ ...draft, repeat: "working_day", workingDay: 3 }, item)).toEqual({ recurrence: THIRD_WORKING_DAY });
    expect(patchFor({ ...draft, repeat: "never" }, item)).toEqual({ recurrence: null });
  });

  it("a new date is only this one, unless every one after moves too", () => {
    expect(patchFor({ ...draft, date: "2026-10-15" }, item)).toEqual({ due_date: "2026-10-15" });
    expect(patchFor({ ...draft, date: "2026-10-15", moves: "after" }, item)).toEqual({ due_date: "2026-10-15", recurrence: MONTHLY });
    // a working day has no day to move: only this one
    const byWorkingDay = own({ recurrence: THIRD_WORKING_DAY, due_date: "2026-10-05" });
    expect(patchFor({ ...draftOf(byWorkingDay), date: "2026-10-07", moves: "after" }, byWorkingDay)).toEqual({ due_date: "2026-10-07" });
    // nor does one that doesn't repeat
    const once = own({ recurrence: null });
    expect(patchFor({ ...draftOf(once), date: "2026-10-07", moves: "after" }, once)).toEqual({ due_date: "2026-10-07" });
  });

  it("keeps a rule the dialog can't make as it is", () => {
    const fortnightly = own({ recurrence: { ...MONTHLY, interval: 2, unit: "weeks" } });
    const kept = draftOf(fortnightly);
    expect(kept.repeat).toBe("current");
    expect(patchFor(kept, fortnightly)).toEqual({});
    expect(patchFor({ ...kept, repeat: "month" }, fortnightly)).toEqual({ recurrence: MONTHLY });
  });
});

describe("Edit your date", () => {
  type Letter = { title: string | null; filename: string } | null;
  function Harness({ item, letter, onClose }: { item: Item; letter: Letter; onClose: () => void }) {
    const [open, setOpen] = useState(true);
    const close = () => {
      setOpen(false);
      onClose();
    };
    return (
      <>
        <EditDateDialog item={item} open={open} onClose={close} letter={letter} />
        <Toaster />
      </>
    );
  }

  function useEditDialog(item: Item, letter: Letter = null) {
    const { srv, calls } = useMockApi();
    srv.db.state.items.push(structuredClone(item));
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderWithProviders(<Harness item={item} letter={letter} onClose={onClose} />, { client: makeTestQueryClient() });
    return { srv, calls, user, onClose, patches: () => calls.filter((c) => c.method === "PATCH").map((c) => c.body) };
  }

  it("is filled in from the date, says whose it is, and asks nothing it can't change", async () => {
    useEditDialog(own({ amount: 50 }));
    const dialog = await screen.findByRole("dialog", { name: "Edit your date" });
    expect(dialog).toHaveAccessibleDescription("A date you added yourself.");
    expect(within(dialog).getByLabelText("What is it?")).toHaveValue("UStVA");
    // while it repeats, the date is the next one
    expect(within(dialog).getByLabelText("Next date")).toHaveValue("2026-10-10");
    expect(within(dialog).getByLabelText("Repeats")).toHaveValue("month");
    expect(within(dialog).getByRole("option", { name: "Every month on the 10th" })).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/^Amount/)).toHaveValue("50,00");
    // kind and letter can't change (the API's ItemPatch has neither)
    expect(within(dialog).queryByRole("radio", { name: "Reminder" })).toBeNull();
    expect(within(dialog).queryByLabelText(/^Letter/)).toBeNull();
    expect(within(dialog).queryByRole("group", { name: "Which dates move?" })).toBeNull();
    expect(within(dialog).getByRole("button", { name: "Remove" })).toBeInTheDocument();
  });

  it("names its letter when it has one", async () => {
    useEditDialog(own({ doc_id: "doc_folder_scan" }), { title: null, filename: "Stadtwerke.pdf" });
    expect(await screen.findByRole("dialog", { name: "Edit your date" })).toHaveAccessibleDescription("For “Stadtwerke.pdf”.");
  });

  it("asks which dates move once the date changes — only this one unless chosen — and saves the answer", async () => {
    const success = vi.spyOn(toast, "success");
    const { user, patches, onClose } = useEditDialog(own());
    const dialog = await screen.findByRole("dialog", { name: "Edit your date" });
    fireEvent.change(within(dialog).getByLabelText("Next date"), { target: { value: "2026-10-15" } });
    const moves = within(dialog).getByRole("group", { name: "Which dates move?" });
    expect(within(moves).getByRole("radio", { name: "Only this one (Thu 15 Oct)" })).toBeChecked();
    await user.click(within(moves).getByRole("radio", { name: "This one and every one after (every month on the 15th)" }));
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patches()).toEqual([{ due_date: "2026-10-15", recurrence: MONTHLY }]));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(success).toHaveBeenCalledWith("Date saved", expect.objectContaining({ description: "UStVA — Thu 15 Oct, repeats every month" }));
  });

  it("doesn't ask for a date that repeats on a working day, nor once Repeats changed", async () => {
    const { user } = useEditDialog(own({ recurrence: THIRD_WORKING_DAY, due_date: "2026-10-05", date_spec: null }));
    const dialog = await screen.findByRole("dialog", { name: "Edit your date" });
    expect(within(dialog).getByLabelText("Which working day?")).toHaveValue("3");
    fireEvent.change(within(dialog).getByLabelText("Next date"), { target: { value: "2026-10-07" } });
    expect(within(dialog).queryByRole("group", { name: "Which dates move?" })).toBeNull();
    await user.selectOptions(within(dialog).getByLabelText("Repeats"), "month");
    expect(within(dialog).queryByRole("group", { name: "Which dates move?" })).toBeNull();
  });

  it("is removed from your dates with Remove, and Undo brings it back", async () => {
    const { user, patches, onClose, srv } = useEditDialog(own());
    const dialog = await screen.findByRole("dialog", { name: "Edit your date" });
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(patches()).toEqual([{ status: "dismissed" }]));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const shown = (await screen.findByText("Removed from your dates")).closest<HTMLElement>("li[data-toast]")!;
    expect(shown).toHaveTextContent("“UStVA” won't remind you any more.");
    await user.click(within(shown).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(patches()).toEqual([{ status: "dismissed" }, { status: "open" }]));
    expect(srv.db.state.items.find((i) => i.id === "itm_own")).toMatchObject({ status: "open", due_date: "2026-10-10" });
  });

  it("brings a date that was done back as done with Undo, not as an open to-do", async () => {
    const { user, patches, srv } = useEditDialog(own({ recurrence: null, date_spec: null, status: "done", completed_at: "2026-09-20T10:00:00Z" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit your date" });
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    const shown = (await screen.findByText("Removed from your dates")).closest<HTMLElement>("li[data-toast]")!;
    await user.click(within(shown).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(patches()).toEqual([{ status: "dismissed" }, { status: "done" }]));
    expect(srv.db.state.items.find((i) => i.id === "itm_own")).toMatchObject({ status: "done" });
  });

  it("brings a snoozed date back snoozed to its day with Undo", async () => {
    const { user, patches } = useEditDialog(own({ status: "snoozed", snoozed_until: "2026-10-03" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit your date" });
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    const shown = (await screen.findByText("Removed from your dates")).closest<HTMLElement>("li[data-toast]")!;
    await user.click(within(shown).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(patches()).toEqual([{ status: "dismissed" }, { status: "snoozed", snoozed_until: "2026-10-03" }]));
  });

  it("closes without a call when nothing changed", async () => {
    const { user, calls, onClose } = useEditDialog(own());
    const dialog = await screen.findByRole("dialog", { name: "Edit your date" });
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
  });
});
