/**
 * "Add a date" and "Edit your date" take one press at a time: two presses before the dialog is drawn busy added two
 * dates (and the Undo removed one), and a failed one takes the next press.
 */
import { afterEach, describe, it, vi } from "vitest";
import { act, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { __clearToasts } from "@/components/ui/Toast";
import { makeItem } from "@/features/document/fixtures";
import { expectOnePressAtATime } from "@/test/busyButton";
import { holdRequests, useMockApi } from "@/test/mockFetch";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { AddDateDialog, EditDateDialog } from "./AddDateDialog";

afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

const mine = makeItem({ id: "itm_own", kind: "reminder", title: "UStVA", origin: "manual", grounding: "user", due_date: "2026-10-10", due_date_source: "manual" });

describe("a date of your own", () => {
  it("“Add date” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "POST" && call.path === "/items");
    renderWithProviders(<AddDateDialog open onClose={() => {}} />, { client: makeTestQueryClient() });
    const dialog = await screen.findByRole("dialog", { name: "Add a date" });
    const user = userEvent.setup();
    await user.type(within(dialog).getByLabelText("What is it?"), "Renew the residence permit");
    fireEvent.change(within(dialog).getByLabelText("When?"), { target: { value: "2026-10-20" } });
    await expectOnePressAtATime({ user, button: () => within(dialog).getByRole("button", { name: "Add date" }), held });
  });

  it("“Save” in “Edit your date” takes one press at a time, and the next once it failed", async () => {
    const { srv } = useMockApi();
    srv.db.state.items.push(structuredClone(mine));
    const held = holdRequests((call) => call.method === "PATCH" && call.path === "/items/itm_own");
    renderWithProviders(<EditDateDialog item={mine} open onClose={() => {}} letter={null} />, { client: makeTestQueryClient() });
    const dialog = await screen.findByRole("dialog", { name: "Edit your date" });
    const user = userEvent.setup();
    await user.type(within(dialog).getByLabelText("What is it?"), " Q3");
    await expectOnePressAtATime({ user, button: () => within(dialog).getByRole("button", { name: "Save" }), held });
  });

  it("“Remove” in “Edit your date” takes one press at a time, and the next once it failed", async () => {
    const { srv } = useMockApi();
    srv.db.state.items.push(structuredClone(mine));
    const held = holdRequests((call) => call.method === "PATCH" && call.path === "/items/itm_own");
    renderWithProviders(<EditDateDialog item={mine} open onClose={() => {}} letter={null} />, { client: makeTestQueryClient() });
    const dialog = await screen.findByRole("dialog", { name: "Edit your date" });
    await expectOnePressAtATime({ user: userEvent.setup(), button: () => within(dialog).getByRole("button", { name: "Remove" }), held });
  });
});
