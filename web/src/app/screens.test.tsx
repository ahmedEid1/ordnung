/**
 * The full-screen states (audit round 1, bucket "shell-b"): a boot splash that says what it is
 * waiting for and gives up waiting silently, the "isn't running" / "open from its link" card with
 * named commands to copy, a 404 with an h1 and a way to the Inbox, and a route error in the same
 * card as a failed load with technical details that are a real target and can be copied.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { ApiError } from "@/api/client";
import { renderWithProviders } from "@/test/render";
import { setClientKind } from "@/api/clientKind";
import { BOOT_SLOW_MS, BOOT_STUCK_MS, BootScreen, NotFound, PHONE_CHECKS, RouteError, UnreachableScreen } from "./screens";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("boot splash", () => {
  it("is a page with an h1, says 'Starting Ordnung…' after a moment and asks whether it runs after a while", () => {
    vi.useFakeTimers();
    const onRetry = vi.fn();
    render(<BootScreen onRetry={onRetry} />);
    const main = screen.getByRole("main");
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(main).toContainElement(h1);
    // a fast start shows the logo only (the heading is there for screen readers)
    expect(h1).toHaveClass("sr-only");
    expect(screen.getByRole("status")).toHaveTextContent("");

    act(() => vi.advanceTimersByTime(BOOT_SLOW_MS));
    expect(h1).not.toHaveClass("sr-only");
    expect(h1).toHaveTextContent("Starting Ordnung…");
    expect(screen.getByRole("status")).toHaveTextContent("Starting Ordnung…");
    expect(screen.queryByRole("button")).toBeNull();

    act(() => vi.advanceTimersByTime(BOOT_STUCK_MS - BOOT_SLOW_MS));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Still waiting — is Ordnung running?");
    expect(main).toHaveTextContent("If you closed the window where it ran, start it again from your apps or with ordnung serve.");
    expect(main).not.toHaveAttribute("aria-busy", "true");
    screen.getByRole("button", { name: "Try again" }).click();
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe("'isn't running' and 'open from its link'", () => {
  it("name each command and let it be copied", async () => {
    // (user-event puts a clipboard of its own on navigator)
    const user = userEvent.setup();
    render(<UnreachableScreen onRetry={() => {}} status={0} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveClass("text-balance");
    const items = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(items.map((li) => li.querySelector("p")?.textContent)).toEqual(["Your letters", "Sample life"]);
    expect(items[0]).toHaveTextContent("ordnung serve");
    expect(items[1]).toHaveTextContent("ordnung demo");
    await user.click(within(items[0]!).getByRole("button", { name: /Copy command .*ordnung serve/ }));
    expect(await navigator.clipboard.readText()).toBe("ordnung serve");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("send whoever added Ordnung to their apps there first, then to the commands", () => {
    const { unmount } = render(<UnreachableScreen onRetry={() => {}} status={0} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Ordnung isn't running");
    const notRunning = screen.getByText(/^This page talks to the Ordnung app/);
    expect(notRunning).toHaveTextContent(
      "This page talks to the Ordnung app on your computer, and it didn't answer. If you added Ordnung to your apps with ordnung shortcut, open it from there. Otherwise start it again with one of these commands, then try again.",
    );
    // the command is set as code, like the ones below it
    expect(within(notRunning).getByText("ordnung shortcut").tagName).toBe("CODE");
    unmount();

    render(<UnreachableScreen onRetry={() => {}} status={401} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Please open Ordnung from its link");
    expect(screen.getByText(/^For your privacy/)).toHaveTextContent(
      "For your privacy, Ordnung only talks to the browser tab it opened itself. If you added Ordnung to your apps with ordnung shortcut, open it from there. Otherwise run one of these commands in a terminal and use the link it prints (or opens).",
    );
    // the commands to copy stay the two ways to start it
    expect(within(screen.getByRole("list")).getAllByRole("listitem").map((li) => li.querySelector("code")?.textContent)).toEqual(["ordnung serve", "ordnung demo"]);
  });

  it("without a session, the button says what to do first", () => {
    render(<UnreachableScreen onRetry={() => {}} status={new ApiError(401, "x").status} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Please open Ordnung from its link");
    expect(screen.getByRole("button", { name: "I opened the link — check again" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });
});

describe("on a paired phone", () => {
  it("the splash that waits asks about the computer and the Wi‑Fi, never for a command", () => {
    vi.useFakeTimers();
    const onRetry = vi.fn();
    render(<BootScreen phone onRetry={onRetry} />);
    act(() => vi.advanceTimersByTime(BOOT_STUCK_MS));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Still waiting — is your computer on?");
    expect(screen.getByRole("main")).toHaveTextContent(/this phone is on the same Wi‑Fi/);
    expect(screen.getByRole("main")).not.toHaveTextContent(/ordnung serve/);
    screen.getByRole("button", { name: "Try again" }).click();
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("a computer that doesn't answer: what to check, Try again, and a failed retry said out loud", async () => {
    const onRetry = vi.fn();
    const { rerender } = render(<UnreachableScreen phone status={0} onRetry={onRetry} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Can't reach your computer");
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual([...PHONE_CHECKS]);
    expect(screen.queryByText(/ordnung serve|ordnung shortcut|your apps|terminal/)).toBeNull();
    await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    rerender(<UnreachableScreen phone status={0} onRetry={onRetry} stillFailing />);
    expect(screen.getByRole("status")).toHaveTextContent("Still can't reach your computer.");
  });

  it("a phone the computer doesn't know any more: pair it again (a fresh page load)", () => {
    render(<UnreachableScreen phone status={401} onRetry={() => {}} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("This phone isn't paired any more");
    expect(screen.getByRole("link", { name: "Pair this phone" })).toHaveAttribute("href", "/pair");
    expect(screen.queryByRole("button", { name: /I opened the link/ })).toBeNull();
  });

  it("knows it is a phone from what the server said (health, or a refusal only a phone gets)", () => {
    setClientKind("phone");
    const { unmount } = render(<UnreachableScreen status={0} onRetry={() => {}} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Can't reach your computer");
    unmount();
    setClientKind("computer");
    render(<UnreachableScreen status={0} onRetry={() => {}} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Ordnung isn't running");
  });
});

describe("404", () => {
  it("has an h1, the way back to Today and one to the Inbox", () => {
    renderWithProviders(<NotFound />);
    expect(screen.getByRole("heading", { level: 1, name: "This page doesn't exist" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Today" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Open Inbox" })).toHaveAttribute("href", "/inbox");
  });
});

describe("route error", () => {
  function renderCrash() {
    function Crash(): never {
      throw new Error("Cannot read properties of undefined (reading 'map')");
    }
    vi.spyOn(console, "error").mockImplementation(() => {});
    const router = createMemoryRouter([{ path: "/", element: <Crash />, errorElement: <RouteError /> }]);
    return render(<RouterProvider router={router} />);
  }

  it("is the failed-load card: h1, Reload, 'Back to Today' and technical details to open and copy", async () => {
    const user = userEvent.setup();
    renderCrash();
    const card = screen.getByRole("alert");
    expect(card).toHaveAttribute("data-variant", "error");
    expect(within(card).getByRole("heading", { level: 1 })).toHaveTextContent("Something went wrong on this page");
    expect(within(card).getByRole("button", { name: "Reload" })).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Back to Today" })).toHaveAttribute("href", "/");
    const summary = within(card).getByText("Technical details");
    expect(summary.tagName).toBe("SUMMARY");
    expect(summary).toHaveClass("min-h-8", "px-2");
    await user.click(summary);
    expect(within(card).getByText(/reading 'map'/)).toBeVisible();
    await user.click(within(card).getByRole("button", { name: "Copy" }));
    expect(await navigator.clipboard.readText()).toContain("reading 'map'");
    expect(within(card).getByRole("button", { name: "Copied" })).toBeInTheDocument();
  });
});
