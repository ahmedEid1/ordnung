/**
 * A household change reaches My numbers at once: the app changes the list of people through `useChangeHousehold`
 * (Settings, a letter's *Add … to your household*) and files letters through `useFileLetters`; both refetch
 * `/numbers`, whose groups follow the filings.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { act, renderHook } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { api } from "@/api/endpoints";
import { useFileLetters, useNumbers } from "@/api/hooks";
import { MOCK_NUMBERS } from "@/mocks/data/numbers";
import { EMPTY_VERSION } from "@/mocks/household";
import { makeTestQueryClient } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import type { MockServer } from "@/mocks/server";
import { useChangeHousehold } from "./save";

afterEach(() => vi.restoreAllMocks());

function setup(srv: MockServer) {
  const qc = makeTestQueryClient();
  const wrapper = ({ children }: { children?: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  const numbers = vi.spyOn(api, "numbers");
  const hooks = renderHook(() => ({ numbers: useNumbers(), change: useChangeHousehold(), file: useFileLetters() }), { wrapper });
  return { srv, qc, numbers, hooks };
}

const health = () => MOCK_NUMBERS.about_you.find((n) => n.kind === "health_insurance")!;

describe("a household change and My numbers", () => {
  it("adding someone with a letter filed for them refetches My numbers, which lists it under them", async () => {
    const { numbers, hooks } = setup(useMockApi().srv);
    await vi.waitFor(() => expect(hooks.result.current.numbers.data).toBeDefined());
    expect(hooks.result.current.numbers.data!.household).toEqual([]);
    const calls = numbers.mock.calls.length;
    await act(async () => {
      await hooks.result.current.change.mutateAsync({ base: EMPTY_VERSION, members: [{ name: "Alex Rivera", signs: true }], also_file: [health().letter!.id] });
    });
    await vi.waitFor(() => expect(numbers.mock.calls.length).toBeGreaterThan(calls));
    await vi.waitFor(() => expect(hooks.result.current.numbers.data!.household.map((p) => p.name)).toEqual(["Alex Rivera"]));
    expect(hooks.result.current.numbers.data!.about_you.map((n) => n.kind)).not.toContain("health_insurance");
  });

  it("filing a letter for someone, and its Undo, refetch My numbers", async () => {
    const { srv, numbers, hooks } = setup(useMockApi().srv);
    await vi.waitFor(() => expect(hooks.result.current.numbers.data).toBeDefined());
    let alex = "";
    await act(async () => {
      const saved = await hooks.result.current.change.mutateAsync({ base: EMPTY_VERSION, members: [{ name: "Alex Rivera", signs: true }], also_file: [] });
      alex = saved.members[0]!.id;
    });
    expect(srv.db.state.household.members.map((m) => m.id)).toEqual([alex]);
    const letter = health().letter!.id;
    const calls = numbers.mock.calls.length;
    await act(async () => {
      await hooks.result.current.file.mutateAsync({ letters: { [letter]: alex } });
    });
    await vi.waitFor(() => expect(numbers.mock.calls.length).toBeGreaterThan(calls));
    await vi.waitFor(() => expect(hooks.result.current.numbers.data!.household).toHaveLength(1));
    await act(async () => {
      await hooks.result.current.file.mutateAsync({ letters: { [letter]: null } });
    });
    await vi.waitFor(() => expect(hooks.result.current.numbers.data!.household).toEqual([]));
  });
});
