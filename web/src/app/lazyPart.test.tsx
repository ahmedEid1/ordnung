/**
 * A part of the shell loaded on first use (the tour, the drawer) whose code can't load leaves the shell as it is,
 * reloads for a new build as a page does when Ordnung answers, and loads again the next time it is asked for.
 */
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { lazyPart } from "./lazyPart";

const reloadIfServing = vi.hoisted(() => vi.fn(async (_reload: () => void) => {}));
vi.mock("./staleChunks", () => ({ reloadIfServing }));

beforeEach(() => reloadIfServing.mockClear());
afterEach(() => vi.restoreAllMocks());

it("shows nothing when its code can't load, asks for a reload as a page would, and tries again when asked again", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  let fail = true;
  const load = vi.fn(async () => {
    if (fail) throw new TypeError("Failed to fetch dynamically imported module");
    return ({ name }: { name: string }) => <p>Drawer for {name}</p>;
  });
  const Part = lazyPart(load);
  const { rerender } = render(
    <main>
      <h1>Inbox</h1>
      <Part name="Stadtwerke" retry="pty_1" />
    </main>,
  );
  await waitFor(() => expect(reloadIfServing).toHaveBeenCalledOnce());
  // the shell stays: the page is there, the part shows nothing
  expect(screen.getByRole("heading", { name: "Inbox" })).toBeInTheDocument();
  expect(screen.queryByText(/Drawer for/)).toBeNull();
  // the same request again does not try again by itself
  rerender(
    <main>
      <h1>Inbox</h1>
      <Part name="Stadtwerke" retry="pty_1" />
    </main>,
  );
  expect(load).toHaveBeenCalledOnce();

  fail = false;
  rerender(
    <main>
      <h1>Inbox</h1>
      <Part name="Stadtwerke" retry="pty_2" />
    </main>,
  );
  expect(await screen.findByText("Drawer for Stadtwerke")).toBeInTheDocument();
  expect(load).toHaveBeenCalledTimes(2);
});

it("says it failed when the app did not reload for it, and not when it did", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const failed = vi.fn();
  const Part = lazyPart(async (): Promise<() => null> => {
    throw new TypeError("Failed to fetch dynamically imported module");
  }, { failed });
  // no reload (one was done a minute ago, or Ordnung doesn't answer)
  const { rerender } = render(<Part retry="pty_1" />);
  await waitFor(() => expect(failed).toHaveBeenCalledOnce());

  // the app reloads for a new build: nothing to say
  reloadIfServing.mockImplementationOnce(async (reload: () => void) => reload());
  const reload = vi.fn();
  vi.stubGlobal("location", { ...window.location, reload });
  try {
    rerender(<Part retry="pty_2" />);
    await waitFor(() => expect(reload).toHaveBeenCalledOnce());
    await act(async () => {});
    expect(failed).toHaveBeenCalledOnce();
  } finally {
    vi.unstubAllGlobals();
  }
});
