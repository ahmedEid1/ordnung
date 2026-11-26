import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { focusAfterLeaving, focusOrigin, focusWhenReady, freeBand, revealPlan, revealWhenStill, setToastHandBack } from "./focus";

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

describe("freeBand: the room the bars really leave", () => {
  // a 320×568 phone as Chromium answers it: nothing at all at innerHeight - 0.5, the bars at whole pixels
  const boxes: { el: HTMLElement; top: number; bottom: number }[] = [];
  const bar = (tag: string, top: number, bottom: number) => {
    const el = document.createElement(tag);
    el.style.position = "fixed";
    el.getBoundingClientRect = () => ({ top, bottom, height: bottom - top, left: 0, right: 320, width: 320, x: 0, y: top, toJSON: () => null });
    document.body.append(el);
    boxes.push({ el, top, bottom });
  };
  const height = window.innerHeight;
  beforeEach(() => {
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 568 });
    document.elementsFromPoint = (_x: number, y: number) =>
      y >= window.innerHeight - 0.5 ? [] : boxes.filter((b) => y >= b.top && y < b.bottom).map((b) => b.el);
  });
  afterEach(() => {
    Object.defineProperty(window, "innerHeight", { configurable: true, value: height });
    // @ts-expect-error -- jsdom has none: put it back as it was
    delete document.elementsFromPoint;
    boxes.length = 0;
    document.body.innerHTML = "";
  });

  it("finds the tab bar at the window's bottom edge (probed at innerHeight - 0.5 it found nothing)", () => {
    bar("header", 0, 56);
    bar("nav", 504, 568);
    expect(freeBand(160)).toEqual({ top: 56, bottom: 504 });
  });

  it("finds the demo's tour bar floating just above the tab bar", () => {
    bar("header", 0, 56);
    bar("nav", 504, 568);
    bar("section", 438, 492);
    expect(freeBand(160)).toEqual({ top: 56, bottom: 438 });
  });

  it("is the whole window when no bar is there", () => {
    expect(freeBand(160)).toEqual({ top: 0, bottom: 568 });
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

  describe("the person's scroll wins over one already under way", () => {
    let y = 0;
    let height = 3000;
    beforeEach(() => {
      y = 0;
      height = 3000;
      Object.defineProperty(window, "scrollY", { configurable: true, get: () => y });
      Object.defineProperty(document.documentElement, "scrollHeight", { configurable: true, get: () => height });
      vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    });
    afterEach(() => {
      // @ts-expect-error -- back to jsdom's own
      delete window.scrollY;
      // @ts-expect-error -- back to jsdom's own
      delete document.documentElement.scrollHeight;
      vi.restoreAllMocks();
    });

    it("a wheel during its smooth scroll stops that scroll where it is (it went on to the card, against the wheel)", () => {
      const stop = revealWhenStill(card);
      // still for four frames after the first: revealed
      for (let i = 0; i < 5; i++) vi.advanceTimersToNextFrame();
      expect(card.scrollIntoView).toHaveBeenCalledTimes(1);
      // the smooth scroll is under way: the page moves
      y = 100;
      top = 800;
      vi.advanceTimersToNextFrame();
      window.dispatchEvent(new WheelEvent("wheel", { deltaY: -300 }));
      expect(window.scrollTo).toHaveBeenCalledWith({ top: 100, behavior: "instant" });
      vi.advanceTimersByTime(2000);
      expect(card.scrollIntoView).toHaveBeenCalledTimes(1);
      stop();
    });

    it("and the wheel's own scroll is done from there (stopping the smooth scroll, Chromium drops it)", () => {
      y = 400;
      const stop = revealWhenStill(card);
      for (let i = 0; i < 5; i++) vi.advanceTimersToNextFrame();
      expect(card.scrollIntoView).toHaveBeenCalledTimes(1);
      const wheel = new WheelEvent("wheel", { deltaY: -300, cancelable: true });
      window.dispatchEvent(wheel);
      expect(wheel.defaultPrevented).toBe(true);
      expect(window.scrollTo).toHaveBeenCalledWith({ top: 100, behavior: "instant" });
      stop();
    });

    /** Revealed with motion on, its smooth scroll under way (the page has moved since): the stop it returns. */
    const underWay = () => {
      const stop = revealWhenStill(card);
      for (let i = 0; i < 5; i++) vi.advanceTimersToNextFrame();
      expect(card.scrollIntoView).toHaveBeenCalledTimes(1);
      y = 100;
      top = 800;
      vi.advanceTimersToNextFrame();
      return stop;
    };

    it.each(["Shift", "Control"])("%s on its own (Shift+Tab begun, a screen reader quieted) neither stops that scroll nor the watch", (key) => {
      const stop = underWay();
      const press = new KeyboardEvent("keydown", { key, cancelable: true, bubbles: true });
      document.body.dispatchEvent(press);
      expect(window.scrollTo).not.toHaveBeenCalled();
      expect(press.defaultPrevented).toBe(false);
      // the watch goes on: the smooth scroll ends short (the page still grew), and the card is brought into view again
      top = 900;
      vi.advanceTimersByTime(200);
      expect((card.scrollIntoView as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(1);
      stop();
    });

    it("a key that scrolls nothing (Tab) leaves that scroll to reach the card", () => {
      const stop = underWay();
      document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
      expect(window.scrollTo).not.toHaveBeenCalled();
      stop();
    });

    it.each(["PageDown", "ArrowUp", " "])("a key that scrolls (%j) stops that scroll where it is, and the watch", (key) => {
      const stop = underWay();
      document.body.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
      expect(window.scrollTo).toHaveBeenCalledWith({ top: 100, behavior: "instant" });
      top = 900;
      vi.advanceTimersByTime(2000);
      expect(card.scrollIntoView).toHaveBeenCalledTimes(1);
      stop();
    });

    it("but Space in a field types a space: it scrolls nothing", () => {
      const stop = underWay();
      const field = document.createElement("input");
      document.body.append(field);
      field.dispatchEvent(new KeyboardEvent("keydown", { key: " ", bubbles: true }));
      expect(window.scrollTo).not.toHaveBeenCalled();
      stop();
    });

    it("a sideways wheel (the lanes chart) stops that scroll but goes on as it came: not taken over", () => {
      const stop = underWay();
      const wheel = new WheelEvent("wheel", { deltaX: 120, deltaY: 0, cancelable: true });
      window.dispatchEvent(wheel);
      expect(wheel.defaultPrevented).toBe(false);
      expect(window.scrollTo).toHaveBeenCalledWith({ top: 100, behavior: "instant" });
      stop();
    });

    it("a wheel that goes more sideways than down (a diagonal swipe on a touchpad) is not taken over either", () => {
      const stop = underWay();
      const wheel = new WheelEvent("wheel", { deltaX: 300, deltaY: 50, cancelable: true });
      window.dispatchEvent(wheel);
      expect(wheel.defaultPrevented).toBe(false);
      // stopped where it is, without the wheel's 50 px added by hand: the browser does the wheel as it came
      expect(window.scrollTo).toHaveBeenCalledWith({ top: 100, behavior: "instant" });
      stop();
    });

    it.each([
      ["Control", { ctrlKey: true }],
      ["Alt", { altKey: true }],
      ["Meta", { metaKey: true }],
    ])("an arrow or End with %s held (a shortcut, not a scroll) leaves that scroll to reach the card", (_name, held) => {
      const stop = underWay();
      document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, ...held }));
      document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true, ...held }));
      expect(window.scrollTo).not.toHaveBeenCalled();
      stop();
    });

    it("a touch stops that scroll where it is, and the watch (the finger takes the page from there)", () => {
      const stop = underWay();
      window.dispatchEvent(new Event("touchstart"));
      expect(window.scrollTo).toHaveBeenCalledWith({ top: 100, behavior: "instant" });
      top = 900;
      vi.advanceTimersByTime(2000);
      expect(card.scrollIntoView).toHaveBeenCalledTimes(1);
      stop();
    });

    it("a wheel once the page stands still stops nothing that is not there", () => {
      top = 200;
      const stop = revealWhenStill(card);
      vi.advanceTimersByTime(200);
      expect(card.scrollIntoView).not.toHaveBeenCalled();
      window.dispatchEvent(new WheelEvent("wheel", { deltaY: -300 }));
      expect(window.scrollTo).not.toHaveBeenCalled();
      stop();
    });

    it("a scroll that comes with no wheel, touch, key or press (the scroll bar dragged) is the person's: not undone", () => {
      (card.scrollIntoView as ReturnType<typeof vi.fn>).mockImplementation(() => {
        y = 700;
        top = 200;
      });
      const stop = revealWhenStill(card, { reducedMotion: true });
      vi.advanceTimersByTime(200);
      expect(card.scrollIntoView).toHaveBeenCalledTimes(1);
      // shown, and the page stands still; then the person drags the scroll bar back to the top
      y = 0;
      top = 900;
      vi.advanceTimersByTime(2000);
      expect(card.scrollIntoView).toHaveBeenCalledTimes(1);
      stop();
    });

    it("but the page growing above the card is not a scroll of the person's: the card is brought back (the control)", () => {
      (card.scrollIntoView as ReturnType<typeof vi.fn>).mockImplementation(() => {
        y = 700;
        top = 200;
      });
      const stop = revealWhenStill(card, { reducedMotion: true });
      vi.advanceTimersByTime(200);
      expect(card.scrollIntoView).toHaveBeenCalledTimes(1);
      // what is above it loads: the page is taller and the card further down
      height = 3700;
      top = 900;
      vi.advanceTimersByTime(2000);
      expect(card.scrollIntoView).toHaveBeenCalledTimes(2);
      stop();
    });
  });
});
