import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useMockApi } from "@/test/mockFetch";
import { renderWithProviders } from "@/test/render";
import { SecretaryNote } from "./SecretaryNote";

afterEach(() => vi.unstubAllGlobals());

describe("Your secretary's note", () => {
  it("is not read out as it changes, and “Write a new note” says once that it was written, keeping focus", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<SecretaryNote fallback="Nothing is due this week." />);
    const note = await screen.findByRole("region", { name: "Your secretary's note" });
    // marking a payment paid rewrites the note: as a live region it read out the changed words alone, mid-sentence
    await waitFor(() => expect(note.querySelector(".display")).not.toBeNull());
    expect(note.querySelector("[aria-live]")).toBeNull();
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("");
    const write = screen.getByRole("button", { name: "Write a new note" });
    write.focus();
    await user.keyboard("{Enter}");
    expect(write).toHaveFocus();
    await waitFor(() => expect(status).toHaveTextContent("New note written"));
    expect(write).toHaveFocus();
  });
});
