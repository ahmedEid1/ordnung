/**
 * Animation frames held back until the test runs them: a focus put off by a frame then lands when the test says,
 * after the steps that came before it — the order a fast run met by chance (Edit pressed, a letter typed and Save
 * reached, all inside one frame), forced every time. Undone by `vi.unstubAllGlobals()`.
 */
import { act } from "@testing-library/react";
import { vi } from "vitest";

export interface HeldFrames {
  /** Run the frames asked for so far (and those they ask for in turn, up to `rounds` frames deep). */
  run: (rounds?: number) => void;
  /** How many frames wait. */
  readonly waiting: number;
}

export function holdFrames(): HeldFrames {
  let queue = new Map<number, FrameRequestCallback>();
  let next = 0;
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    queue.set(++next, cb);
    return next;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => queue.delete(id));
  return {
    run: (rounds = 1) =>
      act(() => {
        for (let i = 0; i < rounds && queue.size; i++) {
          const now = queue;
          queue = new Map();
          for (const cb of now.values()) cb(performance.now());
        }
      }),
    get waiting() {
      return queue.size;
    },
  };
}
