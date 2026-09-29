import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { focusAfterLeaving } from "./focus";

describe("focusAfterLeaving", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame", "performance", "setTimeout", "Date"] });
    document.body.innerHTML = `<h2 id="top3">Top 3</h2><h3 id="card-a">Pay the bill</h3><h3 id="card-b">Object to the order</h3>`;
  });
  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  const headings = () => Array.from(document.querySelectorAll<HTMLElement>("h3"));

  it("waits for a card whose exit is slow, then focuses the one now in its place (review round 4: focus was lost on a busy machine)", () => {
    focusAfterLeaving(headings, "card-a", "top3");
    vi.advanceTimersByTime(8_000);
    expect(document.activeElement).toBe(document.body);
    document.getElementById("card-a")?.remove();
    vi.advanceTimersByTime(50);
    expect(document.activeElement?.id).toBe("card-b");
  });

  it("never pulls back someone who moved on", () => {
    const other = document.createElement("button");
    document.body.append(other);
    focusAfterLeaving(headings, "card-a", "top3");
    other.focus();
    document.getElementById("card-a")?.remove();
    vi.advanceTimersByTime(50);
    expect(document.activeElement).toBe(other);
  });

  it("hands focus to the section heading when no card is left", () => {
    document.getElementById("card-b")?.remove();
    focusAfterLeaving(headings, "card-a", "top3");
    document.getElementById("card-a")?.remove();
    vi.advanceTimersByTime(50);
    expect(document.activeElement?.id).toBe("top3");
  });
});
