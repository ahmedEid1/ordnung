/**
 * `/dev/ui`: the design-system gallery shows in development, mock mode and the demos (where the end-to-end
 * tests and the UI audit open it); the app itself has no such page.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { qk } from "@/api/hooks";
import { makeTestQueryClient, renderWithProviders, TEST_HEALTH } from "@/test/render";
import DevUiPage from "./DevUiPage";

function healthOf(demo: boolean) {
  const client = makeTestQueryClient();
  client.setQueryData(qk.health, { ...TEST_HEALTH, demo, simulated_today: demo ? TEST_HEALTH.simulated_today : null });
  return client;
}

beforeEach(() => {
  vi.stubGlobal("fetch", async () => new Response("null", { status: 404 }));
  vi.stubEnv("DEV", false); // as built: `npm run build`
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  sessionStorage.clear();
});

describe("/dev/ui", () => {
  it("is not a page of the app as built", () => {
    renderWithProviders(<DevUiPage />, { client: healthOf(false) });
    expect(screen.getByRole("heading", { level: 1, name: "This page doesn't exist" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Design system" })).toBeNull();
  });

  it("shows the gallery in the demo", () => {
    renderWithProviders(<DevUiPage />, { client: healthOf(true) });
    expect(screen.getByRole("heading", { level: 1, name: "Design system" })).toBeInTheDocument();
  });

  it("shows the gallery in mock mode", () => {
    sessionStorage.setItem("ordnung.mock", "on");
    renderWithProviders(<DevUiPage />, { client: healthOf(false) });
    expect(screen.getByRole("heading", { level: 1, name: "Design system" })).toBeInTheDocument();
  });

  it("shows the gallery in development", () => {
    vi.stubEnv("DEV", true);
    renderWithProviders(<DevUiPage />, { client: healthOf(false) });
    expect(screen.getByRole("heading", { level: 1, name: "Design system" })).toBeInTheDocument();
  });
});
