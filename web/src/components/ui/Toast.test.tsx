import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
