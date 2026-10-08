/**
 * Test helpers: render with a QueryClient (pre-seeded `/api/health` so `useToday()` is the demo
 * date) and a memory router.
 *
 * Phone mode: after `useMockApi({ client: "phone" })` (or `setClientKind("phone")`), a new test QueryClient is
 * seeded with {@link PHONE_TEST_HEALTH}, so `usePhoneCompanion()` is true; `makeTestQueryClient({ client })` says
 * so explicitly. `src/test/setup.ts` puts the tab back on "computer" after each test.
 */
import type { ReactElement, ReactNode } from "react";
import { render, type RenderOptions } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import type { ClientKind, Health } from "@/api/types";
import { qk } from "@/api/hooks";
import { clientKind, setClientKind } from "@/api/clientKind";
import { phoneHealth } from "@/mocks/phone";

export const TEST_TODAY = "2026-09-28";

export const TEST_HEALTH: Health = {
  version: "test",
  data_dir: "/tmp/ordnung-test",
  demo: true,
  simulated_today: TEST_TODAY,
  today: TEST_TODAY,
  backend: "fake",
  claude: { installed: true, version: "test", path: null, ok: true, detail: null, needs_version: null },
  model_pinned: null,
  rules_last_checked: "2026-09-25",
  checks: [],
  client: "computer",
};

/** Health as a paired phone gets it: `client: "phone"`, no data folder, never the demo (as the API trims it). */
export const PHONE_TEST_HEALTH: Health = phoneHealth(TEST_HEALTH);

/**
 * A QueryClient for one test, with health seeded: the computer's ({@link TEST_HEALTH}), or a phone's
 * ({@link PHONE_TEST_HEALTH}) when `client` is "phone" — by default whatever the tab is now (`clientKind()`,
 * which `useMockApi({ client })` sets).
 */
export function makeTestQueryClient({ client = clientKind() }: { client?: ClientKind } = {}): QueryClient {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
  setClientKind(client);
  qc.setQueryData(qk.health, client === "phone" ? PHONE_TEST_HEALTH : TEST_HEALTH);
  return qc;
}

export function renderWithProviders(
  ui: ReactElement,
  { route = "/", client = makeTestQueryClient(), ...options }: { route?: string; client?: QueryClient } & Omit<RenderOptions, "wrapper"> = {},
) {
  const router = createMemoryRouter([{ path: "*", element: ui }], { initialEntries: [route] });
  const Wrapper = ({ children }: { children?: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return { client, router, ...render(<RouterProvider router={router} />, { wrapper: Wrapper, ...options }) };
}
