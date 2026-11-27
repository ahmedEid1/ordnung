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
    // shown once it starts just below the bar (its scroll margins land it 4 px below)
    expect(revealPlan({ top: 60, bottom: 60 + 533 }, phone)).toEqual({ shown: true, block: "start" });
    expect(revealPlan({ top: 64, bottom: 64 + 533 }, phone).shown).toBe(true);
    // pushed 54 px further down by the page, its name is no longer the first thing under the bar: not in view (it
    // once was, anywhere in the room's upper half, and stayed there)
    expect(revealPlan({ top: 114, bottom: 114 + 533 }, phone).shown).toBe(false);
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

  describe("the page changes after the card was placed: it is put back where it belongs (a 320×568 phone)", () => {
    let y = 0;
    let height = 3000;
    let cardHeight = 403;
    const bars: { el: HTMLElement; top: number; bottom: number }[] = [];
    const bar = (tag: string, barTop: number, barBottom: number) => {
      const el = document.createElement(tag);
      el.style.position = "fixed";
      el.getBoundingClientRect = () => ({ top: barTop, bottom: barBottom, height: barBottom - barTop, left: 0, right: 320, width: 320, x: 0, y: barTop, toJSON: () => null });
      document.body.append(el);
      bars.push({ el, top: barTop, bottom: barBottom });
    };
    const innerHeight = window.innerHeight;
    /** Where scrollIntoView puts the card: "start" 4 px below the top bar, "center" in the middle of the room. */
    const lands = (room: { top: number; bottom: number }) => (options?: boolean | ScrollIntoViewOptions) => {
      const block = typeof options === "object" ? options.block : "start";
      const to = block === "center" ? room.top + (room.bottom - room.top - cardHeight) / 2 : 60;
      y += top - to;
      top = to;
    };
    beforeEach(() => {
      y = 0;
      height = 3000;
      cardHeight = 403;
      top = 900;
      Object.defineProperty(window, "innerHeight", { configurable: true, value: 568 });
      Object.defineProperty(window, "scrollY", { configurable: true, get: () => y });
      Object.defineProperty(document.documentElement, "scrollHeight", { configurable: true, get: () => height });
      card.getBoundingClientRect = () => ({ top, bottom: top + cardHeight, height: cardHeight, left: 0, right: 320, width: 320, x: 0, y: top, toJSON: () => null });
      document.elementsFromPoint = (_x: number, at: number) =>
        at >= window.innerHeight - 0.5 ? [] : bars.filter((b) => at >= b.top && at < b.bottom).map((b) => b.el);
      bar("header", 0, 56);
      bar("nav", 504, 568);
    });
    afterEach(() => {
      Object.defineProperty(window, "innerHeight", { configurable: true, value: innerHeight });
      // @ts-expect-error -- back to jsdom's own
      delete window.scrollY;
      // @ts-expect-error -- back to jsdom's own
      delete document.documentElement.scrollHeight;
      // @ts-expect-error -- jsdom has none: put it back as it was
      delete document.elementsFromPoint;
      bars.length = 0;
    });

    it("a card that fitted starts below the top bar once a bar that arrived late leaves too little room (the demo's tour bar)", () => {
      (card.scrollIntoView as ReturnType<typeof vi.fn>).mockImplementation(lands({ top: 56, bottom: 504 }));
      const stop = revealWhenStill(card, { reducedMotion: true });
      vi.advanceTimersByTime(200);
      // 403 px fits the 448 px between the bars: centred, at 78.5
      expect(card.scrollIntoView).toHaveBeenLastCalledWith({ block: "center", behavior: "auto" });
      expect(top).toBe(78.5);
      // the tour bar comes after it (its code loads on its own), floating above the tab bar; the page keeps room for it
      bar("section", 438, 492);
      height += 66;
      vi.advanceTimersByTime(500);
      // 382 px are left: the card is too tall for them now and starts just below the top bar (centred it stayed
      // there, its name 23 px down and its bottom under the tour bar)
      expect(card.scrollIntoView).toHaveBeenCalledTimes(2);
      expect(card.scrollIntoView).toHaveBeenLastCalledWith({ block: "start", behavior: "auto" });
      expect(top).toBe(60);
      stop();
    });

    describe("a scroll back during its smooth reveal, with motion on", () => {
      /** Centred at once; its smooth "start" moves nothing by itself: each case moves the page frame by frame. */
      const placeThenTourBar = (setOff = 3) => {
        const centre = lands({ top: 56, bottom: 504 });
        (card.scrollIntoView as ReturnType<typeof vi.fn>).mockImplementation((options?: boolean | ScrollIntoViewOptions) => {
          if (typeof options === "object" && options.block === "center") centre(options);
        });
        const stop = revealWhenStill(card);
        vi.advanceTimersByTime(200);
        expect(top).toBe(78.5);
        // the tour bar arrives late, the page keeps room for it, and the card is too tall for what is left
        bar("section", 438, 492);
        height += 66;
        // (frame by frame: its smooth scroll starts in the frame after the call)
        for (let i = 0; i < 30 && (card.scrollIntoView as ReturnType<typeof vi.fn>).mock.calls.length < 2; i++) vi.advanceTimersToNextFrame();
        expect(card.scrollIntoView).toHaveBeenCalledTimes(2);
        expect(card.scrollIntoView).toHaveBeenLastCalledWith({ block: "start", behavior: "smooth" });
        // its smooth scroll sets off towards the card
        for (let i = 0; i < setOff; i++) {
          y += 3;
          top -= 3;
          vi.advanceTimersToNextFrame();
        }
        return stop;
      };

      it("with no input event (an assistive technology, a script) is someone else's: it wins, no reveal follows", () => {
        const stop = placeThenTourBar();
        // the page goes back up, its height unchanged: a scroll of its own never turns round
        for (let i = 0; i < 3; i++) {
          y -= 15;
          top += 15;
          vi.advanceTimersToNextFrame();
        }
        vi.advanceTimersByTime(2000);
        // (it was fought before: revealed again each time the page stood still)
        expect(card.scrollIntoView).toHaveBeenCalledTimes(2);
        stop();
      });

      it("also in its first frame, before its own scroll has moved", () => {
        const stop = placeThenTourBar(0);
        y -= 150;
        top += 150;
        vi.advanceTimersByTime(2000);
        expect(card.scrollIntoView).toHaveBeenCalledTimes(2);
        stop();
      });

      it("but the page shrinking above the card moves it back without anyone scrolling: it is brought there again (the control)", () => {
        const stop = placeThenTourBar();
        // a block above it goes: the page is shorter and the browser keeps the card's place by scrolling up
        height -= 45;
        y -= 45;
        vi.advanceTimersByTime(2000);
        expect(card.scrollIntoView).toHaveBeenCalledTimes(3);
        stop();
      });
    });

    describe("a scroll the same way as its reveal, during it, with no input event (an assistive technology, a script)", () => {
      /** Centred at once, then the late tour bar: a second reveal ("start"), whose smooth scroll each case moves. */
      const placeThenTourBar = ({ reducedMotion = false } = {}) => {
        const centre = lands({ top: 56, bottom: 504 });
        (card.scrollIntoView as ReturnType<typeof vi.fn>).mockImplementation((options?: boolean | ScrollIntoViewOptions) => {
          // with motion reduced the second reveal lands at once, 4 px below the top bar
          if (typeof options === "object" && (options.block === "center" || reducedMotion)) centre(options);
        });
        const stop = revealWhenStill(card, { reducedMotion });
        vi.advanceTimersByTime(200);
        bar("section", 438, 492);
        height += 66;
        for (let i = 0; i < 30 && (card.scrollIntoView as ReturnType<typeof vi.fn>).mock.calls.length < 2; i++) vi.advanceTimersToNextFrame();
        expect(card.scrollIntoView).toHaveBeenLastCalledWith({ block: "start", behavior: reducedMotion ? "auto" : "smooth" });
        return stop;
      };

      it("taking the page past the card is someone else's: it wins, the page is not pulled back to the card", () => {
        const stop = placeThenTourBar();
        // two frames of its own smooth scroll, then a script scrolls on by 300 px
        for (let i = 0; i < 2; i++) {
          y += 3;
          top -= 3;
          vi.advanceTimersToNextFrame();
        }
        y += 300;
        top -= 300;
        vi.advanceTimersByTime(2000);
        // (a reveal of its own ends where it aimed: it was revealed again, and the page pulled back)
        expect(card.scrollIntoView).toHaveBeenCalledTimes(2);
        expect(top).toBe(-227.5);
        stop();
      });

      it("also with motion reduced, the scroll coming in the frame after its reveal landed", () => {
        const stop = placeThenTourBar({ reducedMotion: true });
        expect(top).toBe(60);
        y += 300;
        top -= 300;
        vi.advanceTimersByTime(2000);
        expect(card.scrollIntoView).toHaveBeenCalledTimes(2);
        expect(top).toBe(-240);
        stop();
      });

      it("the tour bar still settling into place meanwhile (its last 4 px) leaves the same room: that scroll still wins", () => {
        const stop = placeThenTourBar();
        y += 3;
        top -= 3;
        bars.pop()!.el.remove();
        bar("section", 434, 488);
        vi.advanceTimersToNextFrame();
        y += 300;
        top -= 300;
        vi.advanceTimersByTime(2000);
        expect(card.scrollIntoView).toHaveBeenCalledTimes(2);
        stop();
      });

      it("but cut short of the card it is revealed again: on a slow machine the router's scroll to the top does that too", () => {
        const stop = placeThenTourBar();
        // its smooth scroll stops 9 px down, and the page stands still there, the card short of where it belongs
        for (let i = 0; i < 3; i++) {
          y += 3;
          top -= 3;
          vi.advanceTimersToNextFrame();
        }
        vi.advanceTimersByTime(2000);
        // (a scroll by script that stops it there is not told apart from that, and is undone)
        expect(card.scrollIntoView).toHaveBeenCalledTimes(3);
        stop();
      });

      it("and a bar arriving during its smooth scroll leaves the card past a top that moved: it is revealed again (the control)", () => {
        const stop = placeThenTourBar();
        for (let i = 0; i < 6; i++) {
          y += 3;
          top -= 3;
          vi.advanceTimersToNextFrame();
        }
        // a banner comes under the top bar, the page's height the same: the card is above the room's new top, though its
        // own scroll ended where it aimed
        bar("div", 0, 116);
        y += 0.5;
        top -= 0.5;
        vi.advanceTimersByTime(2000);
        expect(top).toBe(60);
        expect(card.scrollIntoView).toHaveBeenCalledTimes(3);
        stop();
      });
    });

    it("a tall card the page then pushes down is put back just below the top bar", () => {
      cardHeight = 533;
      (card.scrollIntoView as ReturnType<typeof vi.fn>).mockImplementation(lands({ top: 56, bottom: 504 }));
      const stop = revealWhenStill(card, { reducedMotion: true });
      vi.advanceTimersByTime(200);
      expect(card.scrollIntoView).toHaveBeenCalledWith({ block: "start", behavior: "auto" });
      expect(top).toBe(60);
      // something above it changes after all and the browser does not keep its place: 54 px further down
      height += 54;
      top += 54;
      vi.advanceTimersByTime(500);
      expect(card.scrollIntoView).toHaveBeenCalledTimes(2);
      expect(top).toBe(60);
      stop();
    });

    it("a tall card the page cannot bring further up (near its end) is left where its reveal put it: no reveal again and again", () => {
      cardHeight = 533;
      // the page is scrolled as far as it goes: the card stays 150 px down
      (card.scrollIntoView as ReturnType<typeof vi.fn>).mockImplementation(() => {
        y += top - 150;
        top = 150;
      });
      const stop = revealWhenStill(card, { reducedMotion: true });
      vi.advanceTimersByTime(3000);
      // once more from there, which moves nothing: then it is left as it is
      expect(card.scrollIntoView).toHaveBeenCalledTimes(2);
      // but once the page changes (it grew below the card), the card can come up and is brought there
      (card.scrollIntoView as ReturnType<typeof vi.fn>).mockImplementation(lands({ top: 56, bottom: 504 }));
      height += 400;
      vi.advanceTimersByTime(500);
      expect(card.scrollIntoView).toHaveBeenCalledTimes(3);
      expect(top).toBe(60);
      stop();
    });
  });
});
