/**
 * Test helpers: render with a QueryClient (pre-seeded `/api/health` so `useToday()` is the demo
 * date) and a memory router.
 */
import type { ReactElement, ReactNode } from "react";
import { render, type RenderOptions } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import type { Health } from "@/api/types";
import { qk } from "@/api/hooks";

export const TEST_TODAY = "2026-09-28";

export const TEST_HEALTH: Health = {
  version: "test",
  data_dir: "/tmp/ordnung-test",
  demo: true,
  simulated_today: TEST_TODAY,
  today: TEST_TODAY,
  backend: "fake",
  claude: { installed: true, version: "test", path: null, ok: true, detail: null },
  model_pinned: null,
  rules_last_checked: "2026-09-25",
  checks: [],
};

export function makeTestQueryClient(): QueryClient {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
  qc.setQueryData(qk.health, TEST_HEALTH);
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
