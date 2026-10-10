/**
 * The new-address letter ("Share a new address") and the moving checklist: after a move the person told, the
 * letter starts with the address before and the day they moved in (both still theirs to change), and a note says
 * where the rest of the list is; without a move, the note says how to start one — in Settings on the computer.
 * The letter never changes the profile.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, within } from "@testing-library/react";
import { __clearToasts } from "@/components/ui/Toast";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import LettersPage from "@/pages/LettersPage";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

const OLD = "Beispielweg 5\n12345 Musterstadt";
const NEW = "Neue Allee 7\n54321 Beispielstadt";

async function openLetter() {
  renderWithProviders(<LettersPage />, { route: "/letters?kind=address_change&to=pty_funknetz" });
  return screen.findByRole("dialog", { name: "New letter" });
}

describe("the new-address letter after a move", () => {
  it("starts with the address before and the day moved in, and points to the checklist on Today", async () => {
    const { srv } = useMockApi();
    srv.db.state.profile = { ...srv.db.state.profile, address: NEW, moved_on: "2026-09-21", old_address: OLD };
    const dialog = await openLetter();
    expect(await within(dialog).findByLabelText(/^Your new address/)).toHaveValue(NEW);
    expect(within(dialog).getByLabelText(/^Your previous address/)).toHaveValue(OLD);
    expect(within(dialog).getByLabelText(/^Moved on/)).toHaveValue("2026-09-21");
    expect(within(dialog).getByText("Your moving checklist on Today lists who else needs your new address.")).toBeInTheDocument();
    expect(within(dialog).queryByText(/tick I moved/)).not.toBeInTheDocument();
  });

  it("without a move, says how to start the checklist, in a Settings tab that keeps the letter", async () => {
    useMockApi();
    const dialog = await openLetter();
    expect(await within(dialog).findByLabelText(/^Your previous address/)).toHaveValue("");
    expect(within(dialog).getByLabelText(/^Moved on/)).toHaveValue("");
    const note = within(dialog).getByText(/Telling several places\?/);
    expect(note).toHaveTextContent(
      "Telling several places? Change your address in Settings → Profile (opens in a new tab, so this letter stays as it is)⁠ and tick I moved: Today then lists everyone who needs it, starting with the Bürgeramt.",
    );
    expect(within(note).getByRole("link", { name: /Settings → Profile/ })).toHaveAttribute("target", "_blank");
  });

  it("on a phone, says the move is told on the computer, with no link to Settings", async () => {
    useMockApi({ client: "phone" });
    const dialog = await openLetter();
    const note = await within(dialog).findByText(/Telling several places\?/);
    expect(note).toHaveTextContent(
      "Telling several places? Change your address in Settings → Profile on your computer and tick I moved: Today then lists everyone who needs it, starting with the Bürgeramt.",
    );
    expect(within(note).queryByRole("link")).not.toBeInTheDocument();
  });

  it("a move more than six months ago still fills in the letter, and the note says how to start a new one", async () => {
    const { srv } = useMockApi();
    srv.db.state.profile = { ...srv.db.state.profile, moved_on: "2026-01-02", old_address: OLD };
    const dialog = await openLetter();
    expect(await within(dialog).findByLabelText(/^Your previous address/)).toHaveValue(OLD);
    expect(within(dialog).getByText(/Telling several places\?/)).toBeInTheDocument();
  });
});
