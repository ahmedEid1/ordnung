import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/endpoints";
import { qk, useHealth, useTour } from "@/api/hooks";
import type { TourState } from "@/api/types";
import { isTourVisible, normalizeTour, reduceTour, type TourEvent } from "./tourMachine";

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
