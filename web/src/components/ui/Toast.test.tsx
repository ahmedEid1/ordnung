import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@/api/client";
import { renderWithProviders } from "@/test/render";
import { Dialog } from "./Dialog";
import { TOAST_DURATION, TOAST_SPACE_VAR, Toaster, __clearToasts, toast, toastDuration } from "./Toast";

/** jsdom has no layout: answer `(min-width: …)` queries for a viewport `px` wide. */
function viewport(px: number) {
  vi.stubGlobal("matchMedia", (query: string) => {
    const min = Number(/min-width:\s*(\d+)px/.exec(query)?.[1] ?? 0);
    return { matches: px >= min, media: query, addEventListener() {}, removeEventListener() {} };
  });
}

const region = () => screen.getByRole("region", { name: /^Notifications/ });
const item = (text: string) => screen.getByText(text).closest("li") as HTMLElement;
/** What a closing toast makes inert: everything inside the li (the li itself stays to take a stray click). */
const contents = (li: HTMLElement) => li.firstElementChild as HTMLElement;

beforeEach(() => {
  viewport(1280);
  act(() => __clearToasts());
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

describe("Toast semantics", () => {
  it("keeps every toast a list item: errors in an assertive list, the rest in a polite one", () => {
    renderWithProviders(<Toaster />);
    act(() => {
      toast.error("That didn't work", { description: "Ordnung isn't reachable." });
      toast.success("Saved");
    });
    const lists = within(region()).getAllByRole("list");
    expect(lists).toHaveLength(2);
    const assertive = lists.find((l) => l.getAttribute("aria-live") === "assertive")!;
    const polite = lists.find((l) => l.getAttribute("aria-live") === "polite")!;
    expect(within(assertive).getByRole("listitem")).toHaveTextContent("That didn't work");
    expect(within(polite).getByRole("listitem")).toHaveTextContent("Saved");
    // no role="alert" on (or in) an item: it would break the list and speak the error twice
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("names the shortcut that reaches it in the region label", () => {
    renderWithProviders(<Toaster />);
    expect(region()).toHaveAccessibleName(/Notifications \((Alt|Option)\+N\)/);
  });
});

describe("Toast lifetime", () => {
  it("lasts long enough for its buttons, and errors wait for the person", () => {
    expect(toastDuration({})).toBe(TOAST_DURATION.plain);
    expect(toastDuration({ action: { label: "Open", onClick() {} } })).toBe(10_000);
    expect(toastDuration({ undo: () => {} })).toBe(15_000);
    expect(toastDuration({ tone: "danger" })).toBe(Infinity);
    expect(toastDuration({ tone: "danger", duration: 3000 })).toBe(3000);
  });

  it("closes a success toast after its time but keeps an error until it is dismissed", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    renderWithProviders(<Toaster />);
    act(() => {
      toast.error("Couldn't create the export");
      toast.success("Saved");
    });
    act(() => void vi.advanceTimersByTime(60_000));
    vi.useRealTimers();
    await waitFor(() => expect(screen.queryByText("Saved")).not.toBeInTheDocument());
    expect(screen.getByText("Couldn't create the export")).toBeInTheDocument();
    fireEvent.click(within(item("Couldn't create the export")).getByRole("button", { name: "Dismiss notification" }));
    await waitFor(() => expect(screen.queryByText("Couldn't create the export")).not.toBeInTheDocument());
  });

  it("pauses every toast while one of them is hovered", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    renderWithProviders(<Toaster />);
    act(() => {
      toast({ title: "First" });
      toast({ title: "Second" });
    });
    fireEvent.mouseEnter(item("Second"));
    act(() => void vi.advanceTimersByTime(30_000));
    expect(screen.getByText("First")).toBeInTheDocument();
    fireEvent.mouseLeave(item("Second"));
    act(() => void vi.advanceTimersByTime(TOAST_DURATION.plain));
    vi.useRealTimers();
    await waitFor(() => expect(screen.queryByText("First")).not.toBeInTheDocument());
    expect(screen.queryByText("Second")).not.toBeInTheDocument();
  });

  it("waits behind an open dialog instead of covering it", () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    renderWithProviders(
      <>
        <Toaster />
        <Dialog open onClose={() => {}} title="Delete this letter?">
          <p>Body</p>
        </Dialog>
      </>,
    );
    act(() => void toast({ title: "Saved" }));
    const column = screen.getByTestId("toaster");
    expect(column).toHaveAttribute("data-behind-modal");
    // behind the modal layer (z-50), not above it
    expect(column.className).toContain("z-[49]");
    act(() => void vi.advanceTimersByTime(60_000));
    expect(screen.getByText("Saved")).toBeInTheDocument();
  });
});

describe("Toast actions and keyboard", () => {
  it("gives Undo and the action 28 px targets whose text lines up with the title", () => {
    renderWithProviders(<Toaster />);
    act(() => void toast({ title: "Marked as done", undo: () => {}, action: { label: "Open", onClick() {} } }));
    const undo = screen.getByRole("button", { name: "Undo" });
    const open = screen.getByRole("button", { name: "Open" });
    for (const b of [undo, open]) expect(b.className).toMatch(/\bh-7\b.*\bpx-2\b/);
    // the row pulls the first button's padding back, so "Undo" starts under the title
    expect(undo.parentElement?.className).toContain("-ml-2");
  });

  it("Alt+N moves focus to the newest toast; Escape closes it and focus goes back", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <button type="button">Mark as paid</button>
        <Toaster />
      </>,
    );
    act(() => {
      toast({ title: "Older" });
      toast({ title: "Marked as paid", undo: () => {} });
    });
    const trigger = screen.getByRole("button", { name: "Mark as paid" });
    trigger.focus();
    fireEvent.keyDown(window, { key: "n", code: "KeyN", altKey: true });
    expect(item("Marked as paid")).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Undo" })).toHaveFocus();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByText("Marked as paid")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });
});

describe("A toast on its way out", () => {
  it("is marked inert and hidden while it slides away: its buttons are gone from role queries; the others are untouched", async () => {
    renderWithProviders(<Toaster />);
    act(() => {
      toast({ title: "Tracking number removed", undo: () => {}, action: { label: "Open", onClick() {} } });
      toast({ title: "Marked as answered", undo: () => {} });
    });
    const leaving = item("Tracking number removed");
    const staying = item("Marked as answered");
    fireEvent.click(within(leaving).getByRole("button", { name: "Dismiss notification" }));
    // still drawn for its exit animation, but its contents inert, and hidden from screen readers (and from role
    // queries); the li is no longer focusable, yet not inert itself, so a second click stops there
    expect(leaving).toBeInTheDocument();
    expect(contents(leaving)).toHaveAttribute("inert");
    expect(leaving).not.toHaveAttribute("inert");
    expect(leaving).not.toHaveAttribute("tabindex");
    expect(leaving).toHaveAttribute("aria-hidden", "true");
    expect(fireEvent.mouseDown(leaving)).toBe(false); // a second click keeps the focus where it is
    expect(within(leaving).queryAllByRole("button")).toHaveLength(0);
    expect(screen.getAllByRole("button", { name: "Undo" })).toEqual([within(staying).getByRole("button", { name: "Undo" })]);
    expect(screen.queryByRole("button", { name: "Open" })).not.toBeInTheDocument();
    expect(contents(staying)).not.toHaveAttribute("inert");
    expect(staying).toHaveAttribute("tabindex", "-1");
    expect(staying).not.toHaveAttribute("aria-hidden");
    expect(fireEvent.mouseDown(staying)).toBe(true);
    await waitFor(() => expect(leaving).not.toBeInTheDocument());
  });

  it("stays in reach while its Undo runs, then hands focus back as it goes", async () => {
    const user = userEvent.setup();
    let done = () => {};
    renderWithProviders(
      <>
        <button type="button">Remove</button>
        <Toaster />
      </>,
    );
    act(() => void toast({ title: "Tracking number removed", undo: () => new Promise<void>((resolve) => (done = resolve)) }));
    const trigger = screen.getByRole("button", { name: "Remove" });
    trigger.focus();
    fireEvent.keyDown(window, { key: "n", code: "KeyN", altKey: true });
    await user.tab();
    await user.keyboard("{Enter}");
    // busy, not leaving: its Undo is disabled but still there to be read
    const toastItem = item("Tracking number removed");
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
    expect(contents(toastItem)).not.toHaveAttribute("inert");
    await act(async () => done());
    expect(toastItem).toBeInTheDocument();
    expect(contents(toastItem)).toHaveAttribute("inert");
    expect(trigger).toHaveFocus();
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
    await waitFor(() => expect(toastItem).not.toBeInTheDocument());
  });

  it("closes after an Undo that fails, hands focus back as after one that works, and lets no rejection escape", async () => {
    // (an escaped rejection fails the run: Vitest reports unhandled rejections as errors)
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <button type="button">Remove</button>
        <Toaster />
      </>,
    );
    act(() => void toast({ title: "Tracking number removed", undo: () => Promise.reject(new ApiError(0, "Ordnung isn't reachable.")) }));
    const trigger = screen.getByRole("button", { name: "Remove" });
    trigger.focus();
    fireEvent.keyDown(window, { key: "n", code: "KeyN", altKey: true });
    await user.tab();
    await user.keyboard("{Enter}");
    const toastItem = item("Tracking number removed");
    await waitFor(() => expect(contents(toastItem)).toHaveAttribute("inert"));
    expect(trigger).toHaveFocus();
    await waitFor(() => expect(toastItem).not.toBeInTheDocument());
  });

  it("closes after an Undo that breaks, and reports the error instead of hiding it", async () => {
    // a bug in an Undo is not a failed request, which has already said so: it must still be seen
    const reported: unknown[] = [];
    const onError = (e: ErrorEvent) => {
      e.preventDefault();
      reported.push(e.error);
    };
    window.addEventListener("error", onError);
    try {
      renderWithProviders(<Toaster />);
      act(
        () =>
          void toast({
            title: "Marked as answered",
            undo: async () => {
              const box = undefined as unknown as HTMLElement;
              box.focus();
            },
          }),
      );
      const toastItem = item("Marked as answered");
      fireEvent.click(screen.getByRole("button", { name: "Undo" }));
      await waitFor(() => expect(contents(toastItem)).toHaveAttribute("inert"));
      expect(reported).toHaveLength(1);
      expect(reported[0]).toBeInstanceOf(TypeError);
      await waitFor(() => expect(toastItem).not.toBeInTheDocument());
    } finally {
      window.removeEventListener("error", onError);
    }
  });

  /** A page with a heading and two controls, and the toasts. */
  function page() {
    renderWithProviders(
      <>
        <main tabIndex={-1}>
          <h1 tabIndex={-1}>Today</h1>
          <button type="button">For taxes</button>
          <button type="button">Next card</button>
        </main>
        <Toaster />
      </>,
    );
    return { toggle: screen.getByRole("button", { name: "For taxes" }), next: screen.getByRole("button", { name: "Next card" }) };
  }
  const failing = () => Promise.reject(new ApiError(500, "Ordnung isn't reachable."));

  it("puts focus on the control the change was about when its Undo fails, not on <main>", async () => {
    const user = userEvent.setup();
    const { toggle, next } = page();
    act(() => void toast({ title: "Marked for taxes", undo: failing, focusIfUndoFails: () => toggle }));
    next.focus(); // the person went on before reaching for Undo
    const toastItem = item("Marked for taxes");
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(contents(toastItem)).toHaveAttribute("inert"));
    expect(toggle).toHaveFocus();
    await waitFor(() => expect(toastItem).not.toBeInTheDocument());
  });

  it("without that control, puts focus back where it was before it moved into the toast", async () => {
    const user = userEvent.setup();
    const { next } = page();
    act(() => void toast({ title: "Marked as paid", undo: failing, focusIfUndoFails: () => null }));
    next.focus(); // where the card that left handed focus
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(screen.queryByText("Marked as paid")).not.toBeInTheDocument());
    expect(next).toHaveFocus();
  });

  it("skips a control that is gone or disabled, and then takes the page's heading — never <main>", async () => {
    const user = userEvent.setup();
    const { toggle, next } = page();
    act(() => void toast({ title: "Marked for taxes", undo: failing, focusIfUndoFails: () => toggle }));
    next.focus();
    toggle.setAttribute("disabled", "");
    next.remove();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(screen.queryByText("Marked for taxes")).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Today" })).toHaveFocus();
  });

  it("counts an Undo that resolves false as failed (it said why itself)", async () => {
    const user = userEvent.setup();
    const { toggle } = page();
    act(() => void toast({ title: "Removed Erika", undo: async () => false, focusIfUndoFails: () => toggle }));
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(screen.queryByText("Removed Erika")).not.toBeInTheDocument());
    expect(toggle).toHaveFocus();
  });

  it("still hands focus to <main> after an Undo that works: the Undo's own code moves it on from there", async () => {
    const user = userEvent.setup();
    const { toggle, next } = page();
    act(() => void toast({ title: "Marked for taxes", undo: async () => {}, focusIfUndoFails: () => toggle }));
    next.focus();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(screen.queryByText("Marked for taxes")).not.toBeInTheDocument());
    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("is out of reach on phones too, when a newer toast takes its place", () => {
    viewport(390);
    renderWithProviders(<Toaster />);
    act(() => void toast({ title: "Tracking number removed", undo: () => {} }));
    const older = item("Tracking number removed");
    act(() => void toast({ title: "Marked as answered", undo: () => {} }));
    // only the newest is shown: the older one slides away (it waits its turn behind "+1 more")
    expect(older).toBeInTheDocument();
    expect(contents(older)).toHaveAttribute("inert");
    expect(screen.getAllByRole("button", { name: "Undo" })).toHaveLength(1);
  });
});

describe("Toast stack on phones", () => {
  it("shows only the newest toast with a +N button for the rest", async () => {
    viewport(390);
    const user = userEvent.setup();
    renderWithProviders(<Toaster />);
    act(() => {
      toast({ title: "One" });
      toast({ title: "Two" });
      toast({ title: "Three" });
    });
    expect(screen.getByText("Three")).toBeInTheDocument();
    expect(screen.queryByText("One")).not.toBeInTheDocument();
    const more = screen.getByRole("button", { name: "+2 more notifications" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    await user.click(more);
    expect(screen.getByText("One")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
  });

  it("uses one breakpoint for the column's width and alignment, 400 px like the upload cards", () => {
    renderWithProviders(<Toaster />);
    const column = screen.getByTestId("toaster");
    // full width on phones (12 px in), a right-aligned 400 px column (20 px in, plus its shadow
    // room) from tablets up
    expect(column.className).toMatch(/(^| )inset-x-0 .*(^| )px-3( |$)/);
    expect(column.className).toMatch(/md:inset-x-auto md:right-0 .*md:w-\[calc\(25rem\+2\.75rem\)\] .*md:pl-6 md:pr-5/);
    expect(column.className).not.toMatch(/\bsm:w-/);
  });

  it("publishes the height it covers, so page bottoms can pad by it", () => {
    const view = renderWithProviders(<Toaster />);
    // jsdom lays nothing out: 0px, but always set while the column is there
    expect(document.documentElement.style.getPropertyValue(TOAST_SPACE_VAR)).toBe("0px");
    view.unmount();
    expect(document.documentElement.style.getPropertyValue(TOAST_SPACE_VAR)).toBe("");
  });

  it("measures a toast where it comes to rest, not where its slide-in draws it for a moment", async () => {
    renderWithProviders(<Toaster />);
    const column = screen.getByTestId("toaster");
    column.style.paddingBottom = "20px";
    // a column 200 px tall whose toast box starts 40 px down it, drawn 16 px lower while it slides in
    // (nothing measures again when the slide ends: the column's size doesn't change)
    const isCard = (el: Element) => el.tagName === "LI";
    const drawn = (el: Element) => ({ top: isCard(el) ? 56 : 0, bottom: isCard(el) ? 180 : 200, left: 0, right: 400, width: 400, height: 0, x: 0, y: 0 });
    const spies = [
      vi.spyOn(Element.prototype, "clientHeight", "get").mockImplementation(function (this: Element) {
        return this === column ? 200 : 0;
      }),
      vi.spyOn(HTMLElement.prototype, "offsetParent", "get").mockImplementation(function (this: HTMLElement) {
        return isCard(this) ? column : null;
      }),
      vi.spyOn(HTMLElement.prototype, "offsetTop", "get").mockImplementation(function (this: HTMLElement) {
        return isCard(this) ? 40 : 0;
      }),
      vi.spyOn(Element.prototype, "getClientRects").mockImplementation(function (this: Element) {
        return (isCard(this) ? [drawn(this)] : []) as unknown as DOMRectList;
      }),
      vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
        return drawn(this) as DOMRect;
      }),
    ];
    try {
      act(() => {
        toast.error("That didn't work", { description: "Ordnung isn't reachable." });
      });
      // 200 − 20 (the column's bottom padding) − 40: where the toast comes to rest (not 180 − 56 = 124)
      await waitFor(() => expect(document.documentElement.style.getPropertyValue(TOAST_SPACE_VAR)).toBe("140px"));
    } finally {
      spies.forEach((s) => s.mockRestore());
    }
  });

  it("leaves room for the shadow inside its clip box", () => {
    renderWithProviders(<Toaster />);
    const column = screen.getByTestId("toaster");
    expect(column.className).toMatch(/\boverflow-hidden\b/);
    // 24 px above and below the stack (the side room reaches the screen edge)
    expect(column.className).toMatch(/(^| )-my-6( |$)/);
    expect(column.className).toMatch(/(^| )py-6( |$)/);
  });
});
