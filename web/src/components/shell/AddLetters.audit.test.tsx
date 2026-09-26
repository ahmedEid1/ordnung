/**
 * Audit (regression): "Keep private — no AI" (docs/privacy.md: "upload a document without ever sending
 * it to Claude") used to be offered only in the "Are these pages of one letter?" dialog, which appears
 * for two or more photos. A single PDF or photo — the usual case — was uploaded at once with
 * `private=false` and sent to Claude; the web app had no way to keep it private.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/render";
import { AddLettersProvider, useAddLetters } from "./AddLetters";

let fetchSpy: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchSpy = vi.fn(async () =>
    new Response(JSON.stringify({ documents: [], jobs: [], duplicates: [], errors: [] }), {
      status: 201,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchSpy);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

function AddOnePdf() {
  const { addFiles } = useAddLetters();
  const pdf = new File(["%PDF-1.7 passport"], "reisepass.pdf", { type: "application/pdf" });
  return (
    <button type="button" onClick={() => addFiles([pdf])}>
      Add my passport
    </button>
  );
}

describe("Keep private — no AI (audit)", () => {
  it("is offered before a single PDF is sent to Claude", async () => {
    renderWithProviders(
      <AddLettersProvider>
        <AddOnePdf />
      </AddLettersProvider>,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Add my passport" }));

    expect(await screen.findByText("Keep private — no AI", {}, { timeout: 500 })).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it.each([
    [true, "Store privately", "true"],
    [false, "Add letter", "false"],
  ])("sends the person's choice (private: %s)", async (keepPrivate, button, sent) => {
    renderWithProviders(
      <AddLettersProvider>
        <AddOnePdf />
      </AddLettersProvider>,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Add my passport" }));
    if (keepPrivate) await user.click(await screen.findByRole("switch", { name: /Keep private/ }));
    await user.click(await screen.findByRole("button", { name: button }));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    const [, init] = fetchSpy.mock.calls[0]! as [string, RequestInit];
    const form = init.body as FormData;
    expect(form.get("private")).toBe(sent);
    expect((form.get("files") as File).name).toBe("reisepass.pdf");
  });

  it("uploads nothing when cancelled", async () => {
    renderWithProviders(
      <AddLettersProvider>
        <AddOnePdf />
      </AddLettersProvider>,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Add my passport" }));
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
