/**
 * Waiting for: "It arrived", "They kept it" and "I got an answer" take one press at a time — two presses before the
 * button is drawn busy send one request — and a failed one takes the next press.
 */
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { expectOnePressAtATime } from "@/test/busyButton";
import { holdRequests, useMockApi } from "@/test/mockFetch";
import { renderWithProviders } from "@/test/render";
import WaitingPage from "@/pages/WaitingPage";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

const CASES = [
  { row: "Deposit back from the student hall", name: "It arrived", method: "PATCH", path: "/items/itm_deposit_hall" },
  { row: "Written confirmation of the cancellation", name: "They kept it", method: "PATCH", path: "/calls/cal_fitwell" },
  { row: "A written confirmation of the end date", name: "I got an answer — close this", method: "POST", path: "/drafts/drf_gym/answered" },
] as const;

describe("Waiting for: an answer on its way", () => {
  for (const { row, name, method, path } of CASES) {
    it(`“${name}” takes one press at a time, and the next once it failed`, async () => {
      useMockApi();
      const held = holdRequests((call) => call.method === method && call.path === path);
      renderWithProviders(
        <>
          <WaitingPage />
          <Toaster />
        </>,
        { route: "/letters/waiting" },
      );
      const li = () => screen.getByText(row).closest("li") as HTMLElement;
      await screen.findByText(row);
      await expectOnePressAtATime({ user: userEvent.setup(), button: () => within(li()).getByRole("button", { name }), held });
    });
  }
});
