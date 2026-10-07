/**
 * Hand-off sync in the shell (design §19.4): the top bar's indicator on the computer in use ("Saved · sam-desktop
 * has it", "Saving…", "Not saved: …"), and the banner under the top bar — a choice to make, standing by on the pages
 * that stay open, a late change being brought over. Neither shows when sync is off, nor ever on a phone.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { bannerKind, SyncBanner } from "./SyncBanner";
import { SyncIndicator } from "./SyncIndicator";

beforeEach(() => vi.stubGlobal("scrollTo", () => {}));
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

const WAIT = { timeout: 5000 };

describe("the sync indicator", () => {
  it("says the latest is saved and has reached the other computer, and leads to Your computers", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp();
    renderWithProviders(<SyncIndicator />);
    const link = await screen.findByRole("link", { name: "Saved · sam-desktop has it" }, WAIT);
    expect(link).toHaveAttribute("href", "/settings?section=computers");
    expect(link).toHaveAttribute("title", "Saved · sam-desktop has it");
  });

  it("says when the other computer hasn't received it yet, when it saves, and when it can't", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp();
    srv.sync.computers[1]!.has_latest = false;
    const { unmount } = renderWithProviders(<SyncIndicator />);
    expect(await screen.findByRole("link", { name: "Saved · sam-desktop hasn't received it yet" }, WAIT)).toBeInTheDocument();
    unmount();
    srv.sync.pending = true;
    const second = renderWithProviders(<SyncIndicator />);
    expect(await screen.findByRole("link", { name: "Saving…" }, WAIT)).toHaveAttribute("data-state", "saving");
    second.unmount();
    srv.sync.setProblem("folder_full");
    renderWithProviders(<SyncIndicator />);
    expect(await screen.findByRole("link", { name: "Not saved: The sync folder is full" }, WAIT)).toHaveAttribute("data-state", "problem");
  });

  it("isn't there when sync is off, or this computer stands by", async () => {
    const { srv, calls } = useMockApi();
    const { container, unmount } = renderWithProviders(<SyncIndicator />);
    await vi.waitFor(() => expect(calls.some((c) => c.path === "/sync")).toBe(true));
    expect(container).toBeEmptyDOMElement();
    unmount();
    srv.sync.setUp().otherTakesOver();
    const standing = renderWithProviders(<SyncIndicator />);
    await vi.waitFor(() => expect(calls.filter((c) => c.path === "/sync").length).toBe(2));
    expect(standing.container).toBeEmptyDOMElement();
  });

  it("never on a phone: sync is the computer's, and a phone doesn't even ask", async () => {
    const { srv, calls } = useMockApi({ client: "phone" });
    srv.sync.setUp();
    const { container } = renderWithProviders(
      <>
        <SyncIndicator />
        <SyncBanner />
      </>,
    );
    await act(() => new Promise((r) => setTimeout(r, 50)));
    expect(container).toBeEmptyDOMElement();
    expect(calls.filter((c) => c.path === "/sync")).toEqual([]);
    expect(srv.refused).toEqual([]);
  });
});

describe("the sync banner", () => {
  it("says what it is about", () => {
    const base = { connected: true, mode: "in_use", choice: null, activity: "idle" } as const;
    expect(bannerKind(undefined)).toBeNull();
    expect(bannerKind({ ...base, connected: false } as never)).toBeNull();
    expect(bannerKind(base as never)).toBeNull();
    expect(bannerKind({ ...base, mode: "standing_by" } as never)).toBe("standby");
    expect(bannerKind({ ...base, choice: { joining: false, sides: [], chosen: null } } as never)).toBe("choice");
    expect(bannerKind({ ...base, activity: "bringing_over" } as never)).toBe("bringing");
  });

  it("both computers changed: Choose… opens the choice, and the person can keep working", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().bothChanged();
    const user = userEvent.setup();
    renderWithProviders(<SyncBanner />);
    const banner = await screen.findByRole("status", {}, WAIT);
    expect(banner).toHaveTextContent("Your two computers both have changes. Nothing is lost: choose which to keep.");
    await user.click(within(banner).getByRole("button", { name: "Choose…" }));
    expect(await screen.findByRole("dialog", { name: "Which Ordnung do you want to keep?" }, WAIT)).toBeInTheDocument();
  });

  it("standing by (on a page that stays open): whose Ordnung is in use, and Use Ordnung here", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().otherTakesOver();
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <SyncBanner />
        <Toaster />
      </>,
    );
    const banner = await screen.findByText("Ordnung is in use on sam-desktop.", {}, WAIT);
    expect(banner.closest("[role=status]")).toHaveTextContent(/This computer is standing by: it changes nothing until you use Ordnung here/);
    await user.click(screen.getByRole("button", { name: "Use Ordnung here" }));
    expect(await screen.findByText("Ordnung is in use here now", {}, WAIT)).toBeInTheDocument();
    expect(srv.sync.mode).toBe("in_use");
  });

  it("a late change being brought over: writes wait a moment", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().arriving(9, 9);
    srv.sync.activity = "bringing_over";
    renderWithProviders(<SyncBanner />);
    expect(await screen.findByText("Bringing over a change from sam-desktop", {}, WAIT)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
