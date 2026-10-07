/**
 * Phone mode: the tab learns from `/api/health` whether it is the computer or a paired phone (`usePhoneCompanion`
 * in components, `clientKind()` elsewhere), and the test helpers put a page in phone mode with one option.
 * The phone-access hooks keep Settings → Phone's status current.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { act, renderHook, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { qk, useHealth, usePhone, useRemovePhone, useUpdatePhone, PHONE_POLL_MS } from "@/api/hooks";
import { makeTestQueryClient, PHONE_TEST_HEALTH, renderWithProviders, TEST_HEALTH } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { clientKind, setClientKind, usePhoneCompanion } from "./client";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/** A QueryClient that asks the (mock) server for health instead of starting with it. */
function freshClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

function wrapper(qc: QueryClient) {
  return ({ children }: { children?: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function Who() {
  return <p>{usePhoneCompanion() ? "on a phone" : "on the computer"}</p>;
}

describe("which device this tab is", () => {
  it("is the computer when the computer's listener answers", async () => {
    useMockApi();
    const { result } = renderHook(() => ({ health: useHealth(), phone: usePhoneCompanion() }), { wrapper: wrapper(freshClient()) });
    await waitFor(() => expect(result.current.health.data?.client).toBe("computer"));
    expect(result.current.phone).toBe(false);
    expect(clientKind()).toBe("computer");
  });

  it("is a phone when the phone listener answers, and health then leaves out the computer's details", async () => {
    useMockApi({ client: "phone" });
    setClientKind("computer"); // only health may say so
    const { result } = renderHook(() => ({ health: useHealth(), phone: usePhoneCompanion() }), { wrapper: wrapper(freshClient()) });
    await waitFor(() => expect(result.current.phone).toBe(true));
    expect(clientKind()).toBe("phone");
    expect(result.current.health.data).toMatchObject({ client: "phone", data_dir: "", demo: false, checks: [] });
  });

  it("is a phone when the phone listener refuses it as not paired (removed on the computer)", async () => {
    useMockApi({ client: "phone", paired: false });
    setClientKind("computer");
    const { result } = renderHook(() => useHealth(), { wrapper: wrapper(freshClient()) });
    await waitFor(() => expect(clientKind()).toBe("phone"));
    // health asks once more before it gives up (useHealth's `retry: 1`)
    await waitFor(() => expect(result.current.isError).toBe(true), { timeout: 3_000 });
    expect(result.current.error).toMatchObject({ status: 401, code: "phone_not_paired" });
  });

  it("starts a rendered page in phone mode after useMockApi({ client: 'phone' }), and back on the computer after the test", () => {
    useMockApi({ client: "phone" });
    const { client } = renderWithProviders(<Who />);
    expect(screen.getByText("on a phone")).toBeInTheDocument();
    expect(client.getQueryData(qk.health)).toEqual(PHONE_TEST_HEALTH);
    expect(PHONE_TEST_HEALTH).toMatchObject({ client: "phone", data_dir: "", demo: false, today: TEST_HEALTH.today });
  });

  it("is the computer again in the next test (src/test/setup.ts)", () => {
    expect(clientKind()).toBe("computer");
    renderWithProviders(<Who />);
    expect(screen.getByText("on the computer")).toBeInTheDocument();
    expect(makeTestQueryClient({ client: "phone" }).getQueryData(qk.health)).toEqual(PHONE_TEST_HEALTH);
  });
});

describe("Settings → Phone's hooks", () => {
  it("polls the status while asked to, and a change or a removal replaces it at once", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { srv, calls } = useMockApi();
    const qc = makeTestQueryClient();
    const { result } = renderHook(() => ({ status: usePhone({ poll: true }), update: useUpdatePhone(), remove: useRemovePhone() }), { wrapper: wrapper(qc) });
    await waitFor(() => expect(result.current.status.data?.enabled).toBe(false));
    const asked = () => calls.filter((c) => c.method === "GET" && c.path === "/phone").length;
    const before = asked();
    await act(() => vi.advanceTimersByTimeAsync(PHONE_POLL_MS * 2 + 10));
    expect(asked()).toBeGreaterThanOrEqual(before + 2);

    await act(() => result.current.update.mutateAsync({ enabled: true }));
    expect(qc.getQueryData(qk.phone)).toMatchObject({ enabled: true, listening: true, url: "https://192.168.178.23:8767" });
    const anna = srv.phone.addPhone({ name: "Anna's iPhone" });
    await act(() => result.current.remove.mutateAsync(anna.id));
    expect(result.current.status.data?.devices).toEqual([]);
  });

  it("asks nothing while not enabled (on a phone)", async () => {
    const { calls, srv } = useMockApi({ client: "phone" });
    renderHook(() => usePhone({ enabled: false }), { wrapper: wrapper(makeTestQueryClient()) });
    await new Promise((r) => setTimeout(r, 20));
    expect(calls).toEqual([]);
    expect(srv.refused).toEqual([]);
  });
});
