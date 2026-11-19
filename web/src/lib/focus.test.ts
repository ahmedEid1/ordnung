import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { focusAfterLeaving, focusOrigin, focusWhenReady, setToastHandBack } from "./focus";

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
