import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, waitFor } from "@testing-library/react";
import { handleServerEvent } from "@/api/sse";
import { renderWithProviders, TEST_TODAY } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { NOTIFY_ENABLED_KEY, batchForDisplay, planNotifications } from "./notify";
import { setBrowserNotifications, useBrowserNotifications } from "./useBrowserNotifications";

class FakeNotification {
  static permission: NotificationPermission = "granted";
  static requestPermission = vi.fn(async () => FakeNotification.permission);
  static shown: { title: string; options?: NotificationOptions }[] = [];
  onclick: (() => void) | null = null;
  constructor(
    public title: string,
    public options?: NotificationOptions,
  ) {
    FakeNotification.shown.push({ title, options });
  }
  close() {}
}

function Probe() {
  useBrowserNotifications();
  return null;
}

beforeEach(() => {
  localStorage.clear();
  FakeNotification.permission = "granted";
  FakeNotification.shown = [];
  FakeNotification.requestPermission.mockClear();
  vi.stubGlobal("Notification", FakeNotification);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  localStorage.clear();
});

describe("browser notifications", () => {
  it("on load: what is due today or tomorrow, once per day — even after Ideas change", async () => {
    const { srv } = useMockApi();
    const today = TEST_TODAY;
    // a critical Idea that is overdue, and a to-do due tomorrow
    srv.db.state.suggestions[0] = { ...srv.db.state.suggestions[0]!, priority: "critical", status: "new", due_date: "2026-09-20" };
    const expected = batchForDisplay(
      planNotifications(
        srv.db.state.items.filter((i) => i.status === "open"),
        srv.db.state.suggestions.filter((s) => s.status === "new"),
        today,
      ),
    );
    expect(expected.length).toBeGreaterThan(0);
    localStorage.setItem(NOTIFY_ENABLED_KEY, "true");

    const { client } = renderWithProviders(<Probe />);

    await waitFor(() => expect(FakeNotification.shown.map((n) => n.title)).toEqual(expected.map((n) => n.title)));
    expect(FakeNotification.shown[0]!.title).toMatch(/^Overdue: /);
    expect(FakeNotification.shown[0]!.options).toMatchObject({ tag: `ordnung:${expected[0]!.key}`, icon: "/favicon.svg" });

    act(() => handleServerEvent(client, { type: "suggestions.updated", data: {} }));
    act(() => handleServerEvent(client, { type: "day.changed", data: { date: today, previous: null } }));
    await new Promise((r) => setTimeout(r, 50));
    expect(FakeNotification.shown).toHaveLength(expected.length);
  });

  it("stays quiet when off, when the browser blocks them, and in the online demo", async () => {
    useMockApi();
    const first = renderWithProviders(<Probe />);
    await new Promise((r) => setTimeout(r, 50));
    expect(FakeNotification.shown).toEqual([]); // not turned on
    first.unmount();

    localStorage.setItem(NOTIFY_ENABLED_KEY, "true");
    FakeNotification.permission = "denied";
    const second = renderWithProviders(<Probe />);
    await new Promise((r) => setTimeout(r, 50));
    expect(FakeNotification.shown).toEqual([]);
    second.unmount();

    FakeNotification.permission = "granted";
    vi.stubEnv("VITE_STATIC_DEMO", "1");
    renderWithProviders(<Probe />);
    await new Promise((r) => setTimeout(r, 50));
    expect(FakeNotification.shown).toEqual([]);
  });

  it("turning them on asks the browser once; a refusal leaves them off", async () => {
    FakeNotification.permission = "default";
    FakeNotification.requestPermission.mockImplementationOnce(async () => {
      FakeNotification.permission = "granted";
      return "granted";
    });
    expect(await setBrowserNotifications(true)).toMatchObject({ enabled: true, permission: "granted" });
    expect(FakeNotification.requestPermission).toHaveBeenCalledTimes(1);
    expect(await setBrowserNotifications(false)).toMatchObject({ enabled: false });

    FakeNotification.permission = "default";
    FakeNotification.requestPermission.mockImplementationOnce(async () => {
      FakeNotification.permission = "denied";
      return "denied";
    });
    expect(await setBrowserNotifications(true)).toMatchObject({ enabled: false, permission: "denied" });
    expect(localStorage.getItem(NOTIFY_ENABLED_KEY)).toBeNull();
  });
});
