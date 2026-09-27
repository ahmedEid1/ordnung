import { describe, expect, it } from "vitest";
import type { TourState } from "@/api/types";
import { INITIAL_TOUR, isLastStep, isTourVisible, normalizeTour, reduceTour, type TourEvent } from "./tourMachine";
import { TOUR_STEPS, onStepRoute } from "./steps";

const run = (events: TourEvent[], start: TourState = INITIAL_TOUR) => events.reduce((s, e) => reduceTour(s, e), start);

describe("tour state machine", () => {
  it("has four steps: new mail → Idea → Ask → Timeline", () => {
    expect(TOUR_STEPS.map((s) => s.route)).toEqual(["/inbox", "/", "/ask", "/timeline"]);
    // (the Idea step says "An idea just arrived" only when a letter brought one — see stepCopy)
    expect(TOUR_STEPS.map((s) => s.title)).toEqual(["You have new mail", "Ideas from your secretary", "Ask anything", "Your year ahead"]);
  });

  it("walks forward and completes after the last step", () => {
    expect(run([{ type: "next" }])).toEqual({ active: true, step: 1, completed: false });
    expect(run([{ type: "next" }, { type: "next" }, { type: "next" }])).toEqual({ active: true, step: 3, completed: false });
    expect(run([{ type: "next" }, { type: "next" }, { type: "next" }, { type: "next" }])).toEqual({ active: false, step: 3, completed: true });
  });

  it("goes back but never below the first step", () => {
    expect(run([{ type: "next" }, { type: "next" }, { type: "back" }]).step).toBe(1);
    expect(run([{ type: "back" }, { type: "back" }]).step).toBe(0);
  });

  it("can be skipped from any step and then ignores everything but restart", () => {
    const skipped = run([{ type: "next" }, { type: "skip" }]);
    expect(skipped).toEqual({ active: false, step: 1, completed: true });
    expect(run([{ type: "next" }, { type: "goto", step: 3 }], skipped)).toEqual(skipped);
    expect(run([{ type: "restart" }], skipped)).toEqual({ active: true, step: 0, completed: false });
  });

  it("restarts at a given step (Undo after ending it), clamped", () => {
    const ended = run([{ type: "next" }, { type: "next" }, { type: "skip" }]);
    expect(run([{ type: "restart", step: 2 }], ended)).toEqual({ active: true, step: 2, completed: false });
    expect(run([{ type: "restart", step: 9 }], ended).step).toBe(3);
    expect(run([{ type: "restart", step: 3 }]).step).toBe(3); // also while it runs
  });

  it("advances to 'An idea just arrived' when a new Idea arrives during step 1 only", () => {
    expect(run([{ type: "idea-arrived" }]).step).toBe(1);
    expect(run([{ type: "next" }, { type: "next" }, { type: "idea-arrived" }]).step).toBe(2);
  });

  it("clamps goto and repairs odd server states", () => {
    expect(run([{ type: "goto", step: 99 }]).step).toBe(3);
    expect(run([{ type: "goto", step: -4 }]).step).toBe(0);
    expect(normalizeTour({ active: true, step: 7, completed: true })).toEqual({ active: false, step: 3, completed: true });
    expect(normalizeTour({ active: true, step: Number.NaN, completed: false }).step).toBe(0);
  });

  it("is visible only in demo mode while active", () => {
    expect(isTourVisible(INITIAL_TOUR, { demo: true })).toBe(true);
    expect(isTourVisible(INITIAL_TOUR, { demo: false })).toBe(false);
    expect(isTourVisible({ active: false, step: 0, completed: false }, { demo: true })).toBe(false);
    expect(isTourVisible({ active: true, step: 2, completed: true }, { demo: true })).toBe(false);
    expect(isTourVisible(undefined, { demo: true })).toBe(false);
    expect(isLastStep({ active: true, step: 3, completed: false })).toBe(true);
  });

  it("matches step routes (Today only on '/')", () => {
    expect(onStepRoute({ route: "/" }, "/")).toBe(true);
    expect(onStepRoute({ route: "/" }, "/inbox")).toBe(false);
    expect(onStepRoute({ route: "/inbox" }, "/inbox")).toBe(true);
    expect(onStepRoute({ route: "/timeline" }, "/timeline/x")).toBe(true);
    expect(onStepRoute({ route: "/ask" }, "/askx")).toBe(false);
  });
});
