/**
 * The batch recap ("I read 3 letters"): what it found is said when it is ready, as one sentence — the dialog takes
 * focus while it still puts the findings together, and a description that changes afterwards is not read out.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import { useMockApi } from "@/test/mockFetch";
import { renderWithProviders } from "@/test/render";
import { BatchRecapDialog } from "./BatchRecap";

afterEach(() => vi.unstubAllGlobals());

describe("the batch recap", () => {
  it("says its findings once they are ready, and has no other live region", async () => {
    useMockApi();
    renderWithProviders(<BatchRecapDialog docIds={["doc_scam", "doc_parking", "doc_library"]} onClose={() => {}} />);
    const dialog = screen.getByRole("dialog");
    const status = within(dialog).getByRole("status");
    // still putting it together (the letters are on their way): nothing said yet, so the findings are said when they come
    expect(status.textContent).toBe("");
    await waitFor(() => expect(status).toHaveTextContent(/^Here's what I found: .+\.$/));
    // the tiles are not a live region of their own (a stray "1possible scam — don't pay" was all that was said)
    expect(dialog.querySelectorAll("[aria-live]")).toHaveLength(0);
  });
});
