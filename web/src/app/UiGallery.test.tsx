/**
 * The design-system gallery (`/dev/ui`, audit round 1, bucket "shell-b"): its samples work with any
 * data (the receipt examples are fixtures, not demo-only items), sample cards use the real money
 * and reference components, pill tabs have their panels, and the shortcut hint names the right key.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import UiGallery from "./UiGallery";

beforeEach(() => {
  // no API data at all: every sample must still render
  vi.stubGlobal("fetch", async () => new Response("null", { status: 404 }));
});
afterEach(() => vi.unstubAllGlobals());

describe("design-system gallery", () => {
  it("shows the 'Why this date?' examples without demo data", async () => {
    renderWithProviders(<UiGallery />);
    expect(await screen.findByRole("button", { name: /Why this date\?.*phone contract/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Why this date\?.*parking fine/ })).toBeInTheDocument();
  });

  it("uses Money and an unbroken reference in its sample cards, which aren't pretend links", () => {
    renderWithProviders(<UiGallery />);
    const pay = screen.getByRole("heading", { name: "Pay TechMarkt reminder" }).closest(".card")!;
    expect(pay.className).not.toMatch(/hover:-translate-y-px/);
    expect(within(pay as HTMLElement).getByText("RE-2026-084213")).toHaveClass("whitespace-nowrap");
    const phone = screen.getByRole("heading", { name: "Decide on your phone contract" }).closest(".card")!;
    expect(phone.textContent).not.toContain("34,99 €");
    expect(phone.textContent).toMatch(/34\.99/);
    // the sample grids let their cards shrink (single column on phones, nothing pushed out)
    expect(pay.parentElement).toHaveClass("[&>*]:min-w-0");
  });

  it("gives the pill tabs their panels", () => {
    renderWithProviders(<UiGallery />);
    const pill = screen.getByRole("tablist", { name: "Show letters" });
    const selected = within(pill).getAllByRole("tab").find((t) => t.getAttribute("aria-selected") === "true")!;
    const panel = document.getElementById(selected.getAttribute("aria-controls")!);
    expect(panel).toHaveAttribute("role", "tabpanel");
  });

  it("names Ctrl, not ⌘, off a Mac", () => {
    renderWithProviders(<UiGallery />);
    expect(screen.getByText("Ctrl", { selector: "kbd" })).toBeInTheDocument();
    expect(screen.queryByText("⌘", { selector: "kbd" })).toBeNull();
  });
});
