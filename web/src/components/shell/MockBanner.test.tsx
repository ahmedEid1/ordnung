import { afterEach, describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { MockBanner } from "./MockBanner";

describe("MockBanner (walkthrough of phase 2)", () => {
  afterEach(() => sessionStorage.clear());

  it("says the tab shows browser-only sample data and links back to the recorded demo", () => {
    sessionStorage.setItem("ordnung.mock", "full");
    renderWithProviders(<MockBanner />);
    const banner = screen.getByRole("status");
    expect(banner).toHaveTextContent("Browser-only sample data — not the recorded demo");
    expect(screen.getByRole("link", { name: "Back to the recorded demo" })).toHaveAttribute("href", "?mock=0");
  });

  it("is not there on the real app", () => {
    renderWithProviders(<MockBanner />);
    expect(screen.queryByRole("status")).toBeNull();
  });
});
