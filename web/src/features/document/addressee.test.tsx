/**
 * A letter addressed to someone else (`DocumentDetail.addressed_to`, worked out by the API): its page says so
 * under the title, as plain text that wraps anywhere on a phone. A letter for the person says nothing new.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import { renderWithProviders, makeTestQueryClient } from "@/test/render";
import { qk } from "@/api/hooks";
import type { DocumentDetail } from "@/api/types";
import { VerdictCard } from "./VerdictCard";
import { selectPrimaryItem } from "./verdict";
import { makeDetail } from "./fixtures";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({}), { status: 200, headers: { "Content-Type": "application/json" } })),
  );
});
afterEach(() => vi.unstubAllGlobals());

function renderVerdict(detail: DocumentDetail) {
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.rules, []);
  renderWithProviders(<VerdictCard detail={detail} primary={selectPrimaryItem(detail.items, detail.set_aside)} />, { client: qc });
  return screen.getByRole("article");
}

describe("a letter addressed to someone else", () => {
  it("says who it is addressed to under the title, next to when it arrived", () => {
    const card = renderVerdict(makeDetail({ addressed_to: "Alex Rivera" }));
    const header = card.querySelector("header")!;
    const line = within(header).getByText(/^Addressed to/);
    expect(line).toHaveTextContent("Addressed to Alex Rivera");
    expect(within(line).getByText("Alex Rivera")).toBeInTheDocument();
    // plain text: nothing to press, and the name isn't marked as German
    expect(within(line).queryByRole("button")).toBeNull();
    expect(within(line).queryByRole("link")).toBeNull();
    expect(line.closest("[lang]")?.getAttribute("lang") ?? null).not.toBe("de");
  });

  it("wraps a long name anywhere rather than widening the page", () => {
    const name = `Alex ${"R".repeat(115)}`;
    const card = renderVerdict(makeDetail({ addressed_to: name }));
    const line = within(card).getByText(/^Addressed to/);
    expect(line).toHaveTextContent(`Addressed to ${name}`);
    expect(line.className).toContain("[overflow-wrap:anywhere]");
  });

  it("says nothing for a letter addressed to the person", () => {
    const card = renderVerdict(makeDetail({ addressed_to: null }));
    expect(within(card).queryByText(/Addressed to/)).toBeNull();
  });
});
