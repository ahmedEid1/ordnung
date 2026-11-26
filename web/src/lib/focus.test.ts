import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { focusAfterLeaving, focusOrigin, focusWhenReady, revealPlan, revealWhenStill, setToastHandBack } from "./focus";

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

  it("waits for a card whose exit is slow, then focuses the one now in its place (focus was once lost on a busy machine)", () => {
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

  it("focuses the card's own heading when the change is saved and the card stayed (a weekly date moved on)", () => {
    const settled = focusAfterLeaving(headings, "card-a", "top3");
    vi.advanceTimersByTime(500);
    settled();
    vi.advanceTimersByTime(50);
    expect(document.activeElement?.id).toBe("card-a");
    // and if it leaves after all, the card now in its place takes over
    document.getElementById("card-a")?.remove();
    vi.advanceTimersByTime(50);
    expect(document.activeElement?.id).toBe("card-b");
  });

  it("leaves focus where the person put it when the card stayed", () => {
    const other = document.createElement("button");
    document.body.append(other);
    const settled = focusAfterLeaving(headings, "card-a", "top3");
    other.focus();
    settled();
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

describe("focusWhenReady from where the action started", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame", "performance", "setTimeout", "Date"] });
    document.body.innerHTML = `<button id="find">Find</button><input id="name"><input id="choice"><ul><li data-toast="t1"><button id="undo">Undo</button></li></ul>`;
  });
  afterEach(() => {
    vi.useRealTimers();
    setToastHandBack(() => null);
    document.body.innerHTML = "";
  });
  const el = (id: string) => document.getElementById(id)!;

  it.each([
    ["moves focus while it is still on the control that was used", null, "choice"],
    ["leaves someone who went on to type elsewhere where they are", "name", "name"],
  ])("%s", (_, movedTo, focused) => {
    el("find").focus();
    const from = focusOrigin();
    if (movedTo) el(movedTo).focus();
    focusWhenReady(() => el("choice"), 5000, { from });
    vi.advanceTimersByTime(50);
    expect(document.activeElement?.id).toBe(focused);
  });

  it("starts an Undo pressed in a toast from where the closing toast hands focus back", () => {
    setToastHandBack(() => el("name"));
    el("undo").focus();
    const from = focusOrigin();
    expect(from).toBe(el("name"));
    // the toast closes and hands focus back before the answer is in
    el("name").focus();
    focusWhenReady(() => el("choice"), 5000, { from });
    vi.advanceTimersByTime(50);
    expect(el("choice")).toHaveFocus();
  });

  it("moves focus to a failed action's error wherever it is (`always`)", () => {
    el("name").focus();
    focusWhenReady(() => el("choice"), 5000, { always: true });
    vi.advanceTimersByTime(50);
    expect(el("choice")).toHaveFocus();
  });
});

describe("revealPlan: in view between the bars, not the window", () => {
  // a 320×568 phone: the top bar to 56, the tab bar from 504 (448 px between them)
  const phone = { top: 56, bottom: 504 };

  it("a card taller than the room comes in from its top (centred, its name ended under the top bar)", () => {
    // 533 px fits the 568 px window, but not the room the bars leave
    expect(revealPlan({ top: 17, bottom: 17 + 533 }, phone)).toEqual({ shown: false, block: "start" });
    // shown once its top is below the bar, in the upper half of the room
    expect(revealPlan({ top: 60, bottom: 60 + 533 }, phone)).toEqual({ shown: true, block: "start" });
    expect(revealPlan({ top: 300, bottom: 300 + 533 }, phone).shown).toBe(false);
  });

  it("a card the room holds is centred, also one that would not fit the root's scroll padding (446 px in 448)", () => {
    // the scroll padding (72 top, 80 bottom) leaves 416 px: measured against it, this card was pinned to the top
    expect(revealPlan({ top: 300, bottom: 300 + 446 }, phone)).toEqual({ shown: false, block: "center" });
    expect(revealPlan({ top: 57, bottom: 57 + 446 }, phone)).toEqual({ shown: true, block: "center" });
    // its bottom under the tab bar is not in view
    expect(revealPlan({ top: 70, bottom: 70 + 446 }, phone).shown).toBe(false);
  });
});

describe("revealWhenStill", () => {
  let card: HTMLElement;
  let top = 900;
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame", "performance"] });
    card = document.createElement("article");
    card.getBoundingClientRect = () => ({ top, bottom: top + 300, height: 300, left: 0, right: 300, width: 300, x: 0, y: top, toJSON: () => null });
    card.scrollIntoView = vi.fn();
    document.body.append(card);
    top = 900;
  });
  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("waits until the page stands still, then brings the card into view (centred, smoothly unless motion is reduced)", () => {
    const stop = revealWhenStill(card);
    // the page above it still grows: the card moves every frame
    for (let i = 0; i < 10; i++) {
      top += 40;
      vi.advanceTimersToNextFrame();
    }
    expect(card.scrollIntoView).not.toHaveBeenCalled();
    vi.advanceTimersByTime(200);
    expect(card.scrollIntoView).toHaveBeenCalledWith({ block: "center", behavior: "smooth" });
    stop();
  });

  it("stops for good when the person scrolls: no scrollIntoView follows their wheel", () => {
    const stop = revealWhenStill(card, { reducedMotion: true });
    vi.advanceTimersToNextFrame();
    window.dispatchEvent(new WheelEvent("wheel", { deltaY: 100 }));
    vi.advanceTimersByTime(2000);
    expect(card.scrollIntoView).not.toHaveBeenCalled();
    // the watch did run, and would have revealed it: without the wheel the same card is brought into view
    const again = revealWhenStill(card, { reducedMotion: true });
    vi.advanceTimersByTime(200);
    expect(card.scrollIntoView).toHaveBeenCalledWith({ block: "center", behavior: "auto" });
    again();
    stop();
  });
});
