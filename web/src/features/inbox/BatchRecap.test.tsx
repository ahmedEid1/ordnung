/**
 * The batch recap ("I read 3 letters"): what it found is said when it is ready, as one sentence — the dialog takes
 * focus while it still puts the findings together, and a description that changes afterwards is not read out.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import { useMockApi } from "@/test/mockFetch";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { qk } from "@/api/hooks";
import type { DocumentDetail } from "@/api/types";
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

  it("says its findings once, when they are final: not first what a letter had before its to-dos came in", async () => {
    useMockApi();
    // a letter just filed: what the app last fetched of it is from before its to-dos were there
    const ids = ["doc_tax", "doc_parking", "doc_uni"];
    const full = (await (await fetch("/api/documents/doc_parking")).json()) as DocumentDetail;
    expect(full.items.length).toBeGreaterThan(0);
    const client = makeTestQueryClient();
    client.setQueryData(qk.documents.detail("doc_parking"), { ...full, items: [] });
    // …and its fresh details come last
    const mocked = globalThis.fetch;
    let release!: () => void;
    const held = new Promise<void>((go) => (release = go));
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith("/documents/doc_parking")) await held;
      return mocked(input, init);
    });
    renderWithProviders(<BatchRecapDialog docIds={ids} onClose={() => {}} />, { client });
    const status = within(screen.getByRole("dialog")).getByRole("status");
    // from the start: empty, as nothing is final yet
    const said: string[] = status.textContent ? [status.textContent] : [];
    const watch = new MutationObserver(() => {
      if (status.textContent && said[said.length - 1] !== status.textContent) said.push(status.textContent);
    });
    watch.observe(status, { subtree: true, childList: true, characterData: true });
    await waitFor(() => expect(ids.every((id) => client.getQueryState(qk.documents.detail(id))?.status !== "pending")).toBe(true));
    await new Promise((r) => setTimeout(r, 50));
    release();
    // its details fetched again: the findings with its to-dos
    await waitFor(() => expect(client.getQueryData<DocumentDetail>(qk.documents.detail("doc_parking"))?.items.length).toBe(full.items.length));
    await waitFor(() => expect(status).toHaveTextContent(/^Here's what I found: .+\.$/));
    await new Promise((r) => setTimeout(r, 50));
    watch.disconnect();
    expect(said).toEqual([status.textContent]);
  });
});
