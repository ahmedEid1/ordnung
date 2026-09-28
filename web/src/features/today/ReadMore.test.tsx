/**
 * ReadMore (UI audit round 2, R2-today-ask-1): a link below the cut takes keyboard focus; focusing it
 * opens the text from its first line instead of leaving the cut box scrolled to the link, while a link
 * in the lines that show (a mouse click on it) leaves the text as it is. jsdom has no layout: the cut and
 * the boxes are stubbed.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReadMore } from "./ReadMore";

function rect(top: number, bottom: number): DOMRect {
  return { top, bottom, left: 0, right: 300, width: 300, height: bottom - top, x: 0, y: top, toJSON: () => ({}) } as DOMRect;
}

beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(private cb: () => void) {}
      observe() {
        this.cb();
      }
      unobserve() {}
      disconnect() {}
    },
  );
  // four lines show (88 px of 132): the paragraph is cut
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(132);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(88);
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    if (this.tagName === "P") return rect(0, 88);
    // "Law: …" in line 1; "Advice: …" in line 6, below the cut
    return this.textContent === "gesetze-im-internet.de" ? rect(0, 22) : rect(110, 132);
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function renderIdea() {
  render(
    <>
      <h3 tabIndex={-1}>Working on a student permit: know your limits</h3>
      <ReadMore>
        Law: <a href="https://www.gesetze-im-internet.de/aufenthg_2004/__16b.html">gesetze-im-internet.de</a> — a student permit allows 140 full days of
        work a year (§ 16b AufenthG). Check the conditions printed on your permit and ask the Studierendenwerk before taking on more. Advice:{" "}
        <a href="https://www.studierendenwerke.de">studierendenwerke.de</a>
      </ReadMore>
    </>,
  );
  const text = screen.getByText(/a student permit allows/);
  return { text, more: screen.getByRole("button", { name: "Read more" }) };
}

describe("ReadMore", () => {
  it("opens the text from its first line when a link below the cut takes focus", async () => {
    const user = userEvent.setup();
    const { text, more } = renderIdea();
    expect(text.className).toContain("line-clamp-4");
    expect(more).toHaveAttribute("aria-expanded", "false");
    // the UI audit's clipped-content probe reads this: the links cut off here are reachable
    expect(text).toHaveAttribute("data-opens-on-focus");

    act(() => screen.getByRole("heading").focus());
    await user.tab(); // "gesetze-im-internet.de", in the first line: nothing changes
    expect(screen.getByRole("link", { name: "gesetze-im-internet.de" })).toHaveFocus();
    expect(text.className).toContain("line-clamp-4");

    // the browser scrolls the cut box to the next link before focus handlers run
    text.scrollTop = 44;
    await user.tab();
    expect(screen.getByRole("link", { name: "studierendenwerke.de" })).toHaveFocus();
    expect(text.className).not.toContain("line-clamp");
    expect(text.scrollTop).toBe(0);
    expect(screen.getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
  });

  it("opens the text for a link below the cut even when the box has not scrolled yet", async () => {
    const user = userEvent.setup();
    const { text } = renderIdea();
    act(() => screen.getByRole("link", { name: "gesetze-im-internet.de" }).focus());
    await user.tab();
    expect(text.className).not.toContain("line-clamp");
  });

  it("cuts the text again from its first line on Show less", async () => {
    const user = userEvent.setup();
    const { text } = renderIdea();
    act(() => screen.getByRole("link", { name: "studierendenwerke.de" }).focus());
    expect(text.className).not.toContain("line-clamp");
    text.scrollTop = 44;
    await user.click(screen.getByRole("button", { name: "Show less" }));
    expect(text.className).toContain("line-clamp-4");
    expect(text.scrollTop).toBe(0);
    expect(screen.getByRole("button", { name: "Read more" })).toHaveAttribute("aria-expanded", "false");
  });
});
