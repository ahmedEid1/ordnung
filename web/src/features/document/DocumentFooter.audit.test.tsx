/**
 * Audit (regression): "Delete this letter?" promises that the file, its page images and everything read
 * from it are removed from this computer (and docs/privacy.md: "Delete means delete"). The button used to
 * only move the letter to the trash (`DELETE /api/documents/{id}` without `purge`), and nothing in the
 * app lists or empties the trash, so the original and its derived data stayed on disk for good.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/render";
import { DocumentFooter, scanTextNote } from "./DocumentFooter";
import { makeDetail, makeDoc } from "./fixtures";

let fetchSpy: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchSpy = vi.fn(async () =>
    new Response(JSON.stringify({ id: "doc_1", purged: false, removed_open_items: 0 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchSpy);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Deleting a letter (audit)", () => {
  it("removes it from this computer as the dialog promises (purge, not just the trash)", async () => {
    renderWithProviders(<DocumentFooter detail={makeDetail({ document: makeDoc({ title: "Tax assessment" }) })} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByText(/removed from this computer/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete letter" }));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const [url, init] = fetchSpy.mock.calls[0]! as [string, RequestInit];
    expect(init.method?.toUpperCase()).toBe("DELETE");
    expect(url).toBe("/api/documents/doc_1?purge=true");
  });
});

describe("Where the letter went (FEAT G4)", () => {
  it("says a letter no model call carried was not sent to Claude (Claude not installed, or it waits)", () => {
    const doc = makeDoc({ status: "queued", ai_processed_at: null });
    renderWithProviders(<DocumentFooter detail={makeDetail({ document: doc, given_to_model: false })} />);
    expect(screen.getByText("Not sent to Claude. The letter hasn't left your computer.")).toBeInTheDocument();
    expect(screen.queryByText(/sent to Anthropic/)).toBeNull();
  });

  it("says it was sent once a call carried it, even if the reading then failed", () => {
    const doc = makeDoc({ status: "failed", ai_processed_at: null });
    renderWithProviders(<DocumentFooter detail={makeDetail({ document: doc, given_to_model: true })} />);
    expect(screen.getByText(/The letter's text or image was sent to Anthropic/)).toBeInTheDocument();
    expect(screen.queryByText(/Not sent to Claude/)).toBeNull();
  });

  it("says a private letter never left the computer", () => {
    renderWithProviders(<DocumentFooter detail={makeDetail({ document: makeDoc({ ai_private: true, ai_processed_at: null }) })} />);
    expect(screen.getByText("This letter never left your computer.")).toBeInTheDocument();
  });
});

describe("A scan's scanner text (ADR 0020)", () => {
  const WHY = "Ordnung keeps it only so search can find the letter: it isn't checked, isn't shown as the letter's words and is never sent to Claude.";
  const scan = (pages: number, scanTextPages: number[]) =>
    makeDetail({
      document: makeDoc({ status: "held", ai_private: true, ai_processed_at: null, pages }),
      scan_text_pages: scanTextPages,
      given_to_model: false,
    });

  it("says what the text the scanner added is kept for, and that it is never checked, shown or sent", () => {
    renderWithProviders(<DocumentFooter detail={scan(1, [1])} />);
    const note = screen.getByText(/^Your scanner added its own text to this file\./);
    expect(note).toHaveTextContent(`Your scanner added its own text to this file. ${WHY}`);
    // the file travels with hand-off sync and backups: never "on this computer only"
    expect(note.textContent).not.toMatch(/computer/);
  });

  it("names the pages when only some of them have such text", () => {
    const { unmount } = renderWithProviders(<DocumentFooter detail={scan(3, [2])} />);
    expect(screen.getByText(/^Your scanner added its own text to page 2 of this file\./)).toBeInTheDocument();
    unmount();
    renderWithProviders(<DocumentFooter detail={scan(3, [2, 3])} />);
    expect(screen.getByText(/^Your scanner added its own text to pages 2 and 3 of this file\./)).toBeInTheDocument();
  });

  it("says nothing for a letter without it", () => {
    renderWithProviders(<DocumentFooter detail={scan(1, [])} />);
    expect(screen.queryByText(/scanner/)).toBeNull();
  });

  it("is the same on a phone: it names no computer", () => {
    expect(scanTextNote(scan(2, [1, 2]))).toBe(`Your scanner added its own text to this file. ${WHY}`);
    expect(scanTextNote(scan(4, [1, 2, 4]))).toBe(`Your scanner added its own text to pages 1, 2 and 4 of this file. ${WHY}`);
    expect(scanTextNote(scan(1, []))).toBeNull();
  });
});
