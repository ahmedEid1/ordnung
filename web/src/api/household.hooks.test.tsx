/**
 * Your household's hooks (D3 contract): the household is part of the ledger's keys (a new reading changes the
 * suggestions), `profile.updated` refreshes it (household writes announce themselves so), and filing sends at
 * most 1,000 letters per request — a larger set goes in chunks, inside one mutation.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Household } from "@/api/types";
import { makeTestQueryClient } from "@/test/render";
import { makeDetail } from "@/features/document/fixtures";
import { FILE_LETTERS_MAX, filedBeforeFailure, invalidateLedger, qk, useFileLetters, useHousehold, useSaveHousehold } from "./hooks";
import { __resetEventsForTests, handleServerEvent } from "./sse";

const EMPTY: Household = { members: [], filed: {}, mine: [], suggested: {}, version: "4f53cda18c2baa0c" };
const ALEX = { id: "hhm_0123456789ab", name: "Alex Rivera", signs: true };
const WITH_ALEX: Household = { ...EMPTY, members: [{ ...ALEX, letters: 0 }], version: "0123456789abcdef" };

const sent: { method: string; url: string; body: unknown }[] = [];

beforeEach(() => {
  sent.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method?.toUpperCase() ?? "GET";
      sent.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : null });
      const answer = method === "GET" ? EMPTY : WITH_ALEX;
      return new Response(JSON.stringify(answer), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  __resetEventsForTests();
});

function setup() {
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.documents.detail("doc_1"), makeDetail());
  const wrapper = ({ children }: { children?: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  return { qc, wrapper };
}

describe("your household's hooks", () => {
  it("reads the household and keeps it with the ledger's keys", async () => {
    const { qc, wrapper } = setup();
    const { result } = renderHook(() => useHousehold(), { wrapper });
    await vi.waitFor(() => expect(result.current.data).toEqual(EMPTY));
    expect(qk.household).toEqual(["household"]);
    const spy = vi.spyOn(qc, "invalidateQueries");
    await invalidateLedger(qc);
    expect(spy).toHaveBeenCalledWith({ queryKey: qk.household });
  });

  it("saving the people sets the answer and refreshes the letters' pages", async () => {
    const { qc, wrapper } = setup();
    const { result } = renderHook(() => useSaveHousehold(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({ base: EMPTY.version, members: [{ name: "Alex Rivera", signs: true }], also_file: [] });
    });
    expect(sent.map(({ method, url }) => [method, url])).toEqual([["PUT", "/api/household"]]);
    expect(qc.getQueryData(qk.household)).toEqual(WITH_ALEX);
    expect(qc.getQueryState(qk.documents.detail("doc_1"))?.isInvalidated).toBe(true);
  });

  it("files at most 1,000 letters a request: a larger set goes in chunks, in one mutation", async () => {
    const { qc, wrapper } = setup();
    const { result } = renderHook(() => useFileLetters(), { wrapper });
    const letters = Object.fromEntries(Array.from({ length: 2_345 }, (_, n) => [`doc_${n}`, n % 2 ? ALEX.id : null]));
    await act(async () => {
      await result.current.mutateAsync({ letters });
    });
    expect(FILE_LETTERS_MAX).toBe(1_000);
    const bodies = sent.map(({ method, url, body }) => {
      expect([method, url]).toEqual(["PATCH", "/api/household"]);
      return (body as { letters: Record<string, string | null> }).letters;
    });
    expect(bodies.map((chunk) => Object.keys(chunk).length)).toEqual([1_000, 1_000, 345]);
    expect(Object.assign({}, ...bodies)).toEqual(letters);
    expect(qc.getQueryData(qk.household)).toEqual(WITH_ALEX);
    expect(qc.getQueryState(qk.documents.detail("doc_1"))?.isInvalidated).toBe(true);
  });

  it("a chunk that fails after others went through says which letters were filed", async () => {
    const { wrapper } = setup();
    const answered = vi.mocked(globalThis.fetch);
    const ok = answered.getMockImplementation()!;
    let patches = 0;
    answered.mockImplementation(async (url, init) => {
      if (init?.method === "PATCH" && ++patches === 2) {
        return new Response(JSON.stringify({ detail: "This letter is in the trash." }), { status: 404, headers: { "Content-Type": "application/json" } });
      }
      return ok(url, init);
    });
    const { result } = renderHook(() => useFileLetters(), { wrapper });
    const letters = Object.fromEntries(Array.from({ length: 2_345 }, (_, n) => [`doc_${n}`, ALEX.id]));
    let failed: unknown = null;
    await act(async () => {
      await result.current.mutateAsync({ letters }).catch((err: unknown) => (failed = err));
    });
    expect(failed).toBeInstanceOf(Error);
    expect(sent.filter((c) => c.method === "PATCH")).toHaveLength(1); // the second chunk was refused, the third never sent
    expect(filedBeforeFailure(failed)).toEqual(Object.keys(letters).slice(0, 1_000));
    // a first chunk that fails filed nothing
    patches = 1;
    await act(async () => {
      await result.current.mutateAsync({ letters }).catch((err: unknown) => (failed = err));
    });
    expect(filedBeforeFailure(failed)).toEqual([]);
    expect(filedBeforeFailure(new Error("x"))).toEqual([]);
  });

  it("a small filing is one request", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useFileLetters(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({ letters: { doc_1: "me" } });
    });
    expect(sent).toEqual([{ method: "PATCH", url: "/api/household", body: { letters: { doc_1: "me" } } }]);
  });

  it("profile.updated refreshes the household as well as the profile", () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    handleServerEvent(qc, { type: "profile.updated", data: {} });
    expect(spy).toHaveBeenCalledWith({ queryKey: qk.profile });
    expect(spy).toHaveBeenCalledWith({ queryKey: qk.household });
  });
});
