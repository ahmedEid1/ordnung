/**
 * "Try again" on the card of letters that couldn't be read (UX audit U4): the card leaves once they are read
 * again, and focus goes to the card now in its place among Today's cards, or to Top 3's heading — never to <body>.
 */
import { useEffect, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Document } from "@/api/types";
import { makeDoc } from "@/features/document/fixtures";
import { renderWithProviders } from "@/test/render";
import { FailedCard } from "./FailedCard";

const FAILED = [makeDoc({ id: "doc_a", status: "failed" }), makeDoc({ id: "doc_b", status: "failed" })];

let reprocessed: string[] = [];
let readAgain: () => void = () => {};

beforeEach(() => {
  reprocessed = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), "http://localhost").pathname;
    if (init?.method === "POST") reprocessed.push(path);
    return new Response(JSON.stringify({}), { status: 200, headers: { "Content-Type": "application/json" } });
  });
});
afterEach(() => vi.unstubAllGlobals());

/** Today's cards, then Top 3; the failed letters' card leaves once they are read again (`readAgain`). */
function Today({ next = false }: { next?: boolean }) {
  const [docs, setDocs] = useState<Document[]>(FAILED);
  useEffect(() => {
    readAgain = () => setDocs([]);
  }, []);
  return (
    <>
      <div>
        <FailedCard docs={docs} />
        {next ? (
          <section aria-labelledby="attention-card-title">
            <h2 id="attention-card-title">2 letters need your answer</h2>
          </section>
        ) : null}
      </div>
      <section aria-labelledby="top3-title">
        <h2 id="top3-title">Top 3 this week</h2>
      </section>
    </>
  );
}

async function tryAgain() {
  const user = userEvent.setup();
  screen.getByRole("button", { name: "Try again" }).focus();
  await user.keyboard("{Enter}");
  await waitFor(() => expect(reprocessed).toEqual(["/api/documents/doc_a/reprocess", "/api/documents/doc_b/reprocess"]));
}

describe("the card of letters that couldn't be read, after Try again", () => {
  it("hands focus to Top 3's heading when it leaves and no card follows it", async () => {
    renderWithProviders(<Today />);
    await tryAgain();
    act(() => readAgain());
    expect(screen.queryByRole("region", { name: "2 letters couldn't be read" })).toBeNull();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Top 3 this week" })).toHaveFocus());
  });

  it("hands focus to the card now in its place", async () => {
    renderWithProviders(<Today next />);
    await tryAgain();
    act(() => readAgain());
    await waitFor(() => expect(screen.getByRole("heading", { name: "2 letters need your answer" })).toHaveFocus());
  });

  it("keeps focus on Try again while the card stays", async () => {
    renderWithProviders(<Today />);
    await tryAgain();
    expect(screen.getByRole("button", { name: "Try again" })).toHaveFocus();
  });
});
