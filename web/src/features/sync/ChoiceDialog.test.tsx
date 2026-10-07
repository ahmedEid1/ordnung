/**
 * "Which Ordnung do you want to keep?" (design §12.2): one radio per side with its letters and newest titles, none
 * chosen at first; keeping one makes this computer the one in use and says where the other side's copy is (finding
 * 28: on that computer, once it next starts); a side still arriving can be chosen and is waited for, with Cancel;
 * a refusal shows in place, focused.
 */
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@/api/client";
import { api } from "@/api/endpoints";
import { useSync } from "@/api/hooks";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { ChoiceDialog } from "./ChoiceDialog";

beforeEach(() => vi.stubGlobal("scrollTo", () => {}));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  act(() => __clearToasts());
});

const WAIT = { timeout: 5000 };

/** The dialog as the app shows it: open, fed by the live status. */
function Harness() {
  const { data } = useSync();
  const [open, setOpen] = useState(true);
  if (!data) return null;
  return (
    <>
      <p>{open ? "open" : "closed"}</p>
      <ChoiceDialog open={open} onClose={() => setOpen(false)} status={data} />
      <Toaster />
    </>
  );
}

async function openDialog() {
  renderWithProviders(<Harness />);
  return screen.findByRole("dialog", { name: "Which Ordnung do you want to keep?" }, WAIT);
}

describe("the choice dialog", () => {
  it("shows each side's letters and newest titles, with nothing chosen yet", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().bothChanged();
    const dialog = await openDialog();
    expect(dialog).toHaveAccessibleDescription(
      "Since you last switched, Ordnung was changed on this computer (sam-laptop) and sam-desktop, and the two can't be combined. Choose one. The other is saved as an encrypted backup on its own computer, so nothing is thrown away.",
    );
    const radios = within(dialog).getAllByRole("radio");
    expect(radios).toHaveLength(2);
    for (const r of radios) expect(r).not.toBeChecked();
    const mine = within(dialog).getByRole("radio", { name: /This computer \(sam-laptop\)/ });
    expect(mine).toHaveAccessibleName(/342 letters, 2 added since you last switched: Stadtwerke Abschlag 2027, Allianz Beitragsanpassung/);
    expect(within(dialog).getByRole("radio", { name: /sam-desktop/ })).toHaveAccessibleName(/341 letters, 1 added since you last switched: Vodafone Rechnung Oktober/);
    expect(within(dialog).getByRole("button", { name: "Keep this one" })).toBeDisabled();
    expect(within(dialog).getByText("Choosing makes this computer the one in use.")).toBeInTheDocument();
    // focus starts in the dialog, on nothing that answers for the person
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    expect(document.activeElement).not.toBe(within(dialog).getByRole("button", { name: "Keep this one" }));
  });

  it("tells the sides apart by their dates and to-dos, latest changes and when each was saved — not only letters", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().bothChanged();
    const dialog = await openDialog();
    const mine = within(dialog).getByRole("radio", { name: /This computer \(sam-laptop\)/ });
    expect(mine).toHaveAccessibleName(/24 open dates and to-dos · 40 done · 3 notes/);
    expect(mine).toHaveAccessibleName(/Latest: to-do “Pay the Stadtwerke instalment” \(7 Oct\), letter “Stadtwerke Abschlag 2027” \(6 Oct\)/);
    const theirs = within(dialog).getByRole("radio", { name: /sam-desktop/ });
    expect(theirs).toHaveAccessibleName(/23 open dates and to-dos · 41 done · 3 notes/);
    expect(theirs).toHaveAccessibleName(/Latest: date “Vodafone payment” \(6 Oct\)/);
    expect(theirs).toHaveAccessibleName(/Saved there .*, arrived here/);
  });

  it("Not now closes it, and nothing is chosen", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().bothChanged();
    const user = userEvent.setup();
    const dialog = await openDialog();
    await user.click(within(dialog).getByRole("button", { name: "Not now" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(srv.sync.choice).not.toBeNull();
  });

  it("keeping this computer's says the other's copy is made there, once it next starts (finding 28)", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().bothChanged();
    const user = userEvent.setup();
    const dialog = await openDialog();
    await user.click(within(dialog).getByRole("radio", { name: /This computer/ }));
    await user.click(within(dialog).getByRole("button", { name: "Keep this one" }));
    expect(await screen.findByText("Kept this computer's Ordnung", {}, WAIT)).toBeInTheDocument();
    expect(screen.getByText("sam-desktop's version stays on that computer as a kept copy once it next starts. Nothing is thrown away.")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(srv.sync.choice).toBeNull();
    expect(srv.db.state.activity.find((a) => a.kind === "sync.chosen")?.message).toMatch(/sam-desktop's version stays on that computer as a kept copy once it next starts/);
  });

  it("keeping the other's: this computer's data is kept as a copy first", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().bothChanged();
    const user = userEvent.setup();
    const dialog = await openDialog();
    await user.click(within(dialog).getByRole("radio", { name: /sam-desktop/ }));
    await user.click(within(dialog).getByRole("button", { name: "Keep this one" }));
    expect(await screen.findByText("Kept sam-desktop's Ordnung", {}, WAIT)).toBeInTheDocument();
    expect(screen.getByText("This computer's is saved as a backup (Settings → Your computers).")).toBeInTheDocument();
    expect(srv.sync.kept).toHaveLength(1);
  });

  it("a side still arriving can be chosen: the dialog waits for it, with Cancel", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().bothChanged({ arriving: true });
    const user = userEvent.setup();
    const dialog = await openDialog();
    const other = within(dialog).getByRole("radio", { name: /sam-desktop/ });
    expect(other).toHaveAccessibleName(/Still arriving: 5 of 9 files/);
    await user.click(other);
    await user.click(within(dialog).getByRole("button", { name: "Keep this one" }));
    expect(await within(dialog).findByText("Waiting for sam-desktop's Ordnung", {}, WAIT)).toBeInTheDocument();
    expect(within(dialog).getByText(/It stops waiting after 30 minutes/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(await within(dialog).findByRole("radio", { name: /sam-desktop/ }, WAIT)).toBeInTheDocument();
    expect(srv.sync.choice?.chosen).toBeNull();
  });

  it("shows a refusal in place, focused", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().bothChanged();
    vi.spyOn(api, "chooseSync").mockRejectedValue(new ApiError(507, "This computer needs 1.4 GB free to keep its copy first.", null, "no_space"));
    const user = userEvent.setup();
    const dialog = await openDialog();
    await user.click(within(dialog).getByRole("radio", { name: /sam-desktop/ }));
    await user.click(within(dialog).getByRole("button", { name: "Keep this one" }));
    const refusal = await within(dialog).findByText("This computer needs 1.4 GB free to keep its copy first.", {}, WAIT);
    await waitFor(() => expect(refusal.closest("[tabindex]")).toHaveFocus());
    expect(within(dialog).getByText("Nothing was changed")).toBeInTheDocument();
  });
});
