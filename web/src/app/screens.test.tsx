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
import { BOOT_SLOW_MS, BOOT_STUCK_MS, BootScreen, NotFound, RouteError, UnreachableScreen } from "./screens";

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

  it("without a session, the button says what to do first", () => {
    render(<UnreachableScreen onRetry={() => {}} status={new ApiError(401, "x").status} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Please open Ordnung from its link");
    expect(screen.getByRole("button", { name: "I opened the link — check again" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
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
