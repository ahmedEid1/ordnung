import { describe, expect, it } from "vitest";
import { labelInName } from "./labelInName";

const el = (html: string): Element => {
  const box = document.createElement("div");
  box.innerHTML = html;
  return box.firstElementChild!;
};

describe("labelInName (axe's Label in Name check, in jsdom)", () => {
  it("fails a name that leaves out what the control shows, as axe 4.14 did on the Inbox link and a sender chip", () => {
    expect(labelInName(el(`<a aria-label="Inbox, 1 letter to check"><span>Inbox</span><span>1</span></a>`))).toMatchObject({ ok: false, shown: "Inbox1" });
    // initials hidden from screen readers are still on screen
    expect(labelInName(el(`<button aria-label="Muster BKK — open details"><span aria-hidden="true">MB</span><span>Muster BKK</span></button>`)).ok).toBe(false);
  });

  it("passes a name that holds what is shown, word for word and in order, whatever the punctuation", () => {
    expect(labelInName(el(`<button aria-label="Demo tour · 1 of 4: Ideas — show the whole step"><span>Demo tour · 1 of 4</span> <span>Ideas</span></button>`)).ok).toBe(true);
    expect(labelInName(el(`<button aria-label="Ideas, 1 of 4"><span>1 of 4</span> <span>Ideas</span></button>`)).ok).toBe(false);
  });

  it("leaves out visually hidden text, and has nothing to check on a control named by its content", () => {
    expect(labelInName(el(`<a aria-label="Inbox"><span>Inbox</span><span class="sr-only">, 2 to check</span></a>`)).ok).toBe(true);
    expect(labelInName(el(`<a><span aria-hidden="true">SR</span><span>Sam</span></a>`))).toMatchObject({ ok: true, name: "" });
  });
});
