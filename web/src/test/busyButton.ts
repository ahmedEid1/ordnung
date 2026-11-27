/**
 * What every button busy with its own request must do, checked the same way in each place: it keeps the keyboard's
 * place (`aria-disabled`, not `disabled`, which drops focus to the page), takes no second press while its request
 * runs, also not two presses that come before it is drawn busy, and takes the next press once a failed request is
 * done (a guard that is never let go leaves the button dead until the page is loaded again).
 */
import { act, waitFor } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";
import { expect } from "vitest";
import type { HeldRequests } from "./mockFetch";

export interface BusyButtonCheck {
  user: UserEvent;
  /** The button, found again each time (a busy one can be drawn anew). */
  button: () => HTMLElement;
  /** The button's own requests, held (`holdRequests`, set up before the first press). */
  held: HeldRequests;
  /** The key that presses it: Enter (a button) or Space (a switch). */
  key?: "{Enter}" | " ";
  /** Whether it says `aria-busy` while its request runs (the button pressed does; a sibling it waits with need not). */
  busy?: boolean;
}

/**
 * Press `button` from the keyboard with its request held: it keeps focus, is `aria-disabled` (and `aria-busy`) but
 * not disabled, and a second press (a key, a click) sends nothing. Then the request fails: once the button is no
 * longer `aria-disabled`, two presses in one go send ONE request. That request is left held for the caller.
 */
export async function expectOnePressAtATime({ user, button, held, key = "{Enter}", busy = true }: BusyButtonCheck): Promise<void> {
  const before = held.count;
  button().focus();
  await user.keyboard(key);
  await waitFor(() => expect(held.count).toBe(before + 1));
  await waitFor(() => expect(button()).toHaveAttribute("aria-disabled", "true"));
  if (busy) expect(button()).toHaveAttribute("aria-busy", "true");
  expect(button()).not.toBeDisabled();
  // a frame goes by first: a focus put off until then (by the press that opened the editor, say) lands now and is
  // caught every time, not only when the steps before happened to fit in one frame
  await act(() => new Promise<void>((done) => requestAnimationFrame(() => done())));
  expect(button()).toHaveFocus();
  await user.keyboard(key);
  await user.click(button());
  expect(held.count, "a press while busy sent a request").toBe(before + 1);
  // the request fails: the button is let go and takes the next press — one, also for two that come in one go
  await act(async () => held.fail());
  await waitFor(() => expect(button()).not.toHaveAttribute("aria-disabled"));
  act(() => {
    button().click();
    button().click();
  });
  await waitFor(() => expect(held.count).toBe(before + 2));
  await act(async () => {}); // let a second request, if one was sent, reach the count
  expect(held.count, "two presses in one go sent two requests").toBe(before + 2);
}
