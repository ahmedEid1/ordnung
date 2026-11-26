/**
 * Today asks for the secretary's note together with the dashboard: the note used to be asked for only once the
 * dashboard had come and the page was drawn (232 ms later on a desktop, about 570 ms on a slowed phone).
 */
import { afterEach, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { TodayView } from "./TodayView";

afterEach(() => vi.unstubAllGlobals());

it("asks for the note while the dashboard is still on its way", async () => {
  const asked: string[] = [];
  vi.stubGlobal("fetch", (input: RequestInfo | URL) => {
    const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
    asked.push(path);
    // nothing answers: the page stays on its stand-in, as while a slow dashboard is worked out
    return new Promise<Response>(() => {});
  });
  renderWithProviders(<TodayView />, { client: makeTestQueryClient() });
  await waitFor(() => expect(asked).toContain("/dashboard"));
  await waitFor(() => expect(asked).toContain("/brief"));
  // the dashboard has not come: the page is still its stand-in
  expect(screen.queryByRole("region", { name: "Top 3 this week" })).toBeNull();
});
