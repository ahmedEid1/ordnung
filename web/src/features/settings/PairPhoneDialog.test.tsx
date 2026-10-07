/**
 * The pairing dialog over time (mock API, the clock moved by hand): it asks again every 2 s while open and stops
 * when closed; its code counts down; after a minute with no phone on the page "Phone can't connect?" opens by
 * itself, with the firewall's narrowest rules for this computer; then the code runs out (nothing left to cancel).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PHONE_POLL_MS } from "@/api/hooks";
import { __clearToasts } from "@/components/ui/Toast";
import SettingsPage from "@/pages/SettingsPage";
import { useMockApi } from "@/test/mockFetch";
import { renderWithProviders } from "@/test/render";
import { firewallCommands } from "./phoneAccess";

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", RO);
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

/** Phone access on (as turned on before), Settings → Phone open, "Pair a phone" pressed. */
async function openPairing({ srv, calls }: ReturnType<typeof useMockApi>) {
  srv.phone.change({ enabled: true });
  const user = userEvent.setup();
  renderWithProviders(<SettingsPage />, { route: "/settings?section=phone" });
  await user.click(await screen.findByRole("button", { name: "Pair a phone" }));
  const dialog = await screen.findByRole("dialog", { name: "Pair a phone" });
  await within(dialog).findByText(/Valid for/);
  return { srv, calls, user, dialog };
}

describe("the pairing dialog over time", () => {
  it("asks again every 2 s while open, and no more once closed", async () => {
    const { calls, user, dialog } = await openPairing(useMockApi());
    const asked = () => calls.filter((c) => c.method === "GET" && c.path === "/phone").length;
    const before = asked();
    await waitFor(() => expect(asked()).toBeGreaterThan(before), { timeout: PHONE_POLL_MS + 1_500 });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const after = asked();
    await new Promise((r) => setTimeout(r, PHONE_POLL_MS + 300));
    expect(asked()).toBe(after);
  });

  it("counts down, offers help after a minute without a phone, and runs out", async () => {
    // only the clock is moved (the dialog's ticks, polling and animations run as they would)
    vi.useFakeTimers({ toFake: ["Date"] });
    const { calls, user, dialog } = await openPairing(useMockApi());
    expect(within(dialog).getByText("10:00")).toBeInTheDocument();
    const help = within(dialog).getByText("Phone can't connect?").closest("details")!;
    expect(help).not.toHaveAttribute("open");

    vi.setSystemTime(Date.now() + 61_000);
    expect(await within(dialog).findByText("8:59", undefined, { timeout: 2_000 })).toBeInTheDocument();
    await waitFor(() => expect(help).toHaveAttribute("open"));
    expect(within(help).getByText(/guest networks and “client isolation” keep devices apart/)).toBeInTheDocument();
    expect(within(help).getByText(/turn it off while you pair/)).toBeInTheDocument();
    expect(within(help).getByText(/^with/)).toHaveTextContent("Type the address with https://: https://192.168.178.23:8767/pair");

    // the firewall: only this address and port, only from the home network
    const commands = firewallCommands("192.168.178.23", 8767, "192.168.178.0/24");
    await user.click(within(help).getByRole("tab", { name: "Windows" }));
    expect(within(help).getByText(/First make this Wi‑Fi a private network/)).toBeInTheDocument();
    expect(within(help).getByRole("button", { name: `Copy command to let phone access through the firewall: ${commands.windows}` })).toBeInTheDocument();
    expect(within(help).getByText(/tick “Private networks” only — never “Public”/)).toBeInTheDocument();
    await user.click(within(help).getByRole("tab", { name: "Linux" }));
    expect(within(help).getByRole("button", { name: `Copy command to let phone access through the firewall: ${commands.linux}` })).toBeInTheDocument();
    await user.click(within(help).getByRole("tab", { name: "Mac" }));
    expect(within(help).getByText(/The rule is for that Python program — the one Ordnung runs with — not for every program\./)).toBeInTheDocument();

    // closing the help keeps it closed
    await user.click(within(help).getByText("Phone can't connect?"));
    expect(help).not.toHaveAttribute("open");

    vi.setSystemTime(Date.now() + 9 * 60_000);
    expect(await within(dialog).findByText("This code expired", undefined, { timeout: 2_000 })).toBeInTheDocument();
    expect(within(dialog).queryByRole("img", { name: /QR code/ })).toBeNull();
    // an expired code needs no cancelling
    await user.click(within(dialog).getByRole("button", { name: "Done" }));
    expect(calls.some((c) => c.method === "DELETE" && c.path === "/phone/pairing")).toBe(false);
  });
});
