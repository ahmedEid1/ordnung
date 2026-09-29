/**
 * The online demo keeps no files (audit round 1, bucket "shell-b"): "Add letters" and a drop
 * explain that straight away — no file picker, no confirmation, then a refusal toast.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/render";
import { AddLettersProvider, useAddLetters } from "./AddLetters";
import { DropZone } from "./DropZone";

vi.mock("@/mocks/mode", () => ({ isStaticDemo: () => true }));

let fetchSpy: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchSpy = vi.fn(async () => new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetchSpy);
});
afterEach(() => vi.unstubAllGlobals());

function Buttons() {
  const { openPicker } = useAddLetters();
  return (
    <button type="button" onClick={openPicker}>
      Add letters
    </button>
  );
}

function renderDemo() {
  const utils = renderWithProviders(
    <AddLettersProvider>
      <Buttons />
      <DropZone />
    </AddLettersProvider>,
  );
  return { ...utils, user: userEvent.setup() };
}

describe("online demo: adding letters", () => {
  it("'Add letters' explains at once instead of opening the file picker", async () => {
    const pick = vi.spyOn(HTMLInputElement.prototype, "click");
    const { user } = renderDemo();
    await user.click(screen.getByRole("button", { name: "Add letters" }));
    const dialog = await screen.findByRole("dialog", { name: "Install Ordnung to add your own letters" });
    expect(pick).not.toHaveBeenCalled();
    expect(dialog).toHaveAccessibleDescription(/can't read or keep your files/);
    expect(within(dialog).getByRole("link", { name: "Open New mail" })).toHaveAttribute("href", "/inbox");
    await user.click(within(dialog).getByRole("button", { name: "Not now" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(fetchSpy).not.toHaveBeenCalled();
    pick.mockRestore();
  });

  it("a drop explains too, and nothing is uploaded", async () => {
    renderDemo();
    const drop = new Event("drop", { bubbles: true }) as DragEvent;
    Object.defineProperty(drop, "dataTransfer", { value: { types: ["Files"], files: [new File(["%PDF"], "brief.pdf", { type: "application/pdf" })] } });
    act(() => {
      fireEvent(window, drop);
    });
    expect(await screen.findByRole("dialog", { name: "Install Ordnung to add your own letters" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: /Add this letter/ })).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
