/**
 * Demo-tour state machine (pure; the state itself lives in `/api/demo/tour` as `TourState`).
 *
 *   inactive ──restart──▶ step 0 ──next──▶ 1 ──next──▶ 2 ──next──▶ 3 ──next/finish──▶ completed
 *                           ▲  ◀──back──    ◀──back──    ◀──back──
 *   any active step ──skip──▶ completed (hidden, not shown again)
 *   step 0 ──idea-arrived (a new Idea after opening a letter)──▶ step 1
 */
import type { TourState } from "@/api/types";
import { TOUR_STEPS } from "./steps";

export type TourEvent =
  | { type: "next" }
  | { type: "back" }
  | { type: "skip" }
  | { type: "finish" }
  | { type: "restart" }
  | { type: "goto"; step: number }
  | { type: "idea-arrived" };

export const INITIAL_TOUR: TourState = { active: true, step: 0, completed: false };

const clamp = (n: number, total: number) => Math.max(0, Math.min(total - 1, Math.floor(Number.isFinite(n) ? n : 0)));

/** Repair a state from the server (step out of range, active and completed at once). */
export function normalizeTour(s: TourState, total = TOUR_STEPS.length): TourState {
  const step = clamp(s.step, total);
  if (s.completed) return { active: false, step, completed: true };
  return { active: Boolean(s.active), step, completed: false };
}

/** Apply one event. Inactive or completed tours ignore everything except `restart`. */
export function reduceTour(state: TourState, ev: TourEvent, total = TOUR_STEPS.length): TourState {
  const s = normalizeTour(state, total);
  if (ev.type === "restart") return { active: true, step: 0, completed: false };
  if (!s.active) return s;
  switch (ev.type) {
    case "next":
      return s.step >= total - 1 ? { active: false, step: s.step, completed: true } : { ...s, step: s.step + 1 };
    case "back":
      return { ...s, step: Math.max(0, s.step - 1) };
    case "goto":
      return { ...s, step: clamp(ev.step, total) };
    case "skip":
    case "finish":
      return { active: false, step: s.step, completed: true };
    case "idea-arrived":
      return s.step === 0 ? { ...s, step: 1 } : s;
  }
}

/** The tour card shows only in demo mode, while the tour is active. */
export function isTourVisible(state: TourState | undefined, opts: { demo: boolean }): boolean {
  if (!opts.demo || !state) return false;
  const s = normalizeTour(state);
  return s.active && !s.completed;
}

export function isLastStep(state: TourState, total = TOUR_STEPS.length): boolean {
  return normalizeTour(state, total).step === total - 1;
}
