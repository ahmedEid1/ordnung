import { describe, expect, it } from "vitest";
import { emptyCopy, isNarrowed, resultLine, type InboxView } from "./status";

const view = (v: Partial<InboxView> = {}): InboxView => ({ filter: "all", kindLabel: null, typed: "", q: "", year: null, who: null, ...v });

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

  it("counts the waiting letters a search found too: they show above, in their own group", () => {
    expect(resultLine(view({ typed: "Rechnung", q: "Rechnung" }), 2, 22, false, 1)).toEqual({ text: "2 letters match “Rechnung”, and 1 not read yet (above)", visible: true });
    expect(resultLine(view({ typed: "Rechnung", q: "Rechnung" }), 1, 22, false, 2).text).toBe("1 letter matches “Rechnung”, and 2 not read yet (above)");
    // only waiting letters match: the empty state on screen says so
    expect(resultLine(view({ typed: "Wasserzähler", q: "Wasserzähler" }), 0, 22, false, 1)).toEqual({ text: "1 letter not read yet matches “Wasserzähler”", visible: false });
    expect(resultLine(view({ typed: "Rechnung", q: "Rechnung" }), 0, 22, false, 2).text).toBe("2 letters not read yet match “Rechnung”");
    expect(resultLine(view({ typed: "Rechnung", q: "Rechnung" }), 0, 22, true, 2).text).toBe("Searching…");
  });

  it("says how many of all letters a filter or kind shows", () => {
    expect(resultLine(view({ filter: "check" }), 1, 22, false)).toEqual({ text: "Showing 1 of 22 letters", visible: true });
    expect(resultLine(view({ kindLabel: "Invoice" }), 3, 22, false).text).toBe("Showing 3 of 22 letters");
    expect(resultLine(view({ filter: "private" }), 0, 22, false)).toEqual({ text: "No letters here", visible: false });
  });

  it("counts a year and whose letters as filters too", () => {
    expect(isNarrowed(view({ year: 2025 }))).toBe(true);
    expect(resultLine(view({ year: 2025 }), 4, 22, false)).toEqual({ text: "Showing 4 of 22 letters", visible: true });
    expect(isNarrowed(view({ who: { kind: "mine" } }))).toBe(true);
    expect(resultLine(view({ who: { kind: "person", name: "Alex Rivera", suggested: 0 } }), 3, 22, false).text).toBe("Showing 3 of 22 letters");
  });
});

describe("the Inbox's empty states", () => {
  it("offers to clear only the search when only the search found nothing", () => {
    expect(emptyCopy(view({ q: "Quittung 1999" }))).toMatchObject({ title: "No letters match “Quittung 1999”", action: "clear-search" });
  });

  it("never says no letter matches when a waiting letter does: it points up to it", () => {
    expect(emptyCopy(view({ q: "Wasserzähler" }), false, 1)).toEqual({
      title: "1 letter not read yet matches “Wasserzähler”",
      description: "It's above, in “From your folder — not read yet”. No other letter matches.",
      illustration: "search",
      action: "clear-search",
    });
    expect(emptyCopy(view({ q: "Rechnung" }), false, 2)).toMatchObject({
      title: "2 letters not read yet match “Rechnung”",
      description: "They're above, in “From your folder — not read yet”. No other letter matches.",
    });
    // a filter or a kind leaves the waiting letters alone (they are in none): only the read letters are narrowed
    expect(emptyCopy(view({ q: "Rechnung", filter: "check" }), false, 1)).toEqual({
      title: "1 letter not read yet matches “Rechnung”",
      description: "It's above, in “From your folder — not read yet”. Filters are on as well — clear them to search all your letters.",
      illustration: "search",
      action: "clear-filters",
    });
    expect(emptyCopy(view({ q: "Rechnung", kindLabel: "Invoice" }), false, 1).action).toBe("clear-filters");
    // without a search the waiting letters change nothing
    expect(emptyCopy(view({ filter: "check" }), false, 1).title).toBe("Nothing to check");
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

  it("an empty year says “No letters dated 2019”", () => {
    expect(emptyCopy(view({ year: 2019 }))).toEqual({
      title: "No letters dated 2019",
      description: "Ordnung files a letter under the year of the date on it, else the day it arrived. Choose another year, or clear the filters.",
      illustration: "search",
      action: "clear-filters",
    });
    // with a kind, a tab or a search as well: the year joins their words
    expect(emptyCopy(view({ year: 2025, kindLabel: "Invoice" }))).toMatchObject({ title: "No “Invoice” letters dated 2025", description: "Clear the filters to see all your letters." });
    expect(emptyCopy(view({ year: 2025, filter: "private" }))).toMatchObject({ title: "No private letters dated 2025", action: "clear-filters" });
    expect(emptyCopy(view({ year: 2025, filter: "check" }))).toMatchObject({ title: "No letters dated 2025 to check", action: "clear-filters" });
    expect(emptyCopy(view({ year: 2025, filter: "check", kindLabel: "Invoice" })).title).toBe("No “Invoice” letters dated 2025 to check");
    expect(emptyCopy(view({ year: 2025, q: "Muster" }))).toEqual({
      title: "No letters match “Muster”",
      description: "Filters are on as well — clear them to search all your letters.",
      illustration: "search",
      action: "clear-filters",
    });
  });

  it("a year counts as a filter for the waiting letters' search state", () => {
    expect(emptyCopy(view({ q: "Rechnung", year: 2025 }), false, 1)).toEqual({
      title: "1 letter not read yet matches “Rechnung”",
      description: "It's above, in “From your folder — not read yet”. Filters are on as well — clear them to search all your letters.",
      illustration: "search",
      action: "clear-filters",
    });
    expect(emptyCopy(view({ q: "Rechnung", who: { kind: "mine" } }), false, 1).action).toBe("clear-filters");
  });

  it("keeps the all-clear of Please check and the Private explanation for the whole inbox only", () => {
    expect(emptyCopy(view({ filter: "check", year: 2025 })).title).toBe("No letters dated 2025 to check");
    expect(emptyCopy(view({ filter: "private", year: 2025 })).action).toBe("clear-filters");
    expect(emptyCopy(view({ filter: "check", who: { kind: "mine" } })).title).toBe("No letters of yours to check");
    expect(emptyCopy(view({ filter: "private", who: { kind: "person", name: "Alex Rivera", suggested: 0 } })).title).toBe("No private letters for Alex Rivera");
    expect(emptyCopy(view({ filter: "private", who: { kind: "person", name: "Alex Rivera", suggested: 0 } })).action).toBe("clear-filters");
  });

  it("says how to file a person's letters when none is filed for them yet", () => {
    expect(emptyCopy(view({ who: { kind: "person", name: "Alex Rivera", suggested: 0 } }))).toEqual({
      title: "No letters filed for Alex Rivera",
      description: "Open a letter and press “Change” next to “For you” to file it for Alex Rivera.",
      illustration: "letter",
      action: "clear-filters",
    });
    // the letters addressed to them wait in the card above
    expect(emptyCopy(view({ who: { kind: "person", name: "Alex Rivera", suggested: 2 } }))).toMatchObject({
      title: "No letters filed for Alex Rivera",
      description: "The letters above are addressed to Alex Rivera. File them with one press.",
    });
    expect(emptyCopy(view({ who: { kind: "mine" } }))).toEqual({
      title: "No letters for you here",
      description: "Every letter is filed for someone in your household.",
      illustration: "letter",
      action: "clear-filters",
    });
    // with a year, a kind or a search as well: the words of those, as for any filter, and whose letters are missing —
    // never "choose another year" when that year has letters of someone else's
    expect(emptyCopy(view({ who: { kind: "person", name: "Alex Rivera", suggested: 0 }, year: 2017 }))).toEqual({
      title: "No letters for Alex Rivera dated 2017",
      description: "Clear the filters to see all your letters.",
      illustration: "search",
      action: "clear-filters",
    });
    expect(emptyCopy(view({ who: { kind: "mine" }, year: 2025 }))).toMatchObject({
      title: "No letters of yours dated 2025",
      description: "Clear the filters to see all your letters.",
    });
    expect(emptyCopy(view({ who: { kind: "mine" }, year: 2025, filter: "check" })).title).toBe("No letters of yours dated 2025 to check");
    expect(emptyCopy(view({ who: { kind: "mine" }, kindLabel: "Invoice" })).title).toBe("No “Invoice” letters of yours");
    expect(emptyCopy(view({ who: { kind: "mine" }, q: "Muster" })).action).toBe("clear-filters");
  });

  it("names the kind and filter that left the list empty, and clears them all", () => {
    expect(emptyCopy(view({ kindLabel: "Tax assessment" }))).toMatchObject({ title: "No “Tax assessment” letters", action: "clear-filters" });
    expect(emptyCopy(view({ filter: "check", kindLabel: "Invoice" })).title).toBe("No “Invoice” letters to check");
    expect(emptyCopy(view({ filter: "private", kindLabel: "Invoice" })).title).toBe("No private “Invoice” letters");
    expect(emptyCopy(view({ filter: "check", q: "Muster" }))).toMatchObject({ title: "No letters match “Muster”", action: "clear-filters" });
  });
});
