import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Document, Household } from "@/api/types";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import SettingsPage from "@/pages/SettingsPage";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}

/** What the letter list leaves out of each letter, like the API (`LEFT_OUT_OF_LIST`): its page and the records copy have it. */
const LEFT_OUT_OF_LIST = ["key_facts", "explanation", "references", "payment", "sha256"] as const;

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", RO);
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  act(() => __clearToasts());
});

describe("Download a copy of your records", () => {
  it("takes every letter whole from documents.json, never from the lighter letter list", async () => {
    const { srv, calls } = useMockApi();
    const files: Blob[] = [];
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: (b: Blob) => (files.push(b), "blob:records"), revokeObjectURL: () => {} }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <SettingsPage />
        <Toaster />
      </>,
      { route: "/settings?section=data" },
    );
    const card = await screen.findByRole("region", { name: "Download a copy of your records" });
    const before = calls.length;
    await user.click(within(card).getByRole("button", { name: "Download JSON" }));
    expect(await screen.findByText("Your records are downloading")).toBeInTheDocument();
    expect(click).toHaveBeenCalledTimes(1);

    // the letters come from the computer-only copy of every letter, not from the list a phone may show too
    const letterReads = calls.slice(before).filter((c) => c.method === "GET" && c.path.startsWith("/documents"));
    expect(letterReads.map((c) => c.path)).toEqual(["/documents.json"]);

    expect(files).toHaveLength(1);
    const records = JSON.parse(await files[0]!.text()) as { documents: Document[] };
    const letters = srv.db.liveDocuments();
    expect(letters.length).toBeGreaterThan(10);
    // every letter, each as stored: what Claude read from inside it, its references, bank details and file hash
    // (and the person's own "For taxes" choice, none here)
    const byId = (docs: Document[]) => Object.fromEntries(docs.map((d) => [d.id, d]));
    const stored = letters.map((d) => ({ ...d, tax_choice: null }));
    expect(byId(records.documents)).toEqual(byId(JSON.parse(JSON.stringify(stored)) as Document[]));
    for (const d of records.documents) for (const field of LEFT_OUT_OF_LIST) expect(d, `${d.id} keeps ${field}`).toHaveProperty(field);
    const read = records.documents.filter((d) => d.ai_processed_at && !d.ai_private && d.status === "processed");
    expect(read.length).toBeGreaterThan(5);
    expect(read.filter((d) => !d.explanation).map((d) => d.id)).toEqual([]);
    expect(records.documents.some((d) => d.key_facts.length > 0)).toBe(true);
    expect(records.documents.some((d) => d.payment?.iban)).toBe(true);
  });

  /** "Download JSON" on the records card; the records it downloads. */
  async function downloadRecords(): Promise<Record<string, unknown>> {
    const files: Blob[] = [];
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: (b: Blob) => (files.push(b), "blob:records"), revokeObjectURL: () => {} }));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <SettingsPage />
        <Toaster />
      </>,
      { route: "/settings?section=data" },
    );
    const card = await screen.findByRole("region", { name: "Download a copy of your records" });
    await user.click(within(card).getByRole("button", { name: "Download JSON" }));
    expect(await screen.findByText("Your records are downloading")).toBeInTheDocument();
    expect(files).toHaveLength(1);
    return JSON.parse(await files[0]!.text()) as Record<string, unknown>;
  }

  it("holds your household: its people, the letters filed for each and the ones you said are yours, never suggestions", async () => {
    useMockApi();
    const household: Household = {
      members: [
        { id: "hhm_alex000000001", name: "Alex Rivera", signs: true, letters: 1 },
        { id: "hhm_mia0000000001", name: "Mia Rivera", signs: false, letters: 0 },
      ],
      filed: { doc_tax: "hhm_alex000000001" },
      mine: ["doc_fee"],
      suggested: { doc_phone: "hhm_mia0000000001" },
      version: "0123456789abcdef",
    };
    const api = globalThis.fetch;
    vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, "http://localhost").pathname;
      if (path === "/api/household") return Promise.resolve(new Response(JSON.stringify(household), { status: 200, headers: { "Content-Type": "application/json" } }));
      return api(input, init);
    });
    const records = await downloadRecords();
    expect(records.household).toEqual({
      members: [
        { id: "hhm_alex000000001", name: "Alex Rivera", signs: true },
        { id: "hhm_mia0000000001", name: "Mia Rivera", signs: false },
      ],
      filed: { doc_tax: "hhm_alex000000001" },
      mine: ["doc_fee"],
    });
  });

  it("holds an empty household when there is no one in it, and says so on the card", async () => {
    useMockApi();
    const records = await downloadRecords();
    expect(records.household).toEqual({ members: [], filed: {}, mine: [] });
    const card = screen.getByRole("region", { name: "Download a copy of your records" });
    expect(
      within(card).getByText(
        "Letters (details, not the files), to-dos & dates, contracts, people & organisations, your household, your drafts, Ideas and how each letter was read — as a JSON file you can open anywhere.",
      ),
    ).toBeInTheDocument();
  });
});
