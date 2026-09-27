import { describe, expect, it } from "vitest";
import { TOUR_STEPS, stepCopy } from "./steps";
import { SPOT_PAD, spotlightBox } from "./useSpotlight";

const [newMail, idea, ask] = TOUR_STEPS as [(typeof TOUR_STEPS)[number], (typeof TOUR_STEPS)[number], (typeof TOUR_STEPS)[number]];

describe("step copy follows the demo", () => {
  it("the New-mail step counts the letters still in the tray", () => {
    expect(stepCopy(newMail, { tray: { unread: 3, total: 3 } }).body).toMatch(/^Three letters just arrived for Sam\. Open one and watch/);
    expect(stepCopy(newMail, { tray: { unread: 2, total: 3 } }).body).toMatch(/^Two letters are still waiting for Sam\. Open another .* or go on and see what your secretary suggests\.$/);
    expect(stepCopy(newMail, { tray: { unread: 1, total: 3 } }).body).toMatch(/^One letter is still waiting for Sam\. Open it /);
    const done = stepCopy(newMail, { tray: { unread: 0, total: 3 } });
    expect(done.title).toBe("All new mail read");
    expect(done.body).toMatch(/Next, see what your secretary suggests/);
    // unknown (still loading): as written
    expect(stepCopy(newMail)).toBe(newMail);
  });

  it("the Idea step says an Idea arrived only when a letter brought one", () => {
    expect(stepCopy(idea).title).toBe("Ideas from your secretary");
    expect(stepCopy(idea, { ideaFromMail: false }).title).toBe("Ideas from your secretary");
    expect(stepCopy(idea, { ideaFromMail: true })).toMatchObject({ title: "An idea just arrived", showLabel: "Show me the Idea" });
  });

  it("no stray punctuation after a quoted question", () => {
    for (const s of TOUR_STEPS) expect(s.body).not.toMatch(/[?!]”[.,]/);
    expect(ask.body).toContain("cancel it?” Answers");
  });
});

describe("the spotlight ring", () => {
  const view = { width: 390, height: 844 };

  it("sits 8 px around the element", () => {
    expect(SPOT_PAD).toBe(8);
    expect(spotlightBox({ top: 200, left: 40, width: 300, height: 120 }, view)).toEqual({ top: 192, left: 32, width: 316, height: 136 });
  });

  it("stays on the visible page: 8 px from the screen's sides, clear of the top bar and the bottom bars", () => {
    // a full-width element: the ring never hugs the screen edge
    expect(spotlightBox({ top: 200, left: 0, width: 390, height: 120 }, view)).toMatchObject({ left: 8, width: 374 });
    // taller than the screen: a closed ring around the visible part, not two lines running off it
    const tall = spotlightBox({ top: -400, left: 16, width: 358, height: 2000 }, view, { top: 72, bottom: 140 });
    expect(tall).toEqual({ top: 64, left: 8, width: 374, height: 844 - 132 - 64 });
  });

  it("is hidden when the element is scrolled away", () => {
    expect(spotlightBox({ top: 1200, left: 16, width: 358, height: 200 }, view)).toBeNull();
    expect(spotlightBox({ top: -300, left: 16, width: 358, height: 200 }, view, { top: 72, bottom: 0 })).toBeNull();
  });
});
