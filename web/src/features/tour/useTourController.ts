import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/endpoints";
import { qk, useHealth, useTour } from "@/api/hooks";
import type { TourState } from "@/api/types";
import { isTourVisible, normalizeTour, reduceTour, type TourEvent } from "./tourMachine";

const restartListeners = new Set<() => void>();

/**
 * Run `fn` whenever the tour is restarted from anywhere (the Demo badge, the Finish toast, the
 * Undo after ending it) — the tour card uses it to open itself again. Returns the unsubscribe.
 */
export function onTourRestart(fn: () => void): () => void {
  restartListeners.add(fn);
  return () => {
    restartListeners.delete(fn);
  };
}

/** Tour state + `send(event)`: optimistic, persisted to `/api/demo/tour` (errors are ignored). */
export function useTourController() {
  const health = useHealth();
  const demo = Boolean(health.data?.demo);
  const tour = useTour(demo);
  const qc = useQueryClient();

  const send = useCallback(
    (ev: TourEvent) => {
      const current = qc.getQueryData<TourState>(qk.tour);
      if (!current) return;
      if (ev.type === "restart") restartListeners.forEach((fn) => fn());
      const next = reduceTour(current, ev);
      if (next === current) return;
      qc.setQueryData(qk.tour, next);
      api.updateTour(next).catch(() => undefined); // the tour is a nicety — never toast about it
    },
    [qc],
  );

  const state = tour.data ? normalizeTour(tour.data) : undefined;
  return { demo, state, visible: isTourVisible(state, { demo }), send };
}
