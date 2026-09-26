/**
 * Audit (regression): the document viewer lists the letters drafted about it (`DocumentDetail.drafts`),
 * but creating or deleting a draft used to invalidate only `["drafts"]` — and the backend publishes no
 * event for a deleted draft. Going back to the letter within the 30 s stale time still showed the
 * deleted draft (clicking it opened "Unknown letter"), and a new draft was missing from the list.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { act, renderHook } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import type { Draft } from "@/api/types";
import { makeTestQueryClient } from "@/test/render";
import { makeDetail } from "@/features/document/fixtures";
import { qk, useCreateDraft, useDeleteDraft } from "./hooks";

const TS = "2026-09-28T07:00:00Z";
const DRAFT = {
  id: "drf_1",
  kind: "general_reply",
  language: "de",
  party_id: null,
  case_id: null,
  doc_id: "doc_1",
  contract_id: null,
  sender_block: "",
  recipient_block: "",
  place_date: "",
  subject: "Ihr Schreiben",
  body: "",
  body_translation: "",
  enclosures: [],
  notes_for_user: [],
  checks: [],
  send_guidance: null,
  sent_channel: null,
  status: "draft",
  sent_at: null,
  created_at: TS,
  updated_at: TS,
} as unknown as Draft;

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method?.toUpperCase() === "DELETE"
        ? new Response(null, { status: 204 })
        : new Response(JSON.stringify(DRAFT), { status: 201, headers: { "Content-Type": "application/json" } }),
    ),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
});

function setup() {
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.documents.detail("doc_1"), makeDetail({ drafts: [DRAFT] }));
  const wrapper = ({ children }: { children?: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  return { qc, wrapper };
}

describe("drafts listed on the letter they are about (audit)", () => {
  it("deleting a draft refreshes the letter's drafts list", async () => {
    const { qc, wrapper } = setup();
    const { result } = renderHook(() => useDeleteDraft(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync("drf_1");
    });
    expect(qc.getQueryState(qk.documents.detail("doc_1"))?.isInvalidated).toBe(true);
  });

  it("creating a draft refreshes the letter's drafts list", async () => {
    const { qc, wrapper } = setup();
    const { result } = renderHook(() => useCreateDraft(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({ kind: "general_reply", doc_id: "doc_1" });
    });
    expect(qc.getQueryState(qk.documents.detail("doc_1"))?.isInvalidated).toBe(true);
  });
});
