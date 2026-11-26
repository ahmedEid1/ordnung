/**
 * A contact's call notes take one press at a time: two presses before the button is drawn busy noted the call twice
 * (its promise twice on Waiting for), deleted it twice or flipped "They kept it" back; a failed one takes the next
 * press.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { expectOnePressAtATime } from "@/test/busyButton";
import { holdRequests, useMockApi } from "@/test/mockFetch";
import { renderWithProviders } from "@/test/render";
import { PartyDrawer } from "./PartyDrawer";
import { __clearCallDrafts } from "./calls";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
  __clearCallDrafts();
});

async function calls() {
  renderWithProviders(
    <>
      <PartyDrawer />
      <Toaster />
    </>,
    { route: "/?party=pty_fitwell" },
  );
  return screen.findByRole("region", { name: /^Calls/ });
}

describe("call notes", () => {
  it("“Save note” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "POST" && call.path === "/calls");
    const section = await calls();
    const user = userEvent.setup();
    await user.click(within(section).getByRole("button", { name: "Note a call" }));
    const form = within(section).getByRole("form", { name: "Note a call" });
    await user.type(within(form).getByLabelText("What was said"), "They will refund the September fee.");
    await expectOnePressAtATime({ user, button: () => within(form).getByRole("button", { name: "Save note" }), held });
  });

  it("“Delete” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "DELETE" && call.path === "/calls/cal_fitwell");
    const section = await calls();
    const user = userEvent.setup();
    await user.click(await within(section).findByRole("button", { name: "Delete the note of the call on Wed 23 Sep" }));
    const confirm = within(section).getByRole("group", { name: "Delete this note?" });
    await waitFor(() => expect(within(confirm).getByRole("button", { name: "Delete" })).toHaveFocus());
    await expectOnePressAtATime({ user, button: () => within(confirm).getByRole("button", { name: "Delete" }), held });
  });

  it("“They kept it” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "PATCH" && call.path === "/calls/cal_fitwell");
    const section = await calls();
    await within(section).findByRole("button", { name: "They kept it" });
    await expectOnePressAtATime({ user: userEvent.setup(), button: () => within(section).getByRole("button", { name: "They kept it" }), held });
  });
});
