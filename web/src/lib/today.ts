/**
 * The app's "today". In demo mode the backend simulates a date (2026-09-28), so relative dates
 * ("in 5 days") must be computed against `/api/health`'s `today`, never `new Date()`.
 */
import { useMemo } from "react";
import { startOfToday } from "date-fns";
import { useHealth } from "@/api/hooks";
import { toISODate, tryParseDate } from "./format";

/** The app's today as a local-midnight `Date` (falls back to the browser date while loading). */
export function useToday(): Date {
  const { data } = useHealth();
  const iso = data?.today ?? data?.simulated_today ?? null;
  return useMemo(() => tryParseDate(iso) ?? startOfToday(), [iso]);
}

/** The app's today as `YYYY-MM-DD`. */
export function useTodayISO(): string {
  const today = useToday();
  return useMemo(() => toISODate(today), [today]);
}

/** Demo info: whether the date is simulated, and the simulated ISO date. */
export function useSimulatedToday(): { simulated: boolean; date: string | null; demo: boolean } {
  const { data } = useHealth();
  return { simulated: Boolean(data?.simulated_today), date: data?.simulated_today ?? null, demo: Boolean(data?.demo) };
}
