/**
 * Offline and error feedback (audit round 1, bucket "shell-b"): a lost connection is one warning
 * that stays (with "Try again") until Ordnung answers again, then "Back online"; a live connection
 * that stays lost asks `/health` so the warning shows even when nothing else refetches; `/health`
 * can't hang the splash forever; and a failed change says what failed ("Couldn't save your
 * profile") with "Try again" when trying again can help.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { act, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { ApiError, request, SERVER_PROBLEM } from "@/api/client";
import { qk, useHealth } from "@/api/hooks";
import hooksSource from "@/api/hooks.ts?raw";
import { OFFLINE_GRACE_MS, __resetEventsForTests, connectEvents } from "@/api/sse";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { TEST_HEALTH } from "@/test/render";
import { __resetOfflineForTests, createQueryClient } from "./queryClient";

let client: QueryClient;
beforeEach(() => {
  client = createQueryClient();
  render(<Toaster />);
});
afterEach(() => {
  act(() => __clearToasts());
  __resetOfflineForTests();
  __resetEventsForTests();
  client.clear();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const offline = () => new ApiError(0, "Ordnung isn't reachable. Is it still running on this computer?");

describe("offline", () => {
  it("is one warning that stays, with 'Try again', until Ordnung answers — then 'Back online'", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    client.setQueryData(["dashboard"], { ok: 1 });
    await act(() => client.fetchQuery({ queryKey: ["dashboard"], queryFn: () => Promise.reject(offline()), retry: false, staleTime: 0 }).catch(() => {}));
    expect(screen.getByText("Can't reach Ordnung")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    // it doesn't time out: the data on screen is stale until Ordnung answers
    act(() => vi.advanceTimersByTime(120_000));
    expect(screen.getByText("Can't reach Ordnung")).toBeInTheDocument();

    vi.useRealTimers();
    await act(() => client.fetchQuery({ queryKey: ["dashboard"], queryFn: () => Promise.resolve({ ok: 2 }), staleTime: 0 }));
    expect(screen.getByText("Back online")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Can't reach Ordnung")).toBeNull());
  });

  it("stays quiet about successes when nothing was lost", async () => {
    await act(() => client.fetchQuery({ queryKey: ["dashboard"], queryFn: () => Promise.resolve(1) }));
    expect(screen.queryByText("Back online")).toBeNull();
  });

  it("'Try again' refetches what is on screen", async () => {
    client.setQueryData(["dashboard"], { ok: 1 });
    await act(() => client.fetchQuery({ queryKey: ["dashboard"], queryFn: () => Promise.reject(offline()), retry: false, staleTime: 0 }).catch(() => {}));
    const refetch = vi.spyOn(client, "refetchQueries").mockResolvedValue();
    act(() => screen.getByRole("button", { name: "Try again" }).click());
    expect(refetch).toHaveBeenCalledWith({ type: "active" });
  });
});

describe("the live connection", () => {
  class FakeEventSource {
    static last: FakeEventSource | null = null;
    static CLOSED = 2;
    readyState = 1;
    onopen: (() => void) | null = null;
    onerror: (() => void) | null = null;
    constructor() {
      FakeEventSource.last = this;
    }
    addEventListener() {}
    close() {}
  }

  it("asks /health when it stays lost (a restart that comes back at once stays quiet)", () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    vi.stubGlobal("EventSource", FakeEventSource);
    const refetch = vi.spyOn(client, "refetchQueries").mockResolvedValue();
    // (a reconnect invalidates the ledger, which refetches too: count only the /health probe)
    const probes = () => refetch.mock.calls.filter(([filters]) => JSON.stringify(filters) === JSON.stringify({ queryKey: qk.health })).length;
    const disconnect = connectEvents(client);
    const es = FakeEventSource.last!;
    act(() => es.onopen!());

    // lost and back within the grace time: nothing asked
    act(() => es.onerror!());
    act(() => vi.advanceTimersByTime(OFFLINE_GRACE_MS / 2));
    act(() => es.onopen!());
    act(() => vi.advanceTimersByTime(OFFLINE_GRACE_MS));
    expect(probes()).toBe(0);

    // lost for good: /health is asked (a failure there shows the warning)
    act(() => es.onerror!());
    act(() => vi.advanceTimersByTime(OFFLINE_GRACE_MS));
    expect(probes()).toBe(1);
    disconnect();
  });
});

describe("/health", () => {
  it("is asked with a signal that has a time limit, so a hung server can't hold the splash", async () => {
    let signal: AbortSignal | null | undefined;
    vi.stubGlobal("fetch", async (_input: RequestInfo | URL, init?: RequestInit) => {
      signal = init?.signal;
      return new Response(JSON.stringify(TEST_HEALTH), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    const { result } = renderHook(() => useHealth(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeTruthy());
    expect(signal).toBeInstanceOf(AbortSignal);
  });
});

describe("a failed change", () => {
  const run = (options: Parameters<ReturnType<QueryClient["getMutationCache"]>["build"]>[1], vars: unknown = undefined) =>
    act(() => client.getMutationCache().build(client, options).execute(vars).catch(() => {}));

  it("says what failed, why, and offers 'Try again' when Ordnung didn't answer", async () => {
    const fn = vi.fn().mockRejectedValueOnce(offline()).mockResolvedValue({ ok: true });
    await run({ mutationFn: fn, meta: { errorTitle: "Couldn't save your profile" } }, { name: "Sam" });
    expect(screen.getByText("Couldn't save your profile")).toBeInTheDocument();
    expect(screen.getByText(/Is it still running/)).toBeInTheDocument();
    await act(async () => screen.getByRole("button", { name: "Try again" }).click());
    await waitFor(() => expect(fn).toHaveBeenCalledTimes(2));
    expect(fn).toHaveBeenLastCalledWith({ name: "Sam" }, expect.anything());
  });

  it("says a server error plainly, its own words under 'Technical details' — never 'Internal Server Error' as the sentence", async () => {
    vi.stubGlobal("fetch", async () => new Response("Internal Server Error", { status: 500, headers: { "Content-Type": "text/plain" } }));
    await run({ mutationFn: () => request("/items", { method: "POST", body: {} }), meta: { errorTitle: "Couldn't add the to-do" } });
    const toast = screen.getByText("Couldn't add the to-do").closest("li")!;
    expect(toast).toHaveTextContent(SERVER_PROBLEM);
    const details = within(toast).getByText("Technical details").closest("details")!;
    expect(details).not.toHaveAttribute("open");
    expect(within(details).getByText("HTTP 500 · Internal Server Error")).toBeInTheDocument();
    // Ordnung failed itself: trying again can help
    expect(within(toast).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("has no 'Try again' when the answer was a refusal", async () => {
    await run({ mutationFn: () => Promise.reject(new ApiError(422, "The date must be after the letter date.")), meta: { errorTitle: "Couldn't update the to-do" } });
    expect(screen.getByText("Couldn't update the to-do")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("keeps the online demo's and Claude's break's own titles", async () => {
    await run({ mutationFn: () => Promise.reject(new ApiError(409, "Install Ordnung to try this.", null, "static_demo")), meta: { errorTitle: "Couldn't add your letters" } });
    expect(screen.getByText("Not available in the online demo")).toBeInTheDocument();
    await run({ mutationFn: () => Promise.reject(new ApiError(429, "Try again at 15:30.")), meta: { errorTitle: "Couldn't read the letter again" } });
    expect(screen.getByText("Claude needs a short break")).toBeInTheDocument();
  });

  it("says `ordnung demo`'s limit calmly: it replays recorded answers and can't read a new letter", async () => {
    const why = "The demo uses recorded answers for Sam's sample letters, so it can't read new ones.";
    await run({ mutationFn: () => Promise.reject(new ApiError(409, why, why, "demo_replay")), meta: { errorTitle: "Couldn't start reading them" } });
    const title = screen.getByText("Not available in the demo");
    expect(screen.queryByText("Couldn't start reading them")).toBeNull();
    // an info note, not an error (the polite list — errors go to the assertive one), nothing to try again
    expect(title.closest("ol")).toHaveAttribute("aria-live", "polite");
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("every mutation hook names what failed (or handles its errors itself)", () => {
    const blocks = hooksSource.split("useMutation(").slice(1).map((b) => b.split(/\nexport function /)[0]!);
    expect(blocks.length).toBeGreaterThan(20);
    for (const b of blocks) expect(b, b.slice(0, 120)).toMatch(/meta: \{ (errorTitle: "Couldn't [^"]+"|silent: true) \}/);
  });
});
