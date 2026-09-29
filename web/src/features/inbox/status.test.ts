import { describe, expect, it } from "vitest";
import { emptyCopy, isNarrowed, resultLine, type InboxView } from "./status";

const view = (v: Partial<InboxView> = {}): InboxView => ({ filter: "all", kindLabel: null, typed: "", q: "", ...v });

describe("the Inbox's result line", () => {
  it("says nothing while the whole inbox shows", () => {
    expect(resultLine(view(), 22, 22, false)).toEqual({ text: "", visible: false });
    expect(isNarrowed(view())).toBe(false);
  });

  it("asks for one more letter instead of silently ignoring a 1-character search", () => {
    expect(resultLine(view({ typed: "M" }), 22, 22, false)).toEqual({ text: "Type one more letter to search.", visible: true });
  });

  it("counts the matches of a search, and leaves 'none' to the empty state on screen", () => {
    expect(resultLine(view({ typed: "Muster", q: "Muster" }), 20, 22, false)).toEqual({ text: "20 letters match “Muster”", visible: true });
    expect(resultLine(view({ typed: "Muster", q: "Muster" }), 1, 22, false).text).toBe("1 letter matches “Muster”");
    expect(resultLine(view({ typed: "Muster", q: "Muster" }), 0, 22, false)).toEqual({ text: "No letters match “Muster”", visible: false });
    expect(resultLine(view({ typed: "Muster", q: "Muster" }), 0, 22, true)).toEqual({ text: "Searching…", visible: true });
  });

  it("says how many of all letters a filter or kind shows", () => {
    expect(resultLine(view({ filter: "check" }), 1, 22, false)).toEqual({ text: "Showing 1 of 22 letters", visible: true });
    expect(resultLine(view({ kindLabel: "Invoice" }), 3, 22, false).text).toBe("Showing 3 of 22 letters");
    expect(resultLine(view({ filter: "private" }), 0, 22, false)).toEqual({ text: "No letters here", visible: false });
  });
});

describe("the Inbox's empty states", () => {
  it("offers to clear only the search when only the search found nothing", () => {
    expect(emptyCopy(view({ q: "Quittung 1999" }))).toMatchObject({ title: "No letters match “Quittung 1999”", action: "clear-search" });
  });

  it("explains Private, where nothing is yet", () => {
    const c = emptyCopy(view({ filter: "private" }));
    expect(c.title).toBe("No private letters");
    expect(c.description).toMatch(/“Keep private — no AI”.*Claude never reads them/);
    expect(c.action).toBe("add");
  });

  it("keeps the all-clear of Please check", () => {
    expect(emptyCopy(view({ filter: "check" }))).toMatchObject({ title: "Nothing to check", illustration: "clear", action: null });
  });

  it("names the kind and filter that left the list empty, and clears them all", () => {
    expect(emptyCopy(view({ kindLabel: "Tax assessment" }))).toMatchObject({ title: "No “Tax assessment” letters", action: "clear-filters" });
    expect(emptyCopy(view({ filter: "check", kindLabel: "Invoice" })).title).toBe("No “Invoice” letters to check");
    expect(emptyCopy(view({ filter: "private", kindLabel: "Invoice" })).title).toBe("No private “Invoice” letters");
    expect(emptyCopy(view({ filter: "check", q: "Muster" }))).toMatchObject({ title: "No letters match “Muster”", action: "clear-filters" });
  });
});
